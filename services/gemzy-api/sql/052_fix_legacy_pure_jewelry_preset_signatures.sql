-- Older clients send slug IDs for Pure Jewelry controls and discard values
-- that do not exist in the active engine definition. Use valid, unique
-- object-world controls while retaining server-owned creative directions.

UPDATE public.creation_look_presets AS preset
SET style = preset.style || signature.controls, updated_at = NOW()
FROM (
  VALUES
    (
      'Pumpkin Harvest',
      '{"style_type":"object-world","object-territory":"Open","relationship":"Resting On"}'::jsonb
    ),
    (
      'Holiday Gift Box',
      '{"style_type":"object-world","object-territory":"Luxury Objects","relationship":"Inside"}'::jsonb
    )
) AS signature(name, controls)
WHERE preset.task_key = 'pure-jewelry'
  AND preset.engine_id = 'pure-jewelry-v5-2'
  AND lower(preset.name) = lower(signature.name)
  AND preset.is_active = TRUE;
