-- Keep named seasonal presets recognizable without freezing their composition.
-- Broad engine controls remain editable; these server-owned directions require
-- only the defining anchor and exclude the most likely wrong substitutions.

UPDATE public.creation_look_presets AS preset
SET
  style = jsonb_set(
    jsonb_set(
      COALESCE(preset.style, '{}'::jsonb),
      '{creative_direction}',
      to_jsonb(anchor.creative_direction),
      TRUE
    ),
    '{creative_exclusions}',
    to_jsonb(anchor.creative_exclusions),
    TRUE
  ),
  updated_at = NOW()
FROM (
  VALUES
    (
      'on-model', 'on-model-v4-5', 'Christmas Tree Glow',
      'Refined Christmas portrait with at least part of a recognizable decorated evergreen Christmas tree visible in the background or near-background, carrying warm holiday lights. Vary the room, tree species, decoration palette, wardrobe, pose, camera distance, subject placement, and crop while preserving strong jewelry visibility. The tree is the seasonal anchor; isolated bokeh or an unrelated plant is not a substitute.',
      'generic houseplant replacing the Christmas tree, tropical foliage, isolated bokeh with no recognizable Christmas tree, undecorated non-holiday room, readable text, logos'
    ),
    (
      'on-model', 'on-model-v4-5', 'Snowy Pine Glow',
      'Elegant winter portrait with recognizable snow-dusted evergreen or pine branches or trees visible in the scene. Vary the location, evergreen species, snowfall, winter styling, pose, camera angle, framing, and balance of cool and warm light. Keep snow, foliage, and clothing away from the clearly visible jewelry.',
      'tropical foliage, large broadleaf jungle plants, green summer forest without snow, bare desert, snow covering the jewelry, branches obscuring the jewelry, readable text, logos'
    ),
    (
      'on-model', 'on-model-v4-5', 'Pumpkin Patch',
      'Elegant autumn portrait in a cultivated pumpkin patch, farm, or harvest field with multiple clearly recognizable pumpkins visible as the seasonal anchor. Vary pumpkin type and color, landscape, wardrobe, pose, camera distance, and golden-hour composition. Never replace the pumpkins with other produce or turn the setting into an arid desert.',
      'tomatoes, tomato vines, apples, citrus fruit, peppers, substitute produce, desert dunes, cacti, pumpkins covering the jewelry, readable text, logos'
    ),
    (
      'on-model', 'on-model-v4-5', 'Holiday Morning Cozy',
      'Cozy luxury morning portrait with at least one restrained winter-holiday cue such as evergreen branches, softly lit tree details, an unbranded wrapped gift, ribbon, or a simple wreath. Vary the room, cue, wardrobe, pose, crop, and window-light direction while keeping everyday jewelry clearly visible and the seasonal styling secondary.',
      'tropical holiday setting, branded packaging, readable gift labels, logos, oversized props, holiday props covering the jewelry'
    ),
    (
      'on-model', 'on-model-v4-5', 'Festive Toast',
      'Elegant festive portrait with a recognizable stemmed glass or refined drink vessel used as a secondary celebratory cue. Vary the vessel, gesture, wardrobe, environment, crop, and warm or editorial lighting. Keep the drink away from the jewelry and ensure the jewelry remains the visual focal point.',
      'brand labels, readable bottle text, logos, oversized drink, glass covering the jewelry, liquid spilling on the jewelry, drinking straw crossing the jewelry'
    ),
    (
      'on-model', 'on-model-v4-5', 'Clean Luxury Gifting',
      'Modern minimalist gifting portrait with at least one subtle neutral gifting cue such as an unbranded box, ribbon, folded tissue, or gift bag detail. Vary the cue, pale palette, styling, pose, framing, and soft-shadow composition while maintaining an evergreen luxury feel and clear jewelry focus.',
      'brand logos, readable packaging text, shipping cartons, product advertising copy, oversized gift boxes, packaging covering the jewelry'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Rustic Harvest',
      'Minimal rustic harvest product photography with at least one restrained harvest cue such as a dried autumn leaf, wheat stem, acorn, husk, or seed pod. Vary the wooden surface, cue, warm earth-tone balance, negative space, camera angle, and shot scale while preserving an uncluttered premium product image.',
      'fresh tomatoes, tomato vines, citrus fruit, grocery still life, food covering the jewelry, dense prop clutter, readable text, logos'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Holiday Gift Box',
      'Luxury Christmas gifting photography with a clearly recognizable open jewelry box, gift box, pouch, ribbon, or folded tissue acting as the gifting anchor. Vary the box material, palette, seasonal accents, surface, camera angle, and composition. A box or gifting element must remain visible and must not be replaced by an unrelated vessel. Use generic unbranded packaging unless actual brand packaging is supplied.',
      'perfume bottle replacing the gift box, drinking glass replacing the gift box, bowl or dish replacing the gift box, food, brand logos, readable packaging text, closed box hiding the jewelry'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Confetti Flatlay',
      'Luxury New Year product photography with clearly visible metallic paper confetti as the celebratory anchor. Vary confetti shape, size, color balance, density, surface, jewelry arrangement, camera angle, negative space, and lighting direction while keeping every jewelry piece crisp and separated. Confetti remains sparse and secondary.',
      'flowers or fruit replacing confetti, loose glitter coating the jewelry, confetti covering gemstones, balloons dominating the frame, invented jewelry, readable text, logos'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Jack-o''-Lantern Glow',
      'Refined Halloween product photography with a clearly recognizable carved pumpkin or jack-o-lantern face glowing within the scene. Vary the carving design, pumpkin type and color, placement, surface, camera angle, and controlled warm-to-dark lighting. Keep the treatment premium and the jewelry dominant, unobstructed, and outside the carved openings.',
      'tomatoes, tomato vines, apples, citrus fruit, peppers, substitute produce, uncarved fruit replacing the jack-o-lantern, cartoon plastic pumpkin, jewelry inside the pumpkin mouth, readable text, logos'
    ),
    (
      'pure-jewelry', 'pure-jewelry-v5-2', 'Clean Luxury Gifting',
      'Modern minimalist gifting product photography with at least one subtle neutral gifting cue such as an unbranded box edge, ribbon, folded tissue, pouch, or abstract paper fold. Vary the cue, pale or pastel palette, surface, negative space, camera angle, and soft-shadow composition while keeping props sparse and jewelry central.',
      'brand logos, readable packaging text, shipping cartons, product advertising copy, oversized packaging, packaging covering the jewelry'
    )
) AS anchor(task_key, engine_id, name, creative_direction, creative_exclusions)
WHERE preset.task_key = anchor.task_key
  AND preset.engine_id = anchor.engine_id
  AND lower(preset.name) = lower(anchor.name);
