-- ============================================================
-- Fix Permissions for Service Role
-- Grants usage and table access to 'service_role' for moments/people schemas
-- ============================================================

BEGIN;

-- 1. Grant usage on schemas
GRANT USAGE ON SCHEMA moments TO service_role;
GRANT USAGE ON SCHEMA people TO service_role;

-- 2. Grant access to all current tables
GRANT ALL ON ALL TABLES IN SCHEMA moments TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA people TO service_role;

-- 3. Grant access to all current sequences
GRANT ALL ON ALL SEQUENCES IN SCHEMA moments TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA people TO service_role;

-- 4. Ensure future tables are accessible (Default Privileges)
ALTER DEFAULT PRIVILEGES IN SCHEMA moments GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA people GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA moments GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA people GRANT ALL ON SEQUENCES TO service_role;

COMMIT;
