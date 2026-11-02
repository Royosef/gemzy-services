-- Retain pumpkins as the recognizable Halloween cue, but give every generated
-- image a different composition grammar so batches do not converge.

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
    'creative_direction', 'Luxury Halloween jewelry photography using pumpkins as abstract sculptural accents rather than a conventional harvest still life. Interpret pumpkin form through selective cropping, silhouette, curved ribbed texture, translucent amber glow, or a restrained natural miniature form. Keep the palette black, smoke, deep plum, amber, and muted orange. The jewelry remains crisp, complete, and dominant; the pumpkin cue supports the mood without becoming the centered subject. Never repeat the pumpkin count, scale, placement, jewelry-to-pumpkin relationship, or viewpoint across a batch.',
    'creative_variation_lanes', 'Use one large pumpkin form cropped decisively at a frame edge, with the jewelry isolated beside its curved silhouette in a low oblique view.||Use two or three separated miniature pumpkin forms at different depths in an asymmetric overhead composition, with the jewelry placed diagonally and generous negative space.||Show only an abstract ribbed pumpkin shadow or translucent amber curve behind the jewelry, using a tighter frontal crop and no complete pumpkin centered in frame.||Use a single small pumpkin form in the distant soft-focus background while the jewelry occupies an off-center foreground arrangement from a lower camera height.',
    'creative_exclusions', 'tomatoes, tomato vines, fruit substitutes, vegetables other than pumpkin, grocery produce display, centered harvest tableau, identical repeated pumpkin arrangement, jack-o-lantern faces, kitschy plastic props, cartoon decorations, fake blood, horror gore, readable text, logos, props covering the jewelry'
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) = lower('Halloween Mood');
