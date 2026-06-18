-- ============================================================================
-- Migration: strip redundant section-role grants from admins
--
-- WHY:
--   Admin is a wildcard for section access — granting it implicitly
--   grants Distribution / Depletions / Marketing.  Explicit grants
--   of those roles on top of admin are redundant: they don't change
--   what the user can do, and they inflate the per-role usage counts
--   on the Admin → Roles tab (admins show up under every section card).
--
--   The Edit Roles dialog already enforces this for future edits
--   (ticking Administrator clears the section checkboxes on save).
--   This migration is a one-time cleanup for existing data created
--   before that UI rule landed.
--
--   field_rep is INTENTIONALLY left alone — it isn't pure access,
--   it carries data ownership (territory, rep profile, "the rep
--   who authored this visit note"), so an admin who is also a
--   working rep must keep field_rep granted.
--
-- WHAT IT DOES:
--   For every user who holds the admin role, delete any explicit
--   grants of distribution / depletions / marketing.  Their access
--   to those sections is unchanged because admin's wildcard still
--   applies.
--
-- HOW TO RUN:
--   psql -d "$DATABASE_URL" -f db/migrations/012_strip_redundant_section_roles_from_admins.sql
--
--   Safe to re-run: any rows we'd delete are already gone after the
--   first execution, so the second run is a no-op.
-- ============================================================================

DELETE FROM auth.user_roles
 WHERE role_id IN (
       SELECT id
         FROM auth.roles
        WHERE name IN ('distribution', 'depletions', 'marketing')
       )
   AND user_id IN (
       SELECT ur.user_id
         FROM auth.user_roles ur
         JOIN auth.roles r ON r.id = ur.role_id
        WHERE r.name = 'admin'
       );
