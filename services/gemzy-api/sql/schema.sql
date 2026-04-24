-- Gemzy content storage schema
-- Run against a PostgreSQL database (e.g. Supabase) to provision
-- the tables used by the mobile application and FastAPI backend.

-- Enable UUID generation helpers if they are not already available.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Enumerated plan tiers that match the PlanTier union in the app.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'plan_tier') THEN
    CREATE TYPE plan_tier AS ENUM ('Free', 'Pro', 'Designer');
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'prompt_engine_status') THEN
    CREATE TYPE prompt_engine_status AS ENUM ('draft', 'published', 'archived');
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT,
  plan plan_tier NOT NULL DEFAULT 'Free',
  credits INTEGER NOT NULL DEFAULT 0 CHECK (credits >= 0),
  avatar_url TEXT,
  notification_preferences JSONB NOT NULL DEFAULT jsonb_build_object(
    'gemzyUpdates', TRUE,
    'personalUpdates', TRUE,
    'email', TRUE
  ),
  is_admin BOOLEAN NOT NULL DEFAULT FALSE,
  deactivated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS plan_settings (
  plan plan_tier PRIMARY KEY,
  initial_credits INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO plan_settings (plan, initial_credits) VALUES
  ('Free', 100),
  ('Pro', 500),
  ('Designer', 1000)
ON CONFLICT (plan) DO UPDATE SET initial_credits = excluded.initial_credits;

CREATE TABLE IF NOT EXISTS collections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  cover_url TEXT,
  curated_by TEXT,
  description TEXT,
  tags TEXT[] NOT NULL DEFAULT '{}',
  liked BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS collections_user_created_idx
  ON collections (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS collection_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  collection_id UUID NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  external_id TEXT NOT NULL,
  image_url TEXT NOT NULL,
  category TEXT,
  model_id TEXT,
  model_name TEXT,
  is_new BOOLEAN NOT NULL DEFAULT FALSE,
  is_favorite BOOLEAN NOT NULL DEFAULT FALSE,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS collection_items_external_idx
  ON collection_items (collection_id, external_id);

CREATE INDEX IF NOT EXISTS collection_items_collection_idx
  ON collection_items (collection_id, created_at DESC);

CREATE INDEX IF NOT EXISTS collection_items_user_created_idx
  ON collection_items (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS models (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  plan plan_tier NOT NULL DEFAULT 'Free',
  highlight TEXT,
  description TEXT,
  image_url TEXT NOT NULL,
  tags TEXT[] NOT NULL DEFAULT '{}',
  spotlight_tag TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_likes (
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  model_id UUID NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  liked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, model_id)
);

CREATE TABLE IF NOT EXISTS model_gallery (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  model_id UUID NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  image_url TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS model_gallery_model_idx
  ON model_gallery (model_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_deletion_queue (
  user_id UUID PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  scheduled_for TIMESTAMPTZ NOT NULL,
  grace_period_days INTEGER NOT NULL DEFAULT 30,
  status TEXT NOT NULL DEFAULT 'scheduled',
  error TEXT,
  deleted_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS user_deletion_queue_schedule_idx
  ON user_deletion_queue (scheduled_for)
  WHERE status = 'scheduled';

CREATE TABLE IF NOT EXISTS app_notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_key TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL CHECK (category IN ('general', 'personal')),
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  action_pathname TEXT,
  action_params JSONB,
  action_url TEXT,
  target_user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  published_by UUID REFERENCES profiles(id) ON DELETE SET NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS app_notifications_created_at_idx
  ON app_notifications (created_at DESC);

CREATE INDEX IF NOT EXISTS app_notifications_target_user_id_idx
  ON app_notifications (target_user_id);

CREATE INDEX IF NOT EXISTS app_notifications_is_active_idx
  ON app_notifications (is_active);

CREATE TABLE IF NOT EXISTS prompt_engines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  task_type TEXT NOT NULL,
  renderer_key TEXT NOT NULL,
  input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
  output_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
  labels JSONB NOT NULL DEFAULT '{}'::jsonb,
  published_version_id UUID,
  created_by UUID REFERENCES profiles(id) ON DELETE SET NULL,
  updated_by UUID REFERENCES profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS prompt_engines_task_type_idx
  ON prompt_engines (task_type);

CREATE TABLE IF NOT EXISTS prompt_engine_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  engine_id UUID NOT NULL REFERENCES prompt_engines(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL CHECK (version_number > 0),
  status prompt_engine_status NOT NULL DEFAULT 'draft',
  change_note TEXT,
  definition JSONB NOT NULL DEFAULT '{}'::jsonb,
  sample_input JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (engine_id, version_number)
);

CREATE INDEX IF NOT EXISTS prompt_engine_versions_engine_idx
  ON prompt_engine_versions (engine_id, version_number DESC);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'prompt_engines_published_version_id_fkey'
  ) THEN
    ALTER TABLE prompt_engines
      ADD CONSTRAINT prompt_engines_published_version_id_fkey
      FOREIGN KEY (published_version_id)
      REFERENCES prompt_engine_versions(id)
      ON DELETE SET NULL;
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS prompt_task_routes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  task_type TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  match_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
  engine_id UUID NOT NULL REFERENCES prompt_engines(id) ON DELETE CASCADE,
  pinned_version_id UUID REFERENCES prompt_engine_versions(id) ON DELETE SET NULL,
  notes TEXT,
  created_by UUID REFERENCES profiles(id) ON DELETE SET NULL,
  updated_by UUID REFERENCES profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS prompt_task_routes_task_idx
  ON prompt_task_routes (task_type, is_active, priority);

CREATE TABLE IF NOT EXISTS push_tokens (
  token TEXT PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  platform TEXT NOT NULL CHECK (platform IN ('ios', 'android')),
  app_version TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  last_registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS push_tokens_user_id_idx
  ON push_tokens (user_id);

CREATE INDEX IF NOT EXISTS push_tokens_is_active_idx
  ON push_tokens (is_active);

CREATE TABLE IF NOT EXISTS push_notification_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  notification_id UUID REFERENCES app_notifications(id) ON DELETE SET NULL,
  user_id UUID REFERENCES profiles(id) ON DELETE SET NULL,
  push_token TEXT,
  provider TEXT NOT NULL DEFAULT 'expo',
  status TEXT NOT NULL CHECK (status IN ('accepted', 'failed')),
  ticket_id TEXT,
  error_code TEXT,
  error_message TEXT,
  payload JSONB,
  ticket JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS push_notification_logs_notification_id_idx
  ON push_notification_logs (notification_id);

CREATE INDEX IF NOT EXISTS push_notification_logs_user_id_idx
  ON push_notification_logs (user_id);

CREATE INDEX IF NOT EXISTS push_notification_logs_status_idx
  ON push_notification_logs (status);

CREATE INDEX IF NOT EXISTS push_notification_logs_ticket_id_idx
  ON push_notification_logs (ticket_id);

-- Utility trigger to keep updated_at columns fresh.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'collections_set_updated_at'
  ) THEN
    CREATE TRIGGER collections_set_updated_at
      BEFORE UPDATE ON collections
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'profiles_set_updated_at'
  ) THEN
    CREATE TRIGGER profiles_set_updated_at
      BEFORE UPDATE ON profiles
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'plan_settings_set_updated_at'
  ) THEN
    CREATE TRIGGER plan_settings_set_updated_at
      BEFORE UPDATE ON plan_settings
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'models_set_updated_at'
  ) THEN
    CREATE TRIGGER models_set_updated_at
      BEFORE UPDATE ON models
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'user_deletion_queue_set_updated_at'
  ) THEN
    CREATE TRIGGER user_deletion_queue_set_updated_at
      BEFORE UPDATE ON user_deletion_queue
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'app_notifications_set_updated_at'
  ) THEN
    CREATE TRIGGER app_notifications_set_updated_at
      BEFORE UPDATE ON app_notifications
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'prompt_engines_set_updated_at'
  ) THEN
    CREATE TRIGGER prompt_engines_set_updated_at
      BEFORE UPDATE ON prompt_engines
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'prompt_task_routes_set_updated_at'
  ) THEN
    CREATE TRIGGER prompt_task_routes_set_updated_at
      BEFORE UPDATE ON prompt_task_routes
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'push_tokens_set_updated_at'
  ) THEN
    CREATE TRIGGER push_tokens_set_updated_at
      BEFORE UPDATE ON push_tokens
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'push_notification_logs_set_updated_at'
  ) THEN
    CREATE TRIGGER push_notification_logs_set_updated_at
      BEFORE UPDATE ON push_notification_logs
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

CREATE OR REPLACE FUNCTION public.handle_auth_user_profile()
RETURNS TRIGGER AS $$
DECLARE
  default_name TEXT;
  default_avatar_url TEXT;
  free_credits INTEGER;
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

  SELECT initial_credits
  INTO free_credits
  FROM public.plan_settings
  WHERE plan::text = 'Free'
  LIMIT 1;

  INSERT INTO public.profiles (
    id,
    name,
    plan,
    credits,
    avatar_url
  )
  VALUES (
    NEW.id,
    default_name,
    'Free',
    COALESCE(free_credits, 0),
    default_avatar_url
  )
  ON CONFLICT (id) DO NOTHING;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'on_auth_user_created'
  ) THEN
    CREATE TRIGGER on_auth_user_created
      AFTER INSERT ON auth.users
      FOR EACH ROW
      EXECUTE FUNCTION public.handle_auth_user_profile();
  END IF;
END$$;
