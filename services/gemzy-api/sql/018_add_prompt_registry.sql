-- Add the DB-backed prompt registry used for prompt-engine management and
-- server-driven generation UI catalogs.
BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'prompt_engine_status') THEN
    CREATE TYPE public.prompt_engine_status AS ENUM ('draft', 'published', 'archived');
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS public.prompt_engines (
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
  created_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  updated_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS prompt_engines_task_type_idx
  ON public.prompt_engines (task_type);

CREATE TABLE IF NOT EXISTS public.prompt_engine_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  engine_id UUID NOT NULL REFERENCES public.prompt_engines(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL CHECK (version_number > 0),
  status public.prompt_engine_status NOT NULL DEFAULT 'draft',
  change_note TEXT,
  definition JSONB NOT NULL DEFAULT '{}'::jsonb,
  sample_input JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (engine_id, version_number)
);

CREATE INDEX IF NOT EXISTS prompt_engine_versions_engine_idx
  ON public.prompt_engine_versions (engine_id, version_number DESC);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'prompt_engines_published_version_id_fkey'
  ) THEN
    ALTER TABLE public.prompt_engines
      ADD CONSTRAINT prompt_engines_published_version_id_fkey
      FOREIGN KEY (published_version_id)
      REFERENCES public.prompt_engine_versions(id)
      ON DELETE SET NULL;
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS public.prompt_task_routes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  task_type TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  match_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
  engine_id UUID NOT NULL REFERENCES public.prompt_engines(id) ON DELETE CASCADE,
  pinned_version_id UUID REFERENCES public.prompt_engine_versions(id) ON DELETE SET NULL,
  notes TEXT,
  created_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  updated_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS prompt_task_routes_task_idx
  ON public.prompt_task_routes (task_type, is_active, priority);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'prompt_engines_set_updated_at'
  ) THEN
    CREATE TRIGGER prompt_engines_set_updated_at
      BEFORE UPDATE ON public.prompt_engines
      FOR EACH ROW
      EXECUTE FUNCTION public.set_updated_at();
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'prompt_task_routes_set_updated_at'
  ) THEN
    CREATE TRIGGER prompt_task_routes_set_updated_at
      BEFORE UPDATE ON public.prompt_task_routes
      FOR EACH ROW
      EXECUTE FUNCTION public.set_updated_at();
  END IF;
END$$;

COMMIT;
