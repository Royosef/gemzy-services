-- Remove the generic Table & Kitchen territory from the positive prompt. The
-- server-owned override guarantees a jewelry presentation box even if a client
-- has stale object-world defaults cached.

UPDATE public.creation_look_presets
SET
  style = jsonb_set(
    jsonb_set(
      COALESCE(style, '{}'::jsonb),
      '{object-territory}',
      to_jsonb('Jewelry Presentation Box'::text),
      TRUE
    ),
    '{creative_object_territory}',
    to_jsonb('Jewelry Presentation Box'::text),
    TRUE
  ),
  updated_at = NOW()
WHERE task_key = 'pure-jewelry'
  AND engine_id = 'pure-jewelry-v5-2'
  AND lower(name) = lower('Holiday Gift Box');
