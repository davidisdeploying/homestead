# Homestead

Homestead is a self-hosted house-hunting workspace. A browser extension captures
listings from Zillow and Redfin; Homestead archives each capture immutably as
source evidence, normalizes it into a comparable property database with capture
lineage, price and tax history, schools, and media, and pairs that with a private
finance dashboard so an offer can be weighed against real affordability.

Because listings are edited and pulled by their sites, the immutable capture
generations matter as much as the normalized view: the database can always be
rebuilt from them, and a delisted property keeps its evidence.

## Running this

A Python server plus a small JS build, with a browser extension loaded
separately.

```sh
npm ci && npm run build
python3 server.py
npm run test:reader && npm run test:scout
python3 -m unittest discover -s . -p "test_*.py"
```

Nothing personal is repository content. Runtime state lives outside the tree at
`/var/lib/homestead` under a dedicated service account: `finance.db`, captured
listings, the content-addressed media archive, and `cf-backups/` are all
gitignored. The finance module ships schema and loaders only — no data.

`extension/` loads unpacked in a Chromium browser and captures listings into the
running server.

`scripts/deploy.sh` is the deploy path and is host-guarded on purpose; it
refuses to run anywhere but the deployment host.

## Repository and deployment

This is Homestead's canonical application repository. It is built on Alpha and served
only on loopback behind the `edge` Cloudflare tunnel and Access policy.

Private runtime state and finance data are not repository content. They live at
`/var/lib/homestead` under the dedicated `homestead` service account. The finance
API exposes only the aggregate dashboard payload; it never returns raw accounts,
transactions, statements, or imported files.

Listing imports keep two private representations under `/var/lib/homestead/listings`:
immutable JSON capture generations are the source evidence, while `listings.sqlite3`
normalizes canonical properties, capture lineage, facts, media, price/tax events,
schools, and attribution for comparisons and future AI analysis. The database can be
rebuilt from the JSON generations. `/api/listings/compare` exposes the current
comparison matrix behind the existing Cloudflare Access gate.

Eligible listing photos, floor-plan images, and direct videos are downloaded during
save into a content-addressed archive at `listings/media/sha256/`. Identical bytes are
stored once even when they appear in multiple captures or listings. SQLite records the
source URL, capture position, SHA-256, MIME type, byte count, and archive status;
`/api/listings/media/<sha256>` serves the verified private copy. Downloads are limited
to approved Zillow/Redfin media hosts, 80 items, 25 MB per asset, and 300 MB per capture.
Interactive 3D applications retain their source metadata and links; downloadable
preview images are archived, but Homestead does not attempt to clone the hosted app.

Build with `npm ci && npm run build`. The system service runs the deployed copy at
`/opt/homestead`.

## Deploy on Scalar

From a clean, committed checkout:

```sh
cd ~/homestead
./scripts/deploy.sh
```

The script rebuilds and syntax-checks the app, stages only the runtime allowlist,
refuses private or mutable data, moves the current runtime to a timestamped rollback
directory, restarts the service, and restores the prior runtime automatically if the
health or derived API canaries fail. It never prunes rollback directories.
