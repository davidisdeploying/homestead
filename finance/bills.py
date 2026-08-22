#!/usr/bin/env python3
"""The bills model — the first data Homestead OWNS rather than borrows from Monarch.

Scope note (homestead-vault/AGENTS.md, 2026-08-06): finances are a lens over Monarch
and Homestead owns no number Monarch holds. Bills are the declared exception, promoted
deliberately: **Monarch tracks the payment; it does not model the obligation.** A
$65.33 charge categorised "Phone" and a 24-month installment loan with a balance, a
term and a credit-report entry are not the same fact, and only one of them matters to
an underwriter.

THE DISTINCTION THIS MODEL EXISTS FOR:

  obligation — owed whether or not you show up. Rent, insurance, phone, subscriptions,
               a loan. Missing one has a consequence beyond going hungry.
  commitment — recurring by arrangement, not by contract. Allowances, a standing
               haircut, a repeat prescription. Real and predictable; not enforceable.
  habit      — frequent spending that a naive recurrence detector flags as a bill.
               Kroger every week is not a bill. This tier exists to be EXCLUDED.

Cadence detection alone cannot tell these apart — it flagged Kroger (27 charges,
weekly) above the actual insurance premium. Category is what separates them.

Usage:
  python3 bills.py --seed     # classify detections and write the bill table
  python3 bills.py            # show the current bill table
"""
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DB = Path(os.environ.get("HOMESTEAD_FINANCE_DB", "/var/lib/homestead/finance/finance.db"))

OBLIGATION_CATEGORIES = {
    "Rent", "Insurance", "Phone", "Digital Subscriptions", "TV Streaming Subscriptions",
    "Gym Memberships", "Utilities", "Water", "Internet", "Home Services", "Education",
    "Business Utilities",
}
COMMITMENT_CATEGORIES = {"Allowance", "Medical", "Grooming"}
# Everything else is treated as habit and excluded.

# Merchants whose statement text proves a credit obligation regardless of how the
# transaction was categorised. Found the hard way: the iPhone Upgrade Program is a
# Citizens One installment loan that Monarch files under "Phone".
INSTALLMENT_MARKERS = ("loan", "installment", "upgrade program", "affirm", "klarna", "afterpay")

CADENCE_DAYS = {"weekly": 7, "biweekly": 14, "monthly": 30.4, "quarterly": 91, "annual": 365}
CADENCE_PER_YEAR = {"weekly": 52, "biweekly": 26, "monthly": 12, "quarterly": 4, "annual": 1}


