#!/usr/bin/env python3
"""Detect recurring obligations from transaction history.

Seeds the bills model from evidence instead of from memory. A household forgets
the $4.99 thing it signed up for in March; the ledger does not.

Method, deliberately conservative:
  * group by (merchant, account) — the same merchant on two cards is two obligations
  * need >= 3 occurrences before calling anything recurring
  * classify cadence from the MEDIAN gap between charges, and require the gaps to be
    consistent (low relative spread) — a merchant you happen to visit often is not a bill
  * report amount stability separately from cadence stability: a subscription with a
    fixed price and a utility that varies are both real bills, but only one is predictable

Nothing here is written to the database. This prints candidates for review, because
promoting an obligation into Homestead-owned data is a decision, not a detection.
"""
import os
import sqlite3
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

DB = Path(os.environ.get("HOMESTEAD_FINANCE_DB", "/var/lib/homestead/finance/finance.db"))

# Money moving between your own accounts is not an obligation to anyone.
SKIP_CATEGORIES = {
    "Transfer", "Credit Card Payment", "Balance Adjustments", "Buy", "Sell",
    "Dividends & Capital Gains", "Paychecks", "Interest Income", "Cash Back Rewards",
}

CADENCES = [
    ("weekly", 7, 2), ("biweekly", 14, 3), ("monthly", 30.4, 6),
    ("quarterly", 91, 12), ("annual", 365, 30),
]


def classify(gaps):
    """Return (cadence, consistency 0-1) or (None, 0) if the spacing looks incidental."""
    med = statistics.median(gaps)
    for name, days, tol in CADENCES:
        if abs(med - days) <= tol:
            spread = statistics.pstdev(gaps) / med if med else 1
            return name, max(0.0, 1.0 - spread)
    return None, 0.0


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT date, merchant, category, account, amount FROM txn "
        "WHERE amount < 0 AND merchant IS NOT NULL AND merchant != '' ORDER BY date"
    ).fetchall()

    groups = defaultdict(list)
    for r in rows:
        if r["category"] in SKIP_CATEGORIES:
            continue
        groups[(r["merchant"], r["account"])].append(r)

    found = []
    for (merchant, account), txns in groups.items():
        if len(txns) < 3:
            continue
        dates = [date.fromisoformat(t["date"]) for t in txns]
        gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        gaps = [g for g in gaps if g > 0]
        if len(gaps) < 2:
            continue
        cadence, consistency = classify(gaps)
        if not cadence or consistency < 0.45:
            continue
        amounts = [abs(t["amount"]) for t in txns]
        med_amt = statistics.median(amounts)
        amt_spread = statistics.pstdev(amounts) / med_amt if med_amt else 1
        found.append({
            "merchant": merchant, "account": account,
            "category": txns[-1]["category"], "cadence": cadence,
            "n": len(txns), "median_amount": med_amt,
            "consistency": consistency, "fixed": amt_spread < 0.05,
            "amount_spread": amt_spread, "last_seen": txns[-1]["date"],
            "annualised": med_amt * {"weekly": 52, "biweekly": 26, "monthly": 12,
                                     "quarterly": 4, "annual": 1}[cadence],
        })

    found.sort(key=lambda f: -f["annualised"])
    total = sum(f["annualised"] for f in found)

    print(f"{'merchant':<30}{'cadence':<11}{'amount':>10}{'n':>4}{'fixed':>7}"
          f"{'conf':>7}  {'per year':>10}  last seen")
    print("-" * 100)
    for f in found:
        print(f"{f['merchant'][:29]:<30}{f['cadence']:<11}{f['median_amount']:>10,.2f}"
              f"{f['n']:>4}{'yes' if f['fixed'] else 'varies':>7}{f['consistency']:>7.2f}"
              f"  {f['annualised']:>10,.2f}  {f['last_seen']}")
    print("-" * 100)
    print(f"{len(found)} recurring obligations detected · "
          f"{total:,.2f}/yr · {total/12:,.2f}/mo")

    stale = [f for f in found if f["last_seen"] < "2026-07-01"]
    if stale:
        print(f"\nNot seen since before July — cancelled, or a missed payment?")
        for f in stale:
            print(f"  {f['merchant'][:34]:<36} last {f['last_seen']}  "
                  f"{f['median_amount']:,.2f} {f['cadence']}")
    c.close()


if __name__ == "__main__":
    main()
