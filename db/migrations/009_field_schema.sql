-- ============================================================================
-- Migration: field schema — sales rep CRM
--
-- WHY:
--   Hooten Young's sales reps work in the field — they drive to retail
--   accounts, log conversations, and follow up over time.  This schema
--   gives them a CRM-style surface on top of the existing
--   depletions.accounts universe:
--
--     * field.rep_profiles    — per-user "I'm a field rep" record.
--                               Carries the rep's home address (used
--                               later for distance-from-home routing)
--                               and phone.  Lives in its own table
--                               rather than as columns on auth.users
--                               because most users are NOT reps; we
--                               don't want every users row carrying
--                               nullable rep-only columns.
--
--     * field.rep_territories — many-to-many (user_id, state_code).
--                               A rep covers one or more states; an
--                               account is "in the rep's territory"
--                               when its state_code matches.  The
--                               account universe is reused from
--                               depletions.accounts — there is no
--                               parallel accounts table.
--
--     * field.account_pins    — accounts the rep has manually flagged
--                               for next-visit attention.  Stored as
--                               (rep_id, account_id) — a pin is owned
--                               by the rep who placed it, so two reps
--                               touching the same account each keep
--                               their own list.
--
--     * field.visit_notes     — the CRM log.  Every visit / call by
--                               a rep generates one row with the
--                               outcome and free-text note.  This is
--                               the source of truth for:
--                                 - "last visit" math (priority score)
--                                 - cooldowns (outcome → days before
--                                   account can resurface)
--                                 - admin oversight (cross-rep feed)
--                                 - per-account history (timeline view)
--
--   account_id always points at depletions.accounts.id (a BIGINT).
--   user_id always points at auth.users.id (a UUID).
--
-- HOW TO RUN:
--   psql -d "$DATABASE_URL" -f db/migrations/009_field_schema.sql
--
--   Idempotent: every CREATE uses IF NOT EXISTS.  Safe to re-run.
-- ============================================================================


-- =====================================================================
-- SCHEMA: field
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS field;

COMMENT ON SCHEMA field IS
  'Sales-rep CRM tables — rep profiles, territories, pins, and visit notes layered on depletions.accounts.';


-- =====================================================================
-- TABLE: field.rep_profiles
-- =====================================================================
-- One row per signed-in user who is a sales rep.  The user_id is BOTH
-- the PK and the FK to auth.users — a user is either a rep or not,
-- never two profiles.  Home address columns are kept loose (no
-- separate addresses table) because reps update their own and we don't
-- need address history.  All-nullable so the row can be created with
-- just user_id (admins fill the rest later via the UI).
CREATE TABLE IF NOT EXISTS field.rep_profiles (
    user_id         UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,

    home_address    TEXT,
    home_city       TEXT,
    home_state      CHAR(2),
    home_zip        TEXT,
    phone           TEXT,

    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE field.rep_profiles IS
  'Per-rep profile data on top of auth.users — home address, phone, active flag.  One row per rep; absence of a row means the user is not (yet) a rep.';


-- =====================================================================
-- TABLE: field.rep_territories
-- =====================================================================
-- Many-to-many: a rep can cover multiple states; a state is normally
-- covered by exactly one rep but the schema doesn't enforce that —
-- the UI surfaces overlap to the admin when it happens (e.g. two
-- reps in Florida during a transition).
CREATE TABLE IF NOT EXISTS field.rep_territories (
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    state_code      CHAR(2)     NOT NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, state_code)
);

CREATE INDEX IF NOT EXISTS idx_rep_territories_state
    ON field.rep_territories (state_code);

COMMENT ON TABLE field.rep_territories IS
  'Many-to-many (rep, state).  The set of states a rep covers; account ownership is derived implicitly by joining on accounts.state_code.';


-- =====================================================================
-- TABLE: field.account_pins
-- =====================================================================
-- Rep-flagged "visit this next" entries.  PK is (rep_id, account_id)
-- so each rep maintains their own pin list — two reps both covering
-- the same account each pin independently.
CREATE TABLE IF NOT EXISTS field.account_pins (
    rep_id          UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id      BIGINT      NOT NULL REFERENCES depletions.accounts(id) ON DELETE CASCADE,

    pinned_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (rep_id, account_id)
);

CREATE INDEX IF NOT EXISTS idx_account_pins_account
    ON field.account_pins (account_id);

COMMENT ON TABLE field.account_pins IS
  'Per-rep account pins.  Strong priority-score boost; rep clears via the UI.';


-- =====================================================================
-- TABLE: field.visit_notes
-- =====================================================================
-- The CRM log.  Every interaction (in-person visit or phone call) gets
-- one row.  The outcome enum drives the cooldown (how long until the
-- account can resurface in "Today's list").  The note text is free-form
-- — reps write what was discussed, the buyer's name, next-step asks.
--
-- visit_date is a DATE (not TIMESTAMPTZ) because reps log "I visited
-- yesterday" — the time of day doesn't matter for the CRM workflow.
-- created_at is a TIMESTAMPTZ so admins can see the actual log-time
-- (which may lag the visit_date by a day or two — reps don't always
-- log on the spot).
CREATE TABLE IF NOT EXISTS field.visit_notes (
    id              BIGSERIAL   PRIMARY KEY,
    account_id      BIGINT      NOT NULL REFERENCES depletions.accounts(id) ON DELETE CASCADE,
    rep_id          UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    visit_date      DATE        NOT NULL,
    channel         VARCHAR(20) NOT NULL,
    outcome         VARCHAR(30) NOT NULL,
    note_text       TEXT        NOT NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT visit_notes_channel_chk
      CHECK (channel IN ('visit', 'call')),
    CONSTRAINT visit_notes_outcome_chk
      CHECK (outcome IN (
        'ordered',
        'follow_up_needed',
        'no_response',
        'declined',
        'info_only'
      ))
);

CREATE INDEX IF NOT EXISTS idx_visit_notes_account_date
    ON field.visit_notes (account_id, visit_date DESC);
CREATE INDEX IF NOT EXISTS idx_visit_notes_rep_date
    ON field.visit_notes (rep_id, visit_date DESC);
CREATE INDEX IF NOT EXISTS idx_visit_notes_created
    ON field.visit_notes (created_at DESC);

COMMENT ON TABLE field.visit_notes IS
  'CRM activity log.  One row per visit / call.  Drives last-visit math, cooldowns, and the admin activity feed.';
COMMENT ON COLUMN field.visit_notes.channel IS
  '''visit'' = in-person, ''call'' = phone.  Email / text would be added here when needed.';
COMMENT ON COLUMN field.visit_notes.outcome IS
  'Drives the cooldown: ordered=30d, follow_up_needed=7d, no_response=3d, declined=60d, info_only=14d.  Cooldown table lives in src/hy_sales/services/field_priority.py.';
