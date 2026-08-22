#!/usr/bin/env python3
"""Homestead origin server — stdlib only, loopback only.

Follows the fleet pattern: bind 127.0.0.1, let the edge tunnel publish it, and
put Cloudflare Access in front. There is deliberately NO application-level auth here,
matching the Nexus cutover (2026-08-02, bdbcb16) — Access is the gate, and a second
half-built gate behind it is worse than none.

Because it binds loopback only, the sole way in is the tunnel, and the sole way past
the tunnel is Access. If that ever changes, this file needs its own auth and this
comment is the warning.

Serves:
  /                     -> static/index.html
  /app.js, /manifest…   -> static assets
  /api/state?key=…      -> GET  the stored blob
  /api/state            -> PUT  {"key":…, "value":…}
  /api/bills            -> GET  obligation register without transactions
  /api/learning         -> GET  bounded excerpts from the compiled book corpus
  /api/listings         -> GET/POST private, versioned listing captures
  /api/listings/compare -> GET  structured multi-listing comparison dataset
  /api/scout            -> GET  email-delivered property leads awaiting review
  /api/scout/review     -> POST shortlist/dismiss/reset one lead
  /api/scout/profile    -> POST record an owner-approved buying-criteria version
  /healthz              -> liveness for the tunnel

Household state remains a small atomic JSON document. Listing captures retain immutable
JSON source generations and are additionally indexed into private SQLite for comparison,
analysis, and future AI tools.

Scout is a lead inbox, not a property list. Its rows come from read-only Gmail alerts and
live in their own database; nothing under /api/scout can create a property, an immutable
capture generation, a listings.sqlite3 row, or archived media. The only crossing is in the
other direction: a capture that has already succeeded may mark one lead `captured`.
"""
import json
import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from finance.dashboard import build_bills_payload, build_dashboard_payload
from listing_db import canonical_capture_bytes, comparison as listing_comparison
from listing_db import attach_archived_media, media_asset
from listing_db import index_capture, normalized_media, records as database_listing_records
from media_archive import archive_capture_media
from reader_library import ReaderUnavailable, reader_asset, reader_section
from scout import db as scout_db
from scout import reconcile as scout_reconcile
from scout.importer import ingestion_freshness

