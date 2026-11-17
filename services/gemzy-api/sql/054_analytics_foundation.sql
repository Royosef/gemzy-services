-- Run before deploying the API. No historical signup events are fabricated.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
-- Keep the historical baseline and trigger installation consistent with
-- concurrent registrations/sign-ins during this migration.
LOCK TABLE auth.users IN SHARE ROW EXCLUSIVE MODE;
CREATE TABLE IF NOT EXISTS public.analytics_outbox (
  id uuid PRIMARY KEY,
  event text NOT NULL,
  distinct_id text NOT NULL,
  properties jsonb NOT NULL DEFAULT '{}',
  occurred_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz
);
CREATE INDEX IF NOT EXISTS analytics_outbox_pending ON public.analytics_outbox(occurred_at)
  WHERE delivered_at IS NULL;
CREATE INDEX IF NOT EXISTS analytics_outbox_identity_events
  ON public.analytics_outbox(distinct_id, event, occurred_at DESC);
CREATE TABLE IF NOT EXISTS public.analytics_registrations (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  completed_at timestamptz NOT NULL DEFAULT now(),
  historical boolean NOT NULL DEFAULT false
);
ALTER TABLE public.analytics_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analytics_registrations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.analytics_outbox, public.analytics_registrations FROM anon, authenticated;
GRANT ALL ON public.analytics_outbox, public.analytics_registrations TO service_role;

-- last_sign_in_at distinguishes existing signed-in accounts from pending OTP accounts.
INSERT INTO public.analytics_registrations(user_id, completed_at, historical)
SELECT id, coalesce(last_sign_in_at, created_at), true FROM auth.users
WHERE last_sign_in_at IS NOT NULL
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION public.record_analytics_registration(
  p_user_id uuid, p_event_id uuid, p_properties jsonb
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE inserted integer; demo_id text;
BEGIN
  IF p_properties->>'application_context_received' = 'true' THEN
    SELECT properties->>'generation_id' INTO demo_id FROM public.analytics_outbox
      WHERE event = 'Demo Generation Completed'
        AND distinct_id = p_properties->>'anonymous_id'
        AND properties->>'success' = 'true'
        AND occurred_at <= coalesce((SELECT occurred_at FROM public.analytics_outbox WHERE id = p_event_id), now())
      ORDER BY occurred_at DESC LIMIT 1;
    p_properties := p_properties || jsonb_build_object(
      'followed_anonymous_demo', demo_id IS NOT NULL,
      'demo_generation_id', demo_id
    );
  END IF;
  INSERT INTO public.analytics_registrations(user_id) VALUES (p_user_id)
    ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS inserted = ROW_COUNT;
  IF inserted = 0 THEN
    -- Enrich the auth trigger's first-success event with application context.
    IF p_properties->>'application_context_received' = 'true' THEN
      UPDATE public.analytics_outbox SET properties = properties || p_properties
        WHERE id = p_event_id
          AND coalesce(properties->>'application_context_received', 'false') <> 'true';
    END IF;
    RETURN false;
  END IF;
  INSERT INTO public.analytics_outbox(id, event, distinct_id, properties)
    VALUES (p_event_id, 'Signup Completed', p_user_id::text, p_properties)
    ON CONFLICT DO NOTHING;
  RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION public.record_analytics_registration(uuid, uuid, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_analytics_registration(uuid, uuid, jsonb) TO service_role;

-- Supabase owns successful authentication. Recording it in the same transaction
-- also covers the client closing before it receives the API response.
CREATE OR REPLACE FUNCTION public.on_analytics_auth_success()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NEW.last_sign_in_at IS NOT NULL THEN
    PERFORM public.record_analytics_registration(
      NEW.id, md5('gemzy:analytics:signup:' || NEW.id::text)::uuid,
      jsonb_build_object(
        'user_id', NEW.id::text,
        'registration_date', NEW.created_at,
        'auth_method', coalesce(NEW.raw_app_meta_data->>'provider', 'unknown'),
        'analytics_schema_version', 2, 'event_source', 'server',
        '$set_once', jsonb_build_object('registration_date', NEW.created_at)
      )
    );
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.on_analytics_auth_success() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS analytics_auth_success ON auth.users;
CREATE TRIGGER analytics_auth_success AFTER INSERT OR UPDATE OF last_sign_in_at ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.on_analytics_auth_success();
NOTIFY pgrst, 'reload schema';
COMMIT;
