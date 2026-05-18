BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

ALTER TABLE dashboard.email_campaign_recipients
  ADD COLUMN IF NOT EXISTS id uuid;

UPDATE dashboard.email_campaign_recipients
SET id = gen_random_uuid()
WHERE id IS NULL;

ALTER TABLE dashboard.email_campaign_recipients
  ALTER COLUMN id SET DEFAULT gen_random_uuid();

ALTER TABLE dashboard.email_campaign_recipients
  ALTER COLUMN id SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'email_campaign_recipients_id_pk'
      AND conrelid = 'dashboard.email_campaign_recipients'::regclass
  ) THEN
    ALTER TABLE dashboard.email_campaign_recipients
      ADD CONSTRAINT email_campaign_recipients_id_pk PRIMARY KEY (id);
  END IF;
END $$;

COMMIT;
