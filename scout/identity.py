"""Discovery identity, URL canonicalization, and address normalization.

Identity order is fixed by the runbook and must not be reordered:

  1. source-native stable ID (Zillow zpid, Redfin property/listing ID);
  2. canonical property URL with tracking parameters removed;
  3. SHA-256 of the normalized street address + city + state + postal code.

Never deduplicate by price or MLS number alone. Price changes between alerts -- that is
the entire point of a repeat alert -- and MLS numbers are reused across relistings.
"""
import hashlib
import re
from urllib.parse import urlparse, urlunparse

SOURCES = ("zillow", "redfin")

# Host suffixes a canonical property URL is allowed to live on. Anything else -- a
# marketing redirect, a click-tracking wrapper, an ad, a recommendation card, a footer
# link -- is refused here rather than silently becoming a lead's identity.
_ALLOWED_HOSTS = {
    "zillow": "zillow.com",
    "redfin": "redfin.com",
}

_ADDRESS_NOISE = re.compile(r"[^A-Z0-9 ]+")


def normalize_source(value):
    source = str(value or "").strip().lower()
    return source if source in SOURCES else ""


def canonical_url(source, value):
    """Return a canonical property URL, or "" when the URL is not one.

    Query strings on Zillow and Redfin property URLs are tracking only -- the path
    carries the identity -- so the whole query is dropped rather than allowlisting
    individual parameter names that both sites change at will.
    """
    source = normalize_source(source)
    raw = str(value or "").strip()
    if not source or not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""
    host = (parsed.hostname or "").lower()
    allowed = _ALLOWED_HOSTS[source]
    if not (host == allowed or host.endswith("." + allowed)):
        return ""
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunparse(("https", host, path, "", "", ""))


def normalize_address(address, city=None, state=None, postal_code=None):
    """Uppercase, punctuation-free address key.

    Deliberately does NOT expand abbreviations (Dr/Drive, N/North). Expansion tables are
    a guessing surface, and a wrong expansion silently fuses two different properties.
    """
    parts = [address, city, state, postal_code]
    joined = " ".join(str(part).strip() for part in parts if part is not None and str(part).strip())
    if not joined:
        return ""
    cleaned = _ADDRESS_NOISE.sub(" ", joined.upper())
    return " ".join(cleaned.split())


def address_key(address, city=None, state=None, postal_code=None):
    normalized = normalize_address(address, city, state, postal_code)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def source_key(source, external_id=None, source_url=None,
               address=None, city=None, state=None, postal_code=None):
    """Resolve the stable per-source identity for one lead.

    Raises ValueError when none of the three identity paths can produce a key, because a
    lead with no identity cannot be deduplicated and would create a fresh row on every
    single alert.
    """
    if not normalize_source(source):
        raise ValueError("source must be zillow or redfin")
    external = re.sub(r"[^A-Za-z0-9_-]", "", str(external_id or ""))[:80]
    if external:
        return f"id:{external}"
    canonical = canonical_url(source, source_url)
    if canonical:
        return f"url:{canonical}"
    digest = address_key(address, city, state, postal_code)
    if digest:
        return f"addr:{digest}"
    raise ValueError("lead has no native id, canonical url, or address to identify it")
