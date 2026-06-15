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
--     history if you ran it via the command line.
--   * Re-running this script will fail if the email already exists
--     (auth.users.email is UNIQUE). That's intentional — preventing
--     accidental duplicate-admin creation.
-- =====================================================================

INSERT INTO auth.users (
    email,
    password_hash,
    first_name,
    last_name,
    role,
    status,
    must_change_password
)
VALUES (
    -- TODO: replace with your real admin email
    'admin@hootenyoung.com',

    -- TODO: replace 'CHANGE-ME-ON-FIRST-LOGIN' with a temp password
    crypt('CHANGE-ME-ON-FIRST-LOGIN', gen_salt('bf', 12)),

    -- TODO: replace with your real first name
    'Prasad',

    -- TODO: replace with your real last name
    'Yalavarthy',

    'admin',     -- role
    'active',    -- status — no approval needed for the bootstrap admin
    true         -- forces password change on first login
);
