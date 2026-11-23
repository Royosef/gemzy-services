-- Web app: purchases are completed in the mobile app for now. Records each time a signed-in
-- user tries to buy on the website (for in-app conversion attribution) and who asked to be
-- told when buying on the website opens.
-- Run before deploying the API that serves /web-purchase. Additive only: no existing table changes.
BEGIN;

CREATE TABLE IF NOT EXISTS public.web_purchase_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  product text NOT NULL,
  source text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- Set when the QR code / app link for this intent is opened (first open only).
  app_link_opened_at timestamptz
);

CREATE INDEX IF NOT EXISTS web_purchase_intents_user_recent
  ON public.web_purchase_intents (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.web_purchase_waitlist (
  user_id uuid PRIMARY KEY REFERENCES public.profiles(id) ON DELETE CASCADE,
  product text NOT NULL,
  source text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- Launch-day email sent ("web purchases are live").
  notified_at timestamptz,
  -- Early-bird perk (e.g. bonus credits) granted, if one is offered.
  early_bird_granted_at timestamptz
);

-- Only the API (service role) reads or writes these tables.
ALTER TABLE public.web_purchase_intents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.web_purchase_waitlist ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.web_purchase_intents FROM anon, authenticated;
REVOKE ALL ON public.web_purchase_waitlist FROM anon, authenticated;
GRANT ALL ON public.web_purchase_intents TO service_role;
GRANT ALL ON public.web_purchase_waitlist TO service_role;

COMMIT;
