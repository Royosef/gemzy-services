-- Abstract composition must not imply levitation. Require believable support
-- and contact shadows while retaining distinct pumpkin arrangements.

UPDATE public.creation_look_presets
SET
  style = jsonb_build_object(
    'category', 'Holiday & Seasonal',
    'season', 'Halloween',
    'style_type', 'surface-light',
    'surface', 'Fabric Drape',
    'light-direction', 'Raking Side Light',
    'shadow-play', 'Long Directional',
    'color-temperature', 'Deep Contrast',
    'composition', 'Close Up',
    'creative_direction', 'Luxury Halloween jewelry photography using pumpkins as abstract sculptural accents rather than a conventional harvest still life. Interpret pumpkin form through selective cropping, silhouette, curved ribbed texture, translucent amber glow, or a restrained natural miniature form. Keep the palette black, smoke, deep plum, amber, and muted orange. Every jewelry item must be physically supported with a believable point of contact and a natural contact shadow: rings lie naturally on the surface or visibly lean against a pumpkin; no jewelry may levitate or stand upright without support. The jewelry remains crisp, complete, and dominant. Never repeat the pumpkin count, scale, placement, jewelry-to-pumpkin relationship, or viewpoint across a batch.',
    'creative_variation_lanes', 'Use one large pumpkin form cropped decisively at a frame edge in a low oblique view. Place the jewelry naturally on the fabric beside it, fully grounded with a visible contact shadow.||Use two or three separated miniature pumpkin forms at different depths in an asymmetric overhead composition. Arrange the jewelry diagonally and flat on the surface with generous negative space.||Show only an abstract ribbed pumpkin shadow or translucent amber curve behind the jewelry in a tighter frontal crop. Let the jewelry visibly lean against a low supported form or rest in a shallow fabric fold.||Use a single small pumpkin form in the distant soft-focus background while the jewelry lies in an off-center foreground arrangement on the surface from a lower camera height.',
    'creative_exclusions', 'floating jewelry, levitating jewelry, suspended jewelry, unsupported upright ring, ring standing on edge without support, missing contact shadow, tomatoes, tomato vines, fruit substitutes, vegetables other than pumpkin, grocery produce display, centered harvest tableau, identical repeated pumpkin arrangement, jack-o-lantern faces, kitschy plastic props, cartoon decorations, fake blood, horror gore, readable text, logos, props covering the jewelry'
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) = lower('Halloween Mood');
