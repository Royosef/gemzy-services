-- Add next_credit_reset_at to track when active subscribers should get their credits refreshed 
-- for yearly subscriptions. Defaults to null (no recurring reset pending).

ALTER TABLE profiles
ADD COLUMN IF NOT EXISTS next_credit_reset_at TIMESTAMPTZ;

-- Backfill existing Pro/Designer profiles with an initial date 1 month from now
UPDATE profiles
SET next_credit_reset_at = NOW() + INTERVAL '1 month'
WHERE plan IN ('Pro', 'Designer') 
  AND next_credit_reset_at IS NULL
  AND subscription_expires_at > NOW();

-- Add an index for faster polling of due credit resets
CREATE INDEX IF NOT EXISTS profiles_next_credit_reset_idx
  ON profiles (next_credit_reset_at)
  WHERE next_credit_reset_at IS NOT NULL;
