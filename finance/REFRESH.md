# Finance refresh runbook

Run only on Alpha from `~/homestead`. Raw exports must already be in
`/var/lib/homestead/finance/imports/` and readable only by `homestead`.

1. Back up `/var/lib/homestead/finance/finance.db` inside the private `backups/`
   directory and record its SHA-256 without printing data rows.
2. Run the appropriate loader as the `homestead` account with
   `HOMESTEAD_FINANCE_DB=/var/lib/homestead/finance/finance.db`.
   - CSV fallback: `load.py` and `load_transactions.py` against protected exports.
   - MCP: pipe the connector's normalized schema-v1 JSON directly to
     `load_mcp.py -`; do not write an intermediate file unless it stays under the
     protected imports directory.
3. Keep Monarch cash-flow semantics: exclude transfer-like categories, net
   within each category, then split positive nets into income and negative nets
   into expenses.
4. Run SQLite `PRAGMA quick_check`, build the derived dashboard payload, and
   compare non-content counts/source hashes with the import receipt.
5. Canary `GET /api/finance`; it must return derived JSON with
   `Cache-Control: no-store`. No frontend rebuild is required for data refreshes.

The loaders default to the private Alpha database and also honor the explicit
`HOMESTEAD_FINANCE_DB` override for isolated tests. The retired JSX patcher is
gone; data refreshes never edit frontend source.

The CSV fallback remains mandatory after MCP activation: compare snapshot counts,
source date spans, and derived cash-flow totals during the first live connector run.
The connector is not trusted merely because its import succeeds.
