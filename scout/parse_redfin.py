"""Redfin saved-search alert parser.

Template verified 2026-08-09 against two real saved-search alerts delivered to David's
Gmail from `listings@redfin.com` — one new-listing and one price-drop.

Structure below is the observed one; addresses and prices are the fixture's fictional
values, because this repository is pushed to GitHub and the properties David is actively
watching are not something to publish.

    Subject: New in <City> at $412K
             Price decrease to $318K on <street>
    Body:    New Saved Search
             Garland - <$425K
             <$425K
             $318,000 $332,000                     <- price drop: new price, then old
             2 Beds · 2 Baths · 1,089 Sq. Ft.
             12 Example Cir, Garland, TX 75044
             2,439 sq ft lot • $86 HOA • Garage
             Tour home
             See all updates
             Related to your search                <- EVERYTHING BELOW IS NOT MY SEARCH
             Nearby similar homes
             $260,000 ... 77 Decoy Ave, Richardson, TX 75082
             $240,000 ... 512 Distractor Dr, Dallas, TX 75240
             $218,000 ... 88 Nearby Ln, Garland, TX 75042

Two findings shape this parser, and neither could have been guessed.

**Every alert advertises other homes.** Both real samples carried a "Related to your
search / Nearby similar homes" block with two to three additional properties — in the
price-drop sample they were in three different cities, none of them the home the alert was
about. Parsing the whole body would have filed three extra properties per email
as if David's saved search had matched them. The body is therefore cut at that marker and
only the head section is read.

**Redfin's links are opaque.** Every href is `redmail3.redfin.com/u/click` or `/a/click`
with no query string at all — the destination lives inside the tracking token, not in the
URL. There is no property ID and no canonical URL to recover, and resolving one would mean
an HTTP request to Redfin, which the runbook forbids. So Redfin leads carry no
`external_id` and no `source_url`, and identity falls to the normalized-address path.
That is a real limitation, recorded rather than papered over with a synthesized search URL
that would then corrupt capture reconciliation.
"""
import re

from .parse_common import (cut_at, find_address, money, number, text_lines)

ALERT_SENDERS = ("listings@redfin.com",)

# Everything from here down is advertising, not the saved search.
RECOMMENDATION_MARKERS = (
    "related to your search",
    "nearby similar homes",
    "more homes to explore",
)

# "2 Beds · 2 Baths · 1,089 Sq. Ft." — the separator arrives as a &middot; entity, which
# is exactly the class of bug that silently fused two fields in Prospect for weeks.
_FACTS = re.compile(
    r"(?P<beds>\d+(?:\.\d+)?)\s*Beds?\s*[·|,]\s*(?P<baths>\d+(?:\.\d+)?)\s*Baths?"
    r"(?:\s*[·|,]\s*(?P<area>[\d,]+)\s*Sq\.?\s*Ft\.?)?",
    re.I,
)

_LOT = re.compile(r"([\d,]+)\s*sq\.?\s*ft\.?\s*lot", re.I)


def parse_redfin_alert(message, decoded):
    """Extract leads from one Redfin saved-search alert, excluding recommendations."""
    lines = text_lines(decoded)
    if not lines:
        return {"accepted": True, "reason": "Redfin alert had no readable body", "leads": []}

    kept = cut_at(lines, RECOMMENDATION_MARKERS)
    excluded = len(lines) - len(kept)

    leads = []
    for index, line in enumerate(kept):
        facts = _FACTS.search(line)
        if not facts:
            continue
        located, address_index = find_address(kept, index + 1, limit=4)
        if not located:
            continue

        # Price sits immediately above the facts line. A price drop prints the new price
        # first and the superseded one second, so the FIRST amount is the current one.
        price = None
        for previous in range(index - 1, max(-1, index - 4), -1):
            price = money(kept[previous])
            if price:
                break

        lot = None
        if address_index is not None:
            for following in kept[address_index + 1:address_index + 3]:
                match = _LOT.search(following)
                if match:
                    lot = number(match.group(1).replace(",", ""))
                    break

        fields = {
            **located,
            "price": price,
            "bedrooms": number(facts.group("beds")),
            "bathrooms": number(facts.group("baths")),
            "living_area": number((facts.group("area") or "").replace(",", "")),
            "lot_sqft": lot,
            # No external_id and no source_url: see the module docstring. Identity comes
            # from the normalized address.
        }
        leads.append({key: value for key, value in fields.items() if value not in (None, "")})

    if not leads:
        return {"accepted": True,
                "reason": "Redfin sender verified but no listing card parsed", "leads": []}
    reason = f"parsed {len(leads)} Redfin listing card(s)"
    if excluded:
        reason += f"; excluded {excluded} recommendation line(s)"
    return {"accepted": True, "reason": reason, "leads": leads}
