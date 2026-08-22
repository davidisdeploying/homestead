# Homestead finance backend

This package is part of the Alpha-only Homestead repository. Code lives here;
private data does not.

- Git/build repo: `~/homestead`
- deployed runtime: `/opt/homestead`
- live database: `/var/lib/homestead/finance/finance.db`
- raw imports: `/var/lib/homestead/finance/imports/`
- service account: `homestead`

Monarch remains the system of record. Homestead stores a structured import and
owns only the obligation fields Monarch does not model. The browser receives
only the derived payload from `GET /api/finance`; it never receives raw account,
transaction, statement, or import rows.

All admin refreshes run on Alpha. Never copy the database or exports into this
repo, `~/Vaults`, a worker prompt, stdout, or journald. Before an import, make a
private database backup, preserve the source SHA-256, run SQLite `quick_check`,
and verify the derived payload before restarting the service.

## Monarch MCP adapter contract

`load_mcp.py` accepts a normalized snapshot from stdin (`-`) or a protected JSON
file. The connector remains replaceable; the database schema and post-import checks
do not change. The root object is:

```json
{
  "schema_version": 1,
  "source": "monarch-mcp",
  "captured_at": "2026-08-09T12:00:00Z",
  "accounts": [{"name":"…","category":"…","subtype":"…","owner":"…","credit_limit":null,"is_liability":false}],
  "balances": [{"account":"…","date":"2026-08-09","balance":0}],
  "goals": [{"name":"…","current_amount":0,"target_amount":0,"target_date":null,"monthly_contribution":null,"status":"…"}],
  "networth": {"net_worth":0,"assets":0,"liabilities":0,"cash":0,"investments":0,"vehicles":0,"credit_cards":0},
  "transactions": [{"id":"provider-stable-id","date":"2026-08-09","merchant":"…","category":"…","account":"…","statement":"…","notes":"…","amount":0,"tags":"…","owner":"…","reviewed":"…"}]
}
```

Required fields are validated before commit. The adapter preserves the source
SHA-256, upserts snapshots, keeps transaction imports idempotent, and applies the
same category-netting cash-flow semantics as the CSV path. It never prints rows.
