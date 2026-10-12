"""Homestead Scout tests.

The acceptance gates in runbooks/scout.md §11 that do NOT depend on a real alert template
are covered here. The gates that do -- "verified Zillow sender accepts Zillow fixture",
"verified Redfin sender accepts Redfin fixture" -- are deliberately absent, because no
genuine alert exists yet to build a sanitized fixture from. `test_no_adapter_is_registered`
asserts that absence explicitly, so this suite fails loudly the moment someone adds an
adapter without also adding its fixture tests.
"""
import base64
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import server
from scout import adapters, db, importer, mime, reconcile
from scout.adapters import Adapter
from scout.identity import address_key, canonical_url, normalize_address, source_key
from scout.parse_redfin import parse_redfin_alert
from scout.parse_zillow import parse_zillow_alert, zpids as zillow_zpids
from scout.profile import assess, validate_profile


def b64url(text):
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def gmail_message(message_id, sender, html_body, *, thread_id="t1", internal_date=None,
                  nested=True):
    """A Gmail `format=full` message shaped like real alert mail: nested multipart."""
    leaf = {"mimeType": "text/html",
            "headers": [{"name": "Content-Type", "value": 'text/html; charset="UTF-8"'}],
            "body": {"data": b64url(html_body)}}
    payload = {
        "mimeType": "multipart/mixed" if nested else "text/html",
        "headers": [{"name": "From", "value": sender},
                    {"name": "Subject", "value": "New listings for your search"}],
        "parts": [{"mimeType": "multipart/alternative", "parts": [leaf]}] if nested else None,
    }
    if not nested:
        payload["body"] = {"data": b64url(html_body)}
        payload.pop("parts")
    return {"id": message_id, "threadId": thread_id,
            "internalDate": str(internal_date or 1786000000000), "payload": payload}


class FakeGmail:
    """Stands in for scout.gmail; records every call so read-only can be asserted."""

    def __init__(self, messages):
        self.messages = {message["id"]: message for message in messages}
        self.calls = []

    def list_messages(self, auth, query, max_results=100):
        self.calls.append(("list", query))
        return [{"id": message_id} for message_id in self.messages]

    def get_message(self, auth, message_id):
        self.calls.append(("get", message_id))
        return self.messages[message_id]


# --------------------------------------------------------------- scope and adapters


class GmailScopeTest(unittest.TestCase):
    def test_scope_is_exactly_readonly(self):
        from scout import gmail
        self.assertEqual(gmail.GMAIL_READONLY_SCOPE,
                         "https://www.googleapis.com/auth/gmail.readonly")

    def test_no_mailbox_mutation_endpoint_is_reachable(self):
        from scout import gmail
        for endpoint in ("messages/abc/modify", "messages/abc/trash", "messages/send",
                         "messages/batchDelete", "labels", "../labels"):
            with self.assertRaises(gmail.GmailError):
                gmail.api_get({"token": {}}, endpoint)

    def test_module_exposes_no_write_helpers(self):
        from scout import gmail
        for forbidden in ("send", "trash", "delete", "modify", "label"):
            self.assertFalse(
                [name for name in dir(gmail) if forbidden in name.lower()],
                f"scout.gmail must expose no {forbidden} helper",
            )


class AdapterRegistryTest(unittest.TestCase):
    def test_both_sources_are_registered_with_verified_senders(self):
        self.assertEqual(adapters.registered_sources(), ("zillow", "redfin"))
        self.assertEqual(adapters.registered_senders(),
                         ("instant-updates@mail.zillow.com", "listings@redfin.com"))
        for adapter in adapters.ADAPTERS:
            self.assertEqual(adapter.verified_on, "2026-08-09")

    def test_account_lifecycle_senders_are_not_alert_senders(self):
        # The four messages that existed before the first real alert. Accepting any of
        # them would file account mail as property leads.
        for impostor in ("no-reply@confirmation.zillow.com", "donotreply@redfin.com",
                         "press@redfin.com", "no-reply@mail.zillow.com"):
            self.assertIsNone(adapters.adapter_for(impostor), impostor)

    def test_query_uses_only_the_two_verified_senders(self):
        query = importer.build_query(14)
        self.assertEqual(
            query,
            "from:(instant-updates@mail.zillow.com OR listings@redfin.com) newer_than:14d")

    def test_importer_fails_closed_without_a_verified_sender(self):
        with self.assertRaises(importer.NoAdaptersConfigured):
            importer.build_query(14, adapters=())

    def test_query_uses_only_verified_senders(self):
        fake = Adapter(source="zillow", senders=("alerts@example-zillow.test",),
                       parse=lambda m, d: {"accepted": True, "leads": []})
        query = importer.build_query(7, adapters=(fake,))
        self.assertEqual(query, "from:(alerts@example-zillow.test) newer_than:7d")
        self.assertNotIn("zillow.com", query)

    def test_sender_matching_is_exact_not_domain_suffix(self):
        fake = Adapter(source="zillow", senders=("alerts@example-zillow.test",), parse=None)
        self.assertTrue(fake.accepts("Alerts@Example-Zillow.Test"))
        self.assertFalse(fake.accepts("marketing@example-zillow.test"))


