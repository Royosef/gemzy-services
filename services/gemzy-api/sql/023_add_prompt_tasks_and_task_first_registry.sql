-- Add first-class prompt tasks plus task-scoped engine/version metadata.
BEGIN;

CREATE TABLE IF NOT EXISTS public.prompt_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  surface TEXT,
  parent_task_id UUID REFERENCES public.prompt_tasks(id) ON DELETE SET NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  updated_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS prompt_tasks_surface_idx
  ON public.prompt_tasks (surface, is_active);

ALTER TABLE public.prompt_engines
  ADD COLUMN IF NOT EXISTS task_id UUID,
  ADD COLUMN IF NOT EXISTS public_engine_key TEXT,
  ADD COLUMN IF NOT EXISTS is_user_selectable BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 100,
  ADD COLUMN IF NOT EXISTS active_version_id UUID;

ALTER TABLE public.prompt_engine_versions
  ADD COLUMN IF NOT EXISTS version_name TEXT,
  ADD COLUMN IF NOT EXISTS ui_definition JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.prompt_task_routes
  ADD COLUMN IF NOT EXISTS task_id UUID;

CREATE INDEX IF NOT EXISTS prompt_engines_task_id_idx
  ON public.prompt_engines (task_id, is_user_selectable, sort_order);

CREATE INDEX IF NOT EXISTS prompt_engines_public_engine_key_idx
  ON public.prompt_engines (public_engine_key);

CREATE INDEX IF NOT EXISTS prompt_engines_active_version_id_idx
  ON public.prompt_engines (active_version_id);

CREATE INDEX IF NOT EXISTS prompt_task_routes_task_id_idx
  ON public.prompt_task_routes (task_id, is_active, priority);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'prompt_engines_task_id_fkey'
  ) THEN
    ALTER TABLE public.prompt_engines
      ADD CONSTRAINT prompt_engines_task_id_fkey
      FOREIGN KEY (task_id)
      REFERENCES public.prompt_tasks(id)
      ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'prompt_engines_active_version_id_fkey'
  ) THEN
    ALTER TABLE public.prompt_engines
      ADD CONSTRAINT prompt_engines_active_version_id_fkey
      FOREIGN KEY (active_version_id)
      REFERENCES public.prompt_engine_versions(id)
      ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'prompt_task_routes_task_id_fkey'
  ) THEN
    ALTER TABLE public.prompt_task_routes
      ADD CONSTRAINT prompt_task_routes_task_id_fkey
      FOREIGN KEY (task_id)
      REFERENCES public.prompt_tasks(id)
      ON DELETE SET NULL;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'prompt_tasks_set_updated_at'
  ) THEN
    CREATE TRIGGER prompt_tasks_set_updated_at
      BEFORE UPDATE ON public.prompt_tasks
      FOR EACH ROW
      EXECUTE FUNCTION public.set_updated_at();
  END IF;
END$$;

INSERT INTO public.prompt_tasks (key, name, description, surface)
VALUES
  ('on-model', 'On Model', 'Primary on-model jewelry generation task.', 'onModel'),
  ('pure-jewelry', 'Pure Jewelry', 'Primary pure-jewelry generation task.', 'pureJewelry'),
  ('on-model/edited', 'On Model Edit', 'Edit flow for on-model generations.', 'onModel'),
  ('pure-jewelry/edited', 'Pure Jewelry Edit', 'Edit flow for pure-jewelry generations.', 'pureJewelry')
ON CONFLICT (key) DO UPDATE
SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  surface = EXCLUDED.surface;

UPDATE public.prompt_tasks AS child
SET parent_task_id = parent.id
FROM public.prompt_tasks AS parent
WHERE child.key = 'on-model/edited'
  AND parent.key = 'on-model'
  AND child.parent_task_id IS DISTINCT FROM parent.id;

UPDATE public.prompt_tasks AS child
SET parent_task_id = parent.id
FROM public.prompt_tasks AS parent
WHERE child.key = 'pure-jewelry/edited'
  AND parent.key = 'pure-jewelry'
  AND child.parent_task_id IS DISTINCT FROM parent.id;

UPDATE public.prompt_engine_versions
SET ui_definition = definition->'ui'
WHERE ui_definition = '{}'::jsonb
  AND jsonb_typeof(definition->'ui') = 'object';

UPDATE public.prompt_engine_versions
SET version_name = COALESCE(
  NULLIF(TRIM(version_name), ''),
  NULLIF(ui_definition->'selector'->>'title', ''),
  CONCAT('v', version_number::text)
)
WHERE version_name IS NULL
   OR TRIM(version_name) = '';

UPDATE public.prompt_engines
SET active_version_id = published_version_id
WHERE active_version_id IS NULL
  AND published_version_id IS NOT NULL;

