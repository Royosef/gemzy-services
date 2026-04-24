-- Make public.profiles the single source of truth for app-owned user state.
-- This migration:
-- 1. Ensures profile rows exist for every auth user.
-- 2. Backfills missing profile-owned fields from auth metadata once.
-- 3. Removes redundant app-owned keys from auth.users.raw_user_meta_data.
-- 4. Creates an auth.users trigger so new users automatically receive a profile row.

ALTER TABLE IF EXISTS public.profiles
  ALTER COLUMN retention_offer_used SET DEFAULT FALSE;

UPDATE public.profiles
SET retention_offer_used = FALSE
WHERE retention_offer_used IS NULL;

ALTER TABLE IF EXISTS public.profiles
  ALTER COLUMN retention_offer_used SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'profiles_credits_nonnegative'
      AND conrelid = 'public.profiles'::regclass
  ) THEN
    ALTER TABLE public.profiles
      ADD CONSTRAINT profiles_credits_nonnegative CHECK (credits >= 0);
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'profiles_id_fkey'
      AND conrelid = 'public.profiles'::regclass
  ) THEN
    ALTER TABLE public.profiles
      ADD CONSTRAINT profiles_id_fkey
      FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;
  END IF;
END$$;

INSERT INTO public.profiles (
  id,
  name,
  plan,
  credits,
  avatar_url,
  next_credit_reset_at
)
SELECT
  u.id,
  NULLIF(BTRIM(COALESCE(
    u.raw_user_meta_data ->> 'name',
    u.raw_user_meta_data ->> 'full_name'
  )), ''),
  'Free',
  COALESCE(
    (
      SELECT ps.initial_credits
      FROM public.plan_settings ps
      WHERE ps.plan::text = 'Free'
      LIMIT 1
    ),
    0
  ),
  NULLIF(BTRIM(COALESCE(
    u.raw_user_meta_data ->> 'avatar_url',
    u.raw_user_meta_data ->> 'avatarUrl',
    u.raw_user_meta_data ->> 'picture'
  )), ''),
  NOW() + INTERVAL '30 days'
FROM auth.users u
LEFT JOIN public.profiles p ON p.id = u.id
WHERE p.id IS NULL;

UPDATE public.profiles p
SET
  name = COALESCE(
    p.name,
    NULLIF(BTRIM(COALESCE(
      u.raw_user_meta_data ->> 'name',
      u.raw_user_meta_data ->> 'full_name'
    )), '')
  ),
  avatar_url = COALESCE(
    p.avatar_url,
    NULLIF(BTRIM(COALESCE(
      u.raw_user_meta_data ->> 'avatar_url',
      u.raw_user_meta_data ->> 'avatarUrl',
      u.raw_user_meta_data ->> 'picture'
    )), '')
  ),
  notification_preferences = COALESCE(
    p.notification_preferences,
    CASE
      WHEN jsonb_typeof(u.raw_user_meta_data -> 'notification_preferences') = 'object'
        THEN u.raw_user_meta_data -> 'notification_preferences'
      WHEN jsonb_typeof(u.raw_user_meta_data -> 'notificationPreferences') = 'object'
        THEN u.raw_user_meta_data -> 'notificationPreferences'
      ELSE NULL
    END,
    jsonb_build_object(
      'gemzyUpdates', TRUE,
      'personalUpdates', TRUE,
      'email', TRUE
    )
  )
FROM auth.users u
WHERE u.id = p.id
  AND (
    p.name IS NULL
    OR p.avatar_url IS NULL
    OR p.notification_preferences IS NULL
  );

UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb) - ARRAY[
  'name',
  'plan',
  'plan_tier',
  'credits',
  'credit_balance',
  'creditsRenewedAt',
  'avatar_url',
  'avatarUrl',
  'notification_preferences',
  'notificationPreferences',
  'is_admin',
  'admin'
]::text[]
WHERE COALESCE(raw_user_meta_data, '{}'::jsonb) ?| ARRAY[
  'name',
  'plan',
  'plan_tier',
  'credits',
  'credit_balance',
  'creditsRenewedAt',
  'avatar_url',
  'avatarUrl',
  'notification_preferences',
  'notificationPreferences',
  'is_admin',
  'admin'
];

CREATE OR REPLACE FUNCTION public.handle_auth_user_profile()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  default_name text;
  default_avatar_url text;
  default_notifications jsonb;
  free_credits integer;
BEGIN
  default_name := NULLIF(BTRIM(COALESCE(
    NEW.raw_user_meta_data ->> 'name',
    NEW.raw_user_meta_data ->> 'full_name'
  )), '');

  default_avatar_url := NULLIF(BTRIM(COALESCE(
    NEW.raw_user_meta_data ->> 'avatar_url',
    NEW.raw_user_meta_data ->> 'avatarUrl',
    NEW.raw_user_meta_data ->> 'picture'
  )), '');

  default_notifications := COALESCE(
    CASE
      WHEN jsonb_typeof(NEW.raw_user_meta_data -> 'notification_preferences') = 'object'
        THEN NEW.raw_user_meta_data -> 'notification_preferences'
      ELSE NULL
    END,
    CASE
      WHEN jsonb_typeof(NEW.raw_user_meta_data -> 'notificationPreferences') = 'object'
        THEN NEW.raw_user_meta_data -> 'notificationPreferences'
      ELSE NULL
    END,
    jsonb_build_object(
      'gemzyUpdates', TRUE,
      'personalUpdates', TRUE,
      'email', TRUE
    )
  );

  SELECT ps.initial_credits
  INTO free_credits
  FROM public.plan_settings ps
  WHERE ps.plan::text = 'Free'
  LIMIT 1;

  INSERT INTO public.profiles (
    id,
    name,
    plan,
    credits,
    avatar_url,
    notification_preferences,
    next_credit_reset_at
  )
  VALUES (
    NEW.id,
    default_name,
    'Free',
    COALESCE(free_credits, 0),
    default_avatar_url,
    default_notifications,
    NOW() + INTERVAL '30 days'
  )
  ON CONFLICT (id) DO UPDATE
  SET
    name = COALESCE(public.profiles.name, EXCLUDED.name),
    avatar_url = COALESCE(public.profiles.avatar_url, EXCLUDED.avatar_url);

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;

CREATE TRIGGER on_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW
EXECUTE FUNCTION public.handle_auth_user_profile();
