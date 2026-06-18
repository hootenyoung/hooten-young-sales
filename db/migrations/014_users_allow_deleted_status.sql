-- 014: allow 'deleted' as a user status.
--
-- The admin user-management surface needs a way to soft-delete users
-- so admins can recreate an account with the same email address
-- without losing the historical record of the original account
-- (visit notes, audit log entries, etc. still reference the original
-- user_id).  The deletion endpoint mutates the user's email to a
-- sentinel value so the email slot frees up for reuse, and sets
-- status='deleted' so the row is filtered out of the active roster.
--
-- This migration just widens the CHECK constraint to allow the new
-- status value.  No data is changed.

ALTER TABLE auth.users DROP CONSTRAINT IF EXISTS users_status_check;

ALTER TABLE auth.users
    ADD CONSTRAINT users_status_check
    CHECK (status IN ('pending', 'active', 'rejected', 'disabled', 'deleted'));
