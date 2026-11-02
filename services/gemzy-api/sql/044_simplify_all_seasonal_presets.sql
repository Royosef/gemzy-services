-- Make every preset introduced by the seasonal collection a broad creative
-- direction rather than a prescribed photograph. Older presets are untouched.

UPDATE public.creation_look_presets AS preset
SET style = update_row.style, updated_at = NOW()
FROM (
  VALUES
    ('on-model', 'on-model-v4-5', 'Gothic Editorial', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Halloween',
      'image_style', 'Moody Dark',
      'creative_direction', 'Create a refined gothic fashion portrait with a dark Halloween mood. Keep the jewelry clear and prominent; freely vary the setting, styling, pose, crop, lighting, and palette.',
      'creative_exclusions', 'costume-store styling, horror gore, jewelry obscured by hair or clothing, readable text, logos'
    )),
    ('on-model', 'on-model-v4-5', 'Autumn Golden Hour', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Autumn / Thanksgiving',
      'image_style', 'Golden Hour',
      'creative_direction', 'Create a sophisticated autumn lifestyle portrait with a warm seasonal atmosphere. Keep the jewelry clear; freely vary the location, wardrobe, pose, weather, framing, lighting, and palette.',
      'creative_exclusions', 'jewelry obscured by clothing or props, heavy orange color cast, readable text, logos'
    )),
    ('on-model', 'on-model-v4-5', 'Christmas Tree Glow', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas',
      'background', 'Evening Glow',
      'creative_direction', 'Create a refined Christmas portrait with a recognizable decorated tree somewhere in the scene. Keep the jewelry clear; vary the setting, tree, styling, pose, crop, lighting, and palette.',
      'creative_exclusions', 'generic houseplant replacing the Christmas tree, jewelry obscured by hair or clothing, readable text, logos'
    )),
    ('on-model', 'on-model-v4-5', 'Snowy Pine Glow', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas / Winter',
      'background', 'Forest Shade',
      'creative_direction', 'Create an elegant winter portrait with recognizable snow-dusted evergreen scenery. Keep the jewelry clear; vary the location, foliage, styling, pose, snowfall, framing, lighting, and palette.',
      'creative_exclusions', 'tropical foliage, snow or branches covering the jewelry, readable text, logos'
    )),
    ('on-model', 'on-model-v4-5', 'Midnight Glam', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'New Year''s Eve',
      'image_style', 'High Contrast',
      'creative_direction', 'Create a glamorous New Year portrait with a subtle celebratory atmosphere. Keep the jewelry clear; freely vary the setting, styling, pose, crop, lighting, palette, and optional accents.',
      'creative_exclusions', 'confetti covering the face or jewelry, oversized drink props, readable text, logos'
    )),
    ('on-model', 'on-model-v4-5', 'Pumpkin Patch', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Autumn / Halloween',
      'image_style', 'Golden Hour',
      'creative_direction', 'Create an elegant autumn portrait in a pumpkin patch or harvest landscape. Keep the jewelry prominent; vary the location, pumpkin type, styling, pose, camera distance, framing, and light.',
      'creative_exclusions', 'tomatoes or substitute produce, desert landscape, pumpkins covering the jewelry, readable text, logos'
    )),
    ('on-model', 'on-model-v4-5', 'Holiday Morning Cozy', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas / Winter',
      'background', 'Warm Interior',
      'creative_direction', 'Create a relaxed luxury winter-holiday morning portrait. Keep the jewelry clear; vary the room, seasonal cue, wardrobe, pose, crop, activity, and natural lighting.',
      'creative_exclusions', 'branded packaging, oversized props, jewelry obscured by clothing or objects, readable text, logos'
    )),
    ('on-model', 'on-model-v4-5', 'Festive Toast', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas / New Year''s Eve',
      'background', 'Evening Glow',
      'creative_direction', 'Create an elegant festive portrait with a celebratory drink as a secondary cue. Keep the jewelry clear; vary the setting, vessel, gesture, wardrobe, crop, lighting, and palette.',
      'creative_exclusions', 'drink covering the jewelry, spills on jewelry, readable labels, logos'
    )),
    ('on-model', 'on-model-v4-5', 'Clean Luxury Gifting', jsonb_build_object(
      'category', 'Evergreen', 'season', 'Evergreen gifting',
      'background', 'White Studio',
      'creative_direction', 'Create a modern minimalist gifting portrait with a subtle neutral gift cue. Keep the jewelry prominent; vary the cue, styling, pose, framing, lighting, and pale color palette.',
      'creative_exclusions', 'branded packaging, shipping cartons, oversized gift props, jewelry obscured by packaging, readable text, logos'
    )),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Gothic Velvet', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Halloween',
      'style_type', 'pure-studio', 'surface', 'Velvet',
      'creative_direction', 'Create a premium dark gothic jewelry image. Keep the jewelry grounded, crisp, and dominant; freely vary the arrangement, viewpoint, surface treatment, lighting, shadows, palette, and subtle Halloween accents.',
      'creative_exclusions', 'floating jewelry, costume-store props, horror gore, props covering jewelry, readable text, logos'
    )),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Pumpkin Harvest', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Halloween / Autumn',
      'style_type', 'object-world', 'relationship', 'Resting On',
      'creative_direction', 'Create a premium autumn jewelry scene using pumpkins as the seasonal accent. Keep the jewelry naturally supported, fully visible, and dominant; freely vary the composition, viewpoint, pumpkin placement, surface, lighting, and palette.',
      'creative_exclusions', 'tomatoes, substitute fruit or vegetables, grocery produce display, floating or unsupported jewelry, props covering jewelry, readable text, logos'
    )),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Rustic Harvest', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Autumn / Thanksgiving',
      'style_type', 'surface-light', 'surface', 'Wood Grain',
      'creative_direction', 'Create a minimal premium harvest jewelry image with a restrained natural autumn cue. Keep the jewelry grounded and dominant; vary the cue, arrangement, viewpoint, surface, lighting, and palette.',
      'creative_exclusions', 'grocery still life, fresh tomatoes, dense prop clutter, floating jewelry, props covering jewelry, readable text, logos'
    )),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Holiday Gift Box', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Christmas',
      'style_type', 'object-world', 'relationship', 'Inside',
      'creative_direction', 'Create a premium holiday gifting image with a recognizable jewelry box, gift box, pouch, ribbon, or tissue detail. Keep the jewelry visible and dominant; vary the gifting cue, arrangement, viewpoint, surface, lighting, and palette.',
      'creative_exclusions', 'unrelated vessel replacing the gift cue, branded packaging, closed box hiding jewelry, floating jewelry, readable text, logos'
    )),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Confetti Flatlay', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'New Year''s Eve',
      'style_type', 'arranged', 'arrangement-style', 'Organic Scatter',
      'creative_direction', 'Create a premium New Year jewelry image with sparse metallic paper confetti as the celebratory cue. Keep every piece clear and dominant; vary the arrangement, viewpoint, surface, lighting, palette, and confetti treatment.',
      'creative_exclusions', 'glitter coating jewelry, confetti covering gemstones, balloons dominating the frame, floating jewelry, invented jewelry, readable text, logos'
    )),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Jack-o''-Lantern Glow', jsonb_build_object(
      'category', 'Holiday & Seasonal', 'season', 'Halloween',
      'style_type', 'object-world', 'relationship', 'Resting On',
      'creative_direction', 'Create a premium Halloween jewelry image with a recognizable glowing jack-o-lantern cue. Keep the jewelry supported and dominant; vary the carving, pumpkin, placement, viewpoint, surface, lighting, and palette.',
      'creative_exclusions', 'tomatoes or substitute produce, plastic cartoon pumpkins, jewelry inside carved openings, floating jewelry, readable text, logos'
    )),
    ('pure-jewelry', 'pure-jewelry-v5-2', 'Clean Luxury Gifting', jsonb_build_object(
      'category', 'Evergreen', 'season', 'Evergreen gifting',
      'style_type', 'pure-studio', 'scene', 'Warm Ivory',
      'creative_direction', 'Create a modern minimalist gifting image with a subtle neutral gift cue. Keep the jewelry grounded and dominant; vary the cue, arrangement, viewpoint, surface, lighting, negative space, and pale palette.',
      'creative_exclusions', 'branded packaging, shipping cartons, oversized gift props, floating jewelry, packaging covering jewelry, readable text, logos'
    ))
) AS update_row(task_key, engine_id, name, style)
WHERE preset.task_key = update_row.task_key
  AND preset.engine_id = update_row.engine_id
  AND lower(preset.name) = lower(update_row.name);
