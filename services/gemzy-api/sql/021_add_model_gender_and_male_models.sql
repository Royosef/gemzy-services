-- Add model gender metadata and seed the first male model beta roster.

BEGIN;

ALTER TABLE public.models
ADD COLUMN IF NOT EXISTS gender TEXT NOT NULL DEFAULT 'female';

UPDATE public.models
SET gender = 'female'
WHERE gender IS NULL OR gender NOT IN ('female', 'male');

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'models_gender_check'
  ) THEN
    ALTER TABLE public.models
      ADD CONSTRAINT models_gender_check CHECK (gender IN ('female', 'male'));
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS models_gender_idx
  ON public.models (gender);

INSERT INTO public.models (
  id,
  slug,
  name,
  email,
  plan,
  gender,
  highlight,
  description,
  image_url,
  tags,
  spotlight_tag
)
VALUES
  (
    '1111aaaa-1111-4111-8111-111111111111',
    'luca-ferrante',
    'Luca Ferrante',
    'luca-ferrante@gemzy-models.local',
    'Pro',
    'male',
    'Beta Model',
    'A clean studio presence for refined catalog and editorial jewelry looks.',
    'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=800&auto=format&fit=crop',
    ARRAY['male','beta','studio','portrait'],
    NULL
  ),
  (
    '2222bbbb-2222-4222-8222-222222222222',
    'mikhil-hames',
    'Mikhil Hames',
    'mikhil-hames@gemzy-models.local',
    'Pro',
    'male',
    'Beta Model',
    'Sharp facial structure and calm expression for premium on-model compositions.',
    'https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=800&auto=format&fit=crop',
    ARRAY['male','beta','premium','portrait'],
    NULL
  ),
  (
    '3333cccc-3333-4333-8333-333333333333',
    'jin-seo-won',
    'Jin Seo-won',
    'jin-seo-won@gemzy-models.local',
    'Pro',
    'male',
    'Beta Model',
    'Minimal, polished styling designed for clean product-forward jewelry imagery.',
    'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=800&auto=format&fit=crop',
    ARRAY['male','beta','minimal','portrait'],
    NULL
  ),
  (
    '4444dddd-4444-4444-8444-444444444444',
    'callum-voss',
    'Callum Voss',
    'callum-voss@gemzy-models.local',
    'Pro',
    'male',
    'Beta Model',
    'Soft editorial energy with a relaxed studio posture and natural expression.',
    'https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=800&auto=format&fit=crop',
    ARRAY['male','beta','editorial','portrait'],
    NULL
  ),
  (
    '5555eeee-5555-4555-8555-555555555555',
    'cole-sable',
    'Cole Sable',
    'cole-sable@gemzy-models.local',
    'Pro',
    'male',
    'Beta Model',
    'Confident, direct styling suited to bold accessories and close portrait crops.',
    'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=800&auto=format&fit=crop',
    ARRAY['male','beta','bold','portrait'],
    NULL
  )
ON CONFLICT (slug) DO UPDATE
SET
  name = EXCLUDED.name,
  email = EXCLUDED.email,
  plan = EXCLUDED.plan,
  gender = EXCLUDED.gender,
  highlight = EXCLUDED.highlight,
  description = EXCLUDED.description,
  image_url = EXCLUDED.image_url,
  tags = EXCLUDED.tags,
  spotlight_tag = EXCLUDED.spotlight_tag;

WITH gallery(model_slug, image_url) AS (
  VALUES
    ('luca-ferrante', 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=800&auto=format&fit=crop'),
    ('luca-ferrante', 'https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=800&auto=format&fit=crop'),
    ('mikhil-hames', 'https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=800&auto=format&fit=crop'),
    ('mikhil-hames', 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=800&auto=format&fit=crop'),
    ('jin-seo-won', 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=800&auto=format&fit=crop'),
    ('jin-seo-won', 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=800&auto=format&fit=crop'),
    ('callum-voss', 'https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=800&auto=format&fit=crop'),
    ('callum-voss', 'https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=800&auto=format&fit=crop'),
    ('cole-sable', 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=800&auto=format&fit=crop'),
    ('cole-sable', 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=800&auto=format&fit=crop')
)
INSERT INTO public.model_gallery (model_id, image_url)
SELECT
  models.id,
  gallery.image_url
FROM gallery
JOIN public.models ON models.slug = gallery.model_slug
WHERE NOT EXISTS (
  SELECT 1
  FROM public.model_gallery existing
  WHERE existing.model_id = models.id
    AND existing.image_url = gallery.image_url
);

COMMIT;
