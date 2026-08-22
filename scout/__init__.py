"""Homestead Scout — email-delivered property leads, kept outside Properties.

Scout reads deliberately configured Zillow and Redfin saved-search alerts from Gmail
(read-only), extracts lightweight leads, deduplicates repeat alerts, and presents them
for review. A lead is NOT a property. It becomes a trusted Homestead property only when
David opens the live listing page, runs the existing active-tab extension, reviews the
full capture, and explicitly saves it through /api/listings.

The load-bearing boundary, restated because it is easy to erode:

    email discovery  ->  review state only
    live-page capture ->  Properties, immutable generations, listings.sqlite3, media

Nothing in this package may write state.properties, an immutable listing generation, a
listings.sqlite3 row, or the media archive. Reconciliation runs in the other direction:
a capture that already succeeded may mark one discovery `captured`.
"""

SCHEMA_VERSION = 1
