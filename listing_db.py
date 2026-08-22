"""Private SQLite index for immutable Homestead listing captures."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS listing (
  listing_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  external_id TEXT,
  source_url TEXT NOT NULL,
  address TEXT NOT NULL,
  city TEXT, state TEXT, postal_code TEXT,
  latitude REAL, longitude REAL,
  price REAL, bedrooms REAL, bathrooms REAL, living_area REAL, lot_sqft REAL,
  year_built INTEGER, hoa_monthly REAL, property_type TEXT, listing_status TEXT,
  description TEXT, mls_id TEXT, agent_name TEXT, agent_phone TEXT, broker_name TEXT,
  first_captured_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  current_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS listing_location_idx ON listing(state, city, postal_code);
CREATE INDEX IF NOT EXISTS listing_price_idx ON listing(price);

CREATE TABLE IF NOT EXISTS capture (
  sha256 TEXT PRIMARY KEY,
  listing_id TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  captured_at TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  payload_bytes INTEGER NOT NULL,
  fields_json TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  missing_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS capture_listing_idx ON capture(listing_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS listing_value (
  capture_sha256 TEXT NOT NULL REFERENCES capture(sha256) ON DELETE CASCADE,
  listing_id TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  namespace TEXT NOT NULL,
  path TEXT NOT NULL,
  label TEXT NOT NULL,
  value_type TEXT NOT NULL,
  value_text TEXT,
  value_number REAL,
  value_json TEXT,
  PRIMARY KEY(capture_sha256, namespace, path)
);
CREATE INDEX IF NOT EXISTS listing_value_compare_idx ON listing_value(namespace, path, listing_id);

CREATE TABLE IF NOT EXISTS media (
  capture_sha256 TEXT NOT NULL REFERENCES capture(sha256) ON DELETE CASCADE,
  listing_id TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  kind TEXT NOT NULL,
  url TEXT NOT NULL,
  label TEXT,
  PRIMARY KEY(capture_sha256, position)
);
CREATE INDEX IF NOT EXISTS media_listing_idx ON media(listing_id, kind, position);

CREATE TABLE IF NOT EXISTS media_asset (
  sha256 TEXT PRIMARY KEY,
  storage_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_archive (
  capture_sha256 TEXT NOT NULL REFERENCES capture(sha256) ON DELETE CASCADE,
  listing_id TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  source_url TEXT NOT NULL,
  asset_sha256 TEXT REFERENCES media_asset(sha256),
  status TEXT NOT NULL,
  error TEXT,
  PRIMARY KEY(capture_sha256, position)
);
CREATE INDEX IF NOT EXISTS media_archive_listing_idx ON media_archive(listing_id, status);

CREATE TABLE IF NOT EXISTS price_event (
  capture_sha256 TEXT NOT NULL REFERENCES capture(sha256) ON DELETE CASCADE,
  listing_id TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  event_date TEXT, event TEXT, price REAL, source TEXT, raw_json TEXT NOT NULL,
  PRIMARY KEY(capture_sha256, position)
);
CREATE TABLE IF NOT EXISTS tax_event (
  capture_sha256 TEXT NOT NULL REFERENCES capture(sha256) ON DELETE CASCADE,
  listing_id TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  event_date TEXT, tax_paid REAL, assessed_value REAL, raw_json TEXT NOT NULL,
  PRIMARY KEY(capture_sha256, position)
);
CREATE TABLE IF NOT EXISTS school (
  capture_sha256 TEXT NOT NULL REFERENCES capture(sha256) ON DELETE CASCADE,
  listing_id TEXT NOT NULL REFERENCES listing(listing_id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  name TEXT, rating REAL, distance REAL, level TEXT, grades TEXT, school_type TEXT,
  raw_json TEXT NOT NULL,
  PRIMARY KEY(capture_sha256, position)
);
"""


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def canonical_capture_bytes(capture):
    """The serialization a listing capture's SHA-256 identity is computed over.

    Key-sorted, so the digest depends on the capture's content and not on the order the
    extension happened to emit its keys. The snapshot file on disk is written in the
    capture's own key order, so a snapshot's bytes generally do NOT hash to its filename --
    only this canonical form does.

    That distinction is the whole reason this function exists. The rule used to be spelled
    out separately in the writer and the repair tool, they disagreed, and the repair tool
    refused three intact snapshots as corrupt because it hashed raw file bytes. Both now
    call this, so they cannot drift again.
    """
    return json.dumps(capture, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode()


def _open(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript(SCHEMA)
    if path.exists():
        os.chmod(path, 0o600)
    return db


@contextmanager
def connect(path):
    """Open the listing index, commit or roll back, and always close.

    This is a context manager rather than a bare connection because
    `sqlite3.Connection.__exit__` commits the transaction but does NOT close the
    connection -- so the long-standing `with connect(path) as db:` at every call site
    left a connection open on every call, one per `/api/listings` request. The inner
    `with db:` below preserves exactly the previous commit-on-success and
    rollback-on-exception behaviour; the `finally` adds the close that was missing.

    Callers must materialise rows (`fetchall`, `fetchone`, `dict(row)`) before leaving
    the block. Every current caller already does; `sqlite3.Row` objects stay readable
    after the connection closes, but a lazy cursor would not.
    """
    db = _open(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _first(item, *keys):
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def _text(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item is not None and item != "")
    return value


def _school_level(item):
    explicit = _first(item, "level", "schoolLevel", "educationLevel")
    if explicit:
        return _text(explicit)
    levels = []
    for keys, label in ((("elementary", "isElementarySchool"), "Elementary"),
                        (("middle", "isMiddleSchool"), "Middle"),
                        (("high", "isHighSchool"), "High")):
        if any(item.get(key) is True for key in keys):
            levels.append(label)
    return ", ".join(levels) or None


def _redfin_assessed_value(item):
    explicit = _first(item, "value", "taxAssessedValue", "assessedValue", "taxableValue",
                      "totalTaxableValue")
    if explicit is not None:
        return explicit
    components = [_number(item.get("taxableImprovementValue")), _number(item.get("taxableLandValue"))]
    present = [value for value in components if value is not None]
    return sum(present) if present else None


def _label(path):
    return path.rsplit(".", 1)[-1].replace("_", " ").replace("-", " ")


def _leaves(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            yield from _leaves(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}[{index}]")
    elif value is not None and value != "":
        yield path, value


def normalized_media(fields):
    items = fields.get("media") or [
        {"url": url, "kind": "photo", "label": ""} for url in fields.get("photo_urls", [])
    ]
    declared = int((fields.get("listing_details") or {}).get("photo_count") or 0)
    photos = [item for item in items if isinstance(item, dict) and item.get("kind", "photo") == "photo"]
    if declared:
        photos = photos[:declared]
    others = [item for item in items if isinstance(item, dict) and item.get("kind", "photo") not in ("photo", "map")]
    seen = set()
    result = []
    for item in photos + others:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def index_capture(db_path, capture, record, digest, canonical_bytes):
    fields = capture["fields"]
    raw = capture["raw"]
    captured_at = raw.get("captured_at") or record["updated_at"]
    media = normalized_media(fields)
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO listing(
              listing_id,source,external_id,source_url,address,city,state,postal_code,latitude,longitude,
              price,bedrooms,bathrooms,living_area,lot_sqft,year_built,hoa_monthly,property_type,
              listing_status,description,mls_id,agent_name,agent_phone,broker_name,first_captured_at,
              updated_at,current_sha256
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(listing_id) DO UPDATE SET
              source=excluded.source,external_id=excluded.external_id,source_url=excluded.source_url,
              address=excluded.address,city=excluded.city,state=excluded.state,postal_code=excluded.postal_code,
              latitude=excluded.latitude,longitude=excluded.longitude,price=excluded.price,
              bedrooms=excluded.bedrooms,bathrooms=excluded.bathrooms,living_area=excluded.living_area,
              lot_sqft=excluded.lot_sqft,year_built=excluded.year_built,hoa_monthly=excluded.hoa_monthly,
              property_type=excluded.property_type,listing_status=excluded.listing_status,
              description=excluded.description,mls_id=excluded.mls_id,agent_name=excluded.agent_name,
              agent_phone=excluded.agent_phone,broker_name=excluded.broker_name,
              updated_at=excluded.updated_at,current_sha256=excluded.current_sha256""",
            (record["listing_id"], record["source"], record["external_id"], record["source_url"],
             fields.get("address"), fields.get("city"), fields.get("state"), fields.get("postal_code"),
             fields.get("latitude"), fields.get("longitude"), fields.get("price"), fields.get("bedrooms"),
             fields.get("bathrooms"), fields.get("living_area"), fields.get("lot_sqft"), fields.get("year_built"),
             fields.get("hoa_monthly"), fields.get("property_type"), fields.get("listing_status"),
             fields.get("description"), fields.get("mls_id"), fields.get("agent_name"), fields.get("agent_phone"),
             fields.get("broker_name"), record["first_captured_at"], record["updated_at"], digest),
        )
        db.execute(
            "INSERT OR IGNORE INTO capture VALUES(?,?,?,?,?,?,?,?)",
            (digest, record["listing_id"], captured_at, capture["schema_version"], len(canonical_bytes),
             _json(fields), _json(raw), _json(capture.get("missing", []))),
        )
        for table in ("listing_value", "media", "price_event", "tax_event", "school"):
            db.execute(f"DELETE FROM {table} WHERE capture_sha256=?", (digest,))
        for namespace in ("facts", "listing_details", "attribution_details"):
            for path, value in _leaves(fields.get(namespace, {})):
                value_type = "boolean" if isinstance(value, bool) else "number" if _number(value) is not None else "text"
                db.execute(
                    "INSERT INTO listing_value VALUES(?,?,?,?,?,?,?,?,?)",
                    (digest, record["listing_id"], namespace, path, _label(path), value_type,
                     str(value) if not isinstance(value, (dict, list)) else None, _number(value), _json(value)),
                )
        for position, item in enumerate(media):
            if isinstance(item, str):
                item = {"url": item, "kind": "photo"}
            if item.get("url"):
                db.execute("INSERT INTO media VALUES(?,?,?,?,?,?)", (digest, record["listing_id"], position,
                           item.get("kind", "photo"), item["url"], item.get("label", "")))
        for position, item in enumerate(fields.get("price_history", [])):
            db.execute("INSERT INTO price_event VALUES(?,?,?,?,?,?,?,?)", (digest, record["listing_id"], position,
                       _first(item, "date", "time", "eventDate"),
                       _first(item, "event", "eventDescription"), item.get("price"),
                       _first(item, "source", "dataSourceName"), _json(item)))
        for position, item in enumerate(fields.get("tax_history", [])):
            db.execute("INSERT INTO tax_event VALUES(?,?,?,?,?,?,?)", (digest, record["listing_id"], position,
                       _first(item, "date", "time", "rollYear"),
                       _first(item, "taxPaid", "taxesDue"), _redfin_assessed_value(item), _json(item)))
        for position, item in enumerate(fields.get("schools", [])):
            db.execute("INSERT INTO school VALUES(?,?,?,?,?,?,?,?,?,?)", (digest, record["listing_id"], position,
                       item.get("name"), _first(item, "rating", "greatSchoolsRating"),
                       _first(item, "distance", "distanceInMiles"), _school_level(item),
                       _text(_first(item, "grades", "gradeRanges")),
                       _first(item, "type", "institutionType"), _json(item)))


def records(db_path):
    with connect(db_path) as db:
        rows = db.execute("""SELECT l.*, c.fields_json, c.missing_json,
          (SELECT COUNT(*) FROM capture x WHERE x.listing_id=l.listing_id) snapshot_count
          FROM listing l JOIN capture c ON c.sha256=l.current_sha256 ORDER BY l.updated_at DESC""").fetchall()
    records = [{
        "listing_id": row["listing_id"], "source": row["source"], "source_url": row["source_url"],
        "external_id": row["external_id"], "first_captured_at": row["first_captured_at"],
        "updated_at": row["updated_at"], "snapshot_count": row["snapshot_count"],
        "current_sha256": row["current_sha256"], "fields": json.loads(row["fields_json"]),
        "missing": json.loads(row["missing_json"]),
    } for row in rows]
    for record in records:
        attach_archived_media(db_path, record)
    return records


def attach_archived_media(db_path, record):
    fields = record.get("fields", {})
    media = normalized_media(fields)
    with connect(db_path) as db:
        rows = db.execute("""SELECT a.position,a.status,a.error,a.asset_sha256,s.bytes,s.mime_type
          FROM media_archive a LEFT JOIN media_asset s ON s.sha256=a.asset_sha256
          WHERE a.capture_sha256=?""", (record["current_sha256"],)).fetchall()
    by_position = {row["position"]: row for row in rows}
    enriched = []
    for position, original in enumerate(media):
        item = {"url": original, "kind": "photo", "label": ""} if isinstance(original, str) else dict(original)
        row = by_position.get(position)
        if row:
            item["archive_status"] = row["status"]
            item["archive_error"] = row["error"]
            if row["asset_sha256"]:
                item["archived_url"] = "/api/listings/media/" + row["asset_sha256"]
                item["archive_sha256"] = row["asset_sha256"]
                item["archive_bytes"] = row["bytes"]
                item["archive_mime_type"] = row["mime_type"]
        enriched.append(item)
    fields["media"] = enriched
    record["media_archive"] = {
        "eligible": len(rows), "archived": sum(row["status"] == "archived" for row in rows),
        "failed": sum(row["status"] == "failed" for row in rows),
        "bytes": sum(row["bytes"] or 0 for row in rows if row["status"] == "archived"),
    }
    return record


def media_asset(db_path, digest):
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    with connect(db_path) as db:
        row = db.execute("SELECT * FROM media_asset WHERE sha256=?", (digest,)).fetchone()
    return dict(row) if row else None


def comparison(db_path, listing_ids=None):
    with connect(db_path) as db:
        where = ""
        args = []
        if listing_ids:
            where = "WHERE listing_id IN (%s)" % ",".join("?" for _ in listing_ids)
            args = listing_ids
        listings = [dict(row) for row in db.execute(f"SELECT * FROM listing {where} ORDER BY updated_at DESC", args)]
        if not listings:
            return {"listings": [], "facts": []}
        ids = [row["listing_id"] for row in listings]
        placeholders = ",".join("?" for _ in ids)
        values = db.execute(f"""SELECT v.listing_id,v.namespace,v.path,v.label,v.value_text,v.value_number,v.value_type
          FROM listing_value v JOIN listing l ON l.current_sha256=v.capture_sha256
          WHERE v.listing_id IN ({placeholders}) ORDER BY v.namespace,v.path,v.listing_id""", ids).fetchall()
    grouped = {}
    for row in values:
        key = (row["namespace"], row["path"], row["label"])
        grouped.setdefault(key, {})[row["listing_id"]] = row["value_number"] if row["value_type"] == "number" else row["value_text"]
    return {"listings": listings, "facts": [
        {"namespace": key[0], "path": key[1], "label": key[2], "values": values}
        for key, values in grouped.items()
    ]}
