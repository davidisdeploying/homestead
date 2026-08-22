-- Homestead finance store
--
-- DELIBERATELY OUTSIDE ~/Vaults. That tree Syncthing-replicates to Delta,
-- Charlie, Alpha and Bravo, is git-committed nightly by Alpha, and
-- pushes to GitHub on an allowlist. A household's full balance history has no
-- business on shared worker hosts where cloud models execute. Mac-local only.
--
-- Source of record remains Monarch. This is a structured local copy for
-- analysis the Monarch UI cannot do — trajectory fitting, payment-shock
-- modelling, and feeding the Homestead dashboard.

CREATE TABLE IF NOT EXISTS import_run (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file  TEXT    NOT NULL,
    source_sha256 TEXT   NOT NULL,
    row_count    INTEGER NOT NULL,
    imported_at  TEXT    NOT NULL,
    note         TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS account (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    category      TEXT,           -- Cash | Credit Cards | Investments | Vehicles
    subtype       TEXT,           -- Checking | Savings | Credit Card | 401k | Car ...
    owner         TEXT,           -- Shared | one owner | the other
    credit_limit  REAL,
    is_liability  INTEGER NOT NULL DEFAULT 0 CHECK (is_liability IN (0,1)),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS balance (
    account_id  INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    date        TEXT    NOT NULL,
    balance     REAL    NOT NULL,
    import_id   INTEGER REFERENCES import_run(id) ON DELETE SET NULL,
    PRIMARY KEY (account_id, date)
);
CREATE INDEX IF NOT EXISTS idx_balance_date ON balance(date);

-- Point-in-time capture of a Monarch savings goal. Goals move; keep the history
-- rather than overwriting, so a changed target or date is visible later.
CREATE TABLE IF NOT EXISTS goal_snapshot (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at          TEXT NOT NULL,
    name                 TEXT NOT NULL,
    current_amount       REAL NOT NULL,
    target_amount        REAL NOT NULL,
    target_date          TEXT,
    monthly_contribution REAL,
    status               TEXT,
    UNIQUE(captured_at, name)
);

-- Household-level totals as Monarch reported them, so derived figures can be
-- checked against the source rather than trusted.
CREATE TABLE IF NOT EXISTS networth_snapshot (
    captured_at   TEXT PRIMARY KEY,
    net_worth     REAL NOT NULL,
    assets        REAL NOT NULL,
    liabilities   REAL NOT NULL,
    cash          REAL,
    investments   REAL,
    vehicles      REAL,
    credit_cards  REAL
);

-- Assumptions behind any affordability figure. Never bake a rate into a
-- computation without a row here saying where it came from and that it is an
-- assumption, not a quote.
CREATE TABLE IF NOT EXISTS assumption (
    key         TEXT PRIMARY KEY,
    value       REAL NOT NULL,
    unit        TEXT NOT NULL,
    source      TEXT NOT NULL,
    confirmed   INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0,1)),
    updated_at  TEXT NOT NULL
);
