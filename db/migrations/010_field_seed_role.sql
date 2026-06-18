-- ============================================================================
-- Migration: seed the `field_rep` role
--
-- WHY:
--   Migration 009 adds the field schema (rep profiles, territories,
--   pins, visit notes).  This migration seeds the corresponding role
--   so the admin UI's role-checkbox list picks it up and admins can
--   assign it to a user via the existing Add User flow.
--
--   No sample reps are created here — those come from the UI.
--
-- HOW TO RUN:
--   psql -d "$DATABASE_URL" -f db/migrations/010_field_seed_role.sql
--
--   Idempotent: ON CONFLICT (name) DO NOTHING.
-- ============================================================================

INSERT INTO auth.roles (name, display_name, description)
VALUES (
    'field_rep',
    'Field Sales Rep',
    'In-territory sales representative. Sees their own accounts in the Field section, logs visit notes, and pins follow-ups. Admins assign territories on user creation.'
)
ON CONFLICT (name) DO NOTHING;