def ensure_schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS bill (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant        TEXT NOT NULL,
        account         TEXT,
        label           TEXT NOT NULL,
        category        TEXT,
        tier            TEXT NOT NULL CHECK (tier IN ('obligation','commitment')),
        obligation_type TEXT NOT NULL CHECK (obligation_type IN
                          ('rent','insurance','phone','subscription','utility',
                           'membership','installment_loan','internal','other')),
        cadence         TEXT NOT NULL,
        amount          REAL NOT NULL,
        amount_is_fixed INTEGER NOT NULL DEFAULT 0,
        annualised      REAL NOT NULL,
        counts_in_dti   INTEGER NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','lapsed','cancelled','watch')),
        source          TEXT NOT NULL DEFAULT 'detected',
        confidence      REAL,
        occurrences     INTEGER,
        first_seen      TEXT,
        last_seen       TEXT,
        next_due_est    TEXT,
        notes           TEXT NOT NULL DEFAULT '',
        UNIQUE(merchant, account, cadence)
    );
    """)


def obligation_type(cat, statement_blob):
    s = (statement_blob or "").lower()
    if any(m in s for m in INSTALLMENT_MARKERS):
        return "installment_loan"
    return {
        "Rent": "rent", "Insurance": "insurance", "Phone": "phone",
        "Digital Subscriptions": "subscription", "TV Streaming Subscriptions": "subscription",
        "Gym Memberships": "membership", "Water": "utility", "Utilities": "utility",
        "Internet": "utility", "Allowance": "internal",
    }.get(cat, "other")


def classify(gaps):
    med = statistics.median(gaps)
    for name, days in CADENCE_DAYS.items():
        tol = {"weekly": 2, "biweekly": 3, "monthly": 6, "quarterly": 12, "annual": 30}[name]
        if abs(med - days) <= tol:
            spread = statistics.pstdev(gaps) / med if med else 1
            return name, max(0.0, 1.0 - spread)
    return None, 0.0


def seed(c):
    rows = c.execute(
        "SELECT date, merchant, category, account, statement, amount FROM txn "
        "WHERE amount < 0 AND merchant IS NOT NULL AND merchant != '' ORDER BY date"
    ).fetchall()

    groups = defaultdict(list)
    for r in rows:
        groups[(r["merchant"], r["account"])].append(r)

    today = c.execute("SELECT MAX(date) d FROM txn").fetchone()["d"]
    kept = skipped_habit = 0

    for (merchant, account), txns in groups.items():
        if len(txns) < 3:
            continue
        cat = txns[-1]["category"]
        blob = " ".join((t["statement"] or "") for t in txns) + " " + merchant

        if cat in OBLIGATION_CATEGORIES:
            tier = "obligation"
        elif cat in COMMITMENT_CATEGORIES:
            tier = "commitment"
        elif any(m in blob.lower() for m in INSTALLMENT_MARKERS):
            tier = "obligation"   # a loan is a loan however it was filed
        else:
            skipped_habit += 1
            continue

        dates = [date.fromisoformat(t["date"]) for t in txns]
        gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        gaps = [g for g in gaps if g > 0]
        if len(gaps) < 2:
            continue
        cadence, conf = classify(gaps)
        if not cadence or conf < 0.40:
            continue

        amounts = [abs(t["amount"]) for t in txns]
        med_amt = statistics.median(amounts)
        fixed = (statistics.pstdev(amounts) / med_amt) < 0.05 if med_amt else False
        otype = obligation_type(cat, blob)
        last = dates[-1]
        nxt = last + timedelta(days=round(CADENCE_DAYS[cadence]))
        # Two full cycles missed reads as lapsed rather than active.
        lapsed = (date.fromisoformat(today) - last).days > CADENCE_DAYS[cadence] * 2

        c.execute(
            "INSERT INTO bill(merchant, account, label, category, tier, obligation_type, cadence,"
            " amount, amount_is_fixed, annualised, counts_in_dti, status, source, confidence,"
            " occurrences, first_seen, last_seen, next_due_est, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(merchant, account, cadence) DO UPDATE SET"
            " amount=excluded.amount, annualised=excluded.annualised, status=excluded.status,"
            " occurrences=excluded.occurrences, last_seen=excluded.last_seen,"
            " next_due_est=excluded.next_due_est, confidence=excluded.confidence",
            (merchant, account, merchant, cat, tier, otype, cadence, round(med_amt, 2),
             int(fixed), round(med_amt * CADENCE_PER_YEAR[cadence], 2),
             int(otype == "installment_loan"),
             "lapsed" if lapsed else "active", "detected", round(conf, 2), len(txns),
             dates[0].isoformat(), last.isoformat(), nxt.isoformat(), ""),
        )
        kept += 1

    c.commit()
    print(f"seeded {kept} bills · {skipped_habit} merchant groups excluded as habit "
          f"(frequent, not owed)")


def show(c):
    rows = c.execute("SELECT * FROM bill ORDER BY counts_in_dti DESC, annualised DESC").fetchall()
    if not rows:
        print("no bills — run with --seed")
        return
    print(f"{'label':<26}{'type':<18}{'cadence':<10}{'amount':>9}{'fixed':>7}"
          f"{'/year':>10}  {'status':<9}{'next~':<12}")
    print("-" * 104)
    for r in rows:
        flag = " ← DTI" if r["counts_in_dti"] else ""
        print(f"{r['label'][:25]:<26}{r['obligation_type']:<18}{r['cadence']:<10}"
              f"{r['amount']:>9,.2f}{'yes' if r['amount_is_fixed'] else 'varies':>7}"
              f"{r['annualised']:>10,.2f}  {r['status']:<9}{r['next_due_est'] or '':<12}{flag}")
    print("-" * 104)
    act = [r for r in rows if r["status"] == "active"]
    obl = [r for r in act if r["tier"] == "obligation"]
    dti = [r for r in act if r["counts_in_dti"]]
    print(f"active: {len(act)}   ·   obligations {sum(r['annualised'] for r in obl)/12:,.2f}/mo"
          f"   ·   all active {sum(r['annualised'] for r in act)/12:,.2f}/mo")
    if dti:
        print(f"\nCOUNTS TOWARD DTI — {sum(r['amount'] for r in dti):,.2f}/mo:")
        for r in dti:
            print(f"  {r['label']} — {r['amount']:,.2f}/mo, filed under '{r['category']}', "
                  f"not linked as a loan account in Monarch")


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    if "--seed" in sys.argv:
        seed(conn)
        print()
    show(conn)
    conn.close()
