#!/usr/bin/env python3
"""Tests for the derived-only finance dashboard."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from finance.bills import ensure_schema as ensure_bill_schema
from finance.dashboard import build_dashboard_payload


class DashboardTest(unittest.TestCase):
    def test_savings_history_uses_account_classification_not_private_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "finance.db"
            conn = sqlite3.connect(db)
            conn.executescript((Path(__file__).parent / "schema.sql").read_text())
            ensure_bill_schema(conn)
            conn.executescript("""
                CREATE TABLE cashflow_snapshot (
                    captured_at TEXT NOT NULL, period TEXT NOT NULL,
                    kind TEXT NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL,
                    PRIMARY KEY (captured_at, period, kind, category)
                );
                CREATE TABLE cashflow_total (
                    captured_at TEXT NOT NULL, period TEXT NOT NULL,
                    income REAL NOT NULL, expenses REAL NOT NULL, savings REAL NOT NULL,
                    savings_rate REAL NOT NULL, months REAL NOT NULL,
                    txn_count INTEGER, first_txn TEXT, last_txn TEXT,
                    source_sha256 TEXT, PRIMARY KEY (captured_at, period)
                );
                INSERT INTO account(name,category,subtype,owner,is_liability,created_at)
                    VALUES ('Private goal label','Cash','Savings','Shared',0,'2026-01-01');
                INSERT INTO account(name,category,subtype,owner,is_liability,created_at)
                    VALUES ('Checking','Cash','Checking','Shared',0,'2026-01-01');
                INSERT INTO balance(account_id,date,balance) VALUES
                    (1,'2026-01-31',10000),(1,'2026-02-28',12000),(1,'2026-03-31',14000),
                    (2,'2026-01-31',99999),(2,'2026-02-28',99999),(2,'2026-03-31',99999);
                INSERT INTO goal_snapshot(
                    captured_at,name,current_amount,target_amount,target_date,
                    monthly_contribution,status
                ) VALUES ('2026-03-31','New Home',14000,50000,'2027-09',2000,'On track');
                INSERT INTO networth_snapshot(
                    captured_at,net_worth,assets,liabilities,cash,investments,vehicles,credit_cards
                ) VALUES ('2026-03-31',100000,110000,10000,20000,80000,10000,10000);
                INSERT INTO cashflow_total VALUES
                    ('2026-03-31','2026 YTD',30000,24000,6000,20,3,10,'2026-01-01','2026-03-31','hash');
                INSERT INTO cashflow_snapshot VALUES
                    ('2026-03-31','2026 YTD','income','Paychecks',30000);
            """)
            conn.commit()
            conn.close()

            payload = build_dashboard_payload(db)

            self.assertEqual(payload["savings"], [["Jan", 10000.0], ["Feb", 12000.0], ["Mar", 14000.0]])
            self.assertEqual(payload["steadyMonthly"], 2000.0)
            self.assertEqual(payload["goalCurrent"], 14000.0)


if __name__ == "__main__":
    unittest.main()