UPDATE public.prompt_engines AS engine
SET
  public_engine_key = COALESCE(
    NULLIF(active_version.ui_definition->>'engineId', ''),
    NULLIF(active_version.definition->'ui'->>'engineId', ''),
    engine.public_engine_key,
    engine.slug
  ),
  is_user_selectable = CASE
    WHEN COALESCE(active_version.ui_definition->>'surface', active_version.definition->'ui'->>'surface', '') IN ('onModel', 'pureJewelry')
      AND COALESCE(
        NULLIF(active_version.ui_definition->>'engineId', ''),
        NULLIF(active_version.definition->'ui'->>'engineId', '')
      ) IS NOT NULL
    THEN TRUE
    ELSE FALSE
  END,
  sort_order = CASE
    WHEN COALESCE(
      active_version.ui_definition->'selector'->>'sortOrder',
      active_version.definition->'ui'->'selector'->>'sortOrder',
      ''
    ) ~ '^\d+$'
    THEN COALESCE(
      active_version.ui_definition->'selector'->>'sortOrder',
      active_version.definition->'ui'->'selector'->>'sortOrder'
    )::INTEGER
    ELSE sort_order
  END
FROM public.prompt_engine_versions AS active_version
WHERE active_version.id = COALESCE(engine.active_version_id, engine.published_version_id);

WITH engine_task_keys AS (
  SELECT
    engine.id,
    COALESCE(
      CASE
        WHEN engine.task_type IN ('on-model', 'pure-jewelry', 'on-model/edited', 'pure-jewelry/edited')
          THEN engine.task_type
      END,
      CASE
        WHEN LOWER(COALESCE(engine.labels->>'surface', '')) = 'on-model' THEN 'on-model'
        WHEN LOWER(COALESCE(engine.labels->>'surface', '')) = 'pure-jewelry' THEN 'pure-jewelry'
      END,
      CASE
        WHEN COALESCE(active_version.ui_definition->>'surface', active_version.definition->'ui'->>'surface', '') = 'onModel'
          THEN 'on-model'
        WHEN COALESCE(active_version.ui_definition->>'surface', active_version.definition->'ui'->>'surface', '') = 'pureJewelry'
          THEN 'pure-jewelry'
      END
    ) AS task_key
  FROM public.prompt_engines AS engine
  LEFT JOIN public.prompt_engine_versions AS active_version
    ON active_version.id = COALESCE(engine.active_version_id, engine.published_version_id)
)
UPDATE public.prompt_engines AS engine
SET task_id = task.id
FROM engine_task_keys
JOIN public.prompt_tasks AS task
  ON task.key = engine_task_keys.task_key
WHERE engine.id = engine_task_keys.id
  AND engine_task_keys.task_key IS NOT NULL
  AND engine.task_id IS DISTINCT FROM task.id;

WITH route_task_keys AS (
  SELECT
    route.id,
    COALESCE(
      CASE
        WHEN route.task_type IN ('on-model', 'pure-jewelry', 'on-model/edited', 'pure-jewelry/edited')
          THEN route.task_type
      END,
      route_engine_task.key,
      CASE
        WHEN engine.task_type IN ('on-model', 'pure-jewelry', 'on-model/edited', 'pure-jewelry/edited')
          THEN engine.task_type
      END,
      CASE
        WHEN LOWER(COALESCE(engine.labels->>'surface', '')) = 'on-model' THEN 'on-model'
        WHEN LOWER(COALESCE(engine.labels->>'surface', '')) = 'pure-jewelry' THEN 'pure-jewelry'
      END,
      CASE
        WHEN COALESCE(active_version.ui_definition->>'surface', active_version.definition->'ui'->>'surface', '') = 'onModel'
          THEN 'on-model'
        WHEN COALESCE(active_version.ui_definition->>'surface', active_version.definition->'ui'->>'surface', '') = 'pureJewelry'
          THEN 'pure-jewelry'
      END
    ) AS task_key
  FROM public.prompt_task_routes AS route
  LEFT JOIN public.prompt_engines AS engine
    ON engine.id = route.engine_id
  LEFT JOIN public.prompt_tasks AS route_engine_task
    ON route_engine_task.id = engine.task_id
  LEFT JOIN public.prompt_engine_versions AS active_version
    ON active_version.id = COALESCE(engine.active_version_id, engine.published_version_id)
)
UPDATE public.prompt_task_routes AS route
SET task_id = task.id
FROM route_task_keys
JOIN public.prompt_tasks AS task
  ON task.key = route_task_keys.task_key
WHERE route.id = route_task_keys.id
  AND route_task_keys.task_key IS NOT NULL
  AND route.task_id IS DISTINCT FROM task.id;

COMMIT;
