-- ============================================================================
-- Migration: seed platform.app_config.locked_sections
--
-- WHY:
--   The landing page shows a card for every analytical section
--   (distribution / depletions / marketing / …).  Some are still
--   in-flight at any given time — we want admins + users to see them
--   listed (so they know what's coming) but unable to enter until the
--   build is done.
--
--   A single config row drives the lock state platform-wide.  Comma-
--   separated section keys go in `value`; everything in that list
--   renders as "Coming soon" on the landing page and ignores clicks.
--
-- HOW TO TOGGLE:
--   Unlock Distribution (keep Marketing locked):
--     UPDATE platform.app_config
--        SET value = 'marketing'
--      WHERE key   = 'locked_sections';
--
--   Unlock everything:
--     UPDATE platform.app_config
--        SET value = ''
--      WHERE key   = 'locked_sections';
--
--   Lock a new section "operations":
--     UPDATE platform.app_config
--        SET value = 'distribution,marketing,operations'
--      WHERE key   = 'locked_sections';
--
-- HOW TO RUN:
--   psql -d "$DATABASE_URL" -f db/migrations/008_platform_locked_sections.sql
-- ============================================================================

INSERT INTO platform.app_config (key, value, description)
VALUES (
    'locked_sections',
    'distribution,marketing',
    'Comma-separated section keys that render as "Coming soon" on the landing page. Sections in this list are visible but not clickable, regardless of the viewer''s roles. Empty string = nothing locked.'
)
ON CONFLICT (key) DO NOTHING;
