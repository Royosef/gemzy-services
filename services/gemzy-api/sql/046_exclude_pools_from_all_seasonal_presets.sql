-- Seasonal presets should not drift into resort or swimwear photography when
-- their setting is intentionally flexible. Apply the boundary to the whole
-- seasonal collection, including currently hidden presets.

UPDATE public.creation_look_presets AS preset
SET
  style = CASE
    WHEN lower(COALESCE(preset.style->>'creative_exclusions', '')) LIKE '%swimming pool%'
      THEN preset.style
    ELSE jsonb_set(
      COALESCE(preset.style, '{}'::jsonb),
      '{creative_exclusions}',
      to_jsonb(
        concat_ws(
          ', ',
          NULLIF(preset.style->>'creative_exclusions', ''),
          'swimming pool, poolside setting, beach resort, swimwear, water-leisure scene'
        )
      ),
      TRUE
    )
  END,
  updated_at = NOW()
FROM (
  VALUES
    ('on-model', 'on-model-v4-5', 'Gothic Editorial'),
    ('on-model', 'on-model-v4-5', 'Autumn Golden Hour'),
    ('on-model', 'on-model-v4-5', 'Christmas Tree Glow'),
    ('on-model', 'on-model-v4-5', 'Snowy Pine Glow'),
    ('on-model', 'on-model-v4-5', 'Midnight Glam'),
    ('on-model', 'on-model-v4-5', 'Pumpkin Patch'),
    ('on-model', 'on-model-v4-5', 'Holiday Morning Cozy'),
    ('on-model', 'on-model-v4-5', 'Festive Toast'),
    ('on-model', 'on-model-v4-5', 'Clean Luxury Gifting'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Gothic Velvet'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Pumpkin Harvest'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Rustic Harvest'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Holiday Gift Box'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Confetti Flatlay'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Jack-o''-Lantern Glow'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Clean Luxury Gifting')
) AS seasonal(task_key, engine_id, name)
WHERE preset.task_key = seasonal.task_key
  AND preset.engine_id = seasonal.engine_id
  AND lower(preset.name) = lower(seasonal.name);
