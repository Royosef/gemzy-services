-- Keep promotional Pro-trial credits separate from renewable plan credits.
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS trial_credits INTEGER NOT NULL DEFAULT 0;

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS subscription_period_type TEXT;

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMPTZ;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'profiles_trial_credits_nonnegative'
  ) THEN
    ALTER TABLE public.profiles
      ADD CONSTRAINT profiles_trial_credits_nonnegative
      CHECK (trial_credits >= 0);
  END IF;
END$$;

CREATE OR REPLACE FUNCTION public.refund_generation_credits(
  p_job_id TEXT,
  p_user_id UUID,
  p_target_refunded_credits INTEGER
)
RETURNS TABLE (
  remaining_credits INTEGER,
  refunded_credits INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  existing_user_id UUID;
  current_refunded INTEGER;
  refund_delta INTEGER;
BEGIN
  IF p_job_id IS NULL OR btrim(p_job_id) = '' THEN
    RAISE EXCEPTION 'job id is required';
  END IF;
  IF p_target_refunded_credits < 0 THEN
    RAISE EXCEPTION 'target refunded credits cannot be negative';
  END IF;

  INSERT INTO public.generation_credit_refunds (job_id, user_id, refunded_credits)
  VALUES (p_job_id, p_user_id, 0)
  ON CONFLICT (job_id) DO NOTHING;

  SELECT refunds.user_id, refunds.refunded_credits
  INTO existing_user_id, current_refunded
  FROM public.generation_credit_refunds refunds
  WHERE refunds.job_id = p_job_id
  FOR UPDATE;

  IF existing_user_id IS DISTINCT FROM p_user_id THEN
    RAISE EXCEPTION 'generation refund owner mismatch';
  END IF;

  refund_delta := GREATEST(0, p_target_refunded_credits - current_refunded);
  IF refund_delta > 0 THEN
    UPDATE public.profiles
    SET trial_credits = CASE
          WHEN subscription_period_type = 'TRIAL'
            AND subscription_expires_at > NOW()
          THEN LEAST(100, trial_credits + refund_delta)
          ELSE trial_credits
        END,
        credits = credits + CASE
          WHEN subscription_period_type = 'TRIAL'
            AND subscription_expires_at > NOW()
          THEN GREATEST(0, refund_delta - (100 - trial_credits))
          ELSE refund_delta
        END
    WHERE id = p_user_id;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'generation refund profile not found';
    END IF;

    current_refunded := current_refunded + refund_delta;
    UPDATE public.generation_credit_refunds
    SET refunded_credits = current_refunded,
        updated_at = NOW()
    WHERE job_id = p_job_id;
  END IF;

  RETURN QUERY
  SELECT
    profiles.trial_credits + profiles.credits + profiles.purchased_credits,
    current_refunded
  FROM public.profiles
  WHERE profiles.id = p_user_id;
END;
$$;

REVOKE ALL ON FUNCTION public.refund_generation_credits(TEXT, UUID, INTEGER)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION public.refund_generation_credits(TEXT, UUID, INTEGER)
  FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.refund_generation_credits(TEXT, UUID, INTEGER)
  TO service_role;
