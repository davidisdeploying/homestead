#!/usr/bin/env python3
"""Isolated contract tests for the normalized Monarch MCP adapter."""
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def fixture():
    return {
        "schema_version": 1,
        "source": "monarch-mcp",
        "captured_at": "2026-08-09T12:00:00Z",
        "accounts": [{"name": "Test Checking", "is_liability": False}],
        "balances": [{"account": "Test Checking", "date": "2026-08-09", "balance": 1000}],
        "goals": [{"name": "New Home", "current_amount": 10, "target_amount": 100}],
        "networth": {"net_worth": 1000, "assets": 1000, "liabilities": 0},
        "transactions": [
            {"id": "income-1", "date": "2026-01-05", "category": "Paychecks", "amount": 5000},
            {"id": "rent-1", "date": "2026-02-05", "category": "Rent", "amount": -1000},
            {"id": "transfer-1", "date": "2026-03-01", "category": "Transfer", "amount": -2000},
        ],
    }


class McpAdapterTest(unittest.TestCase):
    def run_loader(self, db, source):
        env = {**os.environ, "HOMESTEAD_FINANCE_DB": str(db)}
        return subprocess.run(
            ["python3", str(HERE / "load_mcp.py"), str(source), "--period-start", "2026-01-01"],
            text=True, capture_output=True, env=env, check=False,
        )

    def test_import_is_idempotent_and_nets_like_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, db = root / "snapshot.json", root / "finance.db"
            source.write_text(json.dumps(fixture()))
            first, second = self.run_loader(db, source), self.run_loader(db, source)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM import_run").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM txn").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT income,expenses FROM cashflow_total").fetchone(), (5000.0, 1000.0))
            conn.close()

    def test_wrong_source_fails_before_database_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, db = root / "bad.json", root / "finance.db"
            bad = fixture(); bad["source"] = "unknown"
            source.write_text(json.dumps(bad))
            result = self.run_loader(db, source)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source must be monarch-mcp", result.stderr)
            self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main()
