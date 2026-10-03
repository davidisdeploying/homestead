#!/usr/bin/env python3
"""Tests for the bounded manual Monarch goal snapshot writer."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from finance.goal_snapshot import normalize_goal_snapshot, save_goal_snapshot


class GoalSnapshotTest(unittest.TestCase):
    def test_snapshot_is_timestamped_hashed_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "finance.db"
            first = save_goal_snapshot(
                {
                    "current_amount": 12345.67,
                    "target_amount": 50000,
                    "target_date": "2027-06",
                    "monthly_contribution": 2500,
                    "status": "Ahead",
                },
                db,
                "2026-09-20T20:30:00Z",
            )
            second = save_goal_snapshot(
                {
                    "current_amount": 15000,
                    "target_amount": 50000,
                    "target_date": "2027-06",
                    "monthly_contribution": 2500,
                    "status": "Ahead",
                },
                db,
                "2026-09-21T20:30:00Z",
            )

            self.assertEqual(first["source"], "monarch-manual")
            self.assertEqual(len(first["receipt_sha256"]), 64)
            self.assertNotEqual(first["receipt_sha256"], second["receipt_sha256"])
            backups = list((db.parent / "backups").glob("finance-before-goal-*.db"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM goal_snapshot").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM import_run").fetchone()[0], 2)
            latest = conn.execute(
                "SELECT current_amount,target_amount,source,source_sha256 FROM goal_snapshot "
                "ORDER BY captured_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
            self.assertEqual(latest[:3], (15000.0, 50000.0, "monarch-manual"))
            self.assertEqual(latest[3], second["receipt_sha256"])

    def test_existing_database_is_migrated_without_losing_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "finance.db"
            conn = sqlite3.connect(db)
            conn.executescript("""
                CREATE TABLE import_run (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_file TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    imported_at TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE goal_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    current_amount REAL NOT NULL,
                    target_amount REAL NOT NULL,
                    target_date TEXT,
                    monthly_contribution REAL,
                    status TEXT,
                    UNIQUE(captured_at, name)
                );
                INSERT INTO goal_snapshot(
                    captured_at,name,current_amount,target_amount,target_date,
                    monthly_contribution,status
                ) VALUES ('2026-01-01','New Home',1000,50000,'2027-06',2500,'On track');
            """)
            conn.close()

            save_goal_snapshot(
                {"current_amount": 2000, "target_amount": 50000},
                db,
                "2026-02-01T12:00:00Z",
            )
            conn = sqlite3.connect(db)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(goal_snapshot)")}
            rows = conn.execute(
                "SELECT captured_at,source FROM goal_snapshot ORDER BY captured_at"
            ).fetchall()
            conn.close()
            self.assertTrue({"source", "source_sha256"}.issubset(columns))
            self.assertEqual(rows, [
                ("2026-01-01", "legacy-import"),
                ("2026-02-01T12:00:00Z", "monarch-manual"),
            ])

    def test_rejects_extra_raw_finance_fields(self):
        with self.assertRaisesRegex(ValueError, "unexpected fields: transactions"):
            normalize_goal_snapshot({
                "current_amount": 10,
                "target_amount": 100,
                "transactions": [{"amount": 1}],
            })

    def test_rejects_invalid_amounts_and_dates(self):
        for payload, message in (
            ({"current_amount": -1, "target_amount": 100}, "current_amount"),
            ({"current_amount": 1, "target_amount": 0}, "target_amount"),
            ({"current_amount": 1, "target_amount": 100, "target_date": "12/2026"}, "target_date"),
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, message):
                    normalize_goal_snapshot(payload)


if __name__ == "__main__":
    unittest.main()
