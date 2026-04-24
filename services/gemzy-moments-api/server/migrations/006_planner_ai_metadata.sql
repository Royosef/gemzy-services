-- ============================================================
-- Gemzy Moments — Migration 006: Planner AI Metadata
-- Adds planning_model_name and execution_engine_name to planner_runs
-- ============================================================

BEGIN;

-- Add new columns for hybrid AI planner metadata
ALTER TABLE moments.planner_runs
    ADD COLUMN IF NOT EXISTS planning_model_name TEXT,
    ADD COLUMN IF NOT EXISTS execution_engine_name TEXT;

-- Backfill existing rows: they were all rule-based
UPDATE moments.planner_runs
SET planning_model_name = 'planner_v1_rule_based',
    execution_engine_name = 'planner_v1_rule_based'
WHERE planning_model_name IS NULL;

COMMIT;
