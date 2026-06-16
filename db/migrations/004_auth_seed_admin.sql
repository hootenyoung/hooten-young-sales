-- =====================================================================
-- 004_auth_seed_admin.sql
-- =====================================================================
-- Seeds the initial admin account so someone can log in to bootstrap
-- the system. Run ONCE per database after 003_auth_schema.sql.
--
-- BEFORE RUNNING:
--   1. Replace the three placeholders below (email, first_name,
--      last_name) with your real values.
--   2. Replace 'CHANGE-ME-ON-FIRST-LOGIN' with a temporary password.
--      You will be forced to change it the first time you log in,
--      so don't pick something you want to keep.
--
-- SECURITY NOTES:
--   * The password is hashed with bcrypt (12 rounds) via pgcrypto's
--     crypt() function. The result is compatible with passlib bcrypt
--     verification on the application side.
--   * After running this script, the plaintext password lives only in
--     this file (and your shell history). Delete it from your shell
--     history if you ran it via the command line:
--         history -d <number>      (bash/zsh)
--   * Re-running this script will fail if the email already exists
--     (auth.users.email is UNIQUE). That's intentional — preventing
--     accidental duplicate-admin creation.
--
-- WHAT THIS SCRIPT DOES:
--   1. Inserts the bootstrap admin user into auth.users.
--   2. Grants that user ALL FOUR seeded system roles
--      (admin, distribution, depletions, marketing) so they can
--      immediately access every section of the dashboard without a
--      chicken-and-egg moment.
--   3. Writes a `seed_admin_bootstrap` row to auth.audit_log so the
--      trail is complete from day zero.
--
-- Run in a single transaction so a partial failure leaves nothing
-- behind to clean up.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Insert the bootstrap admin user
-- ---------------------------------------------------------------------
INSERT INTO auth.users (
    email,
    password_hash,
    first_name,
    last_name,
    status,
    must_change_password
)
VALUES (
    -- TODO: replace with your real admin email
    'admin@hootenyoung.com',

    -- TODO: replace 'CHANGE-ME-ON-FIRST-LOGIN' with a temp password
    crypt('CHANGE-ME-ON-FIRST-LOGIN', gen_salt('bf', 12)),

    -- TODO: replace with your real first name
    'Admin',

    -- TODO: replace with your real last name
    'User',

    'active',    -- status — no approval needed for the bootstrap admin
    true         -- forces password change on first login
);


-- ---------------------------------------------------------------------
-- 2. Grant the bootstrap admin all four system roles
-- ---------------------------------------------------------------------
INSERT INTO auth.user_roles (user_id, role_id)
SELECT
    (SELECT id FROM auth.users WHERE email = 'admin@hootenyoung.com'),
    r.id
FROM auth.roles r
WHERE r.name IN ('admin', 'distribution', 'depletions', 'marketing');


-- ---------------------------------------------------------------------
-- 3. Audit-log the bootstrap so the trail starts from day zero
-- ---------------------------------------------------------------------
INSERT INTO auth.audit_log (user_id, action, metadata)
SELECT
    u.id,
    'seed_admin_bootstrap',
    jsonb_build_object(
        'note',          'Initial admin seeded via 004_auth_seed_admin.sql',
        'granted_roles', ARRAY['admin', 'distribution', 'depletions', 'marketing']
    )
FROM auth.users u
WHERE u.email = 'admin@hootenyoung.com';

COMMIT;


-- =====================================================================
-- HOW TO ADD MORE ADMINS LATER (without re-running this seed):
--
--   Either: via the admin UI (the bootstrap admin creates them).
--
--   Or: by running this SQL pattern (replace the placeholders):
--       BEGIN;
--       INSERT INTO auth.users (email, password_hash, first_name, last_name, status, must_change_password)
--            VALUES ('second.admin@hootenyoung.com',
--                    crypt('TEMP-PASSWORD', gen_salt('bf', 12)),
--                    'First', 'Last', 'active', true);
--       INSERT INTO auth.user_roles (user_id, role_id)
--            SELECT (SELECT id FROM auth.users WHERE email = 'second.admin@hootenyoung.com'),
--                   id FROM auth.roles WHERE name = 'admin';
--       COMMIT;
--
-- HOW TO ADD A NEW ROLE LATER (no migration needed):
--   INSERT INTO auth.roles (name, display_name, description)
--        VALUES ('analyst', 'Data Analyst', 'Read-only data access');
--   The admin UI's role-checkbox list reads from auth.roles at runtime,
--   so the new role appears immediately. Assign it via the UI.
-- =====================================================================
