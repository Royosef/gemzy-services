-- Prepend a strict product identity lock to every V4.5 prompt definition that
-- can currently be selected at runtime. New installs receive the same text
-- from packages/prompting/prompting/on_model_constants.py.
BEGIN;

WITH target_engine AS (
  SELECT id, active_version_id, published_version_id
  FROM public.prompt_engines
  WHERE slug = 'on-model-v4-5'
),
target_versions AS (
  SELECT active_version_id AS id
  FROM target_engine
  WHERE active_version_id IS NOT NULL
  UNION
  SELECT published_version_id AS id
  FROM target_engine
  WHERE published_version_id IS NOT NULL
  UNION
  SELECT route.pinned_version_id AS id
  FROM public.prompt_task_routes AS route
  JOIN target_engine AS engine ON engine.id = route.engine_id
  WHERE route.pinned_version_id IS NOT NULL
),
fidelity_text AS (
  SELECT $prompt$PRODUCT FIDELITY OVERRIDE: Treat every uploaded jewelry image as an immutable product specification, never as loose inspiration. The generated scene, model pose, styling, lighting, and camera treatment may change; the jewelry product may not. If any aesthetic, editorial, composition, preset, or creative-direction instruction conflicts with product fidelity, product fidelity wins.

EXACT PRODUCT PRESERVATION: Reproduce the exact uploaded product. Preserve its geometry, proportions, silhouette, topology, construction, orientation on the body, relative scale, and every visible stone, crystal, bead, pearl, link, setting, prong, clasp, connector, engraving, edge, opening, and repeated element, including exact count, order, spacing, size relationships, and placement. Preserve exact materials, metal color, gemstone colors, transparency, finish, texture, reflectivity, and mixed-material boundaries. Keep enough jewelry pixels in frame for the smallest details to remain distinct. Do not redesign, stylize, simplify, merge, blur, substitute, recolor, resize, add, remove, repair, or reinterpret any jewelry detail. Do not repair asymmetry or invent hidden details.$prompt$::text AS value
)
UPDATE public.prompt_engine_versions AS version
SET definition = jsonb_set(
  version.definition,
  '{texts,quality}',
  to_jsonb(
    fidelity_text.value
    || E'\n\n'
    || COALESCE(version.definition->'texts'->>'quality', '')
  ),
  true
)
FROM target_versions, fidelity_text
WHERE version.id = target_versions.id
  AND COALESCE(version.definition->'texts'->>'quality', '')
      NOT LIKE 'PRODUCT FIDELITY OVERRIDE:%';

COMMIT;
