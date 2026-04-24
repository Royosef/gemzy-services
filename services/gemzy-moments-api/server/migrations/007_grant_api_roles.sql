-- ============================================================
-- Grant Schema Permissions to API Roles
-- Grants usage and table access to 'anon' and 'authenticated'
-- for 'moments' and 'people' schemas so PostgREST can access them.
-- ============================================================

BEGIN;

-- 1. Grant usage on schemas
GRANT USAGE ON SCHEMA moments TO anon, authenticated;
GRANT USAGE ON SCHEMA people TO anon, authenticated;

-- 2. Grant access to all current tables
GRANT ALL ON ALL TABLES IN SCHEMA moments TO anon, authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA people TO anon, authenticated;

-- 3. Grant access to all current sequences
GRANT ALL ON ALL SEQUENCES IN SCHEMA moments TO anon, authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA people TO anon, authenticated;

-- 4. Ensure future tables are accessible (Default Privileges)
ALTER DEFAULT PRIVILEGES IN SCHEMA moments GRANT ALL ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA people GRANT ALL ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA moments GRANT ALL ON SEQUENCES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA people GRANT ALL ON SEQUENCES TO anon, authenticated;

COMMIT;
