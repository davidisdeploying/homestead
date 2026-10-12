"""Link a successfully saved live capture back to the Scout lead that surfaced it.

The direction matters. Email never promotes itself into Properties; a capture that has
ALREADY succeeded reaches back and marks at most one discovery `captured`.

Three consequences follow, and all three are enforced below:

  - reconciliation runs after the listing is durably stored, so a failure here loses a
    convenience link and never a property;
  - it is idempotent -- re-capturing the same listing re-links the same discovery instead
    of duplicating either side;
  - two matching discoveries is an error surfaced for review, not a coin flip. Guessing
    would attach a property to the wrong lead and silently hide the other.
"""
from .identity import canonical_url, normalize_address, normalize_source


def _rows_to_ids(rows):
    return [row["id"] for row in rows]


def find_matches(conn, *, source, external_id=None, source_url=None,
                 address=None, city=None, state=None, postal_code=None):
    """Resolve candidate discoveries in the runbook's fixed precedence order."""
    source = normalize_source(source)
    if not source:
        return {"strategy": None, "ids": []}

    external = str(external_id or "").strip()
    if external:
        rows = conn.execute(
            "SELECT id FROM scout_discovery WHERE source = ? AND external_id = ?",
            (source, external),
        ).fetchall()
        if rows:
            return {"strategy": "external_id", "ids": _rows_to_ids(rows)}

    canonical = canonical_url(source, source_url)
    if canonical:
        rows = conn.execute(
            "SELECT id FROM scout_discovery WHERE source = ? AND source_url = ?",
            (source, canonical),
        ).fetchall()
        if rows:
            return {"strategy": "canonical_url", "ids": _rows_to_ids(rows)}

    normalized = normalize_address(address, city, state, postal_code)
    if normalized:
        rows = conn.execute(
            "SELECT id, address, city, state, postal_code FROM scout_discovery WHERE source = ?",
            (source,),
        ).fetchall()
        matched = [
            row["id"] for row in rows
            if normalize_address(row["address"], row["city"], row["state"], row["postal_code"])
            == normalized
        ]
        if matched:
            return {"strategy": "normalized_address", "ids": matched}

    return {"strategy": None, "ids": []}


def reconcile_capture(conn, record):
    """Mark one discovery `captured` for a listing record that is already stored.

    Returns a status dict; it never raises for a normal no-match, and it never touches
    the listing record, the immutable generation, listings.sqlite3, or the media archive.
    """
    fields = record.get("fields") or {}
    result = find_matches(
        conn,
        source=record.get("source"),
        external_id=record.get("external_id") or fields.get("external_id"),
        source_url=record.get("source_url") or fields.get("source_url"),
        address=fields.get("address"),
        city=fields.get("city"),
        state=fields.get("state"),
        postal_code=fields.get("postal_code"),
    )
    listing_id = record.get("listing_id")
    ids = result["ids"]

    if not ids:
        return {"status": "no_match", "strategy": None, "discovery_id": None}
    if len(ids) > 1:
        return {"status": "ambiguous", "strategy": result["strategy"],
                "discovery_ids": ids,
                "detail": "more than one lead matches this capture; resolve it by hand"}

    discovery_id = ids[0]
    row = conn.execute(
        "SELECT status, linked_listing_id FROM scout_discovery WHERE id = ?", (discovery_id,)
    ).fetchone()
    if row["status"] == "captured" and row["linked_listing_id"] == listing_id:
        return {"status": "already_linked", "strategy": result["strategy"],
                "discovery_id": discovery_id}

    conn.execute(
        "UPDATE scout_discovery SET status = 'captured', linked_listing_id = ? WHERE id = ?",
        (listing_id, discovery_id),
    )
    conn.commit()
    return {"status": "linked", "strategy": result["strategy"], "discovery_id": discovery_id}
