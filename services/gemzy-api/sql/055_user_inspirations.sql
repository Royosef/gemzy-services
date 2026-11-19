-- Saved Explore inspirations, synced across devices (previously kept on each device).
-- Run before deploying the API that serves /inspirations.
BEGIN;

CREATE TABLE IF NOT EXISTS public.user_inspirations (
  user_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  media_id text NOT NULL,
  look_id text NOT NULL,
  look_name text NOT NULL,
  task_key text NOT NULL,
  engine_id text,
  kind text NOT NULL DEFAULT 'image' CHECK (kind IN ('image', 'video')),
  uri text NOT NULL,
  preview_uri text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, media_id)
);

CREATE INDEX IF NOT EXISTS user_inspirations_recent
  ON public.user_inspirations (user_id, created_at DESC);

-- Only the API (service role) reads or writes this table.
ALTER TABLE public.user_inspirations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.user_inspirations FROM anon, authenticated;
GRANT ALL ON public.user_inspirations TO service_role;

COMMIT;