class AdapterConformanceTest(unittest.TestCase):
    """The contract every future Zillow/Redfin adapter must satisfy.

    These are the "failing parser tests first" of the runbook's step 1, written in the only
    form that is honest while no real alert exists: they encode the *contract*, which is
    knowable, and assert nothing about *template structure*, which is not.

    Today ADAPTERS is empty, so the per-adapter tests iterate zero times and pass
    vacuously. That is the point -- the moment someone registers an adapter these become
    live and will fail it for the mistakes that actually matter: a domain-wide sender, an
    unrecorded reconnaissance date, a lead with no resolvable identity, an empty-string
    field standing in for a missing one, or a parser that raises on junk input.

    They are the machine-enforced half of the stop gate. The documented half is the
    module docstring in scout/adapters.py.
    """

    def test_every_adapter_declares_exact_lowercase_senders(self):
        for adapter in adapters.ADAPTERS:
            with self.subTest(source=adapter.source):
                self.assertIn(adapter.source, ("zillow", "redfin"))
                self.assertIsInstance(adapter.senders, tuple)
                self.assertGreater(len(adapter.senders), 0,
                                   "an adapter with no sender would never be queried")
                for sender in adapter.senders:
                    self.assertEqual(sender, sender.lower())
                    self.assertIn("@", sender, "senders are addresses, not domains")
                    self.assertNotIn("*", sender, "wildcard senders are not verification")
                    # A bare domain would let marketing and account mail into the parser.
                    self.assertFalse(sender.startswith("@"))

    def test_every_adapter_records_when_its_template_was_verified(self):
        # Without this, a guessed adapter is indistinguishable from a verified one.
        for adapter in adapters.ADAPTERS:
            with self.subTest(source=adapter.source):
                self.assertTrue(adapter.verified_on.strip(),
                                "record the date the real alert was observed")

    def test_sender_matching_never_widens_to_the_domain(self):
        for adapter in adapters.ADAPTERS:
            with self.subTest(source=adapter.source):
                domain = adapter.senders[0].split("@", 1)[1]
                for impostor in (f"marketing@{domain}", f"no-reply@{domain}",
                                 f"donotreply@{domain}", f"evil@notreally{domain}"):
                    if impostor in adapter.senders:
                        continue
                    self.assertFalse(adapter.accepts(impostor),
                                     f"{adapter.source} must not accept {impostor}")

    def test_adapters_do_not_share_a_sender(self):
        seen = {}
        for adapter in adapters.ADAPTERS:
            for sender in adapter.senders:
                self.assertNotIn(sender, seen,
                                 f"{sender} is claimed by both {seen.get(sender)} "
                                 f"and {adapter.source}")
                seen[sender] = adapter.source

    def test_parse_returns_the_contract_shape_and_never_raises_on_junk(self):
        junk = [
            gmail_message("j1", "whoever@example.test", ""),
            gmail_message("j2", "whoever@example.test", "<p>unrelated marketing</p>"),
            gmail_message("j3", "whoever@example.test", "<a href='https://ads.example'>ad</a>",
                          nested=False),
            {"id": "j4", "payload": {}},
        ]
        for adapter in adapters.ADAPTERS:
            for message in junk:
                with self.subTest(source=adapter.source, message=message["id"]):
                    result = adapter.parse(message, mime.message_text(message))
                    self.assertIsInstance(result, dict)
                    self.assertIn("accepted", result)
                    self.assertIn("reason", result)
                    self.assertIsInstance(result.get("leads") or [], list)

    def test_every_emitted_lead_has_a_resolvable_identity_and_no_blank_placeholders(self):
        junk = gmail_message("k1", "whoever@example.test", "<p>nothing here</p>")
        for adapter in adapters.ADAPTERS:
            result = adapter.parse(junk, mime.message_text(junk))
            for lead in (result.get("leads") or []):
                with self.subTest(source=adapter.source):
                    # Must be identifiable, or it creates a new row on every single alert.
                    source_key(adapter.source, external_id=lead.get("external_id"),
                               source_url=lead.get("source_url"),
                               address=lead.get("address"), city=lead.get("city"),
                               state=lead.get("state"), postal_code=lead.get("postal_code"))
                    # A missing field must be absent or None -- never "" or 0, which would
                    # read downstream as "the alert said this" rather than "it did not say".
                    for key, value in lead.items():
                        if value is None:
                            continue
                        if isinstance(value, str):
                            self.assertEqual(value, value.strip())
                            self.assertNotEqual(value, "",
                                                f"{key} should be absent, not empty")

    def test_registering_an_adapter_requires_its_own_fixture_tests(self):
        # Tripwire. An adapter may only land alongside sanitized fixture tests built from
        # a genuine alert; this fails loudly if someone adds one without them.
        module_tests = [name for name in globals() if name.endswith("FixtureTest")]
        for adapter in adapters.ADAPTERS:
            with self.subTest(source=adapter.source):
                expected = f"{adapter.source.capitalize()}FixtureTest"
                self.assertIn(
                    expected, module_tests,
                    f"add {expected} with a sanitized fixture from a real "
                    f"{adapter.source} alert before registering the adapter",
                )


class ConformanceHarnessBitesTest(unittest.TestCase):
    """Proof that AdapterConformanceTest is not vacuous scaffolding.

    Those checks currently iterate an empty registry, so "they pass" says nothing. Here
    each one is pointed at a deliberately defective adapter and required to FAIL. If a
    future refactor guts the harness, this is what notices.
    """

    def run_check(self, method, bad_adapter):
        original = adapters.ADAPTERS
        adapters.ADAPTERS = (bad_adapter,)
        try:
            case = AdapterConformanceTest(method)
            result = unittest.TestResult()
            case.run(result)
            return result
        finally:
            adapters.ADAPTERS = original

    def ok(self, **overrides):
        base = {
            "source": "zillow",
            "senders": ("alerts@example-zillow.test",),
            "verified_on": "2026-08-09",
            "parse": lambda message, decoded: {"accepted": True, "reason": "x", "leads": []},
        }
        base.update(overrides)
        return Adapter(**base)

    def assert_rejected(self, method, adapter, reason):
        result = self.run_check(method, adapter)
        self.assertTrue(result.failures or result.errors,
                        f"conformance check {method} failed to catch {reason}")

    def test_domain_wide_sender_is_caught(self):
        self.assert_rejected("test_every_adapter_declares_exact_lowercase_senders",
                             self.ok(senders=("@zillow.com",)), "a bare domain sender")

    def test_uppercase_sender_is_caught(self):
        self.assert_rejected("test_every_adapter_declares_exact_lowercase_senders",
                             self.ok(senders=("Alerts@Example.test",)), "an uppercase sender")

    def test_missing_verification_date_is_caught(self):
        self.assert_rejected("test_every_adapter_records_when_its_template_was_verified",
                             self.ok(verified_on="  "), "an unrecorded verification date")

    def test_parser_that_raises_on_junk_is_caught(self):
        def explode(message, decoded):
            raise ValueError("template changed")
        self.assert_rejected("test_parse_returns_the_contract_shape_and_never_raises_on_junk",
                             self.ok(parse=explode), "a parser that raises on junk")

    def test_wrong_return_shape_is_caught(self):
        self.assert_rejected("test_parse_returns_the_contract_shape_and_never_raises_on_junk",
                             self.ok(parse=lambda m, d: ["a lead"]), "a non-dict return")

    def test_unidentifiable_lead_is_caught(self):
        self.assert_rejected(
            "test_every_emitted_lead_has_a_resolvable_identity_and_no_blank_placeholders",
            self.ok(parse=lambda m, d: {"accepted": True, "reason": "x",
                                        "leads": [{"price": 400000}]}),
            "a lead with no id, url, or address")

    def test_blank_placeholder_field_is_caught(self):
        self.assert_rejected(
            "test_every_emitted_lead_has_a_resolvable_identity_and_no_blank_placeholders",
            self.ok(parse=lambda m, d: {"accepted": True, "reason": "x",
                                        "leads": [{"external_id": "1", "city": ""}]}),
            "an empty string standing in for a missing field")

    def test_missing_fixture_tests_are_caught(self):
        # A hypothetical third source. Zillow and Redfin now have fixture tests, so they
        # would legitimately pass this check -- the defect being probed is a source that
        # has none.
        self.assert_rejected("test_registering_an_adapter_requires_its_own_fixture_tests",
                             self.ok(source="trulia"),
                             "an adapter registered with no fixture tests")

    def test_a_well_formed_adapter_passes_every_check(self):
        # The harness must not be so strict that a legitimate adapter cannot land.
        good = self.ok(parse=lambda m, d: {
            "accepted": True, "reason": "parsed",
            "leads": [{"external_id": "90000001", "address": "1 Example St",
                       "city": "Richardson", "price": 399000}]})
        for method in ("test_every_adapter_declares_exact_lowercase_senders",
                       "test_every_adapter_records_when_its_template_was_verified",
                       "test_sender_matching_never_widens_to_the_domain",
                       "test_adapters_do_not_share_a_sender",
                       "test_parse_returns_the_contract_shape_and_never_raises_on_junk",
                       "test_every_emitted_lead_has_a_resolvable_identity_and_no_blank_placeholders"):
            with self.subTest(check=method):
                result = self.run_check(method, good)
                self.assertEqual((result.failures, result.errors), ([], []))


