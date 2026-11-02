-- Permanently remove seasonal concepts that were merged or dropped from the
-- product. The is_active guard protects any preset that may have been restored.

DELETE FROM public.creation_look_presets AS preset
USING (
  VALUES
    ('on-model', 'on-model-v4-5', 'Gothic Editorial'),
    ('on-model', 'on-model-v4-5', 'Pumpkin Patch'),
    ('on-model', 'on-model-v4-5', 'Holiday Morning Cozy'),
    ('on-model', 'on-model-v4-5', 'Festive Toast'),
    ('on-model', 'on-model-v4-5', 'Clean Luxury Gifting'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Rustic Harvest'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Jack-o''-Lantern Glow'),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Clean Luxury Gifting')
) AS removed(task_key, engine_id, name)
WHERE preset.task_key = removed.task_key
  AND preset.engine_id = removed.engine_id
  AND lower(preset.name) = lower(removed.name)
  AND preset.is_active = FALSE;
