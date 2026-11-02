-- Keep Halloween Mood atmospheric. Mentioning literal props in the positive
-- direction, even as optional, can make the image model repeat them.

UPDATE public.creation_look_presets
SET
  style = jsonb_build_object(
    'category', 'Holiday & Seasonal',
    'season', 'Halloween',
    'style_type', 'surface-light',
    'surface', 'Fabric Drape',
    'light-direction', 'Raking Side Light',
    'shadow-play', 'Long Directional',
    'color-temperature', 'Deep Contrast',
    'composition', 'Close Up',
    'creative_direction', 'Abstract luxury Halloween product photography expressed only through dramatic shadow geometry, tactile dark surfaces, and a restrained palette of black, smoke, deep plum, amber, or muted orange. Use non-representational folds, pools of light, soft haze, and negative space rather than recognizable seasonal objects. Make every look a substantially different composition by changing the jewelry orientation and position, camera angle and distance, surface folds, negative-space distribution, shadow direction, and atmospheric accent while keeping the jewelry crisp and dominant.',
    'creative_exclusions', 'pumpkins, gourds, tomatoes, fruit, vegetables, grocery produce still life, recognizable Halloween props, carved faces, cobweb decorations, kitschy plastic props, cartoon decorations, fake blood, horror gore, readable text, logos, props covering the jewelry'
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) = lower('Halloween Mood');
