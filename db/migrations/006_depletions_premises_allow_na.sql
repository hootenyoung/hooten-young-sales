-- =====================================================================
-- 006_depletions_premises_allow_na.sql
-- =====================================================================
-- Widen depletions.accounts.premises_type to accept 'NA' as a fourth
-- legal value, alongside the existing 'ON' / 'OFF' / NULL.
--
-- WHY
--   The iDIG Rolling Periods export added an "OnOff Premises" column
--   in mid-June 2025. The broker classifies most accounts as either
--   'ON' (bars, restaurants) or 'OFF' (liquor stores, retail), but a
--   non-trivial slice (~10% in the first file we received) come
--   classified as 'NA'. That 'NA' is itself a signal — the broker
--   actively decided neither ON nor OFF applies (clubs, cigar lounges,
--   military exchanges, etc.) — and it's distinct from NULL, which
--   means "we don't have this info" (older accounts predating the
--   premises column, or files that don't carry it at all).
--
--   The original CHECK constraint in migration 005 only allowed
--   ON / OFF / NULL, so an ingestion of a current file would either
--   reject 'NA' rows or have to collapse them into NULL — losing the
--   distinction. This migration loosens the constraint so we can
--   store all four states.
--
-- WHAT
--   Drops the old chk_dep_accounts_premises constraint and recreates
--   it with 'NA' added to the IN-list. Same constraint name so the
--   ORM constraint declaration stays in sync.
--
-- SAFE TO REPLAY?
--   No — DROP CONSTRAINT IF NOT EXISTS would be a syntax error. The
--   ADD CONSTRAINT step would fail on the second run because the
--   constraint already exists with the new shape. Run once, in
--   sequence, like the prior migrations.
-- =====================================================================

BEGIN;

SET search_path TO depletions, public;

ALTER TABLE accounts
    DROP CONSTRAINT chk_dep_accounts_premises;

ALTER TABLE accounts
    ADD CONSTRAINT chk_dep_accounts_premises CHECK (
        premises_type IS NULL OR premises_type IN ('ON', 'OFF', 'NA')
    );

COMMIT;
