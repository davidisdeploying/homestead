#!/usr/bin/env python3
"""Load a Monarch balances CSV plus hand-captured account/goal facts into finance.db.

Idempotent: re-running with the same CSV replaces that file's rows rather than
duplicating them. Every import records the file's SHA-256 so a figure can be
traced back to the exact export it came from.

Usage:  python3 load.py ~/Downloads/Balances_YYYY-MM-DDTHH-MM-SS.csv
"""
import csv
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("HOMESTEAD_FINANCE_DB", "/var/lib/homestead/finance/finance.db"))

# Household facts that are not in the balances CSV: category, owner, credit limit.
#
# A real deployment puts its own figures in finance/local_facts.py, which is
# gitignored. When that file is absent the fictional demo household below is
# used instead, so the loader runs end to end for anyone who clones this without
# putting a real balance sheet in version control.
import importlib.util as _ilu

_local = HERE / "local_facts.py"
if _local.exists():
    _spec = _ilu.spec_from_file_location("homestead_local_facts", _local)
    _facts = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_facts)
    ACCOUNT_FACTS = _facts.ACCOUNT_FACTS
    GOALS = _facts.GOALS
    NETWORTH = _facts.NETWORTH
    ASSUMPTIONS = _facts.ASSUMPTIONS
else:
    # Fictional demo household. Every figure here is invented.
    ACCOUNT_FACTS = {
        "Joint Checking":                  ("Cash", "Checking", "Shared", None, 0),
        "Joint Savings":                   ("Cash", "Savings", "Shared", None, 0),
        "Everyday Rewards Card":           ("Credit Cards", "Credit Card", "Shared", 20000.00, 1),
        "Travel Rewards Card":             ("Credit Cards", "Credit Card", "Shared", 15000.00, 1),
        "Store Financing Card":            ("Credit Cards", "Credit Card", "Shared", 10000.00, 1),
        "Starter Secured Card":            ("Credit Cards", "Credit Card", "Alex", 500.00, 1),
        "Cashback Mastercard":             ("Credit Cards", "Credit Card", "Sam", 18000.00, 1),
        "Employer 401(K)":                 ("Investments", "401k", "Alex", None, 0),
        "Previous Employer 401(K)":        ("Investments", "401k", "Sam", None, 0),
        "Taxable Brokerage":               ("Investments", "Brokerage (Taxable)", "Shared", None, 0),
        "Sedan":                           ("Vehicles", "Car", "Alex", None, 0),
        "Hatchback":                       ("Vehicles", "Car", "Sam", None, 0),
    }

    GOALS = [
        ("New Home",       40000.00, 75000.00, "2026-12", 5000.00, "On track"),
        ("Emergency fund",  2000.00,  9000.00,      None,    None, "No target date"),
    ]

    NETWORTH = dict(
        net_worth=150000.00, assets=152000.00, liabilities=2000.00,
        cash=50000.00, investments=70000.00, vehicles=32000.00, credit_cards=2000.00,
    )

    ASSUMPTIONS = [
        # key, value, unit, source, confirmed
        ("current_housing_cost_monthly", 1500.00, "USD/mo",
         "Current rent for the household. Replace with your own figure.", 1),
        ("down_payment_target", 75000.00, "USD", "Savings goal", 1),
        ("mortgage_rate_annual", 0.065, "rate",
         "ASSUMPTION - not a quote. Replace with a real Loan Estimate.", 0),
        ("property_tax_rate_annual", 0.022, "rate",
         "ASSUMPTION - varies hugely by taxing district; verify per property.", 0),
        ("insurance_annual", 2500.00, "USD/yr",
         "ASSUMPTION - regional hail exposure. Get real quotes.", 0),
        ("closing_cost_rate_low", 0.02, "rate", "2-5% of price, standard range", 1),
        ("closing_cost_rate_high", 0.05, "rate", "2-5% of price, standard range", 1),
    ]


def main():
    csv_path = Path(sys.argv[1]).expanduser()
    raw = csv_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript((HERE / "schema.sql").read_text())

    # Replace any prior import of the same file, so re-running is safe.
    old = conn.execute("SELECT id FROM import_run WHERE source_sha256 = ?", (sha,)).fetchone()
    if old:
        conn.execute("DELETE FROM balance WHERE import_id = ?", (old["id"],))
        conn.execute("DELETE FROM import_run WHERE id = ?", (old["id"],))

    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    conn.execute(
        "INSERT INTO import_run(source_file, source_sha256, row_count, imported_at, note) "
        "VALUES (?,?,?,?,?)",
        (csv_path.name, sha, len(rows), now, "Monarch account-balances export"),
    )
    import_id = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]

    for name, (cat, sub, owner, limit, liab) in ACCOUNT_FACTS.items():
        conn.execute(
            "INSERT INTO account(name, category, subtype, owner, credit_limit, is_liability, created_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
            "category=excluded.category, subtype=excluded.subtype, owner=excluded.owner, "
            "credit_limit=excluded.credit_limit, is_liability=excluded.is_liability",
            (name, cat, sub, owner, limit, liab, now),
        )

    ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM account")}
    unknown = set()
    for r in rows:
        name = r["Account"].strip()
        if name not in ids:
            unknown.add(name)
            conn.execute(
                "INSERT OR IGNORE INTO account(name, created_at) VALUES (?,?)", (name, now))
            ids = {x["name"]: x["id"] for x in conn.execute("SELECT id, name FROM account")}
        conn.execute(
            "INSERT INTO balance(account_id, date, balance, import_id) VALUES (?,?,?,?) "
            "ON CONFLICT(account_id, date) DO UPDATE SET balance=excluded.balance, import_id=excluded.import_id",
            (ids[name], r["Date"], float(r["Balance"]), import_id),
        )

    for name, cur, tgt, tdate, mo, status in GOALS:
        conn.execute(
            "INSERT INTO goal_snapshot(captured_at, name, current_amount, target_amount, "
            "target_date, monthly_contribution, status) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(captured_at, name) DO NOTHING",
            (now[:10], name, cur, tgt, tdate, mo, status),
        )

    conn.execute(
        "INSERT INTO networth_snapshot(captured_at, net_worth, assets, liabilities, cash, "
        "investments, vehicles, credit_cards) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(captured_at) DO UPDATE SET net_worth=excluded.net_worth",
        (now[:10], NETWORTH["net_worth"], NETWORTH["assets"], NETWORTH["liabilities"],
         NETWORTH["cash"], NETWORTH["investments"], NETWORTH["vehicles"], NETWORTH["credit_cards"]),
    )

    for key, val, unit, src, conf in ASSUMPTIONS:
        conn.execute(
            "INSERT INTO assumption(key, value, unit, source, confirmed, updated_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "value=excluded.value, source=excluded.source, confirmed=excluded.confirmed, "
            "updated_at=excluded.updated_at",
            (key, val, unit, src, conf, now),
        )

    conn.commit()
    print(f"import   {csv_path.name}")
    print(f"sha256   {sha}")
    print(f"rows     {len(rows)}")
    print(f"accounts {conn.execute('SELECT COUNT(*) FROM account').fetchone()[0]}")
    print(f"balances {conn.execute('SELECT COUNT(*) FROM balance').fetchone()[0]}")
    if unknown:
        print(f"WARNING  accounts in CSV with no recorded facts: {sorted(unknown)}")
    conn.close()


if __name__ == "__main__":
    main()
