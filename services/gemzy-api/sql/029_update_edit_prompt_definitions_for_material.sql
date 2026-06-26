BEGIN;

WITH target_versions AS (
  SELECT pev.id, COALESCE(pev.definition, '{}'::jsonb) AS definition
  FROM public.prompt_engine_versions AS pev
  JOIN public.prompt_engines AS pe ON pe.id = pev.engine_id
  JOIN public.prompt_tasks AS pt ON pt.id = pe.task_id
  WHERE pt.key IN ('on-model/edited', 'pure-jewelry/edited')
),
patched AS (
  SELECT
    id,
    jsonb_set(
      jsonb_set(
        definition,
        '{editOptions}',
        (
          SELECT
            COALESCE(jsonb_agg(
              CASE
                WHEN option->>'id' = 'jewelry_smaller' THEN jsonb_set(option, '{exclusiveGroup}', to_jsonb('jewelry_scale'::text), true)
                WHEN option->>'id' = 'jewelry_bigger' THEN jsonb_set(option, '{exclusiveGroup}', to_jsonb('jewelry_scale'::text), true)
                ELSE option
              END
            ), '[]'::jsonb)
            || CASE
              WHEN EXISTS (
                SELECT 1
                FROM jsonb_array_elements(COALESCE(definition->'editOptions', '[]'::jsonb)) AS existing_option
                WHERE existing_option->>'id' = 'material_aluminum'
              ) THEN '[]'::jsonb
              ELSE '[
                {"id":"material_aluminum","label":"Aluminum","description":"Change the material of jewelry","category":"jewelry","parentId":"jewelry_material","parentLabel":"Jewelry material","exclusiveGroup":"jewelry_material","prompt":"Change the jewelry material to brushed aluminum while preserving the exact design, gemstones, scale, placement, and overall composition."},
                {"id":"material_gold","label":"Gold","description":"Change the material of jewelry","category":"jewelry","parentId":"jewelry_material","parentLabel":"Jewelry material","exclusiveGroup":"jewelry_material","prompt":"Change the jewelry material to polished gold while preserving the exact design, gemstones, scale, placement, and overall composition."},
                {"id":"material_silver","label":"Silver","description":"Change the material of jewelry","category":"jewelry","parentId":"jewelry_material","parentLabel":"Jewelry material","exclusiveGroup":"jewelry_material","prompt":"Change the jewelry material to polished silver while preserving the exact design, gemstones, scale, placement, and overall composition."},
                {"id":"material_bronze","label":"Bronze","description":"Change the material of jewelry","category":"jewelry","parentId":"jewelry_material","parentLabel":"Jewelry material","exclusiveGroup":"jewelry_material","prompt":"Change the jewelry material to bronze while preserving the exact design, gemstones, scale, placement, and overall composition."}
              ]'::jsonb
            END
          FROM jsonb_array_elements(COALESCE(definition->'editOptions', '[]'::jsonb)) AS option
        ),
        true
      ),
      '{editCategories}',
      (
        SELECT COALESCE(jsonb_agg(
          CASE
            WHEN category->>'id' = 'jewelry'
             AND NOT EXISTS (
               SELECT 1
               FROM jsonb_array_elements_text(COALESCE(category->'options', '[]'::jsonb)) AS option_id
               WHERE option_id = 'jewelry_material'
             )
            THEN jsonb_set(category, '{options}', COALESCE(category->'options', '[]'::jsonb) || '["jewelry_material"]'::jsonb, true)
            ELSE category
          END
        ), '[]'::jsonb)
        FROM jsonb_array_elements(COALESCE(definition->'editCategories', '[]'::jsonb)) AS category
      ),
      true
    ) AS updated_definition
  FROM target_versions
)
UPDATE public.prompt_engine_versions AS pev
SET definition = patched.updated_definition
FROM patched
WHERE pev.id = patched.id;

COMMIT;
