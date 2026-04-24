ALTER TABLE user_deletion_queue
  ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;
