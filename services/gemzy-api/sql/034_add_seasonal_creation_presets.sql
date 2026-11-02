-- Curated seasonal and holiday photography presets.
--
-- The structured fields select the closest editable engine controls. The
-- creative_direction field carries a flexible thematic guardrail through the app
-- and is appended by the prompt renderer after the standard fidelity rules.

INSERT INTO public.creation_look_presets (
  task_key, engine_id, name, style, required_plan, sort_order, is_active
)
VALUES
  (
    'on-model', 'on-model-v4-5', 'Gothic Editorial',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Halloween',
      'background', 'Dark Studio', 'emotion', 'Mysterious',
      'hair', 'Slicked Back', 'outfit', 'Evening Wear',
      'pose', 'Side Profile', 'lighting', 'Backlit',
      'camera', 'Beauty Close-Up', 'image_style', 'Moody Dark',
      'creative_direction', 'Dark high-fashion Halloween portrait with restrained gothic styling, dramatic rim light, and a black-to-burgundy palette. Keep the jewelry prominent while allowing natural variation in clothing, pose, framing, and setting.'
    ), 'Free'::plan_tier, 100, FALSE
  ),
  (
    'on-model', 'on-model-v4-5', 'Autumn Golden Hour',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Autumn / Thanksgiving',
      'background', 'Warm Interior', 'emotion', 'Soft Warmth',
      'hair', 'Natural', 'outfit', 'Quiet Luxury',
      'pose', 'Candid', 'lighting', 'Scene Light',
      'camera', 'Portrait', 'image_style', 'Golden Hour',
      'creative_direction', 'Warm, sophisticated autumn lifestyle photography with soft golden light, seasonal earth tones, and refined cold-weather styling. Vary the location, clothing, pose, and subtle seasonal details while keeping the jewelry clear and central.'
    ), 'Free'::plan_tier, 110, TRUE
  ),
  (
    'on-model', 'on-model-v4-5', 'Christmas Tree Glow',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas',
      'background', 'Evening Glow', 'emotion', 'Soft Warmth',
      'hair', 'Behind Ear', 'outfit', 'Evening Wear',
      'pose', 'At Rest', 'lighting', 'Soft Wrap',
      'camera', 'Beauty Close-Up', 'image_style', 'Warm Film',
      'creative_direction', 'Cozy, luxurious Christmas portrait with warm ambient light, elegant festive styling, and softly blurred holiday lights. Vary the wardrobe, pose, decorations, and framing while preserving a refined seasonal mood and strong jewelry visibility.'
    ), 'Free'::plan_tier, 120, TRUE
  ),
  (
    'on-model', 'on-model-v4-5', 'Snowy Pine Glow',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas / Winter',
      'background', 'Forest Shade', 'emotion', 'Soft Warmth',
      'hair', 'Behind Ear', 'outfit', 'Quiet Luxury',
      'pose', 'At Rest', 'lighting', 'Scene Light',
      'camera', 'Portrait', 'image_style', 'Warm Film',
      'creative_direction', 'Elegant winter portrait among snow-dusted pines with restrained warm lights and a cool-to-warm holiday balance. Vary the foliage, winter styling, pose, snowfall, and framing while keeping snow and clothing away from the clearly visible jewelry.'
    ), 'Free'::plan_tier, 125, TRUE
  ),
  (
    'on-model', 'on-model-v4-5', 'Midnight Glam',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'New Year''s Eve',
      'background', 'Dark Studio', 'emotion', 'Bold Presence',
      'hair', 'Slicked Back', 'outfit', 'Evening Wear',
      'pose', 'Power Stance', 'lighting', 'Hard Directional',
      'camera', 'Three Quarter', 'image_style', 'High Contrast',
      'creative_direction', 'High-fashion New Year''s Eve portrait with glamorous evening styling, editorial flash, and restrained black, gold, or silver accents. Allow variation in wardrobe, celebratory details, pose, and crop without obscuring the jewelry.'
    ), 'Free'::plan_tier, 130, TRUE
  ),
  (
    'on-model', 'on-model-v4-5', 'Pumpkin Patch',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Autumn / Halloween',
      'parent_preset', 'Autumn Golden Hour',
      'background', 'Desert Light', 'emotion', 'Ease',
      'hair', 'Natural', 'outfit', 'Quiet Luxury',
      'pose', 'Lost in Thought', 'lighting', 'Backlit',
      'camera', 'Film', 'image_style', 'Golden Hour',
      'creative_direction', 'Elegant pumpkin-patch or autumn-countryside portrait at golden hour with refined seasonal styling. Include a subtle pumpkin cue, but vary the landscape, wardrobe, pose, and framing while keeping the jewelry as the focal point.'
    ), 'Free'::plan_tier, 140, FALSE
  ),
  (
    'on-model', 'on-model-v4-5', 'Holiday Morning Cozy',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas / Winter',
      'parent_preset', 'Christmas Tree Glow',
      'background', 'Warm Interior', 'emotion', 'Ease',
      'hair', 'Natural', 'outfit', 'Quiet Luxury',
      'pose', 'At Rest', 'lighting', 'Scene Light',
      'camera', 'Portrait', 'image_style', 'Bright Airy',
      'creative_direction', 'Cozy luxury morning at home with soft window light, relaxed refined styling, and a calm winter atmosphere. Vary the room, wardrobe, pose, and optional morning details while keeping everyday jewelry clearly visible.'
    ), 'Free'::plan_tier, 150, FALSE
  ),
  (
    'on-model', 'on-model-v4-5', 'Festive Toast',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas / New Year''s Eve',
      'parent_preset', 'Midnight Glam / Christmas Tree Glow',
      'background', 'Evening Glow', 'emotion', 'Joyful',
      'hair', 'Behind Ear', 'outfit', 'Evening Wear',
      'pose', 'Self Touch', 'lighting', 'Accent Light',
      'camera', 'Beauty Close-Up', 'image_style', 'Cinematic',
      'creative_direction', 'Elegant festive-toast portrait with a celebratory drink, refined evening styling, and warm or editorial holiday light. Vary the gesture, wardrobe, crop, and environment; keep the drink secondary and the jewelry unobstructed.'
    ), 'Free'::plan_tier, 160, FALSE
  ),
  (
    'on-model', 'on-model-v4-5', 'Clean Luxury Gifting',
    jsonb_build_object(
      'category', 'Evergreen', 'season', 'Evergreen gifting',
      'background', 'White Studio', 'emotion', 'Calm Confidence',
      'hair', 'Natural', 'outfit', 'Quiet Luxury',
      'pose', 'Turn', 'lighting', 'Soft Wrap',
      'camera', 'Three Quarter', 'image_style', 'Bright Airy',
      'creative_direction', 'Modern minimalist gifting portrait with high-key light, soft shadows, and a clean pale or pastel palette. Vary styling, pose, framing, and subtle gifting cues while maintaining an evergreen luxury feel and clear jewelry focus.'
    ), 'Free'::plan_tier, 170, FALSE
  ),
  (
    'pure-jewelry', 'pure-jewelry-v5-2', 'Gothic Velvet',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Halloween',
      'style_type', 'pure-studio', 'scene', 'Deep Black',
      'surface', 'Velvet', 'lighting', 'Side Rim',
      'shadow', 'Dramatic', 'composition', 'Close Up',
      'creative_direction', 'Dark gothic luxury product photography with rich tactile surfaces, low-key light, and restrained warm highlights. Vary the dark materials, subtle Halloween accents, arrangement, and camera angle while keeping the jewelry crisp and dominant.'
    ), 'Free'::plan_tier, 200, TRUE
  ),
  (
    'pure-jewelry', 'pure-jewelry-v5-2', 'Pumpkin Harvest',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Halloween / Autumn',
      'style_type', 'object-world', 'object-territory', 'Living & Fresh',
      'relationship', 'Resting On', 'lighting', 'Soft Diffused',
      'mood', 'Intimate', 'composition', 'Centered',
      'creative_direction', 'Elegant autumn-harvest product scene with warm light, natural textures, and a restrained pumpkin or seasonal-organic cue. Vary the surface, props, palette balance, and arrangement without covering or competing with the jewelry.'
    ), 'Free'::plan_tier, 210, TRUE
  ),
  (
    'pure-jewelry', 'pure-jewelry-v5-2', 'Rustic Harvest',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Autumn / Thanksgiving',
      'style_type', 'surface-light', 'surface', 'Wood Grain',
      'light-direction', 'Golden Hour', 'shadow-play', 'Leaf & Nature Shadow',
      'color-temperature', 'Warm Gold', 'composition', 'Flat Lay',
      'creative_direction', 'Minimal rustic harvest photography with natural materials, warm earth tones, and sparse organic accents. Vary the surface, seasonal details, composition, and shot scale while preserving an uncluttered premium product image.'
    ), 'Free'::plan_tier, 220, FALSE
  ),
  (
    'pure-jewelry', 'pure-jewelry-v5-2', 'Holiday Gift Box',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas',
      'style_type', 'object-world', 'object-territory', 'Luxury Objects',
      'relationship', 'Inside', 'lighting', 'Soft Diffused',
      'mood', 'Intimate', 'composition', 'Close Up',
      'creative_direction', 'Luxury Christmas gifting photography with warm light, refined festive materials, and a subtle gift-opening or gift-box cue. Vary the composition, seasonal accents, surfaces, and palette; use generic packaging unless actual brand packaging is supplied as a reference.'
    ), 'Free'::plan_tier, 230, TRUE
  ),
  (
    'pure-jewelry', 'pure-jewelry-v5-2', 'Confetti Flatlay',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'New Year''s Eve',
      'style_type', 'arranged', 'arrangement-style', 'Organic Scatter',
      'surface', 'Deep Black', 'lighting', 'Hard Directional',
      'quantity', 'Small Collection', 'color-palette', 'Rich & Dark',
      'composition', 'Flat Lay',
      'creative_direction', 'Luxury New Year''s Eve product image with a dark reflective mood, metallic celebration accents, and controlled high-contrast highlights. Vary the surface, confetti placement, geometry, and arrangement while maintaining clean separation around every jewelry piece.'
    ), 'Free'::plan_tier, 240, TRUE
  ),
  (
    'pure-jewelry', 'pure-jewelry-v5-2', 'Jack-o''-Lantern Glow',
    jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Halloween',
      'parent_preset', 'Pumpkin Harvest',
      'style_type', 'object-world', 'object-territory', 'Living & Fresh',
      'relationship', 'Resting On', 'lighting', 'Side Rim',
      'mood', 'Playful', 'composition', 'Close Up',
      'creative_direction', 'Refined Halloween product scene with a recognizable glowing jack-o''-lantern cue and controlled warm light against a darker setting. Vary the pumpkin design, placement, surface, and composition while keeping the treatment premium and the jewelry dominant.'
    ), 'Free'::plan_tier, 250, FALSE
  ),
  (
    'pure-jewelry', 'pure-jewelry-v5-2', 'Clean Luxury Gifting',
    jsonb_build_object(
      'category', 'Evergreen', 'season', 'Evergreen gifting',
      'style_type', 'pure-studio', 'scene', 'Warm Ivory',
      'surface', 'Studio Seamless', 'lighting', 'Soft Diffused',
      'shadow', 'Soft', 'composition', 'Centered',
      'creative_direction', 'Modern minimalist gifting product photography with high-key light, soft shadows, and a clean pale or pastel palette. Vary the surface, composition, abstract gifting cues, and palette balance while keeping props sparse, packaging neutral, and jewelry central.'
    ), 'Free'::plan_tier, 260, FALSE
  )
ON CONFLICT (task_key, engine_id, (lower(name)))
DO UPDATE SET
  style = EXCLUDED.style,
  required_plan = EXCLUDED.required_plan,
  sort_order = EXCLUDED.sort_order,
  is_active = EXCLUDED.is_active;
