-- ============================================================
-- Add App-Specific Onboarding Column
-- Adds `moments_onboarding_completed` to profiles table
-- leaving `onboarding_completed` intact for Gemzy Core.
-- ============================================================

ALTER TABLE profiles 
ADD COLUMN IF NOT EXISTS "moments_onboarding_completed" BOOLEAN NOT NULL DEFAULT FALSE;
