-- Clients predating presetId preserve only recognized structured controls.
-- Give every active seasonal preset a conservative unique signature so the API
-- can restore server-owned prompt fields without a mobile release.

UPDATE public.creation_look_presets AS preset
SET style = preset.style || signature.controls, updated_at = NOW()
FROM (
  VALUES
    ('on-model', 'on-model-v4-5', 'Autumn Golden Hour', '{"background":"Warm Interior","image_style":"Golden Hour"}'::jsonb),
    ('on-model', 'on-model-v4-5', 'Christmas Tree Glow', '{"background":"Evening Glow","lighting":"Soft Wrap"}'::jsonb),
    ('on-model', 'on-model-v4-5', 'Snowy Pine Glow', '{"background":"Forest Shade","lighting":"Scene Light"}'::jsonb),
    ('on-model', 'on-model-v4-5', 'Midnight Glam', '{"background":"Dark Studio","image_style":"High Contrast"}'::jsonb),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Gothic Velvet', '{"style_type":"pure-studio","surface":"Velvet"}'::jsonb),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Pumpkin Harvest', '{"style_type":"object-world","object-territory":"Pumpkin Accents"}'::jsonb),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Holiday Gift Box', '{"style_type":"object-world","object-territory":"Jewelry Presentation Box"}'::jsonb),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Confetti Flatlay', '{"style_type":"arranged","arrangement-style":"Organic Scatter","color-palette":"Rich & Dark"}'::jsonb)
) AS signature(task_key, engine_id, name, controls)
WHERE preset.task_key = signature.task_key
  AND preset.engine_id = signature.engine_id
  AND lower(preset.name) = lower(signature.name)
  AND preset.is_active = TRUE;