# --------------------------------------------------------------- sanitized fixtures
#
# Structure copied from the real 2026-08-09 alerts; every address, ID, price, and token
# replaced with fictional values. Entities (&#9679;, &middot;) are left encoded on purpose
# so the fixtures exercise the decoder rather than bypassing it.


def zillow_wrapper(target_path):
    """A click.mail.zillow.com tracking wrapper, as Zillow actually sends them."""
    from urllib.parse import quote
    real = f"https://www.zillow.com{target_path}?z&amp;utm_source=email"
    return ("https://click.mail.zillow.com/f/a/FAKETOKEN~~/AAAAAQA~/FAKE?target="
            + quote(real.replace("&amp;", "&"), safe=""))


ZILLOW_SUBJECT = ("New Listing: 4102 Cottonwood Bend Richardson, TX 75082. "
                  "Your 'For Sale in Richardson MAX 425' search")

ZILLOW_ALERT_HTML = f"""
<table><tbody>
<tr><td>New listing for sale at $398,500</td></tr>
<tr><td>This home matches your search For Sale in Richardson MAX 425: $425K or less,
        and more.</td></tr>
<tr><td>&#9679; For sale</td></tr>
<tr><td>New</td></tr>
<tr><td><a href="{zillow_wrapper('/routing/email/property-notifications/zpid_target/90000001_zpid/X1-FAKE_8qnd1_sse/')}">
        $398,500</a></td></tr>
<!-- Each separator sits in its own cell, exactly as the real alert sends it. An
     earlier fixture put this run on one line, which is why the suite passed while the
     importer parsed nothing. -->
<tr><td>3 bd</td><td>|</td><td>2 ba</td><td>|</td><td>1,880 sqft</td></tr>
<tr><td>4102 Cottonwood Bend, Richardson, TX</td></tr>
<tr><td><a href="{zillow_wrapper('/homes/for_sale/')}">See latest search results</a></td></tr>
<tr><td><a href="{zillow_wrapper('/homeloans/eligibility')}">Get pre-qualified</a></td></tr>
<tr><td>Zillow, Inc. 1301 Second Avenue, Floor 36 Seattle, WA 98101</td></tr>
<tr><td><a href="{zillow_wrapper('/email/unsubscribe')}">Unsubscribe from this email</a>
        | <a href="{zillow_wrapper('/myzillow/notifications')}">Update your preferences</a>
        </td></tr>
</tbody></table>
"""

REDFIN_NEW_LISTING_HTML = """
<table><tbody>
<tr><td>New Saved Search</td></tr>
<tr><td>Garland - &lt;$425K</td></tr>
<tr><td>$412,000</td></tr>
<tr><td>4 Beds &middot; 2 Baths &middot; 2,100 Sq. Ft.</td></tr>
<tr><td>9 Fictional Ln, Garland, TX 75040</td></tr>
<tr><td>7,000 sq ft lot &bull; Garage</td></tr>
<tr><td><a href="https://redmail3.redfin.com/u/click">Tour home</a></td></tr>
<tr><td><a href="https://redmail3.redfin.com/a/click">See all updates</a></td></tr>
<tr><td>Related to your search</td></tr>
<tr><td>Nearby similar homes</td></tr>
<tr><td>$260,000</td></tr>
<tr><td>2 Beds &middot; 1.5 Baths &middot; 1,234 Sq. Ft.</td></tr>
<tr><td>77 Decoy Ave, Richardson, TX 75082</td></tr>
<tr><td>1,234 sq ft lot &bull; 2 garage spots</td></tr>
<tr><td>$218,000</td></tr>
<tr><td>3 Beds &middot; 2 Baths &middot; 1,408 Sq. Ft.</td></tr>
<tr><td>512 Distractor Dr, Dallas, TX 75240</td></tr>
<tr><td>Redfin, 1099 Stewart St, Suite 600, Seattle, WA 98101</td></tr>
</tbody></table>
"""

REDFIN_PRICE_DROP_HTML = """
<table><tbody>
<tr><td>New Saved Search</td></tr>
<tr><td>Garland - &lt;$425K</td></tr>
<tr><td>$318,000 $332,000</td></tr>
<tr><td>2 Beds &middot; 2 Baths &middot; 1,089 Sq. Ft.</td></tr>
<tr><td>12 Example Cir, Garland, TX 75044</td></tr>
<tr><td>2,439 sq ft lot &bull; $86 HOA &bull; Garage</td></tr>
<tr><td>Related to your search</td></tr>
<tr><td>$260,000</td></tr>
<tr><td>2 Beds &middot; 1 Bath &middot; 900 Sq. Ft.</td></tr>
<tr><td>88 Nearby Ln, Dallas, TX 75240</td></tr>
</tbody></table>
"""


def zillow_message(message_id="z1"):
    message = gmail_message(message_id, "Zillow <instant-updates@mail.zillow.com>",
                            ZILLOW_ALERT_HTML)
    message["payload"]["headers"] = [
        {"name": "From", "value": "Zillow <instant-updates@mail.zillow.com>"},
        {"name": "Subject", "value": ZILLOW_SUBJECT},
    ]
    return message


