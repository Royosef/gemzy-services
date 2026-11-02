-- Midnight Glam needs an environmental boundary without prescribing the full
-- photograph. Prevent lifestyle/resort interpretations such as pool scenes.

UPDATE public.creation_look_presets
SET
  style = jsonb_set(
    jsonb_set(
      jsonb_set(
        COALESCE(style, '{}'::jsonb),
        '{background}',
        to_jsonb('Dark Studio'::text),
        TRUE
      ),
      '{creative_direction}',
      to_jsonb('Create a glamorous New Year evening fashion portrait in a dry studio, party, or refined urban-interior setting. Keep the jewelry clear; vary the styling, pose, crop, lighting, palette, and subtle celebratory accents.'::text),
      TRUE
    ),
    '{creative_exclusions}',
    to_jsonb('swimming pool, poolside setting, water, beach, seaside, resort, swimwear, daytime leisure scene, confetti covering the face or jewelry, oversized drink props, readable text, logos'::text),
    TRUE
  ),
  updated_at = NOW()
WHERE task_key = 'on-model'
  AND engine_id = 'on-model-v4-5'
  AND lower(name) = lower('Midnight Glam');
