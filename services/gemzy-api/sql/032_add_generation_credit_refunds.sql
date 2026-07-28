-- Persistent idempotency for generation failure/cancellation refunds.

CREATE TABLE IF NOT EXISTS public.generation_credit_refunds (
  job_id TEXT PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  refunded_credits INTEGER NOT NULL DEFAULT 0 CHECK (refunded_credits >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.generation_credit_refunds ENABLE ROW LEVEL SECURITY;

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

  INSERT INTO public.generation_credit_refunds (
    job_id,
    user_id,
    refunded_credits
  )
  VALUES (
    p_job_id,
    p_user_id,
    0
  )
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
    SET credits = credits + refund_delta
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
    profiles.credits + profiles.purchased_credits,
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
