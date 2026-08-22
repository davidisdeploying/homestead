#!/usr/bin/env python3
"""Load a normalized Monarch MCP snapshot into Homestead's existing finance schema.

The connector is intentionally outside this repository. It should emit the bounded
JSON contract documented in finance/README.md and pipe it to this adapter. CSV stays
the offline fallback and the independent comparison source.

Usage:
  monarch-connector export --json | python3 finance/load_mcp.py -
  python3 finance/load_mcp.py normalized-monarch-mcp.json --period-start 2026-01-01
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from load_transactions import netted_cashflow

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("HOMESTEAD_FINANCE_DB", "/var/lib/homestead/finance/finance.db"))


def fail(message: str) -> None:
    raise SystemExit(f"invalid MCP snapshot: {message}")


def read_payload(source: str) -> tuple[bytes, dict]:
    raw = sys.stdin.buffer.read() if source == "-" else Path(source).expanduser().read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"JSON parse failed at byte {exc.pos}")
    if not isinstance(payload, dict):
        fail("root must be an object")
    if payload.get("schema_version") != 1:
        fail("schema_version must be 1")
    if payload.get("source") != "monarch-mcp":
        fail("source must be monarch-mcp")
    for key in ("captured_at", "accounts", "balances", "goals", "networth", "transactions"):
        if key not in payload:
            fail(f"missing {key}")
    for key in ("accounts", "balances", "goals", "transactions"):
        if not isinstance(payload[key], list):
            fail(f"{key} must be an array")
    if not isinstance(payload["networth"], dict):
        fail("networth must be an object")
    return raw, payload


def required(row: dict, fields: tuple[str, ...], label: str) -> None:
    missing = [field for field in fields if row.get(field) in (None, "")]
    if missing:
        fail(f"{label} missing {', '.join(missing)}")


def load(source: str, period_start: str) -> None:
    raw, payload = read_payload(source)
    source_sha = hashlib.sha256(raw).hexdigest()
    captured = str(payload["captured_at"])
    captured_date = captured[:10]
    datetime.fromisoformat(captured.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(DB)
    try:
        conn.executescript((HERE / "schema.sql").read_text())
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS txn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            row_hash TEXT NOT NULL UNIQUE,
            date TEXT NOT NULL,
            merchant TEXT,
            category TEXT,
            account TEXT,
            statement TEXT,
            notes TEXT,
            amount REAL NOT NULL,
            tags TEXT,
            owner TEXT,
            reviewed TEXT,
            import_id INTEGER REFERENCES import_run(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_txn_date ON txn(date);
        CREATE INDEX IF NOT EXISTS idx_txn_cat ON txn(category);
        CREATE TABLE IF NOT EXISTS cashflow_snapshot (
            captured_at TEXT NOT NULL, period TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('income','expense')),
            category TEXT NOT NULL, amount REAL NOT NULL,
            PRIMARY KEY (captured_at, period, kind, category)
        );
        CREATE TABLE IF NOT EXISTS cashflow_total (
            captured_at TEXT NOT NULL, period TEXT NOT NULL,
            income REAL NOT NULL, expenses REAL NOT NULL, savings REAL NOT NULL,
            savings_rate REAL NOT NULL, months REAL NOT NULL,
            txn_count INTEGER, first_txn TEXT, last_txn TEXT,
            source_sha256 TEXT, PRIMARY KEY (captured_at, period)
        );
        """)
        old = conn.execute("SELECT id FROM import_run WHERE source_sha256=?", (source_sha,)).fetchone()
        if old:
            print(f"already imported  sha256={source_sha}  import_id={old[0]}")
            return
        conn.execute(
            "INSERT INTO import_run(source_file, source_sha256, row_count, imported_at, note) VALUES (?,?,?,?,?)",
            ("monarch-mcp", source_sha, len(payload["transactions"]), now, "Normalized Monarch MCP snapshot"),
        )
        import_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        for row in payload["accounts"]:
            required(row, ("name",), "account")
            conn.execute(
                "INSERT INTO account(name, category, subtype, owner, credit_limit, is_liability, created_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET category=excluded.category, "
                "subtype=excluded.subtype, owner=excluded.owner, credit_limit=excluded.credit_limit, "
                "is_liability=excluded.is_liability",
                (row["name"], row.get("category"), row.get("subtype"), row.get("owner"),
                 row.get("credit_limit"), int(bool(row.get("is_liability"))), now),
            )
        account_ids = {row[0]: row[1] for row in conn.execute("SELECT name,id FROM account")}

        for row in payload["balances"]:
            required(row, ("account", "date", "balance"), "balance")
            if row["account"] not in account_ids:
                fail(f"balance references unknown account {row['account']!r}")
            conn.execute(
                "INSERT INTO balance(account_id,date,balance,import_id) VALUES (?,?,?,?) "
                "ON CONFLICT(account_id,date) DO UPDATE SET balance=excluded.balance,import_id=excluded.import_id",
                (account_ids[row["account"]], row["date"], float(row["balance"]), import_id),
            )

        for row in payload["goals"]:
            required(row, ("name", "current_amount", "target_amount"), "goal")
            conn.execute(
                "INSERT INTO goal_snapshot(captured_at,name,current_amount,target_amount,target_date,monthly_contribution,status) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(captured_at,name) DO UPDATE SET "
                "current_amount=excluded.current_amount,target_amount=excluded.target_amount,target_date=excluded.target_date," 
                "monthly_contribution=excluded.monthly_contribution,status=excluded.status",
                (captured_date, row["name"], float(row["current_amount"]), float(row["target_amount"]),
                 row.get("target_date"), row.get("monthly_contribution"), row.get("status")),
            )

        nw = payload["networth"]
        required(nw, ("net_worth", "assets", "liabilities"), "networth")
        conn.execute(
            "INSERT INTO networth_snapshot(captured_at,net_worth,assets,liabilities,cash,investments,vehicles,credit_cards) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(captured_at) DO UPDATE SET net_worth=excluded.net_worth," 
            "assets=excluded.assets,liabilities=excluded.liabilities,cash=excluded.cash,investments=excluded.investments," 
            "vehicles=excluded.vehicles,credit_cards=excluded.credit_cards",
            (captured_date, float(nw["net_worth"]), float(nw["assets"]), float(nw["liabilities"]),
             nw.get("cash"), nw.get("investments"), nw.get("vehicles"), nw.get("credit_cards")),
        )

        normalized_txns = []
        occurrence: dict[str, int] = {}
        added = 0
        for row in payload["transactions"]:
            required(row, ("date", "category", "amount"), "transaction")
            normalized = {
                "Date": str(row["date"]), "Merchant": str(row.get("merchant") or ""),
                "Category": str(row["category"]), "Account": str(row.get("account") or ""),
                "Amount": str(row["amount"]), "Original Statement": str(row.get("statement") or ""),
            }
            normalized_txns.append(normalized)
            identity = str(row.get("id") or "|".join(normalized.values()))
            occurrence[identity] = occurrence.get(identity, 0) + 1
            row_hash = hashlib.sha256(f"mcp|{identity}|#{occurrence[identity]}".encode()).hexdigest()
            cur = conn.execute(
                "INSERT OR IGNORE INTO txn(row_hash,date,merchant,category,account,statement,notes,amount,tags,owner,reviewed,import_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (row_hash, row["date"], row.get("merchant"), row["category"], row.get("account"),
                 row.get("statement"), row.get("notes"), float(row["amount"]), row.get("tags"),
                 row.get("owner"), row.get("reviewed"), import_id),
            )
            added += cur.rowcount

        period_rows = [row for row in normalized_txns if row["Date"] >= period_start]
        if not period_rows:
            fail(f"no transactions on or after {period_start}")
        income, expense = netted_cashflow(period_rows)
        first_date = min(row["Date"] for row in period_rows)
        last_date = max(row["Date"] for row in period_rows)
        months = max((datetime.fromisoformat(last_date) - datetime.fromisoformat(period_start)).days / 30.44, 1 / 30.44)
        period = f"{period_start[:4]}-YTD"
        income_total, expense_total = sum(income.values()), sum(expense.values())
        conn.execute("DELETE FROM cashflow_snapshot WHERE captured_at=? AND period=?", (captured_date, period))
        for kind, values in (("income", income), ("expense", expense)):
            for category, amount in values.items():
                conn.execute("INSERT INTO cashflow_snapshot VALUES (?,?,?,?,?)", (captured_date, period, kind, category, round(amount, 2)))
        conn.execute(
            "INSERT OR REPLACE INTO cashflow_total VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (captured_date, period, round(income_total, 2), round(expense_total, 2),
             round(income_total - expense_total, 2),
             round((income_total - expense_total) / income_total * 100, 1) if income_total else 0,
             round(months, 2), len(period_rows), first_date, last_date, source_sha),
        )
        conn.commit()
        print(f"source     monarch-mcp")
        print(f"sha256     {source_sha}")
        print(f"accounts   {len(payload['accounts'])}")
        print(f"balances   {len(payload['balances'])}")
        print(f"transactions {len(payload['transactions'])} ({added} new)")
        print(f"period     {period}  {first_date} -> {last_date}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: load_mcp.py <snapshot.json|-> [--period-start YYYY-MM-DD]")
    start = "2026-01-01"
    if "--period-start" in sys.argv:
        start = sys.argv[sys.argv.index("--period-start") + 1]
    load(sys.argv[1], start)
