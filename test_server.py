import hashlib
import json
import tempfile
import unittest
import unittest.mock
import sqlite3
import re
from pathlib import Path

import server
from listing_db import attach_archived_media, normalized_media
from media_archive import _sniff_content_type, archive_capture_media


class AppIconTest(unittest.TestCase):
    def test_pwa_mark_uses_shared_fill_and_exact_visible_bounds_center(self):
        source = (Path(__file__).parent / "static" / "pwa-icon.svg").read_text()
        match = re.search(r'translate\(([\d.]+) ([\d.]+)\) scale\(([\d.]+)\)', source)
        self.assertIsNotNone(match)
        tx, ty, scale = map(float, match.groups())

        # Record Stack stroked bounds: x=16.5..112, y=13..115.5 on its
        # 128-unit source grid. Longest edge is 76% of the app-icon canvas.
        self.assertAlmostEqual(scale * (115.5 - 13), 512 * 0.76, places=2)
        self.assertAlmostEqual(tx + scale * ((16.5 + 112) / 2), 256, places=2)
        self.assertAlmostEqual(ty + scale * ((13 + 115.5) / 2), 256, places=2)


class ListingStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = server.LISTINGS_DIR
        server.LISTINGS_DIR = Path(self.temp.name)

    def tearDown(self):
        server.LISTINGS_DIR = self.previous
        self.temp.cleanup()

    def capture(self, price=625000):
        return {
            "schema_version": 1,
            "fields": {
                "source": "Redfin",
                "source_url": "https://www.redfin.com/TX/Dallas/Example/home/12345678",
                "external_id": "12345678",
                "address": "123 Example St",
                "city": "Dallas",
                "state": "TX",
                "postal_code": "75201",
                "price": price,
                "bedrooms": 3,
                "media": [
                    {"kind": "photo", "url": "https://photos.example/house.jpg", "label": "Front"},
                    {"kind": "floor_plan", "url": "https://photos.example/plan.svg", "label": "Floor plan"},
                ],
                "facts": {"heating": ["Central"], "rooms": [{"roomType": "Kitchen", "dimensions": "12 x 10"}]},
                "listing_details": {"price_per_square_foot": 298},
                "attribution_details": {"agentName": "Ada Agent"},
                "price_history": [{"date": "2026-08-09", "event": "Listed", "price": price}],
                "tax_history": [{"time": 1735689600000, "taxPaid": 7000, "value": 500000}],
                "schools": [{"name": "Example School", "rating": 8, "distance": 0.5}],
            },
            "raw": {"captured_at": "2026-08-09T12:00:00Z", "visible_text": "Example"},
            "missing": [],
        }

    def test_capture_generations_are_idempotent_and_enumerable(self):
        first, duplicate = server.store_listing_capture(self.capture())
        self.assertFalse(duplicate)
        self.assertEqual(first["snapshot_count"], 1)

        second, duplicate = server.store_listing_capture(self.capture())
        self.assertTrue(duplicate)
        self.assertEqual(second["snapshot_count"], 1)

        third, duplicate = server.store_listing_capture(self.capture(price=610000))
        self.assertFalse(duplicate)
        self.assertEqual(third["snapshot_count"], 2)
        self.assertEqual(server.listing_records()[0]["fields"]["price"], 610000)
        db = sqlite3.connect(Path(self.temp.name) / "listings.sqlite3")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM listing").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM capture").fetchone()[0], 2)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM media").fetchone()[0], 4)
        self.assertGreater(db.execute("SELECT COUNT(*) FROM listing_value").fetchone()[0], 0)
        comparison = server.listing_comparison(Path(self.temp.name) / "listings.sqlite3", [])
        self.assertEqual(comparison["listings"][0]["price"], 610000)
        self.assertTrue(any(row["path"] == "heating[0]" for row in comparison["facts"]))
        db.close()

    def test_source_url_must_match_source(self):
        capture = self.capture()
        capture["fields"]["source_url"] = "https://example.com/not-redfin"
        with self.assertRaisesRegex(ValueError, "do not match"):
            server.store_listing_capture(capture)

    def test_media_is_content_addressed_deduplicated_and_linked(self):
        record, _ = server.store_listing_capture(self.capture())
        body = b"durable listing image"
        media = [
            {"kind": "photo", "url": "https://photos.zillowstatic.com/fp/front.webp", "label": "Front"},
            {"kind": "floor_plan", "url": "https://www.zillowstatic.com/floor_map/plan.svg", "label": "Plan"},
            {"kind": "three_d", "url": "https://www.zillow.com/view-3d-home/not-a-file", "label": "Tour"},
        ]
        summary = archive_capture_media(
            Path(self.temp.name) / "listings.sqlite3", Path(self.temp.name) / "media",
            record["listing_id"], record["current_sha256"], media,
            fetcher=lambda _: (body, "image/webp"),
        )
        self.assertEqual(summary["eligible"], 2)
        self.assertEqual(summary["archived"], 2)
        self.assertEqual(summary["failed"], 0)
        db = sqlite3.connect(Path(self.temp.name) / "listings.sqlite3")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM media_asset").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM media_archive").fetchone()[0], 2)
        db.close()
        reused = archive_capture_media(
            Path(self.temp.name) / "listings.sqlite3", Path(self.temp.name) / "media",
            record["listing_id"], record["current_sha256"], media,
            fetcher=lambda _: (_ for _ in ()).throw(AssertionError("archived media was fetched again")),
        )
        self.assertEqual((reused["archived"], reused["failed"]), (2, 0))
        record["fields"]["media"] = media
        attach_archived_media(Path(self.temp.name) / "listings.sqlite3", record)
        self.assertTrue(record["fields"]["media"][0]["archived_url"].startswith("/api/listings/media/"))
        self.assertNotIn("archived_url", record["fields"]["media"][2])

    def test_media_normalization_honors_declared_photo_count(self):
        fields = {
            "listing_details": {"photo_count": 2},
            "media": [
                {"kind": "photo", "url": "https://photos.zillowstatic.com/a.webp"},
                {"kind": "photo", "url": "https://photos.zillowstatic.com/b.webp"},
                {"kind": "photo", "url": "https://photos.zillowstatic.com/a-duplicate-size.jpg"},
                {"kind": "map", "url": "https://maps.googleapis.com/map.png"},
                {"kind": "floor_plan", "url": "https://www.zillowstatic.com/plan.svg"},
            ],
        }
        media = normalized_media(fields)
        self.assertEqual([item["url"] for item in media], [
            "https://photos.zillowstatic.com/a.webp",
            "https://photos.zillowstatic.com/b.webp",
            "https://www.zillowstatic.com/plan.svg",
        ])

    def test_media_type_sniffing_recovers_mislabeled_cdn_images(self):
        self.assertEqual(_sniff_content_type(b"\xff\xd8\xffmock-jpeg"), "image/jpeg")
        self.assertEqual(_sniff_content_type(b"RIFF1234WEBPmock"), "image/webp")
        self.assertEqual(_sniff_content_type(b"not media"), "")

    def test_redfin_history_tax_and_school_aliases_are_normalized(self):
        capture = self.capture()
        capture["fields"]["price_history"] = [{
            "eventDate": 1785740400000, "eventDescription": "Listed", "price": 349950,
            "dataSourceName": "NTREIS",
        }]
        capture["fields"]["tax_history"] = [{
            "rollYear": 2025, "taxesDue": 7358.05,
            "taxableImprovementValue": 237300, "taxableLandValue": 100000,
        }]
        capture["fields"]["schools"] = [{
            "name": "Yale Elementary School", "greatSchoolsRating": 9,
            "distanceInMiles": 0.3, "gradeRanges": ["PreK", "6"],
            "institutionType": "Public", "elementary": True, "middle": False, "high": False,
        }]
        record, _ = server.store_listing_capture(capture)
        db = sqlite3.connect(Path(self.temp.name) / "listings.sqlite3")
        db.row_factory = sqlite3.Row
        price = dict(db.execute("SELECT * FROM price_event WHERE capture_sha256=?", (record["current_sha256"],)).fetchone())
        tax = dict(db.execute("SELECT * FROM tax_event WHERE capture_sha256=?", (record["current_sha256"],)).fetchone())
        school = dict(db.execute("SELECT * FROM school WHERE capture_sha256=?", (record["current_sha256"],)).fetchone())
        db.close()
        self.assertEqual((price["event_date"], price["event"], price["source"]),
                         ("1785740400000", "Listed", "NTREIS"))
        self.assertEqual((tax["event_date"], tax["tax_paid"], tax["assessed_value"]),
                         ("2025", 7358.05, 337300))
        self.assertEqual((school["rating"], school["distance"], school["level"],
                          school["grades"], school["school_type"]),
                         (9, 0.3, "Elementary", "PreK, 6", "Public"))


