-- ============================================================
-- Add avatar_url to people.personas
-- ============================================================

BEGIN;

ALTER TABLE people.personas
ADD COLUMN IF NOT EXISTS avatar_url TEXT;

COMMIT;
