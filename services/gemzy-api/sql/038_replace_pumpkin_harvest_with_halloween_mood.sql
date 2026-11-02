-- A literal pumpkin anchor made multi-look generations converge on the same
-- composition. Express Halloween through atmosphere instead, leaving literal
-- seasonal props optional and forcing the jewelry composition to carry variety.

UPDATE public.creation_look_presets
SET
  name = 'Halloween Mood',
  style = jsonb_build_object(
    'category', 'Holiday & Seasonal',
    'season', 'Halloween',
    'style_type', 'surface-light',
    'surface', 'Fabric Drape',
    'light-direction', 'Raking Side Light',
    'shadow-play', 'Long Directional',
    'color-temperature', 'Deep Contrast',
    'composition', 'Close Up',
    'creative_direction', 'Abstract luxury Halloween product photography expressed through dramatic shadow geometry, tactile dark surfaces, and a restrained palette of black, smoke, deep plum, amber, or muted orange. Literal pumpkins, carved faces, cobwebs, and novelty props are optional rather than required. Vary the jewelry orientation and position, camera angle and distance, surface folds, negative space, shadow direction, and subtle atmospheric accents while keeping the jewelry crisp and dominant.',
    'creative_exclusions', 'tomatoes, tomato vines, grocery produce still life, kitschy plastic Halloween props, cartoon decorations, fake blood, horror gore, readable text, logos, props covering the jewelry'
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) IN (lower('Pumpkin Harvest'), lower('Halloween Mood'));
