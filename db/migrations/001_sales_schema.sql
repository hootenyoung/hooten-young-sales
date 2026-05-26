-- =====================================================================
-- 001_sales_schema.sql
-- =====================================================================
-- Initial schema for the Hooten Young sales backend (hooten-young-sales).
--
-- Purpose:
--   Creates the `sales` schema and all tables used by the sales API.
--   These tables back two data domains:
--     1. Sales invoices  — QuickBooks "Sales by Product/Service Detail"
--                          feed, dropped weekly by the broker partner.
--     2. Depletions       — state x account x product x month pull-through
--                          at the retail level, also dropped weekly.
--
-- Why both domains live in one schema:
--   Both feeds describe product movement through the 3-tier US alcohol
--   distribution model (Producer -> Distributor -> Retail Account).
--   Sales tracks what HY invoices to its direct customers (distributors,
--   state control boards, military exchanges). Depletions tracks the
--   downstream pull-through at retail (what bars, restaurants, and
--   liquor stores actually moved). They are different layers of the
--   same business, and the dashboards routinely join them.
--
-- Design principles encoded here:
--   * Long-format facts. Depletions are stored one row per
--     (account, product, month), never as wide monthly columns. This
--     makes every aggregate a clean GROUP BY date_trunc('month', ...).
--   * Idempotent ingestion. Every fact table has a natural-key UNIQUE
--     constraint, and file_uploads dedups by SHA256. Re-uploading the
--     same file is a no-op; re-uploading a corrected file overwrites
--     in place. The broker may send month-to-date snapshots or weekly
--     deltas — either is safe.
--   * Alias tables decouple raw source strings from canonical entities.
--     product_aliases and customer_aliases mean broker-format changes
--     (truncation, casing, renaming) require no DDL.
--   * source_system column on invoices and file_uploads namespaces
--     external references. If the broker changes and a new invoice
--     numbering scheme collides with the old one, old and new data
--     coexist cleanly via the composite UNIQUE.
--   * Tunable business values (commission rate, current source system)
--     live in sales.app_config so they can be changed without a deploy.
--   * Money/quantity columns are NUMERIC (never float). Source data
--     contains fractional cases (e.g. 6.83, 0.083334) and money that
--     must round predictably.
--
-- Audit columns convention:
--   * Dimension and config tables get: created_at, updated_at, is_active.
--   * Fact tables (invoices, invoice_lines, depletions) get only
--     created_at + a file_upload_id FK — the upload ledger is the audit
--     trail. invoice_lines has no updated_at because re-uploading an
--     invoice deletes-and-reinserts its lines.
--   * created_by / updated_by intentionally deferred until user/auth
--     integration. ALTER tables to add them then.
--
-- How to run:
--   psql "$DATABASE_URL" -f db/migrations/001_sales_schema.sql
--
-- Idempotency:
--   The script is wrapped in a transaction. It is intended to run once
--   against an empty `sales` schema. Re-running will fail (CREATE TABLE
--   without IF NOT EXISTS) — by design, so accidental re-execution
--   doesn't silently mask drift. To reset for development:
--       DROP SCHEMA sales CASCADE;
-- =====================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS sales;
SET search_path TO sales;


