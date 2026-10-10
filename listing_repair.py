#!/usr/bin/env python3
"""Rebuild listing indexes and retry private media archival from immutable captures."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from listing_db import canonical_capture_bytes, index_capture, normalized_media
from media_archive import archive_capture_media


def repair_listing(listings_dir, media_dir, listing_id):
    root = Path(listings_dir) / listing_id
    record_path = root / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    snapshots = sorted((root / "snapshots").glob("*.json"))
    if not snapshots:
        raise ValueError(f"no immutable snapshots for {listing_id}")
    db_path = Path(listings_dir) / "listings.sqlite3"
    current_capture = None
    for snapshot in snapshots:
        payload = snapshot.read_bytes()
        capture = json.loads(payload)
        # Verify against the canonical, key-sorted serialization the writer named the file
        # after -- not the raw file bytes, which are stored in the capture's own key order
        # and therefore usually hash to something else entirely.
        canonical = canonical_capture_bytes(capture)
        if hashlib.sha256(canonical).hexdigest() != snapshot.stem:
            raise ValueError(f"snapshot integrity check failed for {listing_id}")
        index_capture(db_path, capture, record, snapshot.stem, canonical)
        if snapshot.stem == record.get("current_sha256"):
            current_capture = capture
    if current_capture is None:
        raise ValueError(f"current snapshot missing for {listing_id}")
    archive = archive_capture_media(
        db_path, media_dir, listing_id, record["current_sha256"],
        normalized_media(current_capture["fields"]),
    )
    return {"listing_id": listing_id, "captures_indexed": len(snapshots), "media": archive}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listing-id", action="append", help="repair only this listing id; repeatable")
    args = parser.parse_args()
    listings_dir = Path(os.environ.get("HOMESTEAD_LISTINGS_DIR", "/var/lib/homestead/listings"))
    media_dir = Path(os.environ.get("HOMESTEAD_LISTING_MEDIA_DIR", str(listings_dir / "media")))
    listing_ids = args.listing_id or sorted(
        path.parent.name for path in listings_dir.glob("*/record.json")
    )
    if not listing_ids:
        raise SystemExit("no saved listings found")
    failed = False
    for listing_id in listing_ids:
        try:
            result = repair_listing(listings_dir, media_dir, listing_id)
            media = result["media"]
            print(f"{listing_id}: {result['captures_indexed']} captures indexed; "
                  f"{media['archived']}/{media['eligible']} media archived; {media['failed']} failed")
            failed = failed or bool(media["failed"])
        except Exception as exc:
            failed = True
            print(f"{listing_id}: repair failed: {exc}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
