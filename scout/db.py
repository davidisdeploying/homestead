"""The private Scout store at /var/lib/homestead/scout/scout.sqlite3.

Scout gets its OWN database, separate from listings.sqlite3, for one concrete reason:
listings.sqlite3 is currently rebuildable from the immutable browser capture generations.
Mixing Gmail receipts and mutable review state into it would quietly make that claim
false, and the claim is what makes the listing warehouse safe to drop and rebuild.

Ownership homestead:homestead, directory 0700, file 0600, WAL, foreign keys on.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA_VERSION
from .identity import canonical_url, normalize_source, source_key
from .profile import assess, profile_hash, validate_profile

REVIEW_STATUSES = ("new", "shortlisted", "dismissed", "captured")
# `captured` is set by reconciliation after a real capture, never by a review click.
REVIEWABLE_STATUSES = ("new", "shortlisted", "dismissed")
RECEIPT_STATUSES = ("imported", "ignored", "parse_empty", "error")

# Columns a repeat alert may refresh. Address/beds/baths/area do not change between
# alerts for the same property; price and status are exactly what a repeat alert exists
# to report, so they take the latest observed value. Every prior value stays readable in
# the append-only sighting chain either way.
_VOLATILE_FIELDS = ("price", "listing_status")
_STABLE_FIELDS = (
    "address", "city", "state", "postal_code", "bedrooms", "bathrooms",
    "living_area", "lot_sqft", "property_type", "description",
)
_ALL_FIELDS = _STABLE_FIELDS + _VOLATILE_FIELDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS scout_profile_version (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  label        TEXT NOT NULL,
  profile_json TEXT NOT NULL,
  profile_hash TEXT NOT NULL UNIQUE,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scout_discovery (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  source             TEXT NOT NULL CHECK (source IN ('zillow','redfin')),
  source_key         TEXT NOT NULL,
  external_id        TEXT,
  source_url         TEXT,
  address            TEXT,
  city               TEXT,
  state              TEXT,
  postal_code        TEXT,
  price              INTEGER,
  bedrooms           REAL,
  bathrooms          REAL,
  living_area        INTEGER,
  lot_sqft           INTEGER,
  property_type      TEXT,
  listing_status     TEXT,
  description        TEXT,
  first_seen_at      TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at       TEXT NOT NULL DEFAULT (datetime('now')),
  status             TEXT NOT NULL DEFAULT 'new'
                       CHECK (status IN ('new','shortlisted','dismissed','captured')),
  profile_version_id INTEGER REFERENCES scout_profile_version(id),
  fit_score          INTEGER,
  fit_label          TEXT,
  assessment_json    TEXT,
  linked_listing_id  TEXT,
  UNIQUE(source, source_key)
);
CREATE INDEX IF NOT EXISTS idx_scout_discovery_review
  ON scout_discovery(status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_scout_discovery_external
  ON scout_discovery(source, external_id);

CREATE TABLE IF NOT EXISTS scout_sighting (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  discovery_id     INTEGER NOT NULL REFERENCES scout_discovery(id),
  seen_at          TEXT NOT NULL DEFAULT (datetime('now')),
  gmail_message_id TEXT,
  raw_payload_json TEXT NOT NULL,
  snapshot_hash    TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_scout_sighting_discovery
  ON scout_sighting(discovery_id, seen_at DESC);

CREATE TABLE IF NOT EXISTS scout_gmail_message (
  gmail_message_id TEXT PRIMARY KEY,
  gmail_thread_id  TEXT,
  received_at      TEXT,
  processed_at     TEXT NOT NULL DEFAULT (datetime('now')),
  source           TEXT,
  status           TEXT NOT NULL
                     CHECK (status IN ('imported','ignored','parse_empty','error')),
  discovery_count  INTEGER NOT NULL DEFAULT 0,
  detail           TEXT
);
CREATE INDEX IF NOT EXISTS idx_scout_gmail_message_received
  ON scout_gmail_message(status, received_at DESC);
"""


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(path, create=True):
    path = Path(path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
    elif not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    if path.exists():
        os.chmod(path, 0o600)
    return conn


# ---------------------------------------------------------------- profiles


def save_profile(conn, label, payload):
    result = validate_profile(payload)
    if not result["ok"]:
        return result
    profile = result["profile"]
    digest = profile_hash(profile)
    conn.execute(
        "INSERT INTO scout_profile_version (label, profile_json, profile_hash) "
        "VALUES (?, ?, ?) ON CONFLICT(profile_hash) DO NOTHING",
        (str(label or "Buying criteria").strip()[:120],
         json.dumps(profile, sort_keys=True, separators=(",", ":")), digest),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM scout_profile_version WHERE profile_hash = ?", (digest,)
    ).fetchone()
    return {"ok": True, "profile": _profile_row(row)}


def latest_profile(conn):
    row = conn.execute(
        "SELECT * FROM scout_profile_version ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _profile_row(row) if row else None


def _profile_row(row):
    return {
        "id": row["id"],
        "label": row["label"],
        "profile": json.loads(row["profile_json"]),
        "profile_hash": row["profile_hash"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------- discoveries


def _snapshot_hash(source, key, payload_json):
    import hashlib
    return hashlib.sha256(f"{source}\n{key}\n{payload_json}".encode("utf-8")).hexdigest()


def record_lead(conn, lead, *, gmail_message_id=None, seen_at=None, profile=None):
    """Upsert one lead and append its immutable sighting.

    Returns {discovery_id, created, new_sighting}. `created` is True only the first time
    a source identity is ever seen; every later alert for it updates last_seen_at and
    appends a sighting when the parsed card actually differs.
    """
    source = normalize_source(lead.get("source"))
    if not source:
        raise ValueError("lead source must be zillow or redfin")
    fields = {name: lead.get(name) for name in _ALL_FIELDS}
    key = source_key(
        source,
        external_id=lead.get("external_id"),
        source_url=lead.get("source_url"),
        address=fields.get("address"),
        city=fields.get("city"),
        state=fields.get("state"),
        postal_code=fields.get("postal_code"),
    )
    seen = seen_at or utc_now()
    payload_json = json.dumps(lead, sort_keys=True, separators=(",", ":"), default=str)
    snapshot = _snapshot_hash(source, key, payload_json)
    assessment = assess(fields, profile["profile"] if profile else None)

    existing = conn.execute(
        "SELECT * FROM scout_discovery WHERE source = ? AND source_key = ?", (source, key)
    ).fetchone()

    if existing is None:
        columns = ["source", "source_key", "external_id", "source_url",
                   "first_seen_at", "last_seen_at"] + list(_ALL_FIELDS)
        values = [source, key,
                  str(lead.get("external_id") or "") or None,
                  canonical_url(source, lead.get("source_url")) or None,
                  seen, seen] + [fields[name] for name in _ALL_FIELDS]
        if assessment:
            columns += ["profile_version_id", "fit_score", "fit_label", "assessment_json"]
            values += [profile["id"], assessment["score"], assessment["label"],
                       json.dumps(assessment, separators=(",", ":"))]
        placeholders = ", ".join("?" for _ in columns)
        cursor = conn.execute(
            f"INSERT INTO scout_discovery ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        discovery_id = cursor.lastrowid
        created = True
    else:
        discovery_id = existing["id"]
        created = False
        updates = {"last_seen_at": seen}
        # Fill gaps only: a later alert may carry a field the first one omitted, but it
        # never overwrites an established value with a different one.
        for name in _STABLE_FIELDS:
            if existing[name] in (None, "") and fields[name] not in (None, ""):
                updates[name] = fields[name]
        for name in _VOLATILE_FIELDS:
            if fields[name] not in (None, ""):
                updates[name] = fields[name]
        if assessment:
            updates.update({
                "profile_version_id": profile["id"],
                "fit_score": assessment["score"],
                "fit_label": assessment["label"],
                "assessment_json": json.dumps(assessment, separators=(",", ":")),
            })
        assignments = ", ".join(f"{name} = ?" for name in updates)
        conn.execute(
            f"UPDATE scout_discovery SET {assignments} WHERE id = ?",
            list(updates.values()) + [discovery_id],
        )

    cursor = conn.execute(
        "INSERT INTO scout_sighting (discovery_id, seen_at, gmail_message_id, "
        "raw_payload_json, snapshot_hash) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(snapshot_hash) DO NOTHING",
        (discovery_id, seen, gmail_message_id, payload_json, snapshot),
    )
    conn.commit()
    return {"discovery_id": discovery_id, "created": created,
            "new_sighting": cursor.rowcount == 1}


def set_review_status(conn, discovery_id, status):
    if status not in REVIEWABLE_STATUSES:
        return {"ok": False, "error": f"status must be one of {', '.join(REVIEWABLE_STATUSES)}"}
    row = conn.execute(
        "SELECT status FROM scout_discovery WHERE id = ?", (discovery_id,)
    ).fetchone()
    if row is None:
        return {"ok": False, "error": "discovery not found"}
    if row["status"] == "captured":
        # A captured lead has a real, reviewed listing behind it. Downgrading it from the
        # lead inbox would misrepresent the property record.
        return {"ok": False, "error": "this lead is already captured in Properties"}
    conn.execute("UPDATE scout_discovery SET status = ? WHERE id = ?", (status, discovery_id))
    conn.commit()
    return {"ok": True, "id": discovery_id, "status": status}


def rescore(conn, profile):
    """Re-assess every discovery against a newly saved profile version."""
    updated = 0
    for row in conn.execute("SELECT * FROM scout_discovery").fetchall():
        fields = {name: row[name] for name in _ALL_FIELDS}
        assessment = assess(fields, profile["profile"])
        if not assessment:
            continue
        conn.execute(
            "UPDATE scout_discovery SET profile_version_id = ?, fit_score = ?, "
            "fit_label = ?, assessment_json = ? WHERE id = ?",
            (profile["id"], assessment["score"], assessment["label"],
             json.dumps(assessment, separators=(",", ":")), row["id"]),
        )
        updated += 1
    conn.commit()
    return updated


def discoveries(conn, status="all"):
    where, params = "", []
    if status and status != "all":
        if status not in REVIEW_STATUSES:
            raise ValueError("unknown status filter")
        where, params = "WHERE d.status = ?", [status]
    rows = conn.execute(
        f"""SELECT d.*,
                   (SELECT COUNT(*) FROM scout_sighting s WHERE s.discovery_id = d.id)
                     AS sighting_count
            FROM scout_discovery d {where}
            ORDER BY (d.fit_score IS NULL), d.fit_score DESC, d.last_seen_at DESC""",
        params,
    ).fetchall()
    return [_discovery_row(row) for row in rows]


def _discovery_row(row):
    record = {key: row[key] for key in row.keys() if key != "assessment_json"}
    record["assessment"] = json.loads(row["assessment_json"]) if row["assessment_json"] else None
    return record


def counts(conn):
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM scout_discovery GROUP BY status"
    ).fetchall()
    tally = {status: 0 for status in REVIEW_STATUSES}
    for row in rows:
        tally[row["status"]] = row["n"]
    tally["all"] = sum(tally[status] for status in REVIEW_STATUSES)
    return tally


# ---------------------------------------------------------------- receipts


def record_receipt(conn, *, gmail_message_id, gmail_thread_id=None, received_at=None,
                   source=None, status="ignored", discovery_count=0, detail=None):
    if status not in RECEIPT_STATUSES:
        raise ValueError("unknown receipt status")
    conn.execute(
        "INSERT INTO scout_gmail_message (gmail_message_id, gmail_thread_id, received_at, "
        "source, status, discovery_count, detail) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(gmail_message_id) DO UPDATE SET "
        "processed_at = datetime('now'), status = excluded.status, "
        "source = excluded.source, discovery_count = excluded.discovery_count, "
        "detail = excluded.detail",
        (gmail_message_id, gmail_thread_id, received_at, source, status,
         discovery_count, (str(detail)[:500] if detail else None)),
    )
    conn.commit()


def known_message_ids(conn):
    return {row[0] for row in conn.execute("SELECT gmail_message_id FROM scout_gmail_message")}


def newest_accepted_receipt(conn):
    row = conn.execute(
        "SELECT MAX(received_at) AS last_at FROM scout_gmail_message WHERE status = 'imported'"
    ).fetchone()
    return row["last_at"] if row else None