def redfin_message(html=REDFIN_NEW_LISTING_HTML, message_id="r1", subject="New in Garland at $412K"):
    message = gmail_message(message_id, "Redfin <listings@redfin.com>", html)
    message["payload"]["headers"] = [
        {"name": "From", "value": "Redfin <listings@redfin.com>"},
        {"name": "Subject", "value": subject},
    ]
    return message


class ZillowFixtureTest(unittest.TestCase):
    def parse(self, message=None):
        message = message or zillow_message()
        return parse_zillow_alert(message, mime.message_text(message))

    def test_verified_sender_is_accepted_and_one_card_is_parsed(self):
        self.assertIsNotNone(adapters.adapter_for("instant-updates@mail.zillow.com"))
        result = self.parse()
        self.assertTrue(result["accepted"])
        self.assertEqual(len(result["leads"]), 1)

    def test_every_field_the_template_carries_is_extracted(self):
        lead = self.parse()["leads"][0]
        self.assertEqual(lead["address"], "4102 Cottonwood Bend")
        self.assertEqual(lead["city"], "Richardson")
        self.assertEqual(lead["state"], "TX")
        self.assertEqual(lead["price"], 398500)
        self.assertEqual(lead["bedrooms"], 3)
        self.assertEqual(lead["bathrooms"], 2)
        self.assertEqual(lead["living_area"], 1880)
        self.assertEqual(lead["listing_status"], "For sale")

    def test_zpid_is_unwrapped_from_the_click_tracking_target(self):
        lead = self.parse()["leads"][0]
        self.assertEqual(lead["external_id"], "90000001")
        self.assertEqual(lead["source_url"],
                         "https://www.zillow.com/homedetails/90000001_zpid/")
        # And that URL survives canonicalization, unlike the wrapper it came from.
        self.assertEqual(canonical_url("zillow", lead["source_url"]),
                         "https://www.zillow.com/homedetails/90000001_zpid")

    def test_postal_code_is_recovered_from_the_subject(self):
        # The card prints "..., Richardson, TX" with no ZIP; the subject has it.
        self.assertEqual(self.parse()["leads"][0]["postal_code"], "75082")

    def test_footer_and_marketing_links_never_become_the_property(self):
        self.assertEqual(zillow_zpids(ZILLOW_ALERT_HTML), ["90000001"])

    def test_identity_uses_the_native_zpid(self):
        lead = self.parse()["leads"][0]
        self.assertEqual(source_key("zillow", external_id=lead["external_id"],
                                    source_url=lead["source_url"]), "id:90000001")

    def test_table_split_facts_are_rejoined_before_matching(self):
        # Regression: the real alert splits "3 bd | 2 ba | 1,880 sqft" across five table
        # cells, so strip_html yields five lines. Gmail's innerText joins them and hid
        # this; the importer saw nothing and reported parse_empty.
        from scout.parse_common import merge_separator_lines
        self.assertEqual(
            merge_separator_lines(["3 bd", "|", "2 ba", "|", "1,880 sqft", "4102 Cottonwood Bend, Richardson, TX"]),
            ["3 bd | 2 ba | 1,880 sqft", "4102 Cottonwood Bend, Richardson, TX"])
        # And the address on the following line must stay its own line.
        lead = self.parse()["leads"][0]
        self.assertEqual(lead["address"], "4102 Cottonwood Bend")
        self.assertEqual(lead["living_area"], 1880)

    def test_a_body_with_no_card_is_accepted_but_empty(self):
        message = zillow_message("z2")
        message["payload"]["parts"][0]["parts"][0]["body"]["data"] = b64url(
            "<p>Your search has a new saved search. See latest results.</p>")
        result = self.parse(message)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["leads"], [])
        self.assertIn("no listing card", result["reason"])