HERE = Path(__file__).resolve().parent
STATIC = Path(os.environ.get("HOMESTEAD_STATIC_DIR", str(HERE / "static")))
DATA_DIR = Path(os.environ.get("HOMESTEAD_DATA_DIR", "/var/lib/homestead"))
STATE_FILE = DATA_DIR / "state" / "state.json"
LEARNING_FILE = Path(os.environ.get(
    "HOMESTEAD_LEARNING_FILE", str(DATA_DIR / "learning" / "learning.json")
))
LISTINGS_DIR = Path(os.environ.get(
    "HOMESTEAD_LISTINGS_DIR", str(DATA_DIR / "listings")
))
LISTING_MEDIA_DIR = Path(os.environ.get(
    "HOMESTEAD_LISTING_MEDIA_DIR", str(LISTINGS_DIR / "media")
))
SCOUT_DB = Path(os.environ.get(
    "HOMESTEAD_SCOUT_DB", str(DATA_DIR / "scout" / "scout.sqlite3")
))
HOST = "127.0.0.1"
PORT = int(os.environ.get("HOMESTEAD_PORT", "8772"))
MAX_BODY = 2 * 1024 * 1024          # a task list is kilobytes; 2 MB is generous
MAX_LISTING_BODY = 2 * 1024 * 1024  # one bounded, user-triggered page capture
MAX_BACKUPS = 14

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def read_state():
    if not STATE_FILE.is_file():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_state(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Keep a rolling backup. The state file IS the user's task list and property
    # notes; a truncated write should never be the only copy.
    if STATE_FILE.is_file():
        bdir = STATE_FILE.parent / "backups"
        bdir.mkdir(exist_ok=True)
        shutil.copy2(STATE_FILE, bdir / f"state-{int(STATE_FILE.stat().st_mtime)}.json")
        old = sorted(bdir.glob("state-*.json"))[:-MAX_BACKUPS]
        for f in old:
            f.unlink(missing_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STATE_FILE)
        os.chmod(STATE_FILE, 0o600)
    finally:
        Path(tmp).unlink(missing_ok=True)


def atomic_json_write(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, mode)
    finally:
        Path(tmp).unlink(missing_ok=True)


def listing_records():
    backfill_listing_database()
    return database_listing_records(LISTINGS_DIR / "listings.sqlite3")


def backfill_listing_database():
    db_path = LISTINGS_DIR / "listings.sqlite3"
    if db_path.exists() or not LISTINGS_DIR.is_dir():
        return
    for record_path in LISTINGS_DIR.glob("*/record.json"):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            snapshots = list((record_path.parent / "snapshots").glob("*.json"))
            snapshots.sort(key=lambda item: item.stem == record.get("current_sha256"))
            for path in snapshots:
                payload = path.read_bytes()
                capture = json.loads(payload)
                index_capture(db_path, capture, record, path.stem, payload)
        except (OSError, json.JSONDecodeError):
            continue


def store_listing_capture(capture):
    if not isinstance(capture, dict) or capture.get("schema_version") != 1:
        raise ValueError("expected listing capture schema_version 1")
    fields = capture.get("fields")
    raw = capture.get("raw")
    if not isinstance(fields, dict) or not isinstance(raw, dict):
        raise ValueError("fields and raw are required")
    source = str(fields.get("source", "")).strip()
    source_url = str(fields.get("source_url", "")).strip()
    allowed_host = {
        "Zillow": "zillow.com",
        "Redfin": "redfin.com",
    }.get(source)
    host = (urlparse(source_url).hostname or "").lower()
    if not allowed_host or not (host == allowed_host or host.endswith("." + allowed_host)):
        raise ValueError("source and source_url do not match an allowed listing site")
    address = str(fields.get("address", "")).strip()
    if not address:
        raise ValueError("address is required before import")

    external_id = re.sub(r"[^A-Za-z0-9_-]", "", str(fields.get("external_id", "")))[:80]
    identity = f"{source.lower()}-{external_id}" if external_id else hashlib.sha256(source_url.encode()).hexdigest()[:24]
    listing_id = re.sub(r"[^a-z0-9_-]", "-", identity.lower()).strip("-")
    canonical = canonical_capture_bytes(capture)
    if len(canonical) > MAX_LISTING_BODY:
        raise ValueError("listing capture too large")
    digest = hashlib.sha256(canonical).hexdigest()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    root = LISTINGS_DIR / listing_id
    snapshot_dir = root / "snapshots"
    snapshot_path = snapshot_dir / f"{digest}.json"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(LISTINGS_DIR, 0o700)
    os.chmod(root, 0o700)
    os.chmod(snapshot_dir, 0o700)
    if not snapshot_path.exists():
        atomic_json_write(snapshot_path, capture)

    record_path = root / "record.json"
    previous = {}
    try:
        previous = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    snapshot_count = len(list(snapshot_dir.glob("*.json")))
    record = {
        "listing_id": listing_id,
        "source": source,
        "source_url": source_url,
        "external_id": external_id,
        "first_captured_at": previous.get("first_captured_at", now),
        "updated_at": now,
        "snapshot_count": snapshot_count,
        "current_sha256": digest,
        "fields": fields,
        "missing": capture.get("missing", []),
    }
    atomic_json_write(record_path, record)
    index_capture(LISTINGS_DIR / "listings.sqlite3", capture, record, digest, canonical)
    media = normalized_media(fields)
    record["media_archive"] = archive_capture_media(
        LISTINGS_DIR / "listings.sqlite3", LISTING_MEDIA_DIR, listing_id, digest, media
    )
    attach_archived_media(LISTINGS_DIR / "listings.sqlite3", record)
    return record, digest == previous.get("current_sha256")


def scout_payload(status="all"):
    """Bounded lead inbox: rows, counts, the current criteria, and ingestion freshness.

    Never returns a Gmail message body, an OAuth value, or a raw MIME part -- the store
    keeps only bounded parsed cards, and this projection drops even those.
    """
    conn = scout_db.connect(SCOUT_DB)
    try:
        profile = scout_db.latest_profile(conn)
        return {
            "discoveries": scout_db.discoveries(conn, status),
            "counts": scout_db.counts(conn),
            "status": status,
            "profile": profile,
            "ranked": bool(profile),
            "ingestion": ingestion_freshness(conn),
            "boundary": (
                "Email lead — verify the live listing with Homestead Capture before "
                "filing it in Properties."
            ),
        }
    finally:
        conn.close()


def reconcile_scout_capture(record):
    """Best-effort link from a stored capture back to one lead.

    Deliberately swallows every failure: the listing is already durably saved by the time
    this runs, and losing a convenience link must never turn into losing a property.
    """
    try:
        conn = scout_db.connect(SCOUT_DB)
    except OSError:
        return {"status": "unavailable"}
    try:
        return scout_reconcile.reconcile_capture(conn, record)
    except (sqlite3.Error, ValueError, OSError) as exc:
        return {"status": "error", "detail": str(exc)[:200]}
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "homestead/1.0"

    def log_message(self, fmt, *args):
        # journald already stamps; keep one terse line and never log bodies.
        path = self.path.split('?')[0]
        if path.startswith("/api/learning/sections/"):
            path = "/api/learning/sections/[private-reader-resource]"
        print(f"{self.command} {path} {args[1] if len(args) > 1 else ''}",
              flush=True)

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/healthz":
            return self._json(200, {"ok": True})
        if u.path == "/api/finance":
            try:
                payload = build_dashboard_payload()
            except Exception:
                return self._json(503, {"error": "finance unavailable"})
            body = json.dumps(payload, separators=(",", ":")).encode()
            return self._send(200, body, "application/json", {"Cache-Control": "no-store"})
        if u.path == "/api/bills":
            try:
                payload = build_bills_payload()
            except Exception:
                return self._json(503, {"error": "obligation register unavailable"})
            body = json.dumps(payload, separators=(",", ":")).encode()
            return self._send(200, body, "application/json", {"Cache-Control": "no-store"})
        if u.path == "/api/learning":
            try:
                body = LEARNING_FILE.read_bytes()
                json.loads(body)
            except (OSError, json.JSONDecodeError):
                return self._json(503, {"error": "learning library unavailable"})
            return self._send(200, body, "application/json", {"Cache-Control": "no-store"})
        reader_match = re.fullmatch(r"/api/learning/sections/([^/]+)/reader", u.path)
        if reader_match:
            payload = reader_section(unquote(reader_match.group(1)))
            if payload is None:
                return self._json(404, {"error": "reader section unavailable"})
            body = json.dumps(payload, separators=(",", ":")).encode()
            return self._send(200, body, "application/json", {"Cache-Control": "no-store"})
        asset_match = re.fullmatch(r"/api/learning/sections/([^/]+)/assets/([a-f0-9]{32})", u.path)
        if asset_match:
            try:
                body, content_type = reader_asset(unquote(asset_match.group(1)), asset_match.group(2))
            except (ReaderUnavailable, OSError, zipfile.BadZipFile):
                return self._send(404, b"not found")
            return self._send(200, body, content_type, {
                "Cache-Control": "private, max-age=31536000, immutable",
                "Content-Disposition": "inline",
            })
        if u.path == "/api/listings":
            body = json.dumps({"listings": listing_records()}, separators=(",", ":")).encode()
            return self._send(200, body, "application/json", {"Cache-Control": "no-store"})
        if u.path == "/api/listings/compare":
            listing_ids = [item for item in parse_qs(u.query).get("ids", [""])[0].split(",") if item]
            body = json.dumps(listing_comparison(LISTINGS_DIR / "listings.sqlite3", listing_ids),
                              separators=(",", ":")).encode()
            return self._send(200, body, "application/json", {"Cache-Control": "no-store"})
        if u.path.startswith("/api/listings/media/"):
            digest = u.path.rsplit("/", 1)[-1].lower()
            asset = media_asset(LISTINGS_DIR / "listings.sqlite3", digest)
            if not asset:
                return self._send(404, b"not found")
            path = Path(asset["storage_path"])
            try:
                body = path.read_bytes()
            except OSError:
                return self._send(404, b"not found")
            if hashlib.sha256(body).hexdigest() != digest:
                return self._send(503, b"media integrity check failed")
            return self._send(200, body, asset["mime_type"], {
                "Cache-Control": "private, max-age=31536000, immutable",
                "Content-Disposition": "inline",
            })
        if u.path == "/api/scout":
            status = parse_qs(u.query).get("status", ["all"])[0] or "all"
            try:
                payload = scout_payload(status)
            except ValueError:
                return self._json(400, {"error": "unknown status filter"})
            except (sqlite3.Error, OSError):
                return self._json(503, {"error": "scout unavailable"})
            body = json.dumps(payload, separators=(",", ":")).encode()
            return self._send(200, body, "application/json", {"Cache-Control": "no-store"})
        if u.path == "/api/state":
            key = parse_qs(u.query).get("key", [""])[0]
            if not key:
                return self._json(400, {"error": "key required"})
            val = read_state().get(key)
            return self._json(200, {"key": key, "value": val})

        rel = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        target = (STATIC / rel).resolve()
        # Refuse anything that escapes the static root.
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            return self._send(404, b"not found")
        ctype = TYPES.get(target.suffix, "application/octet-stream")
        cache = "no-cache" if target.suffix in (".html", ".js") else "public, max-age=3600"
        self._send(200, target.read_bytes(), ctype, {"Cache-Control": cache})

    do_HEAD = do_GET

    def do_PUT(self):
        if urlparse(self.path).path != "/api/state":
            return self._send(404, b"not found")
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._json(400, {"error": "bad length"})
        if n <= 0 or n > MAX_BODY:
            return self._json(413, {"error": "body too large"})
        try:
            payload = json.loads(self.rfile.read(n))
            key, value = payload["key"], payload["value"]
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError
        except Exception:
            return self._json(400, {"error": "expected {key: str, value: str}"})
        data = read_state()
        data[key] = value
        write_state(data)
        return self._json(200, {"ok": True, "key": key, "bytes": len(value)})

    def _read_json_body(self, limit=MAX_BODY):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None, self._json(400, {"error": "bad length"})
        if n <= 0 or n > limit:
            return None, self._json(413, {"error": "body too large"})
        try:
            return json.loads(self.rfile.read(n)), None
        except json.JSONDecodeError:
            return None, self._json(400, {"error": "expected a JSON object"})

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/scout/review":
            payload, error = self._read_json_body()
            if error is not None:
                return error
            if not isinstance(payload, dict):
                return self._json(400, {"error": "expected {id, status}"})
            try:
                discovery_id = int(payload.get("id"))
            except (TypeError, ValueError):
                return self._json(400, {"error": "id must be a discovery id"})
            try:
                conn = scout_db.connect(SCOUT_DB)
            except OSError:
                return self._json(503, {"error": "scout unavailable"})
            try:
                # set_review_status enforces the allowlist; `captured` is reachable only
                # through reconciliation after a real capture, never through this route.
                result = scout_db.set_review_status(conn, discovery_id, payload.get("status"))
            except sqlite3.Error:
                return self._json(503, {"error": "scout unavailable"})
            finally:
                conn.close()
            body = json.dumps(result, separators=(",", ":")).encode()
            return self._send(200 if result["ok"] else 400, body, "application/json",
                              {"Cache-Control": "no-store"})

        if path == "/api/scout/profile":
            payload, error = self._read_json_body()
            if error is not None:
                return error
            if not isinstance(payload, dict):
                return self._json(400, {"error": "expected a profile object"})
            try:
                conn = scout_db.connect(SCOUT_DB)
            except OSError:
                return self._json(503, {"error": "scout unavailable"})
            try:
                result = scout_db.save_profile(
                    conn, payload.get("label"), payload.get("profile") or {})
                if result["ok"]:
                    result["rescored"] = scout_db.rescore(conn, result["profile"])
            except sqlite3.Error:
                return self._json(503, {"error": "scout unavailable"})
            finally:
                conn.close()
            body = json.dumps(result, separators=(",", ":")).encode()
            return self._send(200 if result["ok"] else 400, body, "application/json",
                              {"Cache-Control": "no-store"})

        if path != "/api/listings":
            return self._send(404, b"not found")
        capture, error = self._read_json_body(MAX_LISTING_BODY)
        if error is not None:
            return error
        try:
            record, duplicate = store_listing_capture(capture)
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except OSError:
            return self._json(503, {"error": "listing store unavailable"})
        # The listing is durably stored by this point. Reconciliation is a link, not a
        # gate: it runs after, and its failure is reported without failing the save.
        return self._json(200, {"ok": True, "duplicate_capture": duplicate, "listing": record,
                                "scout": reconcile_scout_capture(record)})


if __name__ == "__main__":
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LISTINGS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(LISTINGS_DIR, 0o700)
    LISTING_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(LISTING_MEDIA_DIR, 0o700)
    SCOUT_DB.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(SCOUT_DB.parent, 0o700)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"homestead serving {STATIC} on http://{HOST}:{PORT} (loopback only)", flush=True)
    srv.serve_forever()
