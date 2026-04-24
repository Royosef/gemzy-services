-- ============================================================
-- Gemzy Moments — ROLLBACK Migration
-- Reverses 001_create_moments_schema.sql
-- WARNING: This will DROP all Moments data. Use with extreme caution.
-- ============================================================

BEGIN;

-- ── Drop all moments schema tables (cascade) ───────────
-- Order: leaf tables first, then parent tables

DROP TABLE IF EXISTS moments.notifications CASCADE;
DROP TABLE IF EXISTS moments.deliveries CASCADE;
DROP TABLE IF EXISTS moments.generation_jobs CASCADE;
DROP TABLE IF EXISTS moments.world_state CASCADE;
DROP TABLE IF EXISTS moments.usage_stats CASCADE;
DROP TABLE IF EXISTS moments.planner_runs CASCADE;
DROP TABLE IF EXISTS moments.moment_context CASCADE;
DROP TABLE IF EXISTS moments.moments CASCADE;
DROP TABLE IF EXISTS moments.plan_blocks CASCADE;
DROP TABLE IF EXISTS moments.content_plans CASCADE;
DROP TABLE IF EXISTS moments.user_preferences CASCADE;

DROP SCHEMA IF EXISTS moments;

-- ── Drop all people schema tables (cascade) ─────────────

DROP TABLE IF EXISTS people.reference_assets CASCADE;
DROP TABLE IF EXISTS people.persona_members CASCADE;
DROP TABLE IF EXISTS people.licensing_policies CASCADE;
DROP TABLE IF EXISTS people.world_wardrobe_items CASCADE;
DROP TABLE IF EXISTS people.world_locations CASCADE;
DROP TABLE IF EXISTS people.persona_style_profile CASCADE;
DROP TABLE IF EXISTS people.personas CASCADE;

DROP SCHEMA IF EXISTS people;

COMMIT;
