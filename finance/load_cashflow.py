#!/usr/bin/env python3
"""Load a scraped Monarch cash-flow capture into finance.db.

Monarch's transactions CSV export does not work (five attempts, 2026-08-06), so
category aggregates are captured from the web UI instead. That makes the capture
a transcription, and transcriptions are exactly where fabricated numbers enter —
so this refuses to load a capture whose category sums do not reconcile with the
totals Monarch itself reported on the same screen.

RECONCILIATION IS A GATE, NOT A WARNING. A capture that does not reconcile is a
bad capture; loading it anyway would put an unverifiable figure into the
dashboard, which is the one thing this project's invariants forbid.

Usage:  python3 load_cashflow.py captures/cashflow-2026-YTD.json
"""
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("HOMESTEAD_FINANCE_DB", "/var/lib/homestead/finance/finance.db"))
TOLERANCE = 1.00  # dollars; Monarch rounds its own displayed totals


def main():
    cap_path = Path(sys.argv[1])
    raw = cap_path.read_bytes()
    cap = json.loads(raw)
    sha = hashlib.sha256(raw).hexdigest()

    inc = cap["income"]
    exp = cap["expenses"]
    rep = cap["reported_totals"]
    inc_sum, exp_sum = sum(inc.values()), sum(exp.values())

    # --- the gate ---
    problems = []
    if abs(inc_sum - rep["income"]) > TOLERANCE:
        problems.append(f"income categories sum {inc_sum:,.2f} vs reported {rep['income']:,.2f}")
    if abs(exp_sum - rep["expenses"]) > TOLERANCE:
        problems.append(f"expense categories sum {exp_sum:,.2f} vs reported {rep['expenses']:,.2f}")
    derived_savings = inc_sum - exp_sum
    if abs(derived_savings - rep["savings"]) > TOLERANCE:
        problems.append(f"derived savings {derived_savings:,.2f} vs reported {rep['savings']:,.2f}")
    if problems:
        print("RECONCILIATION FAILED — capture not loaded:")
        for p in problems:
            print("  •", p)
        print("\nRe-capture from Monarch. Do not hand-edit the JSON to make it balance.")
        sys.exit(1)

    print(f"reconciled  income {inc_sum:,.2f} / expenses {exp_sum:,.2f}  (within ${TOLERANCE:.2f})")

    months = cap["span"]["months"]
    period = cap["period"]
    now = datetime.now(timezone.utc).isoformat()[:10]

    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS cashflow_snapshot (
        captured_at TEXT NOT NULL, period TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('income','expense')),
        category TEXT NOT NULL, amount REAL NOT NULL,
        PRIMARY KEY (captured_at, period, kind, category));
    CREATE TABLE IF NOT EXISTS cashflow_total (
        captured_at TEXT NOT NULL, period TEXT NOT NULL,
        income REAL NOT NULL, expenses REAL NOT NULL, savings REAL NOT NULL,
        savings_rate REAL NOT NULL, months REAL NOT NULL,
        txn_count INTEGER, first_txn TEXT, last_txn TEXT,
        source_sha256 TEXT, PRIMARY KEY (captured_at, period));
    """)
    try:
        conn.execute("ALTER TABLE cashflow_total ADD COLUMN source_sha256 TEXT")
    except sqlite3.OperationalError:
        pass

    conn.execute("DELETE FROM cashflow_snapshot WHERE captured_at=? AND period=?", (now, period))
    for kind, rows in (("income", inc), ("expense", exp)):
        for cat, amt in rows.items():
            conn.execute("INSERT INTO cashflow_snapshot VALUES (?,?,?,?,?)",
                         (now, period, kind, cat, amt))

    conn.execute(
        "INSERT OR REPLACE INTO cashflow_total VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (now, period, inc_sum, exp_sum, derived_savings, rep["savings_rate_pct"], months,
         rep.get("txn_count"), cap["span"]["first_txn"], cap["span"]["last_txn"], sha),
    )
    conn.commit()

    w2_cats = set(cap.get("w2_income_categories", []))
    w2 = sum(v for k, v in inc.items() if k in w2_cats)
    print(f"loaded      {len(inc)} income + {len(exp)} expense categories, period {period}")
    print(f"monthly     income {inc_sum/months:,.2f}  expenses {exp_sum/months:,.2f}  "
          f"surplus {derived_savings/months:,.2f}")
    print(f"qualifying  W-2 {w2/months:,.2f}/mo ({w2/inc_sum*100:.1f}%)  "
          f"non-W-2 {(inc_sum-w2)/months:,.2f}/mo ({(inc_sum-w2)/inc_sum*100:.1f}%)")
    print(f"sha256      {sha}")
    conn.close()


if __name__ == "__main__":
    main()
