import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { test } from "node:test";
import { JSDOM } from "jsdom";

const root = path.resolve(import.meta.dirname, "..");

function parse(site, fixture, url) {
  const dom = new JSDOM(fs.readFileSync(path.join(root, "test/fixtures", fixture), "utf8"), { url });
  const context = vm.createContext({ self: dom.window, globalThis: dom.window, console });
  for (const file of ["shared.js", `${site}.js`]) {
    vm.runInContext(fs.readFileSync(path.join(root, "src/adapters", file), "utf8"), context);
  }
  return dom.window.HomesteadListingAdapters[site].parse(dom.window.document, url);
}

function matches(site, url) {
  const dom = new JSDOM("", { url });
  const context = vm.createContext({ self: dom.window, globalThis: dom.window, console });
  for (const file of ["shared.js", `${site}.js`]) {
    vm.runInContext(fs.readFileSync(path.join(root, "src/adapters", file), "utf8"), context);
  }
  return dom.window.HomesteadListingAdapters[site].match(url);
}

test("Zillow adapter preserves structured and page evidence", () => {
  const result = parse("zillow", "zillow.html", "https://www.zillow.com/homedetails/4102-Example-Bend-Dallas-TX-75248/10000001_zpid/");
  assert.equal(result.fields.external_id, "10000001");
  assert.equal(result.fields.address, "4102 Example Bend");
  assert.equal(result.fields.city, "Dallas");
  assert.equal(result.fields.price, 1299000);
  assert.equal(result.fields.bedrooms, 4);
  assert.equal(result.fields.living_area, 3964);
  assert.equal(result.fields.lot_sqft, 12000);
  assert.equal(result.fields.estimate, 1252600);
  assert.equal(result.fields.description, "The correct full listing description.");
  assert.equal(result.fields.facts.architecturalStyle, "Traditional");
  assert.equal(result.fields.attribution_details.agentName, "Ada Agent");
  assert.equal(result.fields.photo_urls[0], "https://photos.example/one-1536.jpg");
  assert.deepEqual(Array.from(result.fields.media, (item) => item.kind).sort(), ["floor_plan", "photo", "three_d"]);
  assert.equal(result.fields.price_history.length, 2);
  assert.equal(result.fields.tax_history.length, 1);
  assert.match(result.raw.visible_text, /Zestimate/);
  assert.ok(JSON.stringify(result).length < 2 * 1024 * 1024);
  assert.equal(result.missing.length, 0);
});

test("Redfin adapter uses DOM fallbacks and structured history", () => {
  const url = "https://www.redfin.com/TX/Dallas/Example-St-75201/home/12345678";
  assert.equal(matches("redfin", url), true);
  assert.equal(matches("redfin", "https://www.redfin.com/city/30794/TX/Richardson"), false);
  const result = parse("redfin", "redfin.html", url);
  assert.equal(result.fields.external_id, "12345678");
  assert.equal(result.fields.address, "123 Example St");
  assert.equal(result.fields.price, 625000);
  assert.equal(result.fields.bathrooms, 2.5);
  assert.equal(result.fields.year_built, 1998);
  assert.equal(result.fields.mls_id, "NTREIS-20480001");
  assert.equal(result.fields.estimate, 618500);
  assert.equal(result.fields.photo_urls.length, 2);
  assert.equal(result.fields.features[0], "Appliances: Dishwasher, Disposal");
  assert.equal(result.fields.price_history.length, 1);
  assert.equal(result.fields.tax_history.length, 1);
  assert.equal(result.fields.schools.length, 1);
  assert.equal(result.fields.listing_details.page_view_count, 321);
  assert.equal(result.fields.latitude, 32.78);
  assert.equal(result.fields.longitude, -96.8);
  assert.ok(Object.keys(result.raw.redfin_server_payloads).length >= 4);
  assert.ok(JSON.stringify(result).length < 2 * 1024 * 1024);
  assert.equal(result.missing.length, 0);
});
