-- Relax seasonal preset copy so it behaves like the existing broad presets.
-- This forward migration also updates environments where migration 034 has
-- already run. It intentionally preserves controls, sort order, and status.

UPDATE public.creation_look_presets AS preset
SET
  style = jsonb_set(
    COALESCE(preset.style, '{}'::jsonb),
    '{creative_direction}',
    to_jsonb(direction.creative_direction),
    TRUE
  ),
  updated_at = NOW()
FROM (
  VALUES
    (
      'on-model', 'on-model-v4-5', 'Gothic Editorial',
      'Dark high-fashion Halloween portrait with restrained gothic styling, dramatic rim light, and a black-to-burgundy palette. Keep the jewelry prominent while allowing natural variation in clothing, pose, framing, and setting.'
    ),
    (
      'on-model', 'on-model-v4-5', 'Autumn Golden Hour',
      'Warm, sophisticated autumn lifestyle photography with soft golden light, seasonal earth tones, and refined cold-weather styling. Vary the location, clothing, pose, and subtle seasonal details while keeping the jewelry clear and central.'
    ),
    (
      'on-model', 'on-model-v4-5', 'Christmas Tree Glow',
      'Cozy, luxurious Christmas portrait with warm ambient light, elegant festive styling, and softly blurred holiday lights. Vary the wardrobe, pose, decorations, and framing while preserving a refined seasonal mood and strong jewelry visibility.'
    ),
    (
      'on-model', 'on-model-v4-5', 'Snowy Pine Glow',
      'Elegant winter portrait among snow-dusted pines with restrained warm lights and a cool-to-warm holiday balance. Vary the foliage, winter styling, pose, snowfall, and framing while keeping snow and clothing away from the clearly visible jewelry.'
    ),
    (
      'on-model', 'on-model-v4-5', 'Midnight Glam',
      'High-fashion New Year''s Eve portrait with glamorous evening styling, editorial flash, and restrained black, gold, or silver accents. Allow variation in wardrobe, celebratory details, pose, and crop without obscuring the jewelry.'
    ),
    (
      'on-model', 'on-model-v4-5', 'Pumpkin Patch',
      'Elegant pumpkin-patch or autumn-countryside portrait at golden hour with refined seasonal styling. Include a subtle pumpkin cue, but vary the landscape, wardrobe, pose, and framing while keeping the jewelry as the focal point.'
    ),
    (
      'on-model', 'on-model-v4-5', 'Holiday Morning Cozy',
      'Cozy luxury morning at home with soft window light, relaxed refined styling, and a calm winter atmosphere. Vary the room, wardrobe, pose, and optional morning details while keeping everyday jewelry clearly visible.'
    ),
    (
      'on-model', 'on-model-v4-5', 'Festive Toast',
      'Elegant festive-toast portrait with a celebratory drink, refined evening styling, and warm or editorial holiday light. Vary the gesture, wardrobe, crop, and environment; keep the drink secondary and the jewelry unobstructed.'
    ),
    (
      'on-model', 'on-model-v4-5', 'Clean Luxury Gifting',
      'Modern minimalist gifting portrait with high-key light, soft shadows, and a clean pale or pastel palette. Vary styling, pose, framing, and subtle gifting cues while maintaining an evergreen luxury feel and clear jewelry focus.'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Gothic Velvet',
      'Dark gothic luxury product photography with rich tactile surfaces, low-key light, and restrained warm highlights. Vary the dark materials, subtle Halloween accents, arrangement, and camera angle while keeping the jewelry crisp and dominant.'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Pumpkin Harvest',
      'Elegant autumn-harvest product scene with warm light, natural textures, and a restrained pumpkin or seasonal-organic cue. Vary the surface, props, palette balance, and arrangement without covering or competing with the jewelry.'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Rustic Harvest',
      'Minimal rustic harvest photography with natural materials, warm earth tones, and sparse organic accents. Vary the surface, seasonal details, composition, and shot scale while preserving an uncluttered premium product image.'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Holiday Gift Box',
      'Luxury Christmas gifting photography with warm light, refined festive materials, and a subtle gift-opening or gift-box cue. Vary the composition, seasonal accents, surfaces, and palette; use generic packaging unless actual brand packaging is supplied as a reference.'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Confetti Flatlay',
      'Luxury New Year''s Eve product image with a dark reflective mood, metallic celebration accents, and controlled high-contrast highlights. Vary the surface, confetti placement, geometry, and arrangement while maintaining clean separation around every jewelry piece.'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Jack-o''-Lantern Glow',
      'Refined Halloween product scene with a recognizable glowing jack-o''-lantern cue and controlled warm light against a darker setting. Vary the pumpkin design, placement, surface, and composition while keeping the treatment premium and the jewelry dominant.'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Clean Luxury Gifting',
      'Modern minimalist gifting product photography with high-key light, soft shadows, and a clean pale or pastel palette. Vary the surface, composition, abstract gifting cues, and palette balance while keeping props sparse, packaging neutral, and jewelry central.'
    )
) AS direction(task_key, engine_id, name, creative_direction)
WHERE preset.task_key = direction.task_key
  AND preset.engine_id = direction.engine_id
  AND lower(preset.name) = lower(direction.name);
