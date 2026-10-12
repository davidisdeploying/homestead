# Homestead Capture

A user-triggered Chrome extension for a single Zillow or Redfin property page.
It never crawls search results and never runs an extractor until **Extract this
listing** is clicked.

## Install

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Choose **Load unpacked** and select this `extension/` directory.
4. Pin **Homestead Capture**.

## Capture flow

1. Open one Zillow or Redfin home-detail page.
2. Click the Homestead extension, then **Extract this listing**.
3. Review the complete listing dossier: photos, floor plans/3D links, description,
   grouped facts, rooms, histories, schools, and attribution.
4. Click **Review in Homestead**.
5. Homestead opens its Properties view. Correct any fields, then save.

The capture contains structured listing facts, description, high-resolution photo
URLs, floor-plan/3D/video references, price/tax history, schools, attribution, JSON-LD, selected embedded
listing data, metadata, and a bounded visible-text source snapshot. The private
Homestead server stores immutable capture generations separately from the
household state blob.

## Adapter contract

`src/adapters/registry.js` is the only site registry. Each adapter returns:

```js
{ fields, raw, missing }
```

Parsed fields are best-effort. `raw` preserves the source evidence used for
later re-parsing. Adding a site requires one adapter file and one registry row.
