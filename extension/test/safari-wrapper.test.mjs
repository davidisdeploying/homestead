import assert from "node:assert/strict";
import { lstat, readFile, readlink } from "node:fs/promises";
import { test } from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(here, "../..");
const wrapper = path.join(repository, "apple", "Homestead for Safari");

test("Safari wrapper consumes the canonical WebExtension resources", async () => {
  const resources = path.join(wrapper, "Shared (Extension)", "Resources");
  assert.equal((await lstat(resources)).isSymbolicLink(), true);
  assert.equal(await readlink(resources), "../../../extension");
});

test("Safari wrapper uses the approved two-ID budget across platforms", async () => {
  const project = await readFile(
    path.join(wrapper, "Homestead for Safari.xcodeproj", "project.pbxproj"),
    "utf8",
  );
  assert.equal(
    project.match(/PRODUCT_BUNDLE_IDENTIFIER = cc\.davidgomez\.homestead\.safari;/g)?.length,
    4,
  );
  assert.equal(
    project.match(/PRODUCT_BUNDLE_IDENTIFIER = cc\.davidgomez\.homestead\.safari\.Extension;/g)?.length,
    4,
  );
});

test("Safari wrapper preserves user-initiated capture permissions", async () => {
  const manifest = JSON.parse(
    await readFile(path.join(repository, "extension", "manifest.json"), "utf8"),
  );
  assert.equal(manifest.name, "Homestead Capture");
  assert.deepEqual(manifest.permissions, ["activeTab", "scripting", "storage"]);
  assert.deepEqual(manifest.host_permissions, [
    "https://www.zillow.com/*",
    "https://www.redfin.com/*",
    "https://homestead.example.com/*",
  ]);
});
