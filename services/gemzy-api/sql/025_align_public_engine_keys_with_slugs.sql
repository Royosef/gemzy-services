BEGIN;

UPDATE public.prompt_engines
SET public_engine_key = slug
WHERE COALESCE(public_engine_key, '') <> slug;

UPDATE public.prompt_engines
SET
  selector_pill_label = CASE slug
    WHEN 'on-model-v2' THEN 'On-Model V2'
    WHEN 'on-model-v4-5' THEN 'On-Model V4.5'
    WHEN 'pure-jewelry-legacy' THEN 'Pure Legacy'
    WHEN 'pure-jewelry-v5-2' THEN 'Pure V5.2'
    ELSE selector_pill_label
  END,
  selector_title = CASE slug
    WHEN 'on-model-v2' THEN 'On-Model V2'
    WHEN 'on-model-v4-5' THEN 'On-Model V4.5'
    WHEN 'pure-jewelry-legacy' THEN 'Pure Jewelry Legacy'
    WHEN 'pure-jewelry-v5-2' THEN 'Pure Jewelry V5.2'
    ELSE selector_title
  END
WHERE slug IN (
  'on-model-v2',
  'on-model-v4-5',
  'pure-jewelry-legacy',
  'pure-jewelry-v5-2'
);

COMMIT;
