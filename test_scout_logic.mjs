import assert from "node:assert/strict";
import test from "node:test";

import { hasDirectListingLink, leadAddressLine, redfinLookupUrl } from "./scout_logic.mjs";

const REDFIN_LEAD = {
  source: "redfin", address: "2922 Canis Cir", city: "Garland", state: "TX",
  postal_code: "75044", price: 230000,
};

const ZILLOW_LEAD = {
  source: "zillow", address: "1817 Millwick St", city: "Garland", state: "TX",
  postal_code: "75044", external_id: "27037578",
  source_url: "https://www.zillow.com/homedetails/27037578_zpid/",
};

test("redfin lookup uses the ZIP browse page, the only verified constructible URL", () => {
  assert.equal(redfinLookupUrl(REDFIN_LEAD), "https://www.redfin.com/zipcode/75044");
});

test("redfin lookup falls back to the site root when the alert carried no ZIP", () => {
  assert.equal(redfinLookupUrl({ ...REDFIN_LEAD, postal_code: null }),
               "https://www.redfin.com/");
  assert.equal(redfinLookupUrl({ ...REDFIN_LEAD, postal_code: "" }),
               "https://www.redfin.com/");
  // Never emit a malformed path from a junk value.
  assert.equal(redfinLookupUrl({ ...REDFIN_LEAD, postal_code: "75044-1234" }),
               "https://www.redfin.com/");
  assert.equal(redfinLookupUrl({}), "https://www.redfin.com/");
});

test("redfin lookup never fabricates an address-precise path", () => {
  // The slug form 404s without the property ID, which the email never provides. If this
  // ever starts returning a /home/ or street-slug path, it is guessing.
  const url = redfinLookupUrl(REDFIN_LEAD);
  assert.ok(!url.includes("/home/"), "must not invent a listing path");
  assert.ok(!url.toLowerCase().includes("canis"), "must not invent an address slug");
});

test("address line is what a person pastes into a search box", () => {
  assert.equal(leadAddressLine(REDFIN_LEAD), "2922 Canis Cir, Garland, TX 75044");
  assert.equal(leadAddressLine({ address: "9 Fictional Ln", city: "Garland", state: "TX" }),
               "9 Fictional Ln, Garland, TX");
  assert.equal(leadAddressLine({ address: "9 Fictional Ln" }), "9 Fictional Ln");
  assert.equal(leadAddressLine({ city: "Garland", state: "TX" }), "",
               "no street means nothing worth pasting");
  assert.equal(leadAddressLine(null), "");
});

test("only a parser-recovered listing URL counts as a direct link", () => {
  assert.equal(hasDirectListingLink(ZILLOW_LEAD), true);
  assert.equal(hasDirectListingLink(REDFIN_LEAD), false);
  assert.equal(hasDirectListingLink({ source_url: "" }), false);
  assert.equal(hasDirectListingLink(null), false);
});

test("the lookup URL is never mistaken for a canonical source_url", () => {
  // Guard on the invariant that matters: reconcile.py matches saved captures against
  // source_url, so the synthesized lookup must never be written back into a lead.
  const lead = { ...REDFIN_LEAD };
  redfinLookupUrl(lead);
  leadAddressLine(lead);
  assert.equal(lead.source_url, undefined, "helpers must not mutate the lead");
});
