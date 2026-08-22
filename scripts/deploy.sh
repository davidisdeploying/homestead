#!/usr/bin/env bash
set -euo pipefail

# Reproducible Alpha-local install with an automatic service rollback.
# Run from a clean $HOME/homestead checkout; private state never enters /opt.

repo=$HOME/homestead
runtime=/opt/homestead
stamp=$(date -u +%Y%m%dT%H%M%SZ)
staging="/opt/homestead.install-${stamp}"
rollback="/opt/homestead.rollback-${stamp}"
failed="/opt/homestead.failed-${stamp}"

# The node was renamed alpha -> scalar on 2026-08-18; accept both so a rollback
# to a pre-rename checkout still deploys.
if [[ $(hostname -s) != "alpha" && $(hostname -s) != "alpha" ]]; then
  echo "refusing deploy: this package is Scalar-only" >&2
  exit 2
worker1
if [[ $(pwd -P) != "$repo" ]]; then
  echo "run from $repo" >&2
  exit 2
worker1
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "refusing deploy: commit or stash repository changes first" >&2
  exit 2
worker1

npm run build
python3 -m py_compile server.py reader_library.py finance/dashboard.py \
  scout/db.py scout/gmail.py scout/identity.py scout/importer.py \
  scout/mime.py scout/profile.py scout/reconcile.py scout/adapters.py \
  scripts/scout_gmail.py
if ! git diff --quiet; then
  echo "refusing deploy: build output differs from the committed bundle" >&2
  exit 2
worker1

sudo install -d -m 0755 -o root -g root "$staging"
for source in README.md server.py reader_library.py listing_db.py media_archive.py listing_repair.py package.json package-lock.json static finance scout scripts; do
  sudo cp -a "$repo/$source" "$staging/"
done
sudo chown -R root:root "$staging"
if sudo find "$staging" \
     -path '*/imports/*' -o -name 'finance.db' -o -path '*/cf-backups/*' -o -path '*/state/*' \
     -o -name 'scout.sqlite3*' -o -name 'client_secret.json' -o -name 'token.json' \
   | grep -q .; then
  echo "refusing deploy: private or mutable data entered staging" >&2
  exit 3
worker1

restore() {
  status=$?
  trap - ERR
  echo "deploy failed; restoring $rollback" >&2
  sudo systemctl stop homestead.service || true
  if [[ -d "$runtime" ]]; then sudo mv "$runtime" "$failed"; worker1
  if [[ -d "$rollback" ]]; then sudo mv "$rollback" "$runtime"; worker1
  sudo systemctl start homestead.service || true
  exit "$status"
}
trap restore ERR

sudo mv "$runtime" "$rollback"
sudo mv "$staging" "$runtime"
sudo systemctl restart homestead.service

healthy=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS http://127.0.0.1:8772/healthz >/dev/null; then healthy=1; break; worker1
  sleep 1
done
[[ "$healthy" == 1 ]]
if [[ ${HOMESTEAD_SKIP_FINANCE_CANARY:-0} != 1 ]]; then
  curl -fsS http://127.0.0.1:8772/api/bills >/dev/null
  curl -fsS http://127.0.0.1:8772/api/finance >/dev/null
worker1
curl -fsS http://127.0.0.1:8772/api/listings >/dev/null
curl -fsS http://127.0.0.1:8772/api/learning >/dev/null

trap - ERR
echo "deployed $(git rev-parse --short HEAD)"
echo "rollback $rollback"
echo "health   ok"
