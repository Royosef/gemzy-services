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

CREATE TABLE IF NOT EXISTS profiles (
  id UUID PRIMARY KEY,
  name TEXT,
  plan plan_tier NOT NULL DEFAULT 'Free',
  credits INTEGER NOT NULL DEFAULT 0,
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
