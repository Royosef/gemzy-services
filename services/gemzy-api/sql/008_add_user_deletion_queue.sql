-- Queue table storing scheduled user deletions with grace periods.
BEGIN;

CREATE TABLE IF NOT EXISTS public.user_deletion_queue (
  user_id UUID PRIMARY KEY REFERENCES public.profiles(id) ON DELETE CASCADE,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  scheduled_for TIMESTAMPTZ NOT NULL,
  grace_period_days INTEGER NOT NULL DEFAULT 30,
  status TEXT NOT NULL DEFAULT 'scheduled',
  error TEXT,
  deleted_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS user_deletion_queue_schedule_idx
  ON public.user_deletion_queue (scheduled_for)
  WHERE status = 'scheduled';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'user_deletion_queue_set_updated_at'
  ) THEN
    CREATE TRIGGER user_deletion_queue_set_updated_at
      BEFORE UPDATE ON public.user_deletion_queue
      FOR EACH ROW
      EXECUTE FUNCTION public.set_updated_at();
  END IF;
END$$;

COMMIT;

