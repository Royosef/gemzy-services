-- Clone the current user-facing on-model "Gemzy V2" engine into a separate
-- DB-managed test engine so it can be exercised through the prompt registry,
-- server-driven UI catalog, and routing system.
--
-- Important:
-- 1. Run sql/018_add_prompt_registry.sql first.
-- 2. Seed the default prompt registry before running this clone script
--    (for example by hitting /prompt-engines or /generations/ui-config once),
--    because this script copies from the seeded `on-model-v4-5` row.

BEGIN;

DO $$
BEGIN
  IF to_regclass('public.prompt_engines') IS NULL
    OR to_regclass('public.prompt_engine_versions') IS NULL
    OR to_regclass('public.prompt_task_routes') IS NULL THEN
    RAISE EXCEPTION 'Prompt registry tables are missing. Run sql/018_add_prompt_registry.sql first.';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM public.prompt_engines
    WHERE slug = 'on-model-v4-5'
      AND published_version_id IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'Source engine on-model-v4-5 was not found. Seed defaults first via /prompt-engines or /generations/ui-config.';
  END IF;
END$$;

WITH source_engine AS (
  SELECT
    e.task_type,
    e.renderer_key,
    e.input_schema,
    e.output_schema,
    e.labels,
    e.created_by,
    e.updated_by
  FROM public.prompt_engines e
  WHERE e.slug = 'on-model-v4-5'
)
INSERT INTO public.prompt_engines (
  slug,
  name,
  description,
  task_type,
  renderer_key,
  input_schema,
  output_schema,
  labels,
  published_version_id,
  created_by,
  updated_by
)
SELECT
  'on-model-gemzy-v2-db-test',
  'On-Model Gemzy V2 DB Test',
  'Server-driven clone of the current user-facing Gemzy V2 on-model engine for prompt registry and UI testing.',
  se.task_type,
  se.renderer_key,
  se.input_schema,
  se.output_schema,
  jsonb_set(
    jsonb_set(COALESCE(se.labels, '{}'::jsonb), '{version}', to_jsonb('v4.5-db-test'::text), true),
    '{variant}',
    to_jsonb('db-test'::text),
    true
  ),
  NULL,
  se.created_by,
  se.updated_by
FROM source_engine se
ON CONFLICT (slug) DO UPDATE
SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  task_type = EXCLUDED.task_type,
  renderer_key = EXCLUDED.renderer_key,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  labels = EXCLUDED.labels,
  updated_by = COALESCE(EXCLUDED.updated_by, public.prompt_engines.updated_by);

WITH source_engine AS (
  SELECT
    e.id AS source_engine_id,
    v.definition AS source_definition,
    v.sample_input AS source_sample_input,
    v.created_by AS source_version_created_by
  FROM public.prompt_engines e
  JOIN public.prompt_engine_versions v ON v.id = e.published_version_id
  WHERE e.slug = 'on-model-v4-5'
),
target_engine AS (
  SELECT id
  FROM public.prompt_engines
  WHERE slug = 'on-model-gemzy-v2-db-test'
)
INSERT INTO public.prompt_engine_versions (
  engine_id,
  version_number,
  status,
  change_note,
  definition,
  sample_input,
  created_by
)
SELECT
  te.id,
  1,
  'published'::public.prompt_engine_status,
  'SQL-seeded clone of the current Gemzy V2 on-model engine for server-driven UI testing.',
  jsonb_set(
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              jsonb_set(
                jsonb_set(
                  jsonb_set(
                    jsonb_set(
                      jsonb_set(
                        COALESCE(se.source_definition, '{}'::jsonb),
                        '{ui,engineId}',
                        to_jsonb('v2-db-test'::text),
                        true
                      ),
                      '{ui,promptVersion}',
                      to_jsonb('v4.5-db-test'::text),
                      true
                    ),
                    '{ui,trialTaskLabel}',
                    to_jsonb('On Model - V2 DB Test Presets'::text),
                    true
                  ),
                  '{ui,isDefault}',
                  'false'::jsonb,
                  true
                ),
                '{ui,selector,id}',
                to_jsonb('v2-db-test'::text),
                true
              ),
              '{ui,selector,pillLabel}',
              to_jsonb('Gemzy V2 DB'::text),
              true
            ),
            '{ui,selector,title}',
            to_jsonb('Gemzy V2 DB Test'::text),
            true
          ),
          '{ui,selector,description}',
          to_jsonb('Server-driven clone of the current Gemzy V2 engine for prompt registry and UI testing.'::text),
          true
        ),
        '{ui,selector,sortOrder}',
        '15'::jsonb,
        true
      ),
      '{ui,selector,badge}',
      'null'::jsonb,
      true
    ),
    '{ui,selector,badgeImageKey}',
    'null'::jsonb,
    true
  ),
  jsonb_set(
    COALESCE(se.source_sample_input, '{}'::jsonb),
    '{request,style,prompt_version}',
    to_jsonb('v4.5-db-test'::text),
    true
  ),
  se.source_version_created_by
FROM target_engine te
CROSS JOIN source_engine se
ON CONFLICT (engine_id, version_number) DO UPDATE
SET
  status = EXCLUDED.status,
  change_note = EXCLUDED.change_note,
  definition = EXCLUDED.definition,
  sample_input = EXCLUDED.sample_input;

UPDATE public.prompt_engines pe
SET published_version_id = pev.id
FROM public.prompt_engine_versions pev
WHERE pe.slug = 'on-model-gemzy-v2-db-test'
  AND pev.engine_id = pe.id
  AND pev.version_number = 1
  AND pe.published_version_id IS DISTINCT FROM pev.id;

INSERT INTO public.prompt_task_routes (
  slug,
  name,
  task_type,
  priority,
  is_active,
  match_rules,
  engine_id,
  pinned_version_id,
  notes,
  created_by,
  updated_by
)
SELECT
  'on-model-gemzy-v2-db-test-route',
  'On-Model Gemzy V2 DB Test',
  pe.task_type,
  35,
  TRUE,
  jsonb_build_object(
    'request.style.prompt_version',
    jsonb_build_object(
      'in',
      jsonb_build_array('v4.5-db-test', 'v45-db-test', 'gemzy-v2-db-test')
    )
  ),
  pe.id,
  pev.id,
  'Server-driven test route for the cloned Gemzy V2 on-model engine.',
  pe.created_by,
  pe.updated_by
FROM public.prompt_engines pe
JOIN public.prompt_engine_versions pev
  ON pev.engine_id = pe.id
 AND pev.version_number = 1
WHERE pe.slug = 'on-model-gemzy-v2-db-test'
ON CONFLICT (slug) DO UPDATE
SET
  name = EXCLUDED.name,
  task_type = EXCLUDED.task_type,
  priority = EXCLUDED.priority,
  is_active = EXCLUDED.is_active,
  match_rules = EXCLUDED.match_rules,
  engine_id = EXCLUDED.engine_id,
  pinned_version_id = EXCLUDED.pinned_version_id,
  notes = EXCLUDED.notes,
  updated_by = COALESCE(EXCLUDED.updated_by, public.prompt_task_routes.updated_by);

COMMIT;