class RedfinFixtureTest(unittest.TestCase):
    def parse(self, html=REDFIN_NEW_LISTING_HTML, subject="New in Garland at $412K"):
        message = redfin_message(html, subject=subject)
        return parse_redfin_alert(message, mime.message_text(message))

    def test_verified_sender_is_accepted_and_only_the_searched_home_is_parsed(self):
        self.assertIsNotNone(adapters.adapter_for("listings@redfin.com"))
        result = self.parse()
        self.assertTrue(result["accepted"])
        # The fixture advertises two nearby homes after the marker. Exactly one lead.
        self.assertEqual(len(result["leads"]), 1)
        self.assertEqual(result["leads"][0]["address"], "9 Fictional Ln")

    def test_recommendation_block_is_excluded_entirely(self):
        addresses = [lead["address"] for lead in self.parse()["leads"]]
        for advertised in ("77 Decoy Ave", "512 Distractor Dr"):
            self.assertNotIn(advertised, addresses)
        self.assertIn("excluded", self.parse()["reason"])

    def test_middot_separated_facts_decode_and_split(self):
        lead = self.parse()["leads"][0]
        self.assertEqual(lead["bedrooms"], 4)
        self.assertEqual(lead["bathrooms"], 2)
        self.assertEqual(lead["living_area"], 2100)
        self.assertEqual(lead["lot_sqft"], 7000)
        self.assertEqual(lead["postal_code"], "75040")

    def test_price_drop_takes_the_new_price_not_the_superseded_one(self):
        lead = self.parse(REDFIN_PRICE_DROP_HTML,
                          subject="Price decrease to $318K on 12 Example Cir")["leads"][0]
        self.assertEqual(lead["address"], "12 Example Cir")
        self.assertEqual(lead["price"], 318000)   # not 332000
        self.assertEqual(lead["bathrooms"], 2)

    def test_leads_carry_no_id_or_url_because_redfin_links_are_opaque(self):
        lead = self.parse()["leads"][0]
        self.assertNotIn("external_id", lead)
        self.assertNotIn("source_url", lead)

    def test_identity_falls_back_to_the_normalized_address(self):
        lead = self.parse()["leads"][0]
        key = source_key("redfin", external_id=lead.get("external_id"),
                         source_url=lead.get("source_url"), address=lead["address"],
                         city=lead["city"], state=lead["state"],
                         postal_code=lead["postal_code"])
        self.assertTrue(key.startswith("addr:"))

    def test_a_repeat_alert_for_the_same_home_is_one_discovery(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        conn = db.connect(Path(temp.name) / "scout" / "scout.sqlite3")
        self.addCleanup(conn.close)
        first = db.record_lead(conn, {**self.parse()["leads"][0], "source": "redfin"})
        drop = self.parse(REDFIN_PRICE_DROP_HTML)["leads"][0]
        same = db.record_lead(conn, {**self.parse()["leads"][0], "source": "redfin"})
        other = db.record_lead(conn, {**drop, "source": "redfin"})
        self.assertTrue(first["created"])
        self.assertFalse(same["created"])
        self.assertTrue(other["created"])
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM scout_discovery").fetchone()[0], 2)


# --------------------------------------------------------------- MIME


class MimeTest(unittest.TestCase):
    def test_nested_multipart_base64url_and_entities_decode(self):
        body = "<div>1514 Hindsdale Dr &middot; Richardson &amp; TX &#8212; $425,000</div>"
        decoded = mime.message_text(gmail_message("m1", "a@b.test", body))
        self.assertIn("·", decoded["plain"])
        self.assertIn("&", decoded["plain"])
        self.assertIn("—", decoded["plain"])
        self.assertNotIn("&middot;", decoded["plain"])
        self.assertNotIn("&amp;", decoded["plain"])

    def test_base64url_tolerates_missing_padding(self):
        self.assertEqual(mime.decode_base64url(b64url("abcde")), b"abcde")
        self.assertEqual(mime.decode_base64url(""), b"")
        self.assertEqual(mime.decode_base64url("!!!not-base64!!!"), b"")

    def test_script_and_style_are_stripped_and_blocks_become_lines(self):
        html = "<style>.a{color:red}</style><p>One</p><script>x()</script><p>Two</p>"
        self.assertEqual(mime.strip_html(html), "One\nTwo")

    def test_sender_address_extraction(self):
        self.assertEqual(mime.sender_address('Zillow <No-Reply@Example.Test>'),
                         "no-reply@example.test")
        self.assertEqual(mime.sender_address("plain@example.test"), "plain@example.test")
        self.assertEqual(mime.sender_address(""), "")

    def test_received_at_converts_internal_date(self):
        self.assertEqual(mime.received_at({"internalDate": "1786000000000"}),
                         "2026-08-06T07:06:40Z")
        self.assertIsNone(mime.received_at({}))


# --------------------------------------------------------------- identity


class IdentityTest(unittest.TestCase):
    def test_native_id_wins(self):
        self.assertEqual(
            source_key("zillow", external_id="26595249",
                       source_url="https://www.zillow.com/homedetails/x_26595249_zpid/",
                       address="1 Main St"),
            "id:26595249")

    def test_canonical_url_is_used_when_no_native_id(self):
        key = source_key("redfin", source_url=(
            "https://www.redfin.com/TX/Richardson/1-Main-St-75080/home/999?utm_source=email"
            "&cid=abc#photo-3"))
        self.assertEqual(key, "url:https://www.redfin.com/TX/Richardson/1-Main-St-75080/home/999")

    def test_address_fallback_when_no_id_or_url(self):
        key = source_key("zillow", address="1 Main St.", city="Richardson",
                         state="TX", postal_code="75080")
        self.assertEqual(key, "addr:" + address_key("1 MAIN ST", "RICHARDSON", "TX", "75080"))

    def test_tracking_wrapper_url_is_refused_as_identity(self):
        # A click-tracking wrapper is not a canonical property URL and must not become one.
        self.assertEqual(canonical_url("zillow", "https://click.mail-example.test/r/abc"), "")
        with self.assertRaises(ValueError):
            source_key("zillow", source_url="https://click.mail-example.test/r/abc")

    def test_address_normalization_does_not_expand_abbreviations(self):
        self.assertEqual(normalize_address("1514 Hindsdale Dr.", "Richardson", "TX", "75080"),
                         "1514 HINDSDALE DR RICHARDSON TX 75080")
        self.assertNotEqual(normalize_address("1 Main Dr"), normalize_address("1 Main Drive"))

    def test_price_alone_never_identifies_a_lead(self):
        with self.assertRaises(ValueError):
            source_key("zillow", external_id="", source_url="", address="")


# --------------------------------------------------------------- profile and scoring


class ProfileTest(unittest.TestCase):
    def test_unconfigured_criteria_yields_no_score(self):
        self.assertIsNone(assess({"price": 400000, "city": "Richardson"}, None))
        self.assertIsNone(assess({"price": 400000, "city": "Richardson"}, {}))

    def test_profile_requires_at_least_one_criterion(self):
        self.assertFalse(validate_profile({})["ok"])
        self.assertFalse(validate_profile({"cities": []})["ok"])
        self.assertFalse(validate_profile({"max_price": 0})["ok"])
        self.assertFalse(validate_profile({"max_price": "lots"})["ok"])

    def test_approved_criteria_score_deterministically(self):
        profile = validate_profile({"max_price": 425000,
                                    "cities": ["richardson", "GARLAND"]})["profile"]
        self.assertEqual(profile["cities"], ["Richardson", "Garland"])

        good = assess({"price": 399000, "city": "Garland"}, profile)
        over = assess({"price": 500000, "city": "Richardson"}, profile)
        away = assess({"price": 300000, "city": "Plano"}, profile)

        self.assertEqual(good["score"], 100)
        self.assertEqual(good["label"], "matches your criteria")
        self.assertEqual(over["score"], 35)
        self.assertEqual(away["score"], 35)
        # Same input, same output, every time.
        self.assertEqual(assess({"price": 399000, "city": "Garland"}, profile), good)

    def test_assessment_declares_what_it_did_not_consider(self):
        profile = validate_profile({"max_price": 425000})["profile"]
        result = assess({"price": 400000}, profile)
        self.assertIn("bedrooms", result["criteria_not_set"])
        self.assertIn("fenced yard for four dogs", result["criteria_not_set"])
        self.assertEqual(result["criteria_considered"], ["asking price"])

    def test_missing_fields_are_cautions_not_invented_values(self):
        profile = validate_profile({"max_price": 425000, "cities": ["Richardson"]})["profile"]
        result = assess({"price": None, "city": ""}, profile)
        self.assertTrue(any("did not state an asking price" in c for c in result["cautions"]))
        self.assertTrue(any("did not state a city" in c for c in result["cautions"]))


# --------------------------------------------------------------- store


class ScoutStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.temp.name) / "scout" / "scout.sqlite3")

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def lead(self, **overrides):
        base = {"source": "zillow", "external_id": "26595249",
                "source_url": "https://www.zillow.com/homedetails/x_26595249_zpid/",
                "address": "1514 Hindsdale Dr", "city": "Richardson", "state": "TX",
                "postal_code": "75080", "price": 399000, "bedrooms": 3, "bathrooms": 2}
        base.update(overrides)
        return base

    def test_private_file_modes(self):
        path = Path(self.temp.name) / "scout" / "scout.sqlite3"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_schema_uses_wal_and_foreign_keys(self):
        self.assertEqual(self.conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_repeat_alert_updates_last_seen_without_duplicating(self):
        first = db.record_lead(self.conn, self.lead(), gmail_message_id="m1",
                               seen_at="2026-08-09T10:00:00Z")
        second = db.record_lead(self.conn, self.lead(), gmail_message_id="m2",
                                seen_at="2026-08-10T10:00:00Z")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertTrue(first["new_sighting"])
        # Identical card -> no second sighting; the snapshot hash is the guard.
        self.assertFalse(second["new_sighting"])
        row = self.conn.execute("SELECT * FROM scout_discovery").fetchone()
        self.assertEqual(row["first_seen_at"], "2026-08-09T10:00:00Z")
        self.assertEqual(row["last_seen_at"], "2026-08-10T10:00:00Z")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM scout_discovery").fetchone()[0], 1)

    def test_changed_price_creates_a_new_immutable_sighting(self):
        db.record_lead(self.conn, self.lead(), gmail_message_id="m1")
        outcome = db.record_lead(self.conn, self.lead(price=385000), gmail_message_id="m2")
        self.assertFalse(outcome["created"])
        self.assertTrue(outcome["new_sighting"])
        sightings = self.conn.execute(
            "SELECT raw_payload_json FROM scout_sighting ORDER BY id").fetchall()
        self.assertEqual(len(sightings), 2)
        # The earlier evidence still says 399000 -- it was not rewritten.
        self.assertEqual(json.loads(sightings[0]["raw_payload_json"])["price"], 399000)
        self.assertEqual(json.loads(sightings[1]["raw_payload_json"])["price"], 385000)
        self.assertEqual(
            self.conn.execute("SELECT price FROM scout_discovery").fetchone()[0], 385000)

    def test_absent_fields_stay_null_and_are_filled_only_when_later_supplied(self):
        db.record_lead(self.conn, self.lead(bedrooms=None, living_area=None))
        row = self.conn.execute("SELECT * FROM scout_discovery").fetchone()
        self.assertIsNone(row["bedrooms"])
        self.assertIsNone(row["living_area"])
        self.assertIsNone(row["fit_score"])

        db.record_lead(self.conn, self.lead(bedrooms=4, living_area=2100))
        row = self.conn.execute("SELECT * FROM scout_discovery").fetchone()
        self.assertEqual(row["bedrooms"], 4)
        self.assertEqual(row["living_area"], 2100)

    def test_established_stable_field_is_not_overwritten(self):
        db.record_lead(self.conn, self.lead())
        db.record_lead(self.conn, self.lead(address="Somewhere else entirely"))
        self.assertEqual(
            self.conn.execute("SELECT address FROM scout_discovery").fetchone()[0],
            "1514 Hindsdale Dr")

    def test_review_states_are_the_only_allowed_set(self):
        outcome = db.record_lead(self.conn, self.lead())
        discovery_id = outcome["discovery_id"]
        for status in ("shortlisted", "dismissed", "new"):
            self.assertTrue(db.set_review_status(self.conn, discovery_id, status)["ok"])
        for status in ("captured", "saved", "offer", "archived", ""):
            self.assertFalse(db.set_review_status(self.conn, discovery_id, status)["ok"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE scout_discovery SET status='tour' WHERE id=?",
                              (discovery_id,))

    def test_profile_versions_are_append_only_and_deduplicated(self):
        first = db.save_profile(self.conn, "Approved", {"max_price": 425000,
                                                        "cities": ["Richardson", "Garland"]})
        again = db.save_profile(self.conn, "Approved", {"max_price": 425000,
                                                        "cities": ["Richardson", "Garland"]})
        changed = db.save_profile(self.conn, "Approved", {"max_price": 400000,
                                                          "cities": ["Richardson"]})
        self.assertEqual(first["profile"]["id"], again["profile"]["id"])
        self.assertNotEqual(first["profile"]["id"], changed["profile"]["id"])
        self.assertEqual(db.latest_profile(self.conn)["id"], changed["profile"]["id"])

    def test_rescore_applies_a_new_profile_to_existing_leads(self):
        db.record_lead(self.conn, self.lead())
        self.assertIsNone(self.conn.execute("SELECT fit_score FROM scout_discovery").fetchone()[0])
        profile = db.save_profile(self.conn, "Approved",
                                  {"max_price": 425000, "cities": ["Richardson", "Garland"]})["profile"]
        self.assertEqual(db.rescore(self.conn, profile), 1)
        row = self.conn.execute("SELECT fit_score, fit_label FROM scout_discovery").fetchone()
        self.assertEqual(row["fit_score"], 100)
        self.assertEqual(row["fit_label"], "matches your criteria")

    def test_counts_cover_every_review_state(self):
        db.record_lead(self.conn, self.lead())
        tally = db.counts(self.conn)
        self.assertEqual(set(tally), {"new", "shortlisted", "dismissed", "captured", "all"})
        self.assertEqual((tally["new"], tally["all"]), (1, 1))


# --------------------------------------------------------------- importer


class ImporterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.temp.name) / "scout" / "scout.sqlite3")
        self.adapter = Adapter(
            source="zillow",
            senders=("alerts@example-zillow.test",),
            parse=lambda message, decoded: {
                "accepted": True, "reason": "fixture",
                "leads": [{"external_id": "555", "source_url":
                           "https://www.zillow.com/homedetails/x_555_zpid/",
                           "address": "1 Example St", "city": "Richardson",
                           "state": "TX", "postal_code": "75080", "price": 410000}],
            },
        )

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def run_once(self, messages, **kwargs):
        fake = FakeGmail(messages)
        summary = importer.run_import(self.conn, {"token": {}}, adapters=(self.adapter,),
                                      gmail=fake, **kwargs)
        return summary, fake

    def test_same_message_is_processed_once(self):
        message = gmail_message("m1", "alerts@example-zillow.test", "<p>lead</p>")
        first, _ = self.run_once([message])
        second, fake = self.run_once([message])
        self.assertEqual((first["imported_messages"], first["new_discoveries"]), (1, 1))
        self.assertEqual((second["imported_messages"], second["skipped_known"]), (0, 1))
        self.assertEqual(second["new_discoveries"], 0)
        self.assertNotIn(("get", "m1"), fake.calls)

    def test_wrong_sender_is_ignored_and_never_parsed(self):
        messages = [
            gmail_message("m1", "no-reply@confirmation.zillow.com", "<p>verify</p>"),
            gmail_message("m2", "donotreply@redfin.com", "<p>verify</p>"),
            gmail_message("m3", "marketing@example-zillow.test", "<p>ad</p>"),
        ]
        summary, _ = self.run_once(messages)
        self.assertEqual(summary["ignored"], 3)
        self.assertEqual(summary["imported_messages"], 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM scout_discovery").fetchone()[0], 0)
        statuses = {row[0] for row in self.conn.execute(
            "SELECT status FROM scout_gmail_message")}
        self.assertEqual(statuses, {"ignored"})

    def test_parse_empty_is_distinct_from_ignored(self):
        empty = Adapter(source="zillow", senders=("alerts@example-zillow.test",),
                        parse=lambda m, d: {"accepted": True, "reason": "no cards", "leads": []})
        fake = FakeGmail([gmail_message("m1", "alerts@example-zillow.test", "<p>x</p>")])
        summary = importer.run_import(self.conn, {"token": {}}, adapters=(empty,), gmail=fake)
        self.assertEqual((summary["parse_empty"], summary["ignored"]), (1, 0))
        self.assertEqual(self.conn.execute(
            "SELECT status FROM scout_gmail_message").fetchone()[0], "parse_empty")

    def test_dry_run_writes_nothing(self):
        summary, _ = self.run_once(
            [gmail_message("m1", "alerts@example-zillow.test", "<p>lead</p>")], dry_run=True)
        self.assertEqual(summary["discoveries_seen"], 1)
        self.assertEqual(summary["new_discoveries"], 0)
        for table in ("scout_discovery", "scout_sighting", "scout_gmail_message"):
            self.assertEqual(
                self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)

    def test_one_bad_message_does_not_kill_the_run(self):
        exploding = Adapter(
            source="zillow", senders=("alerts@example-zillow.test",),
            parse=lambda m, d: (_ for _ in ()).throw(ValueError("template changed")))
        fake = FakeGmail([gmail_message("m1", "alerts@example-zillow.test", "<p>x</p>")])
        summary = importer.run_import(self.conn, {"token": {}}, adapters=(exploding,), gmail=fake)
        self.assertFalse(summary["ok"])
        self.assertEqual(len(summary["errors"]), 1)
        self.assertEqual(self.conn.execute(
            "SELECT status FROM scout_gmail_message").fetchone()[0], "error")

    def test_summary_reports_every_required_stage(self):
        summary, _ = self.run_once(
            [gmail_message("m1", "alerts@example-zillow.test", "<p>lead</p>")])
        for key in ("query", "listed", "skipped_known", "imported_messages", "discoveries_seen",
                    "new_discoveries", "ignored", "parse_empty", "errors", "ingestion"):
            self.assertIn(key, summary)

    def test_leads_are_unranked_until_criteria_exist(self):
        summary, _ = self.run_once(
            [gmail_message("m1", "alerts@example-zillow.test", "<p>lead</p>")])
        self.assertIn("unranked", summary["ranking"])
        self.assertIsNone(self.conn.execute(
            "SELECT fit_score FROM scout_discovery").fetchone()[0])


class StalenessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.temp.name) / "scout" / "scout.sqlite3")
        self.now = datetime(2026, 8, 20, tzinfo=timezone.utc)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_no_baseline_is_not_stale(self):
        result = importer.ingestion_freshness(self.conn, now=self.now, threshold_days=3)
        self.assertFalse(result["stale"])
        self.assertIn("no accepted alert mail", result["reason"])

    def test_rejected_mail_alone_never_establishes_a_baseline(self):
        # Ignored/parse_empty/error receipts must not look like healthy ingestion.
        for index, status in enumerate(("ignored", "parse_empty", "error")):
            db.record_receipt(self.conn, gmail_message_id=f"m{index}",
                              received_at="2026-08-19T00:00:00Z", status=status)
        result = importer.ingestion_freshness(self.conn, now=self.now, threshold_days=3)
        self.assertIsNone(result["last_accepted_at"])
        self.assertFalse(result["stale"])

    def test_staleness_measures_accepted_mail_not_discoveries(self):
        db.record_receipt(self.conn, gmail_message_id="m1",
                          received_at="2026-08-19T00:00:00Z", status="imported")
        fresh = importer.ingestion_freshness(self.conn, now=self.now, threshold_days=3)
        self.assertFalse(fresh["stale"])
        self.assertAlmostEqual(fresh["days_since"], 1.0, places=1)

        db.record_receipt(self.conn, gmail_message_id="m2",
                          received_at="2026-08-01T00:00:00Z", status="imported")
        # MAX() over imported receipts -- an older duplicate must not move the baseline back.
        still_fresh = importer.ingestion_freshness(self.conn, now=self.now, threshold_days=3)
        self.assertEqual(still_fresh["last_accepted_at"], "2026-08-19T00:00:00Z")

    def test_threshold_breach_and_recovery(self):
        db.record_receipt(self.conn, gmail_message_id="m1",
                          received_at="2026-08-01T00:00:00Z", status="imported")
        self.assertTrue(
            importer.ingestion_freshness(self.conn, now=self.now, threshold_days=3)["stale"])
        db.record_receipt(self.conn, gmail_message_id="m2",
                          received_at=(self.now - timedelta(hours=2)).isoformat(),
                          status="imported")
        self.assertFalse(
            importer.ingestion_freshness(self.conn, now=self.now, threshold_days=3)["stale"])

    def test_malformed_date_is_reported_not_crashed(self):
        db.record_receipt(self.conn, gmail_message_id="m1", received_at="not a date",
                          status="imported")
        result = importer.ingestion_freshness(self.conn, now=self.now, threshold_days=3)
        self.assertFalse(result["stale"])
        self.assertIn("could not be parsed", result["reason"])

    def test_unmeasured_threshold_reports_without_alerting(self):
        db.record_receipt(self.conn, gmail_message_id="m1",
                          received_at="2026-01-01T00:00:00Z", status="imported")
        result = importer.ingestion_freshness(self.conn, now=self.now, threshold_days=None)
        self.assertFalse(result["stale"])
        self.assertIn("not yet measured", result["reason"])
        self.assertGreater(result["days_since"], 200)

    def test_threshold_is_configurable(self):
        self.assertEqual(importer.stale_threshold_days({"HOMESTEAD_SCOUT_STALE_DAYS": "5"}), 5)
        self.assertIsNone(importer.stale_threshold_days({"HOMESTEAD_SCOUT_STALE_DAYS": "0"}))
        self.assertIsNone(importer.stale_threshold_days({"HOMESTEAD_SCOUT_STALE_DAYS": "junk"}))
        self.assertIsNone(importer.stale_threshold_days({}))


