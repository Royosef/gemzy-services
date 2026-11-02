-- The preset name promises a gift box. Do not allow ribbon, tissue, pouches,
-- trays, or unrelated holders to satisfy the gifting cue on their own.

UPDATE public.creation_look_presets
SET
  style = jsonb_set(
    jsonb_set(
      COALESCE(style, '{}'::jsonb),
      '{creative_direction}',
      to_jsonb('Create a premium holiday gifting image with at least one clearly recognizable open gift box or open jewelry gift box. Place the jewelry inside or naturally against the open box while keeping it fully visible and dominant. Freely vary the box style, material, color, placement, viewpoint, surface, lighting, and palette.'::text),
      TRUE
    ),
    '{creative_exclusions}',
    to_jsonb('egg holder, egg carton, food packaging, jewelry tray replacing the gift box, dish, bowl, pedestal, pouch without a visible gift box, ribbon or tissue without a visible gift box, unrelated vessel, closed box hiding the jewelry, branded packaging, floating jewelry, readable text, logos, swimming pool, poolside setting, beach resort, swimwear, water-leisure scene'::text),
    TRUE
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) = lower('Holiday Gift Box');
