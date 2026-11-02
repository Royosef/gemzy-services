-- Restore the original literal Pumpkin Harvest art direction. Keep the shared
-- batch-diversity behavior, but remove Halloween Mood's abstract scene lanes.

UPDATE public.creation_look_presets
SET
  name = 'Pumpkin Harvest',
  style = jsonb_build_object(
    'mood', 'Intimate',
    'season', 'Halloween / Autumn',
    'category', 'Holiday & Seasonal',
    'lighting', 'Soft Diffused',
    'style_type', 'object-world',
    'composition', 'Centered',
    'relationship', 'Resting On',
    'object-territory', 'Living & Fresh',
    'creative_direction', 'Create an elegant centered autumn harvest still life on one coherent dark-wood or textured-stone surface. Rest the jewelry naturally in the foreground and arrange two or three miniature orange and white pumpkins with a few dried leaves around it, leaving clean negative space around the complete product silhouette. Use warm, soft directional light that suggests late golden hour, with gentle shadows and accurate metal and gemstone color. Keep the palette pumpkin orange, cream, rust, warm brown, and gold. The result should feel premium and restrained rather than rustic or decorative, optimized for yellow gold, rings, necklaces, and warm gemstones.'
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) IN (lower('Halloween Mood'), lower('Pumpkin Harvest'));