# --------------------------------------------------------------- the promotion boundary


class PromotionBoundaryTest(unittest.TestCase):
    """The invariant the whole feature exists to protect."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conn = db.connect(self.root / "scout" / "scout.sqlite3")
        self.previous_listings = server.LISTINGS_DIR
        self.previous_scout = server.SCOUT_DB
        server.LISTINGS_DIR = self.root / "listings"
        server.LISTINGS_DIR.mkdir()
        server.SCOUT_DB = self.root / "scout" / "scout.sqlite3"
        self.adapter = Adapter(
            source="zillow", senders=("alerts@example-zillow.test",),
            parse=lambda m, d: {"accepted": True, "reason": "fixture", "leads": [
                {"external_id": "555",
                 "source_url": "https://www.zillow.com/homedetails/x_555_zpid/",
                 "address": "1 Example St", "city": "Richardson", "state": "TX",
                 "postal_code": "75080", "price": 410000}]},
        )

    def tearDown(self):
        self.conn.close()
        server.LISTINGS_DIR = self.previous_listings
        server.SCOUT_DB = self.previous_scout
        self.temp.cleanup()

    def test_email_import_creates_no_property_no_generation_no_media_no_listing_row(self):
        fake = FakeGmail([gmail_message("m1", "alerts@example-zillow.test", "<p>lead</p>")])
        summary = importer.run_import(self.conn, {"token": {}}, adapters=(self.adapter,),
                                      gmail=fake)
        self.assertEqual(summary["new_discoveries"], 1)

        # Nothing on the trusted side came into existence.
        self.assertEqual(list(server.LISTINGS_DIR.glob("**/*.json")), [])
        self.assertFalse((server.LISTINGS_DIR / "listings.sqlite3").exists())
        self.assertFalse((server.LISTINGS_DIR / "media").exists())
        self.assertEqual(server.listing_records(), [])

        # And the Scout database holds no listing/property/media table at all.
        tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables & {"listing", "capture", "media", "media_asset",
                                   "media_archive", "properties"}, set())

    def test_only_an_explicit_capture_promotes_and_it_links_exactly_one_lead(self):
        fake = FakeGmail([gmail_message("m1", "alerts@example-zillow.test", "<p>lead</p>")])
        importer.run_import(self.conn, {"token": {}}, adapters=(self.adapter,), gmail=fake)

        capture = {
            "schema_version": 1,
            "fields": {"source": "Zillow",
                       "source_url": "https://www.zillow.com/homedetails/x_555_zpid/?utm_source=x",
                       "external_id": "555", "address": "1 Example St", "city": "Richardson",
                       "state": "TX", "postal_code": "75080", "price": 410000},
            "raw": {"captured_at": "2026-08-09T12:00:00Z"}, "missing": [],
        }
        record, duplicate = server.store_listing_capture(capture)
        self.assertFalse(duplicate)

        outcome = reconcile.reconcile_capture(self.conn, record)
        self.assertEqual(outcome["status"], "linked")
        self.assertEqual(outcome["strategy"], "external_id")
        row = self.conn.execute("SELECT status, linked_listing_id FROM scout_discovery").fetchone()
        self.assertEqual(row["status"], "captured")
        self.assertEqual(row["linked_listing_id"], record["listing_id"])

        # Re-capturing duplicates neither side.
        record_again, _ = server.store_listing_capture(capture)
        repeat = reconcile.reconcile_capture(self.conn, record_again)
        self.assertEqual(repeat["status"], "already_linked")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM scout_discovery").fetchone()[0], 1)

    def test_a_captured_lead_cannot_be_reviewed_back_out(self):
        outcome = db.record_lead(self.conn, {
            "source": "zillow", "external_id": "555", "address": "1 Example St"})
        self.conn.execute("UPDATE scout_discovery SET status='captured' WHERE id=?",
                          (outcome["discovery_id"],))
        self.conn.commit()
        result = db.set_review_status(self.conn, outcome["discovery_id"], "dismissed")
        self.assertFalse(result["ok"])


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.temp.name) / "scout" / "scout.sqlite3")

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_canonical_url_match_when_ids_differ(self):
        db.record_lead(self.conn, {
            "source": "redfin",
            "source_url": "https://www.redfin.com/TX/Garland/1-A-St-75040/home/42?utm_source=email"})
        outcome = reconcile.reconcile_capture(self.conn, {
            "listing_id": "redfin-42", "source": "Redfin", "external_id": "",
            "source_url": "https://www.redfin.com/TX/Garland/1-A-St-75040/home/42#photos",
            "fields": {}})
        self.assertEqual((outcome["status"], outcome["strategy"]), ("linked", "canonical_url"))

    def test_normalized_address_fallback(self):
        db.record_lead(self.conn, {"source": "zillow", "address": "1514 Hindsdale Dr.",
                                   "city": "Richardson", "state": "TX", "postal_code": "75080"})
        outcome = reconcile.reconcile_capture(self.conn, {
            "listing_id": "zillow-x", "source": "Zillow", "external_id": "", "source_url": "",
            "fields": {"address": "1514 HINDSDALE DR", "city": "richardson",
                       "state": "tx", "postal_code": "75080"}})
        self.assertEqual((outcome["status"], outcome["strategy"]),
                         ("linked", "normalized_address"))

    def test_ambiguous_match_is_an_error_not_a_guess(self):
        for index in (1, 2):
            db.record_lead(self.conn, {"source": "zillow", "external_id": f"dup{index}",
                                       "address": "9 Same St", "city": "Garland",
                                       "state": "TX", "postal_code": "75040"})
        outcome = reconcile.reconcile_capture(self.conn, {
            "listing_id": "zillow-y", "source": "Zillow", "external_id": "", "source_url": "",
            "fields": {"address": "9 Same St", "city": "Garland", "state": "TX",
                       "postal_code": "75040"}})
        self.assertEqual(outcome["status"], "ambiguous")
        self.assertEqual(len(outcome["discovery_ids"]), 2)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM scout_discovery WHERE status='captured'").fetchone()[0], 0)

    def test_no_match_is_quiet(self):
        outcome = reconcile.reconcile_capture(self.conn, {
            "listing_id": "zillow-z", "source": "Zillow", "external_id": "999",
            "source_url": "https://www.zillow.com/homedetails/x_999_zpid/", "fields": {}})
        self.assertEqual(outcome["status"], "no_match")


if __name__ == "__main__":
    unittest.main()
