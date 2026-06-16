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
-- ROLES ARE FULLY DATA-DRIVEN — adding a new role is a single INSERT,
-- never a code change. The schema below implements the standard
-- relational RBAC pattern used in production systems (Auth0, Keycloak,
-- Postgres' own role system):
--
--      auth.users  ──< auth.user_roles >──  auth.roles
--                            |
--                            └── tracks who assigned each role + when
--
-- This separates three concerns that DIFFERENT people manage at
-- DIFFERENT cadences:
--   * Roles      — the catalog of what roles exist (rarely changes;
--                  managed by org admins)
--   * Users      — who has an account (changes constantly; managed
--                  by the signup + admin flows)
--   * Assignments — which user has which role(s) (changes frequently;
--                  managed by admins in the Users tab)
--
-- HOW TO ADD A NEW ROLE LATER (e.g. 'analyst'):
--   INSERT INTO auth.roles (name, display_name, description)
--        VALUES ('analyst', 'Data Analyst', 'Read-only data access');
--   That's it. The admin UI dynamically pulls available roles from
--   auth.roles, so the new checkbox appears with zero application
--   code change.
--
-- Other design principles encoded here:
--   * Email is plain text, normalized to lowercase by the application
--     (Pydantic validator at the API boundary). Single source of
--     truth: the app layer. Direct SQL inserts (migrations, ops
--     scripts) must lowercase emails themselves.
--   * Password hashes use bcrypt via pgcrypto. Compatible with the
--     application's passlib-bcrypt verification.
--   * `updated_at` is set by the application ORM (onupdate=func.now()),
--     not by a Postgres trigger — matches the convention used in the
--     sales schema.
--   * The audit log is append-only. Every meaningful auth action lands
--     a row here for traceability.
--   * Password reset / set-password is mediated by the separate
--     `auth.password_reset_tokens` table. Tokens are stored as
--     SHA-256 hashes (never plaintext) and are single-use + TTL-bound.
--     The same table powers BOTH the forgot-password flow AND the
--     "admin created your account, set your password" email flow —
--     the `purpose` column distinguishes them.
--
-- Run order: after 002_depletions_allow_negatives.sql. The CREATE
-- SCHEMA / CREATE EXTENSION lines are idempotent; the CREATE TABLE
-- lines will error if re-run on a database that already has them.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Required extensions
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";     -- gen_random_uuid(), crypt(), gen_salt(), digest()

-- ---------------------------------------------------------------------
-- Schema
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS auth;

COMMENT ON SCHEMA auth IS
  'Authentication and authorization. Owned by hooten-young-sales but '
  'readable by other backends (e.g. marketing) for identity lookup.';


-- =====================================================================
-- auth.roles
-- =====================================================================
-- The canonical catalog of roles in the platform. Used to populate the
-- admin UI's role-checkbox list and to validate that an assignment
-- references a known role.
--
-- Adding a new role is a single INSERT into this table — no application
-- code change required. The admin UI reads this catalog at runtime.
-- =====================================================================
CREATE TABLE auth.roles (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Machine-readable identifier used in code + JWT claims.
    -- Lowercase, no spaces, no punctuation. E.g. 'admin', 'distribution',
    -- 'depletions', 'marketing'. App layer normalizes to lowercase
    -- before insert; DB stores plain text.
    name            text        NOT NULL UNIQUE
                                CHECK (name = lower(name) AND name <> ''),

    -- Human-readable label shown in the admin UI.
    -- E.g. 'Administrator', 'Sales Team', 'Marketing'.
    display_name    text        NOT NULL,

    -- One-line explanation shown next to the checkbox in the admin UI.
    description     text,

    -- System roles are seeded by this migration and cannot be deleted
    -- through the admin UI (preventing accidental loss of `admin`).
    -- Roles added later by INSERT have is_system = false and ARE
    -- deletable.
    is_system       boolean     NOT NULL DEFAULT false,

    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE auth.roles IS
  'Canonical catalog of platform roles. The admin UI reads from here '
  'to populate the role-checkbox list — adding a row here surfaces a '
  'new role across the platform with zero code change.';


-- =====================================================================
-- auth.users
-- =====================================================================
-- One row per user account. Status drives the signup-approval workflow
-- (pending → active / rejected) and the disable flow. Role assignments
-- live in the separate auth.user_roles join table.
-- =====================================================================
CREATE TABLE auth.users (
    id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Email is the login identifier. App layer normalizes to lowercase
    -- before insert (Pydantic validator), so the UNIQUE constraint on
    -- plain text is sufficient. The CHECK guards direct SQL inserts.
    email                  text        NOT NULL UNIQUE
                                       CHECK (email = lower(email) AND email <> ''),

    -- bcrypt hash (60 chars, $2b$ format). Never store plaintext.
    -- For admin-created accounts the hash is a placeholder marker
    -- because the real password gets set via the "set password" email
    -- flow — see auth.password_reset_tokens. The placeholder is still
    -- bcrypt-formatted so passlib's verification doesn't crash; it
    -- just never matches any real password the user might guess.
    password_hash          text        NOT NULL,

    first_name             text        NOT NULL,
    last_name              text        NOT NULL,

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

COMMENT ON TABLE auth.users IS
  'User accounts. One row per person. Email is the login identifier. '
  'Role assignments live in auth.user_roles.';

COMMENT ON COLUMN auth.users.status IS
  'Lifecycle: pending → active (approve) or rejected (deny). '
  'Active accounts can be disabled later by an admin.';

COMMENT ON COLUMN auth.users.must_change_password IS
  'TRUE means the user must change their password before they can use '
  'the app. Set after admin-created accounts or password resets.';


-- =====================================================================
-- auth.user_roles
-- =====================================================================
-- Many-to-many join between users and roles. One row per (user, role)
-- assignment. Tracks who made the assignment and when so the audit
-- trail is complete without having to grep auth.audit_log.
--
-- A user with NO rows here has effectively zero access — application
-- code treats that the same as a disabled account.
-- =====================================================================
CREATE TABLE auth.user_roles (
    user_id      uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role_id      uuid        NOT NULL REFERENCES auth.roles(id) ON DELETE RESTRICT,
    assigned_at  timestamptz NOT NULL DEFAULT now(),
    -- Which admin assigned this role. NULL for the bootstrap seed.
    assigned_by  uuid        REFERENCES auth.users(id),

    PRIMARY KEY (user_id, role_id)
);

-- Used by the "show me everyone with role X" admin filter and by the
-- per-user "show me this user's roles" lookup.
CREATE INDEX user_roles_user_id_idx ON auth.user_roles(user_id);
CREATE INDEX user_roles_role_id_idx ON auth.user_roles(role_id);

COMMENT ON TABLE auth.user_roles IS
  'User ↔ role assignments. ON DELETE CASCADE on user_id means deleting '
  'a user automatically removes their assignments. ON DELETE RESTRICT '
  'on role_id prevents deleting a role that''s still assigned to users.';


-- =====================================================================
-- auth.password_reset_tokens
-- =====================================================================
-- One-time-use tokens that grant a user the right to set a new
-- password. Issued by:
--   * The forgot-password flow (user clicks "forgot password" → email
--     them a link containing this token)
--   * The admin-creates-user flow (admin creates the account → email
--     the new user a link containing this token so they can set their
--     initial password — same mechanism, different purpose)
--
-- Storage:
--   * Only the SHA-256 digest of the token is stored. The plaintext
--     token only ever lives in the email to the user.
--   * Tokens are single-use: `used_at IS NOT NULL` means the token has
--     been consumed and cannot be reused.
--   * Tokens expire after a TTL (typically 24 hours, controlled by
--     the application — `expires_at` is the absolute cutoff).
-- =====================================================================
CREATE TABLE auth.password_reset_tokens (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- The user this token is for. ON DELETE CASCADE so a deleted user
    -- automatically loses all outstanding tokens.
    user_id         uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- SHA-256 hex digest of the plaintext token (64 chars).
    -- Compare on lookup using:
    --     WHERE token_hash = encode(digest($1::bytea, 'sha256'), 'hex')
    token_hash      text        NOT NULL UNIQUE,

    -- What the token grants. Distinguishes the two flows:
    --   'forgot_password'  - user requested a reset themselves
    --   'set_password'     - admin created the account, this is the
    --                        initial password-set link
    purpose         text        NOT NULL,

    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,

    -- NULL until the token is consumed. After consumption, the row is
    -- KEPT (for audit) but the token can no longer be used.
    used_at         timestamptz,

    -- Forensics — IP that triggered the request (forgot_password) or
    -- the admin who created the account (set_password).
    requested_by_ip inet,

    CONSTRAINT password_reset_tokens_purpose_check CHECK (
        purpose IN ('forgot_password', 'set_password')
    )
);

-- Used by the lookup-by-token endpoint:
--     WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()
CREATE INDEX password_reset_tokens_user_id_idx     ON auth.password_reset_tokens(user_id);
CREATE INDEX password_reset_tokens_expires_at_idx  ON auth.password_reset_tokens(expires_at);
CREATE INDEX password_reset_tokens_purpose_idx     ON auth.password_reset_tokens(purpose);

COMMENT ON TABLE auth.password_reset_tokens IS
  'Single-use, time-limited tokens for password reset and initial '
  'password set. Tokens are stored as SHA-256 hashes; the plaintext '
  'only lives in the email sent to the user.';


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
    --   'signup_submitted'          - new account created via /auth/signup
    --   'signup_approved'           - admin approved a pending account
    --   'signup_rejected'           - admin rejected a pending account
    --   'admin_created_user'        - admin created a user directly
    --   'login_success'             - user logged in
    --   'login_failed'              - bad password / no user / not active
    --   'logout'                    - user logged out
    --   'password_reset_requested'  - user clicked "forgot password"
    --   'password_set'              - user set password via reset / set link
    --   'password_changed'          - user changed password while logged in
    --   'roles_changed'             - admin changed a user's roles
    --   'role_created'              - admin added a new role to auth.roles
    --   'role_deleted'              - admin removed a non-system role
    --   'account_enabled'           - admin re-enabled a disabled account
    --   'account_disabled'          - admin disabled an account
    --   'account_deleted'           - admin deleted (soft) an account
    --   'seed_admin_bootstrap'      - 004 seed bootstrap (one-time)
    action          text        NOT NULL,

    -- Action-specific context, e.g.
    --   {"old_roles": ["sales"], "new_roles": ["sales", "marketing"]}
    --   {"reason": "bad_password"}
    --   {"created_by": "<admin-uuid>"}
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


-- =====================================================================
-- Seed the system roles
-- =====================================================================
-- These four roles ship with the platform and cannot be deleted from
-- the admin UI (is_system = true). The bootstrap admin user is granted
-- all four in migration 004 so they can immediately access every
-- section.
--
-- Role-per-section model:
--   Each role corresponds to one access scope in the platform. Frontend
--   route guards check `requireRole('depletions')`, backend endpoints
--   check the same. A user who needs Distribution + Depletions just has
--   both roles checked in the admin UI.
--
-- Why `distribution` and `depletions` are separate roles (not one `sales`):
--   The sales backend serves two distinct dashboard sections. Some users
--   should see Distribution but not Depletions, or vice versa. Splitting
--   them at the role level keeps access independent without writing any
--   mapping logic.
--
-- ADD A NEW ROLE / SECTION LATER WITHOUT A MIGRATION:
--   INSERT INTO auth.roles (name, display_name, description)
--        VALUES ('forecasting', 'Forecasting', 'Forecasting dashboard access.');
-- The admin UI will surface the new role automatically.
-- =====================================================================
INSERT INTO auth.roles (name, display_name, description, is_system) VALUES
    ('admin',        'Administrator', 'Full platform access. Manages users, roles, and configuration.', true),
    ('distribution', 'Distribution',  'Access to the Distribution dashboard sections (sales backend).', true),
    ('depletions',   'Depletions',    'Access to the Depletions dashboard sections (sales backend).',   true),
    ('marketing',    'Marketing',     'Access to the Marketing intelligence sections.',                 true);
