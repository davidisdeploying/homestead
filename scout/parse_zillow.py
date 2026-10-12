"""Zillow saved-search alert parser.

Template verified 2026-08-09 against one real "instant" saved-search alert delivered to
David's Gmail from `instant-updates@mail.zillow.com`.

Observed structure, with the real address and price replaced by the fixture's fictional
ones -- this repository is pushed to GitHub, and the properties David is actively watching
are not something to publish:

    Subject: New Listing: <street> <City>, <ST> <ZIP>. Your '<search name>' search
    Body:    New listing for sale at $398,500
             This home matches your search <search name>: ...
             ● For sale
             New
             $398,500
             3 bd | 2 ba | 1,880 sqft
             4102 Cottonwood Bend, Richardson, TX
             ...footer: pre-qualification, privacy, unsubscribe...

Note the card omits the ZIP that the subject carries.

Two things about the links matter more than the text.

**Every href is a `click.mail.zillow.com` tracking wrapper.** The real destination is
URL-encoded in its `target=` query parameter. `identity.canonical_url()` deliberately
refuses the wrapper host, so unwrapping here is not a convenience — without it a lead has
no canonical URL at all.

**Only one link shape is the property.** The unwrapped targets in the real alert were:

    /routing/email/property-notifications/zpid_target/<ID>_zpid/<token>/   <- the listing
    /homes/for_sale/ , /homeloans/eligibility , /email/feedback ,
    /email/unsubscribe , /myzillow/notifications ,
    /search/SwitchEmailFrequency.htm , zillowgroup.com/zg-privacy-policy/  <- everything else

So the zpid is taken from that one path and nowhere else. Matching `\\d+_zpid` anywhere in
the message would eventually pick up a footer or recommendation link.
"""
import re
from urllib.parse import parse_qs, unquote, urlparse

from .parse_common import (find_address, money, number, postal_from_subject, text_lines)

ALERT_SENDERS = ("instant-updates@mail.zillow.com",)

# The single link shape that identifies the property this alert is about.
_ZPID_TARGET = re.compile(r"/routing/email/property-notifications/zpid_target/(\d+)_zpid/")

# "4 bd | 2 ba | 1,376 sqft". Baths may be fractional.
_FACTS = re.compile(
    r"(?P<beds>\d+(?:\.\d+)?)\s*bd\s*\|\s*(?P<baths>\d+(?:\.\d+)?)\s*ba"
    r"(?:\s*\|\s*(?P<area>[\d,]+)\s*sqft)?",
    re.I,
)

_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def _unwrap(href):
    """Return the real destination behind a click.mail.zillow.com wrapper."""
    raw = unquote(str(href or "")).replace("&amp;", "&")
    try:
        query = parse_qs(urlparse(raw).query)
    except ValueError:
        return raw
    target = (query.get("target") or query.get("url") or [None])[0]
    return target or raw


def zpids(html):
    """Ordered, de-duplicated zpids from property-notification links only."""
    found = []
    for href in _HREF.findall(str(html or "")):
        match = _ZPID_TARGET.search(_unwrap(href))
        if match and match.group(1) not in found:
            found.append(match.group(1))
    return found


def canonical_property_url(zpid):
    return f"https://www.zillow.com/homedetails/{zpid}_zpid/"


def parse_zillow_alert(message, decoded):
    """Extract leads from one Zillow saved-search alert.

    Returns {"accepted", "reason", "leads"}. `accepted` is False only when the message is
    not a Zillow alert at all; a Zillow alert carrying no parseable card is accepted with
    zero leads so the importer can record `parse_empty` and make the difference visible.
    """
    headers = (decoded or {}).get("headers") or {}
    subject = headers.get("subject", "")
    lines = text_lines(decoded)
    if not lines:
        return {"accepted": True, "reason": "Zillow alert had no readable body", "leads": []}

    ids = zpids((decoded or {}).get("html") or "")
    cards = []

    for index, line in enumerate(lines):
        facts = _FACTS.search(line)
        if not facts:
            continue
        located, address_index = find_address(lines, index + 1, limit=4)
        if not located:
            continue

        # The price is the nearest dollar amount above the facts line. The card prints it
        # immediately above; the headline "New listing for sale at $X" repeats it.
        price = None
        for previous in range(index - 1, max(-1, index - 5), -1):
            price = money(lines[previous])
            if price:
                break

        status = None
        for previous in range(index - 1, max(-1, index - 6), -1):
            candidate = lines[previous].lstrip("● ").strip()
            if candidate.lower() in ("for sale", "for rent", "sold", "pending"):
                status = candidate
                break

        cards.append({
            "fields": {
                **located,
                "postal_code": located["postal_code"]
                or postal_from_subject(subject, located["address"]),
                "price": price,
                "bedrooms": number(facts.group("beds")),
                "bathrooms": number(facts.group("baths")),
                "living_area": number((facts.group("area") or "").replace(",", "")),
                "listing_status": status,
            },
            "at": address_index,
        })

    leads = []
    for position, card in enumerate(cards):
        fields = card["fields"]
        # Positional pairing only when the counts agree. If they do not, the zpid is left
        # off and identity falls back to the normalized address rather than risking a
        # listing being filed under another listing's ID.
        if len(ids) == len(cards):
            fields["external_id"] = ids[position]
            fields["source_url"] = canonical_property_url(ids[position])
        elif len(ids) == 1 and len(cards) == 1:
            fields["external_id"] = ids[0]
            fields["source_url"] = canonical_property_url(ids[0])
        leads.append({key: value for key, value in fields.items() if value not in (None, "")})

    if not leads:
        return {"accepted": True,
                "reason": "Zillow sender verified but no listing card parsed", "leads": []}
    return {"accepted": True, "reason": f"parsed {len(leads)} Zillow listing card(s)",
            "leads": leads}
