-- Persist user-created looks so the redesigned create flow and library can
-- restore them across sessions and devices.

CREATE TABLE IF NOT EXISTS public.saved_looks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  surface TEXT NOT NULL DEFAULT 'on-model',
  engine_id TEXT,
  style JSONB NOT NULL DEFAULT '{}'::jsonb,
  preview_url TEXT,
  preview_storage_path TEXT,
  required_plan plan_tier DEFAULT 'Pro',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS saved_looks_user_surface_updated_idx
  ON public.saved_looks (user_id, surface, updated_at DESC);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'saved_looks_set_updated_at'
  ) THEN
    CREATE TRIGGER saved_looks_set_updated_at
      BEFORE UPDATE ON public.saved_looks
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;
