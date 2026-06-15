-- =====================================================================
-- 005_depletions_idig_redesign.sql
-- =====================================================================
-- Isolates the depletions domain into its own Postgres schema.
--
-- WHY
--   The depletions feed (iDIG / VTinfo Rolling Periods) and the sales
--   feed (QuickBooks "Sales by Product/Service Detail") describe two
--   physically different events:
--     * Sales       — what Hooten Young invoices to its direct customers
--                     (distributors, control states, military exchanges).
--     * Depletions  — what retail accounts purchased from those
--                     distributors. Different feed, different broker,
--                     different cadence, different reconciliation cycle.
--
--   The original 001 schema kept both domains in the `sales` schema and
--   shared dimension tables (products, distributors, file_uploads) on
--   the assumption that cross-domain joins (White-Space Matrix etc.)
--   would benefit. In practice the two feeds spell the same SKU
--   differently ("Hooten Young 12 Year Amer" vs "HOOTEN & YOUNG
--   AMERICAN WHISKEY 12YR - 750") and the implicit "shared dimension"
--   was already requiring an alias layer to bridge them. Pulling
--   depletions into its own schema makes the separation explicit and
--   removes any risk of one feed's data leaking into the other's
--   analytics.
--
-- WHAT
--   1. Drop the depletions-side tables from the `sales` schema:
--        sales.depletions, sales.accounts
--      (No production data yet — this is a clean cut.)
--   2. Create a new `depletions` schema with its own:
--        file_uploads, products, product_aliases, accounts, facts
--   3. Sales-side tables are untouched (sales.invoices, invoice_lines,
--      customers, customer_aliases, products, product_aliases,
--      distributors, file_uploads, app_config — all stay in `sales`).
--
-- CROSS-DOMAIN IMPLICATION
--   The MVP's White-Space Matrix joined sales × depletions through a
--   shared products table. After this migration the two domains'
--   products live in different schemas and may have different rows for
--   the same physical SKU. Re-enabling that matrix later will require
--   an explicit cross-feed product mapping table (e.g.
--   `analytics.product_xref(sales_product_id, dep_product_id)`). That
--   work is intentionally deferred until both feeds are live and we
--   know the actual SKU overlap.
--
-- HOW TO RUN
--   psql "$DATABASE_URL" -f db/migrations/005_depletions_idig_redesign.sql
-- =====================================================================

BEGIN;


-- ---------------------------------------------------------------------
-- 1. Remove depletions-side tables from the sales schema
-- ---------------------------------------------------------------------
-- CASCADE because sales.depletions FKs into sales.accounts and we are
-- dropping both. The sales-side facts (invoices, invoice_lines) do not
-- reference either table and survive untouched.

DROP TABLE IF EXISTS sales.depletions CASCADE;
DROP TABLE IF EXISTS sales.accounts   CASCADE;


-- ---------------------------------------------------------------------
-- 2. Create the depletions schema and its tables
-- ---------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS depletions;
SET search_path TO depletions;


-- =====================================================================
-- TABLE: depletions.file_uploads
-- =====================================================================
-- Audit ledger for every depletions xlsx (or other source file) we
-- ingest. Same shape as sales.file_uploads but scoped to this domain so
-- the two feeds' upload histories cannot be confused.
--
-- DEDUP via sha256 UNIQUE. Re-uploading the same file is a no-op. A
-- corrected file produces a new upload row and re-upserts the affected
-- depletion rows.
-- ---------------------------------------------------------------------
CREATE TABLE file_uploads (
    id                      BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    filename                TEXT        NOT NULL,
    sha256                  CHAR(64)    NOT NULL UNIQUE,
    source_system           TEXT        NOT NULL,                   -- e.g. 'idig' (current), 'broker_monthly' (legacy)

    uploaded_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at            TIMESTAMPTZ,
    source_generated_at     TIMESTAMPTZ,                            -- "Report Created on …" timestamp embedded in the file

    period_start            DATE,
    period_end              DATE,

    uploaded_by             TEXT,

    status                  TEXT        NOT NULL DEFAULT 'pending',
    row_count_processed     INT         NOT NULL DEFAULT 0,
    row_count_inserted      INT         NOT NULL DEFAULT 0,
    row_count_updated       INT         NOT NULL DEFAULT 0,
    row_count_skipped       INT         NOT NULL DEFAULT 0,
    row_count_failed        INT         NOT NULL DEFAULT 0,
    error_message           TEXT,

    notes                   TEXT,

    CONSTRAINT chk_dep_file_uploads_status CHECK (
        status IN ('pending', 'processing', 'success', 'failed', 'partial')
    )
);

CREATE INDEX idx_dep_file_uploads_uploaded_at  ON file_uploads (uploaded_at DESC);
CREATE INDEX idx_dep_file_uploads_status       ON file_uploads (status) WHERE status <> 'success';


-- =====================================================================
-- TABLE: depletions.products
-- =====================================================================
-- iDIG-canonical product catalog. One row per SKU as the depletions
-- feed labels it. Separate from sales.products because the two feeds
-- use different naming conventions and we keep them physically distinct
-- until/unless a cross-feed mapping is intentionally added.
-- ---------------------------------------------------------------------
CREATE TABLE products (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    full_name       TEXT        NOT NULL UNIQUE,                    -- Canonical name as the depletions feed presents it
    short_name      TEXT,                                            -- Optional display abbreviation
    category        TEXT,                                            -- Free-form (Whiskey, Bourbon, Rye, etc.)

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- TABLE: depletions.product_aliases
-- =====================================================================
-- Raw text from a depletions file → canonical depletions.products row.
-- The iDIG export truncates product names to ~25 chars ("Hooten Young
-- 12 Year Amer"); future iDIG re-templates or other depletions sources
-- may spell them differently. The alias layer absorbs that.
-- ---------------------------------------------------------------------
CREATE TABLE product_aliases (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    alias_text      TEXT        NOT NULL UNIQUE,
    product_id      BIGINT      NOT NULL,
    source          TEXT        NOT NULL,                           -- e.g. 'idig', 'manual'
    notes           TEXT,

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_dep_product_aliases_product
        FOREIGN KEY (product_id) REFERENCES products (id)
);

CREATE INDEX idx_dep_product_aliases_product ON product_aliases (product_id);


-- =====================================================================
-- TABLE: depletions.accounts
-- =====================================================================
-- Retail accounts — liquor stores, bars, restaurants. Sourced entirely
-- from depletions files. Natural key (name, address, state_code) — same
-- chain at different addresses are different rows.
--
-- iDIG-NATIVE COLUMNS
--   county          — "Acct Counties" (e.g. "ORANGE, FL"). Useful for
--                     state-level rollups; helps disambiguate accounts
--                     with the same name in different counties.
--   zip_code        — "Acct Zips" (TEXT, not INT — leading zeros).
--   dist_state_code — "Dist States". The state where the servicing
--                     distributor operates, which may differ from
--                     state_code (the account's physical state). Seen
--                     in iDIG data — FL distributor servicing GA
--                     accounts. Both stored so we can roll up by
--                     physical market AND by distribution territory.
--   distributor_code — short code (e.g. "FL13") from the iDIG feed.
--                     Stored as raw text; no resolution to a canonical
--                     distributor entity (the iDIG export no longer
--                     carries a full distributor name).
-- ---------------------------------------------------------------------
CREATE TABLE accounts (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    name                TEXT        NOT NULL,
    address             TEXT,
    city                TEXT,
    state_code          CHAR(2),
    county              TEXT,
    zip_code            TEXT,
    dist_state_code     CHAR(2),
    distributor_code    TEXT,
    premises_type       TEXT,                                        -- 'ON' / 'OFF' / NULL. Nullable: iDIG Rolling Periods export doesn't carry this.
    notes               TEXT,

    is_active           BOOLEAN     NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_dep_accounts_premises CHECK (
        premises_type IS NULL OR premises_type IN ('ON', 'OFF')
    ),
    CONSTRAINT uq_dep_accounts_natural UNIQUE NULLS NOT DISTINCT (name, address, state_code)
);

CREATE INDEX idx_dep_accounts_state             ON accounts (state_code);
CREATE INDEX idx_dep_accounts_dist_state        ON accounts (dist_state_code);
CREATE INDEX idx_dep_accounts_distributor_code  ON accounts (distributor_code);


-- =====================================================================
-- TABLE: depletions.facts
-- =====================================================================
-- The long-format fact table. One row per (account, product, month).
--
-- WHY "facts" instead of repeating the schema name:
--   `depletions.depletions` reads awkwardly in queries. `facts` is
--   unambiguous in context (the schema name itself says what kind of
--   facts these are) and matches the dimensional-modeling convention.
--
-- IDEMPOTENCY
--   UNIQUE (account_id, product_id, period_month) is the upsert key.
--   The ingest path uses INSERT ... ON CONFLICT DO UPDATE with a WHERE
--   clause so unchanged values are true no-ops (no row write, no
--   attribution change).
--
-- NULL-ABILITY
--   cases_physical is nullable — iDIG Rolling Periods exports 9L only.
--   Older / different formats may include physical cases too.
--
-- NEGATIVE VALUES
--   Both case columns CAN be negative — represent product returns from
--   retail back to the distributor ("pullbacks"). The original
--   non-negativity CHECKs were dropped in migration 002 and are not
--   reintroduced here.
-- ---------------------------------------------------------------------
CREATE TABLE facts (
    id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    account_id          BIGINT      NOT NULL,
    product_id          BIGINT      NOT NULL,
    period_month        DATE        NOT NULL,                       -- First-of-month canonical form

    cases_9l            NUMERIC(14, 4) NOT NULL,                    -- 9-Liter equivalents
    cases_physical      NUMERIC(14, 4),                             -- Physical cases at actual pack size; nullable

    file_upload_id      BIGINT      NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_dep_facts_account
        FOREIGN KEY (account_id) REFERENCES accounts (id),
    CONSTRAINT fk_dep_facts_product
        FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT fk_dep_facts_file
        FOREIGN KEY (file_upload_id) REFERENCES file_uploads (id),
    CONSTRAINT uq_dep_facts_natural UNIQUE (account_id, product_id, period_month),
    CONSTRAINT chk_dep_facts_period_first_of_month CHECK (
        EXTRACT(DAY FROM period_month) = 1
    )
);

CREATE INDEX idx_dep_facts_period          ON facts (period_month);
CREATE INDEX idx_dep_facts_period_product  ON facts (period_month, product_id);
CREATE INDEX idx_dep_facts_account_period  ON facts (account_id, period_month);
CREATE INDEX idx_dep_facts_file            ON facts (file_upload_id);


COMMIT;


-- =====================================================================
-- POST-MIGRATION VERIFICATION (run manually)
-- =====================================================================
-- \dn                                              -- expect: sales, depletions, auth
-- \dt depletions.*                                 -- expect: accounts, facts, file_uploads, product_aliases, products
-- \dt sales.*                                      -- depletions, accounts no longer present
-- SELECT count(*) FROM depletions.facts;           -- expect 0
-- SELECT column_name FROM information_schema.columns
--   WHERE table_schema='depletions' AND table_name='accounts'
--   ORDER BY ordinal_position;
