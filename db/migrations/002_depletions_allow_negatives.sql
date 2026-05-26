-- =====================================================================
-- 002_depletions_allow_negatives.sql
-- =====================================================================
-- Drops the "non-negative" CHECK constraints on sales.depletions.
--
-- Why:
--   Real broker depletion data contains negative case counts when a
--   retail account returns product to the distributor (a "pullback").
--   Observed in the May 2025 row for LUEKENS WINE & SPIRITS (FL):
--   cases_9l = -5, cases_physical = -10.
--
--   The original 001_sales_schema.sql included
--     CHECK (cases_9L >= 0)
--     CHECK (cases_physical IS NULL OR cases_physical >= 0)
--   which would reject legitimate return rows. This migration removes
--   them. The first-of-month constraint stays — that's a format
--   invariant, not a value-sign assumption.
--
-- How to run:
--   psql "$DATABASE_URL" -f db/migrations/002_depletions_allow_negatives.sql
-- =====================================================================

BEGIN;

ALTER TABLE sales.depletions
    DROP CONSTRAINT IF EXISTS chk_depletions_cases_9l_nonneg,
    DROP CONSTRAINT IF EXISTS chk_depletions_cases_phys_nonneg;

COMMIT;
