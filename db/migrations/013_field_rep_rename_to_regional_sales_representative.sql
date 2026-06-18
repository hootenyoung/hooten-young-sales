-- ============================================================================
-- Migration: rename field_rep role display copy
--
-- WHY:
--   "Field Sales Rep" reads slightly casual for a premium whiskey
--   brand.  Unifying on "Regional Sales Representative" gives the
--   role a more formal name in admin pickers + role pages while
--   keeping the underlying identifier (auth.roles.name = 'field_rep')
--   stable — every existing grant keeps working, no API or schema
--   churn.
--
--   The shorter form "representative" is used elsewhere in the UI
--   (dialog titles, roster headers); the full form lives here on
--   the role row.
--
-- HOW TO RUN:
--   psql -d "$DATABASE_URL" -f db/migrations/013_field_rep_rename_to_regional_sales_representative.sql
--
--   Idempotent — re-running rewrites the same values.
-- ============================================================================

UPDATE auth.roles
   SET display_name = 'Regional Sales Representative',
       description  = (
        'Works accounts in their assigned states — logs visit notes, '
        || 'pins follow-ups, and sees their own territory. Tick alongside '
        || 'Administrator if an admin will also work the field; the '
        || 'address + territory panel appears below once this is ticked.'
       )
 WHERE name = 'field_rep';
