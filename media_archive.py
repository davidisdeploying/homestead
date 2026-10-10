"""Bounded, content-addressed archive for listing media."""

import hashlib
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen

from listing_db import connect


MAX_MEDIA_ITEMS = 80
MAX_ASSET_BYTES = 25 * 1024 * 1024
MAX_CAPTURE_BYTES = 300 * 1024 * 1024
ALLOWED_HOST_SUFFIXES = ("zillowstatic.com", "cdn-redfin.com", "redfin.com")
ALLOWED_KINDS = {"photo", "floor_plan", "video"}
ALLOWED_CONTENT_TYPES = ("image/", "video/", "application/pdf")
FETCH_ATTEMPTS = 5
FETCH_BACKOFF_SECONDS = 0.5


def _utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _allowed_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_HOST_SUFFIXES)


def _eligible(item):
    kind = item.get("kind", "photo")
    url = item.get("url", "")
    if kind in ALLOWED_KINDS:
        return _allowed_url(url)
    if kind == "three_d" and urlparse(url).path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".svg")):
        return _allowed_url(url)
    return False


def fetch_media(url):
    last_error = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            return _fetch_media_once(url)
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < FETCH_ATTEMPTS - 1:
                time.sleep(min(4, FETCH_BACKOFF_SECONDS * (2 ** attempt)))
    raise last_error


def _fetch_media_once(url):
    request = Request(url, headers={"User-Agent": "Homestead/1.0 personal listing archive", "Accept": "image/*,video/*,application/pdf"})
    with urlopen(request, timeout=20) as response:
        final_url = response.geturl()
        if not _allowed_url(final_url):
            raise ValueError("redirected outside approved listing media hosts")
        content_type = response.headers.get_content_type().lower()
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_ASSET_BYTES:
            raise ValueError("media asset exceeds 25 MB")
        chunks = []
        size = 0
        while True:
            chunk = response.read(min(1024 * 1024, MAX_ASSET_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_ASSET_BYTES:
                raise ValueError("media asset exceeds 25 MB")
        body = b"".join(chunks)
        if not any(content_type.startswith(prefix) for prefix in ALLOWED_CONTENT_TYPES):
            content_type = _sniff_content_type(body, url)
        if not content_type:
            raise ValueError(f"unsupported media type {response.headers.get_content_type().lower()}")
        return body, content_type


def _sniff_content_type(body, url=""):
    """Accept mislabeled CDN responses only when their bytes prove a supported media type."""
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if body.startswith(b"%PDF-"):
        return "application/pdf"
    head = body[:1024].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "image/svg+xml"
    return ""


def _store_asset(media_root, body):
    digest = hashlib.sha256(body).hexdigest()
    root = Path(media_root) / "sha256" / digest[:2]
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(Path(media_root), 0o700)
    os.chmod(Path(media_root) / "sha256", 0o700)
    os.chmod(root, 0o700)
    target = root / digest
    if not target.exists():
        fd, tmp = tempfile.mkstemp(dir=root, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        finally:
            Path(tmp).unlink(missing_ok=True)
    return digest, target


def archive_capture_media(db_path, media_root, listing_id, capture_sha256, media, fetcher=fetch_media):
    candidates = []
    for position, item in enumerate((media or [])[:MAX_MEDIA_ITEMS]):
        if isinstance(item, str):
            item = {"url": item, "kind": "photo", "label": ""}
        if _eligible(item):
            candidates.append((position, item))
    with connect(db_path) as db:
        existing_rows = db.execute("""SELECT a.position,a.source_url,a.asset_sha256,a.status,
          s.storage_path,s.mime_type,s.bytes FROM media_archive a
          LEFT JOIN media_asset s ON s.sha256=a.asset_sha256
          WHERE a.capture_sha256=?""", (capture_sha256,)).fetchall()
    existing = {row["position"]: row for row in existing_rows}
    results = []
    pending = []
    for position, item in candidates:
        row = existing.get(position)
        path = Path(row["storage_path"]) if row and row["storage_path"] else None
        reusable = bool(row and row["status"] == "archived" and row["source_url"] == item["url"]
                        and row["asset_sha256"] and path and path.is_file())
        if reusable:
            body = path.read_bytes()
            reusable = hashlib.sha256(body).hexdigest() == row["asset_sha256"] and len(body) == row["bytes"]
        if reusable:
            results.append({"position": position, "url": item["url"], "status": "archived",
                            "asset_sha256": row["asset_sha256"], "storage_path": row["storage_path"],
                            "mime_type": row["mime_type"], "bytes": row["bytes"], "error": None})
        else:
            pending.append((position, item))

    def archive_one(position, item):
        try:
            body, content_type = fetcher(item["url"])
            digest, path = _store_asset(media_root, body)
            return {"position": position, "url": item["url"], "status": "archived", "asset_sha256": digest,
                    "storage_path": str(path), "mime_type": content_type, "bytes": len(body), "error": None}
        except Exception as exc:
            return {"position": position, "url": item.get("url", ""), "status": "failed", "asset_sha256": None,
                    "storage_path": None, "mime_type": None, "bytes": 0, "error": str(exc)[:300]}

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(archive_one, position, item) for position, item in pending]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["position"])
    total = 0
    for row in results:
        if row["status"] == "archived":
            total += row["bytes"]
            if total > MAX_CAPTURE_BYTES:
                row.update(status="failed", error="capture media exceeds 300 MB", asset_sha256=None,
                           storage_path=None, mime_type=None, bytes=0)
    now = _utcnow()
    with connect(db_path) as db:
        db.execute("DELETE FROM media_archive WHERE capture_sha256=?", (capture_sha256,))
        for row in results:
            if row["asset_sha256"]:
                db.execute("INSERT OR IGNORE INTO media_asset VALUES(?,?,?,?,?)",
                           (row["asset_sha256"], row["storage_path"], row["mime_type"], row["bytes"], now))
            db.execute("INSERT INTO media_archive VALUES(?,?,?,?,?,?,?)",
                       (capture_sha256, listing_id, row["position"], row["url"], row["asset_sha256"],
                        row["status"], row["error"]))
    return {
        "eligible": len(candidates),
        "archived": sum(row["status"] == "archived" for row in results),
        "failed": sum(row["status"] == "failed" for row in results),
        "bytes": sum(row["bytes"] for row in results if row["status"] == "archived"),
    }
