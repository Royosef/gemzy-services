-- Persistent reference assets for evolving persona/world consistency.

BEGIN;

CREATE TABLE IF NOT EXISTS people.reference_assets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id          UUID NOT NULL REFERENCES people.personas(id) ON DELETE CASCADE,
    asset_kind          TEXT NOT NULL
                        CHECK (asset_kind IN ('persona', 'location', 'scene')),
    source_kind         TEXT NOT NULL DEFAULT 'generation'
                        CHECK (source_kind IN ('upload', 'generation', 'seed')),
    storage_url         TEXT NOT NULL,
    mime_type           TEXT,
    origin_moment_id    UUID REFERENCES moments.moments(id) ON DELETE SET NULL,
    origin_job_id       UUID REFERENCES moments.generation_jobs(id) ON DELETE SET NULL,
    location_id         UUID REFERENCES people.world_locations(id) ON DELETE SET NULL,
    quality_score       FLOAT NOT NULL DEFAULT 0.0,
    consistency_score   FLOAT NOT NULL DEFAULT 0.0,
    is_canonical        BOOLEAN NOT NULL DEFAULT false,
    is_active           BOOLEAN NOT NULL DEFAULT true,
    metadata_json       JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reference_assets_persona
    ON people.reference_assets(persona_id, asset_kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reference_assets_location
    ON people.reference_assets(location_id)
    WHERE location_id IS NOT NULL;

ALTER TABLE people.reference_assets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Read reference assets" ON people.reference_assets;
CREATE POLICY "Read reference assets"
    ON people.reference_assets FOR SELECT
    USING (persona_id IN (
        SELECT id FROM people.personas
        WHERE owner_user_id = auth.uid()
           OR is_public = true
           OR id IN (SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid())
    ));

DROP POLICY IF EXISTS "Write reference assets" ON people.reference_assets;
CREATE POLICY "Write reference assets"
    ON people.reference_assets FOR INSERT
    WITH CHECK (persona_id IN (
        SELECT id FROM people.personas WHERE owner_user_id = auth.uid()
        UNION
        SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid() AND role IN ('owner', 'editor')
    ));

DROP POLICY IF EXISTS "Update reference assets" ON people.reference_assets;
CREATE POLICY "Update reference assets"
    ON people.reference_assets FOR UPDATE
    USING (persona_id IN (
        SELECT id FROM people.personas WHERE owner_user_id = auth.uid()
        UNION
        SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid() AND role IN ('owner', 'editor')
    ));

DROP POLICY IF EXISTS "Delete reference assets" ON people.reference_assets;
CREATE POLICY "Delete reference assets"
    ON people.reference_assets FOR DELETE
    USING (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()));

DROP POLICY IF EXISTS "srv people.reference_assets" ON people.reference_assets;
CREATE POLICY "srv people.reference_assets"
    ON people.reference_assets FOR ALL TO service_role
    USING (true) WITH CHECK (true);

COMMIT;
