-- "Gift box" can be interpreted as a box containing toys. Anchor the object to
-- small luxury jewelry packaging and make the uploaded jewelry its only content.

UPDATE public.creation_look_presets
SET
  style = jsonb_set(
    jsonb_set(
      COALESCE(style, '{}'::jsonb),
      '{creative_direction}',
      to_jsonb('Create a premium holiday image with at least one clearly recognizable small luxury jewelry presentation box, open and scaled appropriately for the jewelry. The uploaded jewelry is the only item inside or against the box and remains fully visible and dominant. Freely vary the box shape, material, color, placement, viewpoint, surface, lighting, and palette.'::text),
      TRUE
    ),
    '{creative_exclusions}',
    to_jsonb('toy box, toy chest, toys, dolls, children''s gifts, children''s packaging, treasure chest, storage box, lunchbox, shipping carton, unrelated objects inside the box, egg holder, egg carton, food packaging, jewelry tray replacing the box, dish, bowl, pedestal, pouch without a visible jewelry box, ribbon or tissue without a visible jewelry box, closed box hiding the jewelry, branded packaging, floating jewelry, readable text, logos, swimming pool, poolside setting, beach resort, swimwear, water-leisure scene'::text),
    TRUE
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) = lower('Holiday Gift Box');
