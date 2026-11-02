-- Keep the Pumpkin Harvest object-world preset on-theme. "Living & Fresh"
-- otherwise encourages the model to substitute visually similar produce.

UPDATE public.creation_look_presets
SET
  style = jsonb_set(
    jsonb_set(
      COALESCE(style, '{}'::jsonb),
      '{creative_direction}',
      to_jsonb(
        'Elegant autumn-harvest product photography featuring at least one clearly recognizable pumpkin or winter squash as a visible seasonal anchor. The pumpkin may vary in type, color, scale, placement, and distance, while the surface, camera angle, lighting, supporting natural textures, and composition remain free to vary. Other botanicals may appear only as secondary accents; never replace the pumpkin with another fruit or vegetable. Keep the jewelry crisp, unobstructed, and dominant.'::text
      ),
      TRUE
    ),
    '{creative_exclusions}',
    to_jsonb(
      'tomatoes, tomato vines, red tomatoes, apples, citrus fruit, peppers, generic fruit still life, non-pumpkin produce replacing the pumpkin'::text
    ),
    TRUE
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) = lower('Pumpkin Harvest');
