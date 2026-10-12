"""The Gmail -> Scout import run: bounded, idempotent, and read-only.

Two lessons from Prospect's 2026-08-07 outage are wired in here deliberately.

**Exit 0 is not proof.** A run that lists mail and imports nothing looks identical whether
the market is quiet or the parser has silently stopped matching. So the summary reports
every stage separately (listed / skipped / imported / discoveries seen / genuinely new /
ignored / parse_empty / errors), and acceptance requires inspecting real parsed field
values, not just a green line.

**Staleness is measured from accepted mail, not from discoveries.** Repeat alerts about
the same property legitimately create zero discoveries while ingestion is perfectly
healthy, so the freshness signal is the newest `received_at` among `imported` receipts.
"""
import os
from datetime import datetime, timezone

from . import db
from .adapters import ADAPTERS, adapter_for, registered_senders
from .mime import message_text, received_at, sender_address

DEFAULT_LOOKBACK_DAYS = 14
DEFAULT_MAX_RESULTS = 100

# Deliberately None. The runbook requires choosing the production threshold only after
# measuring the real alert cadence -- copying Prospect's 3-day job-alert number would be
# a guess about a different mail stream. Until it is measured, freshness is reported and
# never alerted on. Set HOMESTEAD_SCOUT_STALE_DAYS once the cadence is known.
DEFAULT_STALE_THRESHOLD_DAYS = None


class NoAdaptersConfigured(RuntimeError):
    """Raised instead of issuing a broad Gmail query with nothing verified to parse."""


def stale_threshold_days(env=None):
    raw = (env or os.environ).get("HOMESTEAD_SCOUT_STALE_DAYS")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_STALE_THRESHOLD_DAYS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_STALE_THRESHOLD_DAYS
    return value if value > 0 else DEFAULT_STALE_THRESHOLD_DAYS


def build_query(lookback_days=DEFAULT_LOOKBACK_DAYS, adapters=ADAPTERS):
    """Gmail query built ONLY from verified alert senders.

    Fails closed when no adapter is registered. The alternative -- querying
    `from:zillow.com OR from:redfin.com` and heuristically parsing whatever returns --
    would ingest marketing, recommendation cards, and account mail as property leads.
    """
    senders = []
    for adapter in adapters:
        for sender in adapter.senders:
            if sender not in senders:
                senders.append(sender)
    if not senders:
        raise NoAdaptersConfigured(
            "no verified Zillow/Redfin alert template is registered, so there is no sender "
            "to query. See scout/adapters.py for what reconnaissance is required first."
        )
    return f"from:({' OR '.join(senders)}) newer_than:{int(lookback_days)}d"


def ingestion_freshness(conn, now=None, threshold_days=None):
    """Interpret how long it has been since accepted alert mail last arrived."""
    threshold = threshold_days if threshold_days is not None else stale_threshold_days()
    last_at = db.newest_accepted_receipt(conn)
    base = {"last_accepted_at": last_at, "days_since": None,
            "threshold_days": threshold, "stale": False}

    if not last_at:
        # A fresh install has no baseline. Alerting here would fire forever on day one.
        return {**base, "reason": "no accepted alert mail has been ingested yet"}
    try:
        parsed = datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return {**base, "reason": "stored received_at could not be parsed"}

    reference = now or datetime.now(timezone.utc)
    days = (reference - parsed).total_seconds() / 86400.0
    result = {**base, "days_since": round(days, 2)}
    if threshold is None:
        return {**result, "reason": "alert cadence not yet measured; freshness reported only"}
    result["stale"] = days >= threshold
    result["reason"] = ("no accepted alert mail within the threshold" if result["stale"]
                        else "fresh")
    return result


def run_import(conn, auth, *, query=None, dry_run=False, lookback_days=DEFAULT_LOOKBACK_DAYS,
               max_results=DEFAULT_MAX_RESULTS, adapters=ADAPTERS, gmail=None, now=None):
    """Execute one bounded import pass.

    `dry_run` reads Gmail and reports exactly what would happen, but writes no discovery,
    no sighting, and no receipt.
    """
    if gmail is None:
        from . import gmail as gmail_module
        gmail = gmail_module
    resolved_query = query or build_query(lookback_days, adapters)

    summary = {
        "query": resolved_query,
        "dry_run": bool(dry_run),
        "listed": 0,
        "skipped_known": 0,
        "imported_messages": 0,
        "discoveries_seen": 0,
        "new_discoveries": 0,
        "new_sightings": 0,
        "ignored": 0,
        "parse_empty": 0,
        "errors": [],
    }

    known = db.known_message_ids(conn)
    profile = db.latest_profile(conn)
    summary["profile"] = (
        {"id": profile["id"], "label": profile["label"], "criteria": profile["profile"]}
        if profile else None
    )
    if not profile:
        summary["ranking"] = "unranked — no owner-approved buying criteria are stored"

    candidates = gmail.list_messages(auth, resolved_query, max_results)
    summary["listed"] = len(candidates)

    # Oldest first so first_seen_at reflects real arrival order.
    for candidate in reversed(candidates):
        message_id = candidate.get("id")
        if not message_id:
            continue
        if message_id in known:
            summary["skipped_known"] += 1
            continue
        try:
            message = gmail.get_message(auth, message_id)
            decoded = message_text(message)
            sender = sender_address(decoded["headers"].get("from"))
            adapter = adapter_for(sender, adapters)
            receipt = {
                "gmail_message_id": message_id,
                "gmail_thread_id": message.get("threadId"),
                "received_at": received_at(message),
            }

            if adapter is None:
                summary["ignored"] += 1
                if not dry_run:
                    db.record_receipt(conn, **receipt, status="ignored",
                                      detail="sender is not a verified alert sender")
                continue

            parsed = adapter.parse(message, decoded)
            leads = parsed.get("leads") or []
            if not parsed.get("accepted"):
                summary["ignored"] += 1
                if not dry_run:
                    db.record_receipt(conn, **receipt, source=adapter.source,
                                      status="ignored", detail=parsed.get("reason"))
                continue
            if not leads:
                summary["parse_empty"] += 1
                if not dry_run:
                    db.record_receipt(conn, **receipt, source=adapter.source,
                                      status="parse_empty", detail=parsed.get("reason"))
                continue

            summary["imported_messages"] += 1
            summary["discoveries_seen"] += len(leads)
            if not dry_run:
                for lead in leads:
                    outcome = db.record_lead(
                        conn, {**lead, "source": adapter.source},
                        gmail_message_id=message_id,
                        seen_at=receipt["received_at"],
                        profile=profile,
                    )
                    summary["new_discoveries"] += 1 if outcome["created"] else 0
                    summary["new_sightings"] += 1 if outcome["new_sighting"] else 0
                db.record_receipt(conn, **receipt, source=adapter.source, status="imported",
                                  discovery_count=len(leads), detail=parsed.get("reason"))
        except Exception as exc:  # bounded, per-message: one bad alert never kills the run
            summary["errors"].append({"gmail_message_id": message_id, "error": str(exc)[:300]})
            if not dry_run:
                try:
                    db.record_receipt(conn, gmail_message_id=message_id, status="error",
                                      detail=str(exc)[:300])
                except Exception:
                    pass

    summary["ingestion"] = ingestion_freshness(conn, now=now)
    summary["ok"] = not summary["errors"]
    return summary
