-- Split one-time purchased credits from monthly plan credits.
-- profiles.credits remains the monthly bucket that resets on plan cycles.
-- profiles.purchased_credits stores paid top-ups that never expire.
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS purchased_credits INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'profiles_purchased_credits_nonnegative'
  ) THEN
    ALTER TABLE public.profiles
      ADD CONSTRAINT profiles_purchased_credits_nonnegative CHECK (purchased_credits >= 0);
  END IF;
END$$;