-- =====================================================================
-- 003_auth_schema.sql
-- =====================================================================
-- Authentication + authorization schema for the HY platform.
--
-- Purpose:
--   Creates the `auth` schema and all tables used by the email/password
--   login system. Owned by the sales backend (hooten-young-sales), which
--   issues JWTs. The marketing backend validates those JWTs using the
--   same shared secret but does NOT own this schema.
--
-- Why a separate schema (not under `sales`):
--   Auth is its own domain — it does not belong to the sales-vs-depletions
--   business model. Keeping it isolated means:
--     * The marketing team (and any future domain) can read auth.users
--       to look up identity without coupling to sales data.
--     * Sales schema migrations never accidentally touch auth tables.
--     * Permissions can be granted independently if we ever lock down
--       per-schema access.
--
-- Design principles encoded here:
--   * `role` is a free-form text column — no enum. We currently only
--     use 'admin'. Adding new roles (e.g. 'sales', 'marketing') in the
--     future is a single line in the application's role constants, no
--     schema migration required.
--   * `status` IS constrained to a known set as a safety guard, but the
--     check can be dropped if we add new states.
--   * Email is citext (case-insensitive). Sarah@HY.com and sarah@hy.com
--     cannot both exist.
--   * Password hashes use bcrypt via pgcrypto. Compatible with the
--     application's passlib-bcrypt verification.
--   * `updated_at` is set by the application ORM (onupdate=func.now()),
--     not by a Postgres trigger — matches the convention used in the
--     sales schema.
--   * The audit log is append-only. Every meaningful auth action lands
--     a row here for traceability.
--
-- Run order: after 002_depletions_allow_negatives.sql. Idempotent
-- on the CREATE SCHEMA / CREATE EXTENSION steps; the CREATE TABLE
-- statements will error if re-run on a database that already has them.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Required extensions
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "citext";       -- case-insensitive email column
CREATE EXTENSION IF NOT EXISTS "pgcrypto";     -- gen_random_uuid(), crypt(), gen_salt()

-- ---------------------------------------------------------------------
-- Schema
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS auth;

COMMENT ON SCHEMA auth IS
  'Authentication and authorization. Owned by hooten-young-sales but '
  'readable by other backends (e.g. marketing) for identity lookup.';


-- =====================================================================
-- auth.users
-- =====================================================================
-- One row per user account. Status drives the signup-approval workflow
-- (pending → active / rejected) and the disable flow.
-- =====================================================================
CREATE TABLE auth.users (
    id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Email is the login identifier. citext makes uniqueness case-insensitive.
    email                  citext      NOT NULL UNIQUE,

    -- bcrypt hash (60 chars, $2b$ format). Never store plaintext.
    password_hash          text        NOT NULL,

    first_name             text        NOT NULL,
    last_name              text        NOT NULL,

    -- Free-form role. Today the only value used is 'admin'. New roles
    -- (e.g. 'sales', 'marketing', 'executive') are added by defining a
    -- constant in the application — no schema change required.
    role                   text        NOT NULL DEFAULT 'admin',

    -- Account lifecycle states:
    --   'pending'   - just signed up, awaiting admin approval
    --   'active'    - approved, can log in
    --   'rejected'  - admin rejected the signup (soft, recoverable)
    --   'disabled'  - was active, admin disabled (left company, etc.)
    status                 text        NOT NULL DEFAULT 'pending',

    -- True after admin creates an account directly or resets a password.
    -- The login flow shows the user a forced password-change screen and
    -- refuses to navigate further until they update it.
    must_change_password   boolean     NOT NULL DEFAULT false,

    last_login_at          timestamptz,

    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),

    -- Tracks who provisioned this user. NULL for self-signup; set to the
    -- admin's id when an admin creates a user directly. Self-reference is
    -- fine — the seed admin will have created_by = NULL.
    created_by             uuid        REFERENCES auth.users(id),

    -- Soft guard against typos. Drop the constraint to add new states.
    CONSTRAINT users_status_check CHECK (
        status IN ('pending', 'active', 'rejected', 'disabled')
    )
);

-- Used by the admin UI when filtering "pending approval" and "active users".
CREATE INDEX users_status_idx ON auth.users(status);

-- Used when filtering or counting by role.
CREATE INDEX users_role_idx ON auth.users(role);

COMMENT ON TABLE auth.users IS
  'User accounts. One row per person. Email is the login identifier.';

COMMENT ON COLUMN auth.users.role IS
  'Free-form role (no enum). Today only ''admin'' is used; add new values '
  'by defining a constant in the application, no schema change required.';

COMMENT ON COLUMN auth.users.status IS
  'Lifecycle: pending → active (approve) or rejected (deny). '
  'Active accounts can be disabled later by an admin.';

COMMENT ON COLUMN auth.users.must_change_password IS
  'TRUE means the user must change their password before they can use '
  'the app. Set after admin-created accounts or password resets.';


-- =====================================================================
-- auth.audit_log
-- =====================================================================
-- Append-only record of meaningful auth actions. Used for forensics,
-- abuse review, and admin transparency ("who did what, when").
-- =====================================================================
CREATE TABLE auth.audit_log (
    id              bigserial   PRIMARY KEY,

    -- NULL is allowed: failed-login attempts against unknown emails still
    -- get recorded for abuse detection.
    user_id         uuid        REFERENCES auth.users(id),

    -- Known action values (also free-form for forward compatibility):
    --   'signup_submitted'   - new account created via /auth/signup
    --   'signup_approved'    - admin approved a pending account
    --   'signup_rejected'    - admin rejected a pending account
    --   'login_success'      - user logged in
    --   'login_failed'       - bad password / no user / account not active
    --   'logout'             - user logged out
    --   'password_changed'   - user (or admin) changed password
    --   'password_reset'     - admin reset a user's password
    --   'role_changed'       - admin changed a user's role
    --   'account_enabled'    - admin re-enabled a disabled account
    --   'account_disabled'   - admin disabled an account
    action          text        NOT NULL,

    -- Action-specific context, e.g. {"old_role": "admin", "new_role": "sales"}
    -- or {"reason": "bad_password"} for failed logins.
    metadata        jsonb       NOT NULL DEFAULT '{}'::jsonb,

    ip_address      inet,
    user_agent      text,

    occurred_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_log_user_id_idx     ON auth.audit_log(user_id);
CREATE INDEX audit_log_action_idx      ON auth.audit_log(action);
CREATE INDEX audit_log_occurred_at_idx ON auth.audit_log(occurred_at DESC);

COMMENT ON TABLE auth.audit_log IS
  'Append-only log of auth events. Never UPDATE or DELETE rows here.';
