"""Source adapter registry.

Both adapters were verified against real saved-search alerts on 2026-08-09, after the
accounts' first alerts arrived at 18:52 and 18:55 CDT. Until then this registry was empty
by design and the importer refused to run — `runbooks/scout.md` §12 forbids building a
parser on a template nobody has seen. The four Zillow/Redfin messages that existed before
those alerts were account-lifecycle mail (`no-reply@confirmation.zillow.com`,
`donotreply@redfin.com`) and are deliberately NOT alert senders.

## Verified alert senders

  - Zillow  `instant-updates@mail.zillow.com`
  - Redfin  `listings@redfin.com`

Membership is checked exactly, never by domain suffix. That matters concretely here:
`donotreply@redfin.com` sends account mail from the same domain as `listings@redfin.com`,
and Zillow's confirmation subdomain is a sibling of its alert subdomain. A domain-wide
rule would ingest both as property leads.

## What is still not allowed

- guessing a sender address, or widening a verified one to its domain;
- writing selectors against a remembered template rather than an observed one;
- a fixture whose structure was invented rather than sanitized from a real message;
- one merged parser handling both templates;
- resolving Redfin's opaque tracking links by fetching them — that is crawling.

## Adding a third source later

Repeat the sequence: observe one real alert read-only, record only sender/subject/MIME/
link-shape/field-availability, sanitize a fixture from it, write its `<Source>FixtureTest`
(the conformance harness requires that class by name), then register the adapter here.
"""
from dataclasses import dataclass, field
from typing import Callable, Tuple

from .parse_redfin import ALERT_SENDERS as REDFIN_SENDERS, parse_redfin_alert
from .parse_zillow import ALERT_SENDERS as ZILLOW_SENDERS, parse_zillow_alert


@dataclass(frozen=True)
class Adapter:
    """One verified source template.

    `senders` are exact, lowercase From addresses proven by reconnaissance against real
    alert mail. Membership is checked exactly -- never by domain suffix -- so that
    transactional and marketing mail from the same company cannot enter the parser.
    """
    source: str
    senders: Tuple[str, ...]
    parse: Callable
    verified_on: str = ""
    notes: str = ""

    def accepts(self, sender):
        return str(sender or "").lower() in self.senders


ADAPTERS: Tuple[Adapter, ...] = (
    Adapter(
        source="zillow",
        senders=ZILLOW_SENDERS,
        parse=parse_zillow_alert,
        verified_on="2026-08-09",
        notes=("Instant saved-search alert. Property link is a click.mail.zillow.com "
               "wrapper whose target= parameter holds a /zpid_target/<ID>_zpid/ path."),
    ),
    Adapter(
        source="redfin",
        senders=REDFIN_SENDERS,
        parse=parse_redfin_alert,
        verified_on="2026-08-09",
        notes=("New-listing and price-drop saved-search alerts. Links are opaque "
               "redmail3.redfin.com tokens, so leads carry no ID or URL and are "
               "identified by normalized address. Every alert appends a 'Nearby similar "
               "homes' block that must be excluded."),
    ),
)


def registered_sources():
    return tuple(adapter.source for adapter in ADAPTERS)


def registered_senders():
    senders = []
    for adapter in ADAPTERS:
        for sender in adapter.senders:
            if sender not in senders:
                senders.append(sender)
    return tuple(senders)


def adapter_for(sender, adapters=None):
    """Resolve the adapter that owns `sender`, within the given registry.

    `adapters` is explicit rather than implicitly global so a caller running against a
    scoped registry cannot silently fall through to the module default.
    """
    for adapter in (ADAPTERS if adapters is None else adapters):
        if adapter.accepts(sender):
            return adapter
    return None