-- =====================================================================
-- TABLE: sales.app_config
-- =====================================================================
-- WHY:
--   Tunable business parameters that may change without a code release.
--   Today this holds the commission rate (currently flat 10%) and the
--   current source-system identifier used when stamping invoices and
--   uploads. Tomorrow it can hold any other "the business sometimes
--   changes this value" knob (default currency, freight pct, etc.).
--
-- HOW:
--   Read once at API startup and cached in memory, or referenced inline
--   in SQL via a subquery when computing derived values:
--       SELECT amount * (SELECT value::numeric FROM sales.app_config
--                        WHERE key = 'commission_rate' AND is_active)
--       FROM sales.invoice_lines;
--
-- NOTE:
--   This table is for CURRENT-VALUE config only. If a value needs
--   historical effective-date ranges (e.g. commission rate that varies
--   by year), that is a different, purpose-built table.
-- ---------------------------------------------------------------------
CREATE TABLE app_config (
    key             TEXT        PRIMARY KEY,                        -- Stable identifier, snake_case (e.g. 'commission_rate')
    value           TEXT        NOT NULL,                           -- Stored as text; callers cast to numeric/bool/etc.
    description     TEXT        NOT NULL,                           -- What this key means and where it's read from. Required to keep the table self-documenting.

    is_active       BOOLEAN     NOT NULL DEFAULT true,              -- Soft-disable without deleting (preserves history of the key existing)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- TABLE: sales.file_uploads
-- =====================================================================
-- WHY:
--   Audit ledger for every xlsx (or other source file) we ingest.
--   Every fact row in invoices, invoice_lines, and depletions carries
--   a FK back to the upload that produced it. This enables:
--     * Re-running an upload (delete by file_upload_id, re-ingest)
--     * Rolling back a bad upload
--     * Showing "data last refreshed from upload X at time Y" in the UI
--     * Diagnosing where any single row originated
--
-- HOW:
--   The upload endpoint:
--     1. Computes SHA256 of the file bytes.
--     2. If a row with the same sha256 already exists -> 200 OK no-op.
--     3. Otherwise INSERT a row with status='pending', then start
--        parsing. As rows are written, increment the counters here.
--     4. On success set status='success'; on failure set status='failed'
--        with error_message populated.
--
-- DEDUP:
--   sha256 UNIQUE is the primary dedup key. Renaming a file does not
--   defeat dedup; editing one cell does (the file becomes a new upload,
--   which is correct — we want to re-ingest corrected files).
-- ---------------------------------------------------------------------
CREATE TABLE file_uploads (
    id                      BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    filename                TEXT        NOT NULL,                   -- Original filename as uploaded (display only; not unique)
    sha256                  CHAR(64)    NOT NULL UNIQUE,            -- Hex SHA-256 of the file bytes. Dedup key.
    kind                    TEXT        NOT NULL,                   -- Type of feed; see CHECK constraint below
    source_system           TEXT        NOT NULL,                   -- Where this file format originated (e.g. 'quickbooks'). Stamped onto downstream invoices.

    -- Timing
    uploaded_at             TIMESTAMPTZ NOT NULL DEFAULT now(),     -- When the upload row was created (start of ingestion)
    processed_at            TIMESTAMPTZ,                            -- When ingestion finished (success or failure)
    source_generated_at     TIMESTAMPTZ,                            -- Timestamp embedded in the file footer (when the broker generated the report). May be null if not present.

    -- Period covered by the file (parsed from headers/data). Useful for
    -- UI like "this upload covers April 2026" without needing to query
    -- the line rows.
    period_start            DATE,
    period_end              DATE,

    -- Who uploaded (deferred until auth). Free-form text for now;
    -- ingestion jobs can set 'system:ingestion' or similar.
    uploaded_by             TEXT,

    -- Ingestion status + counters
    status                  TEXT        NOT NULL DEFAULT 'pending', -- See CHECK below
    row_count_processed     INT         NOT NULL DEFAULT 0,         -- Total non-junk data rows seen in the file
    row_count_inserted      INT         NOT NULL DEFAULT 0,         -- New fact rows added
    row_count_updated       INT         NOT NULL DEFAULT 0,         -- Existing fact rows whose values changed
    row_count_skipped       INT         NOT NULL DEFAULT 0,         -- Rows identical to existing (no-op upserts)
    row_count_failed        INT         NOT NULL DEFAULT 0,         -- Rows that errored during ingestion
    error_message           TEXT,                                   -- Populated when status='failed' or partial

    notes                   TEXT,                                   -- Free-form notes (manual annotations, e.g. "historical backfill from email 2026-05-25")

    CONSTRAINT chk_file_uploads_kind CHECK (
        kind IN ('sales', 'sales_historical', 'depletions', 'depletions_ytd')
    ),
    CONSTRAINT chk_file_uploads_status CHECK (
        status IN ('pending', 'processing', 'success', 'failed', 'partial')
    )
);

-- Most common access patterns:
--   * "Show recent uploads of a kind" (admin UI)
--   * "Which uploads failed?" (ops)
CREATE INDEX idx_file_uploads_kind_uploaded_at  ON file_uploads (kind, uploaded_at DESC);
CREATE INDEX idx_file_uploads_status            ON file_uploads (status) WHERE status <> 'success';


-- =====================================================================
-- TABLE: sales.products
-- =====================================================================
-- WHY:
--   Canonical SKU catalog. One row per real Hooten Young product as
--   the business thinks of it (e.g. "Hooten & Young American Whiskey
--   12yr - 750ml/6"). Joined from invoice_lines and depletions.
--
-- HOW:
--   Populated initially from the MVP's product list and grown as new
--   SKUs appear in uploads. The ingestion job resolves raw text from
--   files via product_aliases; if no alias matches, the row ingests
--   with product_id=NULL and an admin can map it later.
--
-- WHY NOT a SKU code column:
--   QB does not provide a stable SKU identifier in the files we receive.
--   Full product name is the only identifier we get. Add a code column
--   if/when an upstream system provides one.
-- ---------------------------------------------------------------------
CREATE TABLE products (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    full_name       TEXT        NOT NULL UNIQUE,                    -- Canonical full name as the business uses it
    short_name      TEXT,                                            -- Optional display abbreviation for charts (e.g. "American Whiskey 12yr")
    category        TEXT,                                            -- 'Whiskey', 'Bourbon', 'Rye', 'Single Barrel', 'Barrel Strength', 'Collaboration', etc. Free-form; can tighten to enum later.
    pack_size       INT,                                             -- Bottles per case (typically 6 or 12)
    bottle_size_ml  INT,                                             -- Bottle volume in ml (typically 750)

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- TABLE: sales.product_aliases
-- =====================================================================
-- WHY:
--   The sales feed uses ALL-CAPS names truncated to ~40 chars
--   ("HOOTEN & YOUNG AMERICAN WHISKEY 12YR - 750"). The depletions feed
--   truncates to ~22 chars ("Hooten Young 12 Year Amer"). Future feeds
--   from a different broker will use yet other spellings. Rather than
--   normalize at parse time (fragile string manipulation), we keep a
--   lookup table from raw text -> canonical product.
--
-- HOW:
--   Ingestion looks up alias_text against this table; on hit, uses the
--   product_id. On miss, the fact row still ingests with product_id=NULL
--   and product_raw_text preserved, plus the alias is logged to be
--   reviewed by an admin.
--
-- NOTE:
--   alias_text is stored as the parser sees it (no trimming, no case
--   normalization). The parser should be deterministic so the same raw
--   string always hashes to the same alias row.
-- ---------------------------------------------------------------------
CREATE TABLE product_aliases (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    alias_text      TEXT        NOT NULL UNIQUE,                    -- Verbatim raw string from a source file
    product_id      BIGINT      NOT NULL,                           -- Canonical product this alias resolves to
    source          TEXT        NOT NULL,                           -- 'sales', 'depletions', 'manual' — where this alias was first seen
    notes           TEXT,                                            -- Optional admin annotation (e.g. "matched via fuzzy review")

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_product_aliases_product
        FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT chk_product_aliases_source CHECK (
        source IN ('sales', 'depletions', 'manual')
    )
);

CREATE INDEX idx_product_aliases_product ON product_aliases (product_id);


-- =====================================================================
-- TABLE: sales.distributors
-- =====================================================================
-- WHY:
--   The 3-tier model's middle layer. HY sells to a distributor or
--   distributor-equivalent (state control board, military exchange),
--   which then sells to retail. This table is the parent entity:
--   "RNDC", "Empire", "GREENLIGHT", "Ohio ABC", "NEXCOM", etc.
--
--   Both sales and depletions reference distributors. On the sales
--   side, customers.distributor_id captures the parent. On the
--   depletions side, accounts.distributor_id captures which distributor
--   services that retail location.
--
-- HOW:
--   Populated from a combination of the sales `Customer` field and the
--   depletions `Distributor` field. The `channel` column captures the
--   structural difference between a typical wholesale distributor and
--   a control-state or military buyer (these don't have downstream
--   retail in the same way).
-- ---------------------------------------------------------------------
CREATE TABLE distributors (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    name            TEXT        NOT NULL UNIQUE,                    -- Canonical name (e.g. "RNDC", "Empire Distributors", "Ohio ABC")
    channel         TEXT        NOT NULL DEFAULT 'distributor',     -- Structural classification; see CHECK below
    notes           TEXT,

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_distributors_channel CHECK (
        channel IN ('distributor', 'control_state', 'military', 'other')
    )
);


-- =====================================================================
-- TABLE: sales.customers
-- =====================================================================
-- WHY:
--   The bill-to entities HY invoices in the QuickBooks sales feed.
--   Examples: "RNDC - TX Houson", "Ohio ABC", "GREENLIGHT - FL",
--   "Coast Guard - Centreville 459". One distributor (RNDC) may map
--   to many customers (RNDC's Houston operation, RNDC's Schertz
--   operation, etc.).
--
-- HOW:
--   The QB `Customer` field is stored as a customer_aliases row;
--   customer_aliases.customer_id points here. canonical_name is the
--   curated name we want to display in the UI (typically without
--   territory suffix, e.g. "RNDC - TX Houston").
--
-- AMBIGUITY HANDLING:
--   Some customer names don't cleanly reveal a state ("MBG",
--   "Empire Distributors - Nashville" — Empire HQ is GA, ships from TN
--   warehouses). state_code is nullable; we flag ambiguous ones for
--   manual review rather than guessing.
-- ---------------------------------------------------------------------
CREATE TABLE customers (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    canonical_name  TEXT        NOT NULL UNIQUE,                    -- Curated display name
    distributor_id  BIGINT,                                          -- Parent distributor (FK below). Nullable for orphans / unmatched.
    state_code      CHAR(2),                                         -- 2-letter US state code; nullable when ambiguous
    territory       TEXT,                                            -- Optional descriptor (e.g. "Houston", "TX Grand Prairie")
    notes           TEXT,

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_customers_distributor
        FOREIGN KEY (distributor_id) REFERENCES distributors (id)
);

CREATE INDEX idx_customers_distributor  ON customers (distributor_id);
CREATE INDEX idx_customers_state        ON customers (state_code);


-- =====================================================================
-- TABLE: sales.customer_aliases
-- =====================================================================
-- WHY:
--   Same rationale as product_aliases. The QB "Customer" string is one
--   particular spelling of a real-world entity; a new broker would
--   spell it differently. Decouple the raw text from the canonical
--   customer.
--
-- HOW:
--   Ingestion looks up the raw QB Customer string here. On hit, uses
--   the resolved customer_id on the invoice. On miss, the invoice
--   ingests with customer_id=NULL (and customer_raw_text preserved),
--   plus a new unresolved-alias row is logged for admin review.
-- ---------------------------------------------------------------------
CREATE TABLE customer_aliases (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    alias_text      TEXT        NOT NULL UNIQUE,                    -- Verbatim raw string from the source file
    customer_id     BIGINT      NOT NULL,                           -- Canonical customer
    source_system   TEXT        NOT NULL DEFAULT 'quickbooks',      -- Which source system used this spelling
    notes           TEXT,

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_customer_aliases_customer
        FOREIGN KEY (customer_id) REFERENCES customers (id)
);

CREATE INDEX idx_customer_aliases_customer ON customer_aliases (customer_id);


-- =====================================================================
-- TABLE: sales.accounts
-- =====================================================================
-- WHY:
--   The downstream layer of the 3-tier model: retail locations
--   (liquor stores, bars, restaurants, military commissaries) that
--   actually move product to the consumer. Sourced from the depletions
--   feed, which lists volume by retail account per month.
--
--   Different from customers. A customer is a bill-to entity for HY;
--   an account is a retail location served by a distributor. The two
--   meet via distributors.
--
-- HOW:
--   The depletions feed provides: state, account name, address, city,
--   distributor code (e.g. "FL13"), and (in the YTD variant) ON/OFF
--   premises classification. Natural key is (name, address, state_code)
--   because the same chain can have many stores at different addresses.
--
-- PREMISES TYPE:
--   ON  = on-premise consumption (bars, restaurants, hotels)
--   OFF = off-premise (liquor stores, retail)
--   NULL = unknown (older depletion files don't include this field)
-- ---------------------------------------------------------------------
CREATE TABLE accounts (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    name                TEXT        NOT NULL,
    address             TEXT,
    city                TEXT,
    state_code          CHAR(2),
    distributor_id      BIGINT,                                     -- Which distributor services this account
    distributor_code    TEXT,                                        -- Raw code from depletions file (e.g. "FL13"); kept for traceability
    premises_type       TEXT,                                        -- 'ON' or 'OFF'; nullable when unknown
    notes               TEXT,

    is_active           BOOLEAN     NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_accounts_distributor
        FOREIGN KEY (distributor_id) REFERENCES distributors (id),
    CONSTRAINT chk_accounts_premises CHECK (
        premises_type IS NULL OR premises_type IN ('ON', 'OFF')
    ),
    -- Natural key: same chain at different addresses are different rows.
    -- Address can be NULL, so use COALESCE-friendly UNIQUE via NULLS NOT
    -- DISTINCT (Postgres 15+). If on older Postgres, an alternative is
    -- a partial unique index.
    CONSTRAINT uq_accounts_natural UNIQUE NULLS NOT DISTINCT (name, address, state_code)
);

CREATE INDEX idx_accounts_state             ON accounts (state_code);
CREATE INDEX idx_accounts_distributor       ON accounts (distributor_id);
CREATE INDEX idx_accounts_state_distributor ON accounts (state_code, distributor_id);


-- =====================================================================
-- TABLE: sales.invoices
-- =====================================================================
-- WHY:
--   The header row for each sales invoice. One row per QB `Num`
--   (e.g. "SI-012682"). Lines hang off invoice_lines.
--
-- HOW (ingestion):
--   UPSERT on (source_system, invoice_ref):
--     INSERT ... ON CONFLICT (source_system, invoice_ref)
--     DO UPDATE SET customer_id=EXCLUDED.customer_id,
--                   invoice_date=EXCLUDED.invoice_date,
--                   ...
--     If nothing changes the row is touched but values are equal,
--     equivalent to a skip (ingestion can detect this via
--     "xmax = 0" or row counters).
--
-- WHY source_system AS PART OF THE KEY:
--   If the broker changes and the new system reuses invoice number
--   "SI-012682" with a different meaning, the composite UNIQUE keeps
--   both rows distinct. Same logic on file_uploads.source_system.
--
-- NULLABLE customer_id:
--   If customer_aliases doesn't resolve the QB Customer string at
--   ingest time, the invoice still ingests with customer_id=NULL and
--   customer_raw_text preserved. An admin maps the alias later, then
--   a one-time backfill sets customer_id on existing rows.
-- ---------------------------------------------------------------------
CREATE TABLE invoices (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    source_system       TEXT        NOT NULL,                       -- Which feed this row came from (e.g. 'quickbooks')
    invoice_ref         TEXT        NOT NULL,                       -- External reference from the source (e.g. "SI-012682"). Not assumed unique globally — only within source_system.
    invoice_date        DATE        NOT NULL,
    transaction_type    TEXT        NOT NULL DEFAULT 'invoice',     -- 'invoice' for now; future formats may include credit memos. CHECK below.

    customer_id         BIGINT,                                     -- FK below; nullable when customer alias not yet resolved
    customer_raw_text   TEXT        NOT NULL,                       -- Verbatim Customer string from source — kept for alias lookup + audit

    po_number           TEXT,                                        -- Source-provided PO/reference (free-form)
    notes               TEXT,

    file_upload_id      BIGINT      NOT NULL,                       -- Which upload last wrote this row
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_invoices_customer
        FOREIGN KEY (customer_id) REFERENCES customers (id),
    CONSTRAINT fk_invoices_file
        FOREIGN KEY (file_upload_id) REFERENCES file_uploads (id),
    CONSTRAINT chk_invoices_transaction_type CHECK (
        transaction_type IN ('invoice', 'credit_memo', 'other')
    ),
    CONSTRAINT uq_invoices_source_ref UNIQUE (source_system, invoice_ref)
);

CREATE INDEX idx_invoices_date          ON invoices (invoice_date);
CREATE INDEX idx_invoices_customer_date ON invoices (customer_id, invoice_date);
CREATE INDEX idx_invoices_file          ON invoices (file_upload_id);


-- =====================================================================
-- TABLE: sales.invoice_lines
-- =====================================================================
-- WHY:
--   One row per product line on an invoice. The grain of all sales-side
--   revenue analysis: revenue by product, by category, by distributor,
--   by month, by state. This is the most-read table in the schema.
--
-- HOW (ingestion):
--   For each invoice in a QB file, the parser DELETEs existing rows in
--   this table for that invoice_id and re-INSERTs all lines. This
--   sidesteps the problem of finding a stable per-line natural key —
--   the same product can legitimately appear on the same invoice twice
--   (observed in real data: SI-012682 had two lines of American
--   Whiskey 12yr both at qty=1, $245.68 each). line_seq is assigned
--   in source-file order at ingest, so it's deterministic for the
--   same input but not stable across re-uploads of a corrected file.
--
-- KEY DESIGN CHOICES:
--   * product_id is nullable. If the alias isn't matched yet, the line
--     ingests with product_raw_text preserved. Backfill product_id once
--     the alias is added.
--   * No updated_at column. Lines are write-once within an ingestion;
--     subsequent re-uploads delete+reinsert, producing fresh created_at.
--   * No commission columns. Flat rate lives in sales.app_config and
--     is applied at query time: amount * (config value).
--   * amount is stored from source rather than computed, so we can
--     verify quantity * sales_price = amount during ingestion and flag
--     discrepancies in the source data.
-- ---------------------------------------------------------------------
CREATE TABLE invoice_lines (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    invoice_id          BIGINT      NOT NULL,                       -- FK below
    line_seq            INT         NOT NULL,                       -- 1-based, assigned at ingest in source-file order. Source doesn't number lines.
    product_id          BIGINT,                                     -- FK below; nullable if alias not resolved
    product_raw_text    TEXT        NOT NULL,                       -- Verbatim Memo/Description string from source

    quantity            NUMERIC(14, 4) NOT NULL,                    -- Cases sold. Fractional values do occur (6.83, 0.083334).
    sales_price         NUMERIC(14, 4) NOT NULL,                    -- Unit price per case
    amount              NUMERIC(14, 2) NOT NULL,                    -- Line total as reported by source. Should equal quantity * sales_price (parser validates).

    file_upload_id      BIGINT      NOT NULL,                       -- Which upload last wrote this row
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_invoice_lines_invoice
        FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE CASCADE,
    CONSTRAINT fk_invoice_lines_product
        FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT fk_invoice_lines_file
        FOREIGN KEY (file_upload_id) REFERENCES file_uploads (id),
    CONSTRAINT uq_invoice_lines_invoice_seq UNIQUE (invoice_id, line_seq),
    CONSTRAINT chk_invoice_lines_quantity   CHECK (quantity   >= 0),
    CONSTRAINT chk_invoice_lines_amount     CHECK (amount     >= 0)
);

CREATE INDEX idx_invoice_lines_product      ON invoice_lines (product_id);
CREATE INDEX idx_invoice_lines_file_upload  ON invoice_lines (file_upload_id);


-- =====================================================================
-- TABLE: sales.depletions
-- =====================================================================
-- WHY:
--   Retail-level pull-through, one row per (account x product x month).
--   Backs all depletions-side analysis: top accounts, follow-up tracker,
--   YoY by state, on-premise vs off-premise mix.
--
--   Stored in LONG format rather than wide monthly columns. The source
--   xlsx is pivoted (51 columns with paired month metrics); the parser
--   un-pivots into normalized rows. This makes time-range queries
--   trivial: WHERE period_month BETWEEN ... AND ....
--
-- HOW (ingestion):
--   UPSERT on (account_id, product_id, period_month). The depletions
--   file is typically cumulative: each weekly drop contains all months
--   to date. Re-uploading the same file = same key, same values = no-op.
--   Re-uploading with a corrected value = same key, new value = update.
--
-- METRICS:
--   cases_9L         — "9 Liter Equivalents". The industry standard
--                      volume measure. Always present.
--   cases_physical   — Physical cases at the actual pack size. Newer
--                      depletion files include this paired with 9L;
--                      older files (and possibly some future formats)
--                      may not — hence nullable.
-- ---------------------------------------------------------------------
CREATE TABLE depletions (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    account_id          BIGINT      NOT NULL,
    product_id          BIGINT      NOT NULL,
    period_month        DATE        NOT NULL,                       -- First-of-month canonical form (e.g. 2026-04-01)

    cases_9L            NUMERIC(14, 4) NOT NULL,                    -- 9-Liter equivalents
    cases_physical      NUMERIC(14, 4),                             -- Physical cases; nullable for source formats that omit it

    file_upload_id      BIGINT      NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_depletions_account
        FOREIGN KEY (account_id) REFERENCES accounts (id),
    CONSTRAINT fk_depletions_product
        FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT fk_depletions_file
        FOREIGN KEY (file_upload_id) REFERENCES file_uploads (id),
    CONSTRAINT uq_depletions_natural UNIQUE (account_id, product_id, period_month),
    CONSTRAINT chk_depletions_period_first_of_month CHECK (
        EXTRACT(DAY FROM period_month) = 1
    ),
    CONSTRAINT chk_depletions_cases_9L_nonneg     CHECK (cases_9L >= 0),
    CONSTRAINT chk_depletions_cases_phys_nonneg   CHECK (cases_physical IS NULL OR cases_physical >= 0)
);

CREATE INDEX idx_depletions_period          ON depletions (period_month);
CREATE INDEX idx_depletions_period_product  ON depletions (period_month, product_id);
CREATE INDEX idx_depletions_account_period  ON depletions (account_id, period_month);
CREATE INDEX idx_depletions_file            ON depletions (file_upload_id);


-- =====================================================================
-- SEED DATA
-- =====================================================================
-- The two app_config rows below are required for ingestion + revenue
-- queries to work. Other seed data (initial product catalog,
-- distributor list) is handled by ingestion as files are uploaded.
-- ---------------------------------------------------------------------
INSERT INTO app_config (key, value, description) VALUES
    ('commission_rate',
     '0.10',
     'Flat commission percentage applied to all sales line amounts. ' ||
     'Read by sales queries that compute commission totals. Change ' ||
     'here to update without redeploy.'),
    ('current_sales_source_system',
     'quickbooks',
     'The source_system value stamped on new sales uploads and ' ||
     'invoices. Update when the broker changes the report format so ' ||
     'old and new data remain distinguishable in the invoices table.');


COMMIT;

-- =====================================================================
-- POST-CREATION VERIFICATION (run manually if desired)
-- =====================================================================
-- \dt sales.*
-- SELECT key, value, description FROM sales.app_config;
-- SELECT table_name FROM information_schema.tables WHERE table_schema='sales' ORDER BY table_name;