class SnapshotIdentityTest(unittest.TestCase):
    """The writer and the repair tool must agree on how a snapshot is identified.

    They did not. `store_listing_capture` named each snapshot after the SHA-256 of the
    key-sorted serialization, while `atomic_json_write` wrote the file in the capture's own
    key order -- so the file's raw bytes usually hash to something else. `listing_repair.py`
    verified raw bytes and therefore rejected three perfectly intact production snapshots as
    corrupt, which is why 106 photos could not be re-archived.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = server.LISTINGS_DIR
        server.LISTINGS_DIR = Path(self.temp.name)

    def tearDown(self):
        server.LISTINGS_DIR = self.previous
        self.temp.cleanup()

    def unsorted_capture(self):
        # Keys deliberately out of alphabetical order, as a real extension capture is.
        return {
            "schema_version": 1,
            "fields": {
                "source": "Zillow",
                "source_url": "https://www.zillow.com/homedetails/90000001_zpid/",
                "external_id": "90000001",
                "address": "4102 Cottonwood Bend",
                "city": "Richardson", "state": "TX", "postal_code": "75082",
                "price": 398500, "bedrooms": 3,
            },
            "raw": {"captured_at": "2026-08-09T12:00:00Z", "visible_text": "Example"},
            "missing": [],
        }

    def test_snapshot_filename_matches_the_canonical_digest_not_the_raw_bytes(self):
        from listing_db import canonical_capture_bytes
        record, _ = server.store_listing_capture(self.unsorted_capture())
        snapshots = list((server.LISTINGS_DIR / record["listing_id"] / "snapshots").glob("*.json"))
        self.assertEqual(len(snapshots), 1)
        raw = snapshots[0].read_bytes()
        canonical = canonical_capture_bytes(json.loads(raw))

        self.assertEqual(hashlib.sha256(canonical).hexdigest(), snapshots[0].stem,
                         "the canonical digest is what names the file")
        self.assertNotEqual(hashlib.sha256(raw).hexdigest(), snapshots[0].stem,
                            "raw bytes differ, which is exactly what broke the repair tool")

    def test_repair_accepts_a_snapshot_the_server_just_wrote(self):
        # The end-to-end guarantee: anything store_listing_capture writes, repair_listing
        # must accept. Media archiving is stubbed so this stays offline.
        import listing_repair
        record, _ = server.store_listing_capture(self.unsorted_capture())
        with unittest.mock.patch.object(
            listing_repair, "archive_capture_media",
            return_value={"eligible": 0, "archived": 0, "failed": 0, "bytes": 0},
        ):
            result = listing_repair.repair_listing(
                server.LISTINGS_DIR, server.LISTINGS_DIR / "media", record["listing_id"])
        self.assertEqual(result["captures_indexed"], 1)

    def test_repair_still_rejects_a_genuinely_altered_snapshot(self):
        import listing_repair
        record, _ = server.store_listing_capture(self.unsorted_capture())
        snapshot = next((server.LISTINGS_DIR / record["listing_id"] / "snapshots").glob("*.json"))
        tampered = json.loads(snapshot.read_bytes())
        tampered["fields"]["price"] = 1
        snapshot.write_text(json.dumps(tampered, ensure_ascii=False, separators=(",", ":")))
        with self.assertRaisesRegex(ValueError, "integrity check failed"):
            listing_repair.repair_listing(
                server.LISTINGS_DIR, server.LISTINGS_DIR / "media", record["listing_id"])


if __name__ == "__main__":
    unittest.main()
