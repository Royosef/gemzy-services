-- Keep curated presets available to both legacy and current clients.
--
-- Migration 030 originally seeded on-model-v2. Some unreleased revisions
-- changed that historical migration to on-model-v4-5, which would make
-- environments diverge depending on when 030 ran. Copy in both directions so
-- this migration repairs either state and remains safe to rerun.

INSERT INTO public.creation_look_presets (
  task_key,
  engine_id,
  name,
  style,
  preview_url,
  preview_storage_path,
  required_plan,
  sort_order,
  is_active
)
SELECT
  task_key,
  'on-model-v4-5',
  name,
  style,
  preview_url,
  preview_storage_path,
  required_plan,
  sort_order,
  is_active
FROM public.creation_look_presets source
WHERE source.task_key = 'on-model'
  AND source.engine_id = 'on-model-v2'
  AND NOT EXISTS (
    SELECT 1
    FROM public.creation_look_presets target
    WHERE target.task_key = source.task_key
      AND target.engine_id = 'on-model-v4-5'
      AND lower(target.name) = lower(source.name)
  );

INSERT INTO public.creation_look_presets (
  task_key, engine_id, name, style, preview_url, preview_storage_path,
  required_plan, sort_order, is_active
)
SELECT
  task_key, 'on-model-v2', name, style, preview_url, preview_storage_path,
  required_plan, sort_order, is_active
FROM public.creation_look_presets source
WHERE source.task_key = 'on-model'
  AND source.engine_id = 'on-model-v4-5'
  AND NOT EXISTS (
    SELECT 1 FROM public.creation_look_presets target
    WHERE target.task_key = source.task_key
      AND target.engine_id = 'on-model-v2'
      AND lower(target.name) = lower(source.name)
  );
