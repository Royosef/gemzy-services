-- Keep Pumpkin Harvest recognizable without prescribing the whole photograph.
-- The shared diversity lanes can then vary framing, layout, light, and setting.

UPDATE public.creation_look_presets
SET
  style = jsonb_build_object(
    'category', 'Holiday & Seasonal',
    'season', 'Halloween / Autumn',
    'style_type', 'object-world',
    'relationship', 'Resting On',
    'creative_direction', 'Create a premium autumn jewelry scene using pumpkins as the seasonal accent. Keep the jewelry naturally supported, fully visible, and visually dominant. Freely vary the composition, viewpoint, pumpkin placement, surface, lighting, and color treatment between images.',
    'creative_exclusions', 'tomatoes, tomato vines, substitute fruit or vegetables, grocery produce display, floating jewelry, unsupported upright jewelry, props covering the jewelry'
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) = lower('Pumpkin Harvest');
