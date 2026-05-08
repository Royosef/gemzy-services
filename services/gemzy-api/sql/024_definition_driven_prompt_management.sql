-- Hard-cut prompt management to definition-driven versions and engine/task display metadata.
BEGIN;

ALTER TABLE public.prompt_tasks
  ADD COLUMN IF NOT EXISTS display_defaults JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.prompt_engines
  ADD COLUMN IF NOT EXISTS selector_pill_label TEXT,
  ADD COLUMN IF NOT EXISTS selector_title TEXT,
  ADD COLUMN IF NOT EXISTS selector_description TEXT,
  ADD COLUMN IF NOT EXISTS selector_badge TEXT,
  ADD COLUMN IF NOT EXISTS selector_image_key TEXT,
  ADD COLUMN IF NOT EXISTS selector_badge_image_key TEXT;

ALTER TABLE public.prompt_engine_versions
  ADD COLUMN IF NOT EXISTS public_version_key TEXT;

UPDATE public.prompt_engine_versions
SET version_name = COALESCE(
  NULLIF(TRIM(version_name), ''),
  NULLIF(ui_definition->'selector'->>'title', ''),
  NULLIF(definition->'ui'->'selector'->>'title', ''),
  CONCAT('v', version_number::text)
)
WHERE version_name IS NULL
   OR TRIM(version_name) = '';

UPDATE public.prompt_engine_versions
SET public_version_key = COALESCE(
  NULLIF(TRIM(public_version_key), ''),
  NULLIF(TRIM(definition->>'publicVersionKey'), ''),
  NULLIF(TRIM(ui_definition->>'promptVersion'), ''),
  NULLIF(TRIM(definition->'ui'->>'promptVersion'), ''),
  CONCAT('v', version_number::text)
)
WHERE public_version_key IS NULL
   OR TRIM(public_version_key) = '';

UPDATE public.prompt_engines
SET active_version_id = published_version_id
WHERE active_version_id IS NULL
  AND published_version_id IS NOT NULL;

UPDATE public.prompt_engines AS engine
SET
  public_engine_key = COALESCE(
    NULLIF(TRIM(engine.public_engine_key), ''),
    NULLIF(TRIM(active_version.ui_definition->>'engineId'), ''),
    NULLIF(TRIM(active_version.definition->'ui'->>'engineId'), ''),
    engine.slug
  ),
  selector_pill_label = COALESCE(
    NULLIF(TRIM(engine.selector_pill_label), ''),
    NULLIF(TRIM(active_version.ui_definition->'selector'->>'pillLabel'), ''),
    NULLIF(TRIM(active_version.definition->'ui'->'selector'->>'pillLabel'), ''),
    NULLIF(TRIM(active_version.ui_definition->'selector'->>'title'), ''),
    NULLIF(TRIM(active_version.definition->'ui'->'selector'->>'title'), ''),
    engine.name
  ),
  selector_title = COALESCE(
    NULLIF(TRIM(engine.selector_title), ''),
    NULLIF(TRIM(active_version.ui_definition->'selector'->>'title'), ''),
    NULLIF(TRIM(active_version.definition->'ui'->'selector'->>'title'), ''),
    NULLIF(TRIM(active_version.ui_definition->'selector'->>'pillLabel'), ''),
    NULLIF(TRIM(active_version.definition->'ui'->'selector'->>'pillLabel'), ''),
    engine.name
  ),
  selector_description = COALESCE(
    NULLIF(TRIM(engine.selector_description), ''),
    NULLIF(TRIM(active_version.ui_definition->'selector'->>'description'), ''),
    NULLIF(TRIM(active_version.definition->'ui'->'selector'->>'description'), ''),
    engine.description
  ),
  selector_badge = COALESCE(
    NULLIF(TRIM(engine.selector_badge), ''),
    NULLIF(TRIM(active_version.ui_definition->'selector'->>'badge'), ''),
    NULLIF(TRIM(active_version.definition->'ui'->'selector'->>'badge'), '')
  ),
  selector_image_key = COALESCE(
    NULLIF(TRIM(engine.selector_image_key), ''),
    NULLIF(TRIM(active_version.ui_definition->'selector'->>'imageKey'), ''),
    NULLIF(TRIM(active_version.definition->'ui'->'selector'->>'imageKey'), '')
  ),
  selector_badge_image_key = COALESCE(
    NULLIF(TRIM(engine.selector_badge_image_key), ''),
    NULLIF(TRIM(active_version.ui_definition->'selector'->>'badgeImageKey'), ''),
    NULLIF(TRIM(active_version.definition->'ui'->'selector'->>'badgeImageKey'), '')
  ),
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
    ELSE engine.sort_order
  END,
  is_user_selectable = CASE
    WHEN (SELECT surface FROM public.prompt_tasks WHERE id = engine.task_id) IN ('onModel', 'pureJewelry') AND COALESCE(
      NULLIF(TRIM(engine.public_engine_key), ''),
      NULLIF(TRIM(active_version.ui_definition->>'engineId'), ''),
      NULLIF(TRIM(active_version.definition->'ui'->>'engineId'), '')
    ) IS NOT NULL
    THEN TRUE
    ELSE engine.is_user_selectable
  END
FROM public.prompt_engine_versions AS active_version
WHERE active_version.id = COALESCE(engine.active_version_id, engine.published_version_id);

UPDATE public.prompt_engine_versions
SET definition = (definition - 'ui') - 'publicVersionKey'
WHERE definition ? 'ui'
   OR definition ? 'publicVersionKey';

ALTER TABLE public.prompt_engine_versions
  ALTER COLUMN public_version_key SET NOT NULL;

ALTER TABLE public.prompt_engine_versions
  DROP COLUMN IF EXISTS ui_definition;

COMMIT;
