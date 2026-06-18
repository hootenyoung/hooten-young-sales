-- ============================================================================
-- Migration: clarify field_rep role description
--
-- WHY:
--   The original description in migration 010 ("In-territory sales
--   representative. Sees their own accounts in the Field section,
--   logs visit notes, and pins follow-ups. Admins assign territories
--   on user creation.") didn't make the orthogonality with the admin
--   role explicit.  Admins viewing the Add User dialog couldn't tell
--   whether ticking Administrator alone was enough to also make
--   someone a field rep, or whether the two had to be combined.
--
--   New copy makes the coexist relationship obvious and tells the
--   admin what to expect when they tick the box (the address +
--   territory panel appears below).
--
-- HOW TO RUN:
--   psql -d "$DATABASE_URL" -f db/migrations/011_field_rep_description_update.sql
--
--   Idempotent: re-running just rewrites the description with the
--   same value.  No effect on grants — every user who already holds
--   field_rep keeps it.
-- ============================================================================

UPDATE auth.roles
   SET description = (
        'Works accounts in the field — logs visit notes, pins follow-ups, '
        || 'sees their own territory. Tick alongside Administrator if an '
        || 'admin will also work the field; the address + territory panel '
        || 'appears below once this is ticked.'
       )
 WHERE name = 'field_rep';
