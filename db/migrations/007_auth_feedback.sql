-- ============================================================================
-- Migration: platform.app_config + auth.feedback
--
-- WHY:
--   The platform now has a "Feedback" pill in the dashboard that lets
--   signed-in users send us notes (ideas / bugs / praise / other).  Two
--   tables land here:
--
--   * platform.app_config — generic key/value store for cross-domain
--     runtime settings.  Lives in its own `platform` schema (NOT
--     inside auth or sales) so any domain — auth, sales, marketing,
--     anything we add later — can park keys here without nesting
--     under a domain-specific schema.  Today it holds the feedback
--     recipient list; tomorrow it can hold any other knob (default
--     role to grant on signup approval, marketing-campaign window,
--     etc.).  Key naming convention: lowercase snake_case, prefix
--     with the consuming subsystem when ambiguous (e.g.
--     `marketing_campaign_window_days`).
--
--     Note: sales.app_config (from migration 001) stays where it is
--     for backwards compatibility — `commission_rate` and friends
--     keep working.  New configs land in platform.app_config; the
--     two tables can coexist indefinitely.
--
--   * auth.feedback — every /api/feedback submission persisted as the
--     source of truth.  Stays in auth because feedback rows belong to
--     a user_id FK and naturally fit the auth domain.  Email dispatch
--     is best-effort on top.
--
-- HOW TO RUN:
--   psql -d "$DATABASE_URL" -f db/migrations/007_auth_feedback.sql
--
--   The seed at the bottom sets the initial feedback recipients to
--   prasad@cach22.ai.  Edit it in this file, or update it later via:
--
--     UPDATE platform.app_config
--        SET value = 'a@hootenyoung.com,b@hootenyoung.com'
--      WHERE key   = 'feedback_recipients';
-- ============================================================================


-- =====================================================================
-- SCHEMA: platform
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS platform;

COMMENT ON SCHEMA platform IS
  'Cross-domain platform-level tables — settings, feature flags, anything that has no natural home in auth / sales / marketing schemas.';


-- =====================================================================
-- TABLE: platform.app_config
-- =====================================================================
-- Same shape as sales.app_config (migration 001) — intentionally
-- identical so future code that wraps it can reuse types/queries.
CREATE TABLE IF NOT EXISTS platform.app_config (
    key             TEXT        PRIMARY KEY,
    value           TEXT        NOT NULL,
    description     TEXT        NOT NULL,

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  platform.app_config IS
  'Cross-domain key/value store for runtime settings.  Values are stored as TEXT — callers parse to list/bool/int/numeric as needed.';
COMMENT ON COLUMN platform.app_config.key IS
  'Stable identifier in lowercase snake_case.  Prefix with the consuming subsystem when ambiguous (e.g. `marketing_campaign_window_days`).';


-- =====================================================================
-- TABLE: auth.feedback
-- =====================================================================
-- One row per feedback submission.  user_id is the submitter; the FK
-- guarantees every row is attributable.  Page path captures where the
-- user was when they hit the Feedback pill.
CREATE TABLE IF NOT EXISTS auth.feedback (
    id              BIGSERIAL   PRIMARY KEY,
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    category        VARCHAR(20) NOT NULL,
    message         TEXT        NOT NULL,
    page_path       VARCHAR(200),
    allow_followup  BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT feedback_category_chk
      CHECK (category IN ('idea', 'bug', 'praise', 'other'))
);

CREATE INDEX IF NOT EXISTS feedback_user_idx
    ON auth.feedback (user_id);
CREATE INDEX IF NOT EXISTS feedback_created_idx
    ON auth.feedback (created_at DESC);

COMMENT ON TABLE auth.feedback IS
  'User-submitted feedback (idea / bug / praise / other).  Persisted as the source of truth; email dispatch is best-effort on top.';


-- =====================================================================
-- SEED: feedback recipient list
-- =====================================================================
-- Initial recipients.  Update the list whenever the team changes:
--   UPDATE platform.app_config SET value = '<csv-emails>' WHERE key = 'feedback_recipients';
INSERT INTO platform.app_config (key, value, description)
VALUES (
    'feedback_recipients',
    'prasad@cach22.ai',
    'Comma-separated email addresses that receive a copy of every /api/feedback submission. Update via UPDATE statement; no redeploy needed.'
)
ON CONFLICT (key) DO NOTHING;
