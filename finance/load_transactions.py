#!/usr/bin/env python3
"""Load a Monarch transactions CSV and derive cash-flow aggregates from the rows.

This supersedes the scraped-aggregate path. Aggregates computed from rows beat
aggregates read off a screen: they are reproducible, they can be re-cut by any
period, and they do not depend on a UI that may re-render.

MONARCH'S CASH-FLOW SEMANTICS, reverse-engineered and verified 2026-08-06:

  1. Drop transfer-like categories entirely (Transfer, Credit Card Payment, ...).
  2. NET within each remaining category — a refund inside "Pets" reduces Pets
     spending rather than counting as income.
  3. Split by the sign of the net: positive nets are income, negative are expense.

Applying that to the 2026 export reproduces Monarch's own figures exactly:
income $89,778.60 and expenses $35,424.67, to the penny. The naive
sum-positives/sum-negatives reading overstates BOTH sides by $4,787.00, which is
precisely the wrong-signed total inside categories. That $4,787 is the whole
reason this rule is written down instead of assumed.

Usage:  python3 load_transactions.py <Transactions.csv> [--period-start 2026-01-01]
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

# Categories Monarch excludes from cash flow: money moving between your own
# accounts, not money entering or leaving the household.
TRANSFER_CATEGORIES = {
    "Transfer", "Credit Card Payment", "Balance Adjustments",
    "Buy", "Sell", "Dividends & Capital Gains",
}

W2_CATEGORIES = {"Paychecks"}


def netted_cashflow(rows):
    """Apply Monarch's netting rule. Returns (income_by_cat, expense_by_cat)."""
    net = {}
    for r in rows:
        cat = r["Category"]
        if cat in TRANSFER_CATEGORIES:
            continue
        net[cat] = net.get(cat, 0.0) + float(r["Amount"])
    income = {c: v for c, v in net.items() if v > 0}
    expense = {c: -v for c, v in net.items() if v < 0}
    return income, expense


def main():
    path = Path(sys.argv[1]).expanduser()
    start = "2026-01-01"
    if "--period-start" in sys.argv:
        start = sys.argv[sys.argv.index("--period-start") + 1]

    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    all_rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS txn (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        row_hash    TEXT NOT NULL UNIQUE,   -- CSV has no stable id; hash the row
        date        TEXT NOT NULL,
        merchant    TEXT,
        category    TEXT,
        account     TEXT,
        statement   TEXT,
        notes       TEXT,
        amount      REAL NOT NULL,
        tags        TEXT,
        owner       TEXT,
        reviewed    TEXT,
        import_id   INTEGER REFERENCES import_run(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_txn_date ON txn(date);
    CREATE INDEX IF NOT EXISTS idx_txn_cat  ON txn(category);
    """)

    conn.execute(
        "INSERT INTO import_run(source_file, source_sha256, row_count, imported_at, note) "
        "VALUES (?,?,?,?,?)",
        (path.name, sha, len(all_rows), now, "Monarch transactions export"),
    )
    import_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # A household genuinely makes two identical charges in a day — two $21.23 Apple
    # renewals, two $43.54 Kroger runs, a repeated interest posting. Hashing only the
    # row's content silently collapses those into one and quietly loses real money
    # (17 rows on the first 2026 export). Disambiguate with an occurrence index so
    # identical rows survive while re-imports stay idempotent.
    added = 0
    occurrence = {}
    for r in all_rows:
        key = "|".join([r["Date"], r.get("Merchant", ""), r.get("Category", ""),
                        r.get("Account", ""), r["Amount"], r.get("Original Statement", "")])
        occurrence[key] = occurrence.get(key, 0) + 1
        h = hashlib.sha256(f"{key}|#{occurrence[key]}".encode()).hexdigest()
        cur = conn.execute(
            "INSERT OR IGNORE INTO txn(row_hash, date, merchant, category, account, statement, "
            "notes, amount, tags, owner, reviewed, import_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (h, r["Date"], r.get("Merchant"), r.get("Category"), r.get("Account"),
             r.get("Original Statement"), r.get("Notes"), float(r["Amount"]),
             r.get("Tags"), r.get("Owner"), r.get("Reviewed"), import_id))
        added += cur.rowcount

    period_rows = [r for r in all_rows if r["Date"] >= start]
    income, expense = netted_cashflow(period_rows)
    inc_t, exp_t = sum(income.values()), sum(expense.values())
    dates = sorted(r["Date"] for r in all_rows)
    months = (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(start)).days / 30.44
    period = f"{start[:4]}-YTD"
    today = now[:10]

    conn.execute("DELETE FROM cashflow_snapshot WHERE captured_at=? AND period=?", (today, period))
    for kind, d in (("income", income), ("expense", expense)):
        for cat, amt in d.items():
            conn.execute("INSERT INTO cashflow_snapshot VALUES (?,?,?,?,?)",
                         (today, period, kind, cat, round(amt, 2)))
    conn.execute(
        "INSERT OR REPLACE INTO cashflow_total VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (today, period, round(inc_t, 2), round(exp_t, 2), round(inc_t - exp_t, 2),
         round((inc_t - exp_t) / inc_t * 100, 1), round(months, 2), len(period_rows),
         dates[0], dates[-1], sha))
    conn.commit()

    w2 = sum(v for c, v in income.items() if c in W2_CATEGORIES)
    print(f"file        {path.name}")
    print(f"sha256      {sha}")
    print(f"rows        {len(all_rows)} in file, {added} new, "
          f"{conn.execute('SELECT COUNT(*) FROM txn').fetchone()[0]} total in db")
    print(f"span        {dates[0]} -> {dates[-1]}")
    print(f"\nperiod {period} ({len(period_rows)} rows, {months:.2f} months) — netted per Monarch's rule")
    print(f"  income    {inc_t:>12,.2f}   ({inc_t/months:>9,.2f}/mo)")
    print(f"  expenses  {exp_t:>12,.2f}   ({exp_t/months:>9,.2f}/mo)")
    print(f"  surplus   {inc_t-exp_t:>12,.2f}   ({(inc_t-exp_t)/months:>9,.2f}/mo)")
    print(f"  rate      {(inc_t-exp_t)/inc_t*100:>11.1f}%")
    print(f"  W-2       {w2/months:>12,.2f}/mo ({w2/inc_t*100:.1f}%)   "
          f"non-W-2 {(inc_t-w2)/months:,.2f}/mo ({(inc_t-w2)/inc_t*100:.1f}%)")
    conn.close()


if __name__ == "__main__":
    main()
