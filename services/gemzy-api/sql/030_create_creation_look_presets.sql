-- System-owned "For you" presets shown in creation task look pickers.
--
-- Prompt engine definitions remain the source of valid sections/options.
-- These rows are curated cards that reference a task + public engine key and
-- store the selected style values for that engine.

CREATE TABLE IF NOT EXISTS public.creation_look_presets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_key TEXT NOT NULL REFERENCES public.prompt_tasks(key) ON DELETE CASCADE,
  engine_id TEXT NOT NULL,
  name TEXT NOT NULL,
  style JSONB NOT NULL DEFAULT '{}'::jsonb,
  preview_url TEXT,
  preview_storage_path TEXT,
  required_plan plan_tier DEFAULT 'Free',
  sort_order INTEGER NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS creation_look_presets_task_engine_idx
  ON public.creation_look_presets (task_key, engine_id, is_active, sort_order);

CREATE UNIQUE INDEX IF NOT EXISTS creation_look_presets_task_engine_name_idx
  ON public.creation_look_presets (task_key, engine_id, lower(name));

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'creation_look_presets_set_updated_at'
  ) THEN
    CREATE TRIGGER creation_look_presets_set_updated_at
      BEFORE UPDATE ON public.creation_look_presets
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

INSERT INTO public.creation_look_presets (
  task_key,
  engine_id,
  name,
  style,
  required_plan,
  sort_order
)
SELECT
  'on-model',
  'on-model-v2',
  'Editorial Studio',
  '{
    "background": "Studio Color (Dynamic)",
    "pose": "Over Shoulder",
    "emotion": "Mysterious",
    "lighting": "Golden Hour Glow",
    "camera": "Beauty Macro",
    "hair": "Behind Ear",
    "image_style": "Soft Luxury",
    "studioColorHex": "#C59981"
  }'::jsonb,
  'Free'::plan_tier,
  10
WHERE EXISTS (SELECT 1 FROM public.prompt_tasks WHERE key = 'on-model')
  AND NOT EXISTS (
    SELECT 1
    FROM public.creation_look_presets
    WHERE task_key = 'on-model'
      AND engine_id = 'on-model-v2'
      AND lower(name) = lower('Editorial Studio')
  );

INSERT INTO public.creation_look_presets (
  task_key,
  engine_id,
  name,
  style,
  required_plan,
  sort_order
)
SELECT
  'on-model',
  'on-model-v2',
  'Desert Contrast',
  '{
    "background": "Coastal Luxury",
    "pose": "Relaxed Luxury",
    "emotion": "Mysterious",
    "lighting": "Golden Hour Glow",
    "camera": "Beauty Macro",
    "hair": "Side Sweep",
    "image_style": "Soft Luxury"
  }'::jsonb,
  'Free'::plan_tier,
  20
WHERE EXISTS (SELECT 1 FROM public.prompt_tasks WHERE key = 'on-model')
  AND NOT EXISTS (
    SELECT 1
    FROM public.creation_look_presets
    WHERE task_key = 'on-model'
      AND engine_id = 'on-model-v2'
      AND lower(name) = lower('Desert Contrast')
  );
