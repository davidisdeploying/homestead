"""Build the derived-only finance payload served by Homestead."""
from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path


def database_path() -> Path:
    return Path(os.environ.get("HOMESTEAD_FINANCE_DB", "/var/lib/homestead/finance/finance.db"))


def build_bills_payload(db_path: Path | None = None) -> dict:
    """Return obligation facts needed by the household register, never transactions."""
    conn = sqlite3.connect(db_path or database_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, label, category, tier, obligation_type, cadence, amount, amount_is_fixed, "
            "annualised, counts_in_dti, status, source, confidence, occurrences, first_seen, "
            "last_seen, next_due_est FROM bill ORDER BY status='active' DESC, label"
        ).fetchall()
        return {
            "bills": [dict(row) for row in rows],
            "ownership": "Homestead owns obligations; Monarch owns payments and balances.",
        }
    finally:
        conn.close()


def build_dashboard_payload(db_path: Path | None = None) -> dict:
    conn = sqlite3.connect(db_path or database_path())
    conn.row_factory = sqlite3.Row

    def one(query, *args):
        row = conn.execute(query, args).fetchone()
        if row is None:
            raise RuntimeError("finance database is missing required snapshots")
        return row

    try:
        nw = one("SELECT * FROM networth_snapshot ORDER BY captured_at DESC LIMIT 1")
        goal = one("SELECT * FROM goal_snapshot WHERE name='New Home' ORDER BY captured_at DESC LIMIT 1")
        flow = one("SELECT * FROM cashflow_total ORDER BY captured_at DESC LIMIT 1")
        as_of = one("SELECT MAX(date) d FROM balance")["d"]

        rows = conn.execute(
            "SELECT date, balance FROM balance b JOIN account a ON a.id=b.account_id "
            "WHERE a.name='REDACTED' ORDER BY date"
        ).fetchall()
        month_ends = {}
        for row in rows:
            month_ends[row["date"][:7]] = row["balance"]
        months = sorted(month_ends)
        series = [
            [datetime.date(int(month[:4]), int(month[5:]), 1).strftime("%b"), round(month_ends[month], 2)]
            for month in months
        ]
        deltas = [month_ends[months[i]] - month_ends[months[i - 1]] for i in range(1, len(months))]
        steady = deltas[1:-1] if len(deltas) > 2 else deltas
        if not steady:
            raise RuntimeError("finance database does not contain enough savings history")
        steady_avg = sum(steady) / len(steady)
        hit = datetime.date.fromisoformat(as_of) + datetime.timedelta(
            days=(goal["target_amount"] - goal["current_amount"]) / steady_avg * 30.44
        )

        dti_rows = conn.execute(
            "SELECT label, amount, category FROM bill WHERE counts_in_dti=1 AND status='active'"
        ).fetchall()
        dti_monthly = sum(row["amount"] for row in dti_rows)
        bills = one(
            "SELECT COUNT(*) n, SUM(annualised)/12 mo FROM bill "
            "WHERE status='active' AND tier='obligation'"
        )
        credit_limit = one("SELECT SUM(credit_limit) t FROM account WHERE credit_limit IS NOT NULL")["t"] or 0
        credit_balance = one(
            "SELECT SUM(ABS(b.balance)) t FROM balance b JOIN account a ON a.id=b.account_id "
            "WHERE a.is_liability=1 AND b.date=(SELECT MAX(date) FROM balance)"
        )["t"] or 0
        income_rows = conn.execute(
            "SELECT category, amount FROM cashflow_snapshot WHERE kind='income' AND captured_at=? AND period=?",
            (flow["captured_at"], flow["period"]),
        ).fetchall()
        w2 = sum(row["amount"] for row in income_rows if row["category"] == "Paychecks")
        non_w2 = flow["income"] - w2
        top = conn.execute(
            "SELECT category, amount FROM cashflow_snapshot WHERE kind='expense' AND captured_at=? "
            "AND period=? ORDER BY amount DESC LIMIT 6",
            (flow["captured_at"], flow["period"]),
        ).fetchall()
        counts = one("SELECT (SELECT COUNT(*) FROM account) accounts, (SELECT COUNT(*) FROM balance) balances")
        period_months = flow["months"]
        return {
            "asOf": as_of,
            "netWorth": nw["net_worth"], "assets": nw["assets"], "liabilities": nw["liabilities"],
            "cash": nw["cash"], "investments": nw["investments"], "vehicles": nw["vehicles"],
            "creditLimit": credit_limit, "creditBalance": credit_balance,
            "utilization": credit_balance / credit_limit * 100 if credit_limit else 0,
            "installmentDebt": dti_monthly,
            "installmentDebtItems": [
                {"label": row["label"], "amount": row["amount"], "filedAs": row["category"]}
                for row in dti_rows
            ],
            "billsMonthly": bills["mo"] or 0, "billsCount": bills["n"] or 0,
            "goalCurrent": goal["current_amount"], "goalTarget": goal["target_amount"],
            "steadyMonthly": steady_avg, "projectedHit": hit.strftime("%b %Y"), "savings": series,
            "accountCount": counts["accounts"], "balanceCount": counts["balances"],
            "flow": {
                "periodLabel": flow["period"], "transactionCount": flow["txn_count"],
                "months": period_months, "income": flow["income"], "expenses": flow["expenses"],
                "monthlyIncome": flow["income"] / period_months,
                "monthlyExpenses": flow["expenses"] / period_months,
                "monthlySurplus": (flow["income"] - flow["expenses"]) / period_months,
                "savingsRate": flow["savings_rate"],
                "rentMonthly": next((row["amount"] for row in top if row["category"] == "Rent"), 0) / period_months,
                "w2Monthly": w2 / period_months, "nonW2Monthly": non_w2 / period_months,
                "nonW2Pct": non_w2 / flow["income"] * 100 if flow["income"] else 0,
                "topExpenses": [[row["category"], row["amount"]] for row in top],
            },
        }
    finally:
        conn.close()
