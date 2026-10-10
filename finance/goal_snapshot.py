#!/usr/bin/env python3
"""Validate and store one manually confirmed Monarch goal snapshot.

This module never connects to Monarch.  A household member reads the current
goal in Monarch and confirms the bounded fields in Homestead.  The resulting
snapshot is a local, timestamped lens over Monarch rather than a competing
system of record.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("HOMESTEAD_FINANCE_DB", "/var/lib/homestead/finance/finance.db"))
ALLOWED_FIELDS = {
    "current_amount",
    "target_amount",
    "target_date",
    "monthly_contribution",
    "status",
}
MAX_AMOUNT = 1_000_000_000
MAX_BACKUPS = 14


def _amount(value, field: str, *, required: bool, positive: bool = False) -> float | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{field} is required")
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if not math.isfinite(number) or number < 0 or number > MAX_AMOUNT:
        raise ValueError(f"{field} must be between 0 and {MAX_AMOUNT}")
    if positive and number <= 0:
        raise ValueError(f"{field} must be greater than 0")
    return round(number, 2)


def _target_date(value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError("target_date must use YYYY-MM")
    year, month = map(int, value.split("-"))
    if year < 2000 or year > 2200 or month < 1 or month > 12:
        raise ValueError("target_date is outside the supported range")
    return value


def _status(value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("status must be text")
    status = value.strip()
    if not status or len(status) > 80:
        raise ValueError("status must contain 1 to 80 characters")
    return status


def normalize_goal_snapshot(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    unexpected = sorted(set(payload) - ALLOWED_FIELDS)
    if unexpected:
        raise ValueError(f"unexpected fields: {', '.join(unexpected)}")
    return {
        "name": "New Home",
        "current_amount": _amount(payload.get("current_amount"), "current_amount", required=True),
        "target_amount": _amount(
            payload.get("target_amount"), "target_amount", required=True, positive=True
        ),
        "target_date": _target_date(payload.get("target_date")),
        "monthly_contribution": _amount(
            payload.get("monthly_contribution"), "monthly_contribution", required=False
        ),
        "status": _status(payload.get("status")),
    }


def ensure_goal_provenance_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(goal_snapshot)")}
    if "source" not in columns:
        conn.execute(
            "ALTER TABLE goal_snapshot ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy-import'"
        )
    if "source_sha256" not in columns:
        conn.execute("ALTER TABLE goal_snapshot ADD COLUMN source_sha256 TEXT")


def backup_database(db_path: Path) -> Path | None:
    """Create a private, consistent rollback copy before changing an existing DB."""
    if not db_path.is_file():
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_dir / f"finance-before-goal-{stamp}.db"
    fd, temporary = tempfile.mkstemp(dir=backup_dir, suffix=".tmp")
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        source_conn = sqlite3.connect(db_path)
        backup_conn = sqlite3.connect(temporary_path)
        try:
            source_conn.backup(backup_conn)
            if backup_conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("backup quick_check failed")
        finally:
            backup_conn.close()
            source_conn.close()
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, destination)
        old = sorted(backup_dir.glob("finance-before-goal-*.db"))[:-MAX_BACKUPS]
        for path in old:
            path.unlink()
        return destination
    finally:
        temporary_path.unlink(missing_ok=True)


def save_goal_snapshot(
    payload: dict,
    db_path: Path | None = None,
    captured_at: str | None = None,
) -> dict:
    goal = normalize_goal_snapshot(payload)
    captured_at = captured_at or datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    try:
        datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("captured_at must be an ISO-8601 timestamp") from exc

    receipt = {
        "schema_version": 1,
        "source": "monarch-manual",
        "captured_at": captured_at,
        "goal": goal,
    }
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    source_sha256 = hashlib.sha256(canonical).hexdigest()

    db_path = Path(db_path or DB)
    backup_database(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript((HERE / "schema.sql").read_text())
        ensure_goal_provenance_columns(conn)
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO import_run(source_file,source_sha256,row_count,imported_at,note) "
            "VALUES (?,?,?,?,?)",
            (
                "monarch-manual:New Home",
                source_sha256,
                1,
                captured_at,
                "Manually confirmed Monarch goal snapshot; no Monarch credentials stored",
            ),
        )
        conn.execute(
            "INSERT INTO goal_snapshot(captured_at,name,current_amount,target_amount,target_date,"
            "monthly_contribution,status,source,source_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                captured_at,
                goal["name"],
                goal["current_amount"],
                goal["target_amount"],
                goal["target_date"],
                goal["monthly_contribution"],
                goal["status"],
                "monarch-manual",
                source_sha256,
            ),
        )
        check = conn.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise sqlite3.DatabaseError(f"SQLite quick_check failed: {check}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        **goal,
        "captured_at": captured_at,
        "source": "monarch-manual",
        "receipt_sha256": source_sha256,
    }
