-- ============================================================
-- Gemzy Moments — UP Migration (Idempotent)
-- Creates: people schema, moments schema
-- Safe to re-run: uses IF NOT EXISTS, DROP POLICY IF EXISTS
-- ============================================================

BEGIN;

-- ============================================================
-- SCHEMA: people (Agency — what the persona HAS)
-- ============================================================
CREATE SCHEMA IF NOT EXISTS people;

-- ── Personas ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS people.personas (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    is_gemzy_owned  BOOLEAN NOT NULL DEFAULT false,
    is_public       BOOLEAN NOT NULL DEFAULT false,
    display_name    TEXT NOT NULL,
    bio             TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_personas_owner ON people.personas(owner_user_id);

-- ── Persona Style Profile ───────────────────────────────

CREATE TABLE IF NOT EXISTS people.persona_style_profile (
    persona_id          UUID PRIMARY KEY REFERENCES people.personas(id) ON DELETE CASCADE,
    realism_level       TEXT NOT NULL DEFAULT 'high'
                        CHECK (realism_level IN ('low', 'medium', 'high', 'hyper')),
    camera_style_tags   JSONB DEFAULT '[]',
    color_palette_tags  JSONB DEFAULT '[]',
    negative_rules      JSONB DEFAULT '[]',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── World Locations (canonical places catalog) ──────────

CREATE TABLE IF NOT EXISTS people.world_locations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id      UUID NOT NULL REFERENCES people.personas(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    tags            JSONB DEFAULT '[]',
    tier            TEXT NOT NULL DEFAULT 'SEMI_STABLE'
                    CHECK (tier IN ('ANCHOR', 'SEMI_STABLE', 'FLEX')),
    reuse_weight    FLOAT NOT NULL DEFAULT 1.0,
    cooldown_hours  INT NOT NULL DEFAULT 0,
    max_per_week    INT,
    ref_asset_id    UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_world_locations_persona ON people.world_locations(persona_id);

-- ── World Wardrobe Items (canonical wardrobe catalog) ───

CREATE TABLE IF NOT EXISTS people.world_wardrobe_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id      UUID NOT NULL REFERENCES people.personas(id) ON DELETE CASCADE,
    category        TEXT NOT NULL
                    CHECK (category IN ('top', 'bottom', 'dress', 'shoes', 'accessory', 'set', 'outerwear')),
    name            TEXT NOT NULL,
    tags            JSONB DEFAULT '[]',
    tier            TEXT NOT NULL DEFAULT 'SEMI_STABLE'
                    CHECK (tier IN ('ANCHOR', 'SEMI_STABLE', 'FLEX')),
    reuse_weight    FLOAT NOT NULL DEFAULT 1.0,
    season_tags     JSONB DEFAULT '[]',
    ref_asset_id    UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_world_wardrobe_persona ON people.world_wardrobe_items(persona_id);

-- ── Licensing Policies (stub for MVP+) ──────────────────

CREATE TABLE IF NOT EXISTS people.licensing_policies (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id              UUID NOT NULL REFERENCES people.personas(id) ON DELETE CASCADE,
    rev_share_creator_pct   FLOAT NOT NULL DEFAULT 70.0,
    rev_share_gemzy_pct     FLOAT NOT NULL DEFAULT 30.0,
    allowed_use_cases       JSONB DEFAULT '[]',
    exclusivity_allowed     BOOLEAN NOT NULL DEFAULT false,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Persona Members (collaboration) ─────────────────────

CREATE TABLE IF NOT EXISTS people.persona_members (
    persona_id  UUID NOT NULL REFERENCES people.personas(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'viewer'
                CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (persona_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_persona_members_user ON people.persona_members(user_id);


-- ============================================================
-- SCHEMA: moments (Social Brain — what the persona DID/WILL DO)
-- ============================================================
CREATE SCHEMA IF NOT EXISTS moments;

-- ── User Preferences ────────────────────────────────────

CREATE TABLE IF NOT EXISTS moments.user_preferences (
    user_id                 UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    default_posts_per_day   INT NOT NULL DEFAULT 1,
    default_stories_per_day INT NOT NULL DEFAULT 3,
    distribution_profile    JSONB DEFAULT '{"morning":0.25,"midday":0.2,"afternoon":0.2,"evening":0.25,"late_night":0.1}',
    novelty_rate            FLOAT NOT NULL DEFAULT 0.15
                            CHECK (novelty_rate >= 0 AND novelty_rate <= 1),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Content Plans ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS moments.content_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id      UUID NOT NULL REFERENCES people.personas(id) ON DELETE CASCADE,
    owner_user_id   UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    plan_type       TEXT NOT NULL DEFAULT 'DAY'
                    CHECK (plan_type IN ('DAY', 'WEEK', 'MONTH')),
    date_start      DATE NOT NULL,
    date_end        DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT', 'AWAITING_CONFIRMATION', 'CONFIRMED', 'GENERATING', 'READY', 'PARTIAL_READY', 'FAILED')),
    source_prompt   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_plans_owner ON moments.content_plans(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_plans_persona ON moments.content_plans(persona_id);
CREATE INDEX IF NOT EXISTS idx_plans_dates ON moments.content_plans(date_start, date_end);

-- ── Plan Blocks (time-of-day groupings) ─────────────────

CREATE TABLE IF NOT EXISTS moments.plan_blocks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         UUID NOT NULL REFERENCES moments.content_plans(id) ON DELETE CASCADE,
    time_of_day     TEXT NOT NULL
                    CHECK (time_of_day IN ('morning', 'midday', 'afternoon', 'evening', 'late_night')),
    target_posts    INT NOT NULL DEFAULT 0,
    target_stories  INT NOT NULL DEFAULT 1,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_plan_blocks_plan ON moments.plan_blocks(plan_id);

-- ── Moments (individual story/post units) ───────────────

CREATE TABLE IF NOT EXISTS moments.moments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         UUID NOT NULL REFERENCES moments.content_plans(id) ON DELETE CASCADE,
    block_id        UUID REFERENCES moments.plan_blocks(id) ON DELETE SET NULL,
    moment_type     TEXT NOT NULL
                    CHECK (moment_type IN ('STORY', 'POST')),
    image_count     INT NOT NULL DEFAULT 1,
    caption_hint    TEXT,
    status          TEXT NOT NULL DEFAULT 'PLANNED'
                    CHECK (status IN ('PLANNED', 'APPROVED', 'GENERATING', 'READY', 'FAILED')),
    scheduled_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_moments_plan ON moments.moments(plan_id);
CREATE INDEX IF NOT EXISTS idx_moments_block ON moments.moments(block_id);
CREATE INDEX IF NOT EXISTS idx_moments_status ON moments.moments(status);

-- ── Moment Context (world ingredients per moment) ───────

CREATE TABLE IF NOT EXISTS moments.moment_context (
    moment_id           UUID PRIMARY KEY REFERENCES moments.moments(id) ON DELETE CASCADE,
    location_id         UUID REFERENCES people.world_locations(id) ON DELETE SET NULL,
    wardrobe_item_ids   UUID[] DEFAULT '{}',
    outfit_composition  JSONB DEFAULT '{}',
    food_theme          JSONB,
    mood_tags           JSONB DEFAULT '[]',
    continuity_notes    TEXT
);

-- ── Planner Runs (versioned LLM outputs) ────────────────

CREATE TABLE IF NOT EXISTS moments.planner_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         UUID NOT NULL REFERENCES moments.content_plans(id) ON DELETE CASCADE,
    model_name      TEXT,
    output_json     JSONB NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_planner_runs_plan ON moments.planner_runs(plan_id);

-- ── Usage Stats (fatigue + cooldown tracking) ───────────

CREATE TABLE IF NOT EXISTS moments.usage_stats (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id      UUID NOT NULL REFERENCES people.personas(id) ON DELETE CASCADE,
    item_type       TEXT NOT NULL
                    CHECK (item_type IN ('location', 'wardrobe', 'outfit_combo')),
    item_id         UUID NOT NULL,
    last_used_at    TIMESTAMPTZ,
    uses_7d         INT NOT NULL DEFAULT 0,
    uses_30d        INT NOT NULL DEFAULT 0,
    fatigue_score   FLOAT NOT NULL DEFAULT 0.0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (persona_id, item_type, item_id)
);

CREATE INDEX IF NOT EXISTS idx_usage_stats_persona ON moments.usage_stats(persona_id);
CREATE INDEX IF NOT EXISTS idx_usage_stats_item ON moments.usage_stats(item_type, item_id);

-- ── World State (operational memory pointers) ───────────

CREATE TABLE IF NOT EXISTS moments.world_state (
    persona_id          UUID PRIMARY KEY REFERENCES people.personas(id) ON DELETE CASCADE,
    recent_location_ids UUID[] DEFAULT '{}',
    recent_outfit_hashes TEXT[] DEFAULT '{}',
    cooldown_map        JSONB DEFAULT '{}',
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Generation Jobs (queue per moment) ──────────────────

CREATE TABLE IF NOT EXISTS moments.generation_jobs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    moment_id           UUID NOT NULL REFERENCES moments.moments(id) ON DELETE CASCADE,
    generation_provider TEXT,
    status              TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'running', 'done', 'failed')),
    cost_estimate       FLOAT,
    attempts            INT NOT NULL DEFAULT 0,
    result_urls         TEXT[] DEFAULT '{}',
    error               TEXT,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_genjobs_moment ON moments.generation_jobs(moment_id);
CREATE INDEX IF NOT EXISTS idx_genjobs_status ON moments.generation_jobs(status);

-- ── Deliveries (ready packs for download) ───────────────

CREATE TABLE IF NOT EXISTS moments.deliveries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         UUID NOT NULL REFERENCES moments.content_plans(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'building'
                    CHECK (status IN ('building', 'ready', 'failed')),
    zip_asset_id    UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deliveries_plan ON moments.deliveries(plan_id);

-- ── Notifications ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS moments.notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL
                    CHECK (type IN ('plan_ready', 'moment_failed', 'delivery_ready', 'plan_generating')),
    payload         JSONB DEFAULT '{}',
    read            BOOLEAN NOT NULL DEFAULT false,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON moments.notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON moments.notifications(user_id, read) WHERE read = false;


-- ============================================================
-- RLS POLICIES (idempotent: DROP IF EXISTS then CREATE)
-- ============================================================

-- ── Enable RLS on all tables ────────────────────────────

ALTER TABLE people.personas              ENABLE ROW LEVEL SECURITY;
ALTER TABLE people.persona_style_profile ENABLE ROW LEVEL SECURITY;
ALTER TABLE people.world_locations       ENABLE ROW LEVEL SECURITY;
ALTER TABLE people.world_wardrobe_items  ENABLE ROW LEVEL SECURITY;
ALTER TABLE people.licensing_policies    ENABLE ROW LEVEL SECURITY;
ALTER TABLE people.persona_members       ENABLE ROW LEVEL SECURITY;

ALTER TABLE moments.user_preferences     ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.content_plans        ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.plan_blocks          ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.moments              ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.moment_context       ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.planner_runs         ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.usage_stats          ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.world_state          ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.generation_jobs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.deliveries           ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments.notifications        ENABLE ROW LEVEL SECURITY;

-- ── people.personas policies ────────────────────────────

DROP POLICY IF EXISTS "Users own/see personas" ON people.personas;
CREATE POLICY "Users own/see personas"
    ON people.personas FOR SELECT
    USING (
        owner_user_id = auth.uid()
        OR is_public = true
        OR id IN (SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid())
    );

DROP POLICY IF EXISTS "Users mutate own personas" ON people.personas;
CREATE POLICY "Users mutate own personas"
    ON people.personas FOR INSERT
    WITH CHECK (owner_user_id = auth.uid());

DROP POLICY IF EXISTS "Owners/editors update personas" ON people.personas;
CREATE POLICY "Owners/editors update personas"
    ON people.personas FOR UPDATE
    USING (
        owner_user_id = auth.uid()
        OR id IN (SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid() AND role IN ('owner', 'editor'))
    )
    WITH CHECK (owner_user_id = auth.uid());

DROP POLICY IF EXISTS "Owners delete personas" ON people.personas;
CREATE POLICY "Owners delete personas"
    ON people.personas FOR DELETE
    USING (owner_user_id = auth.uid());

-- ── people.persona_style_profile policies ───────────────

DROP POLICY IF EXISTS "Read style profiles" ON people.persona_style_profile;
CREATE POLICY "Read style profiles"
    ON people.persona_style_profile FOR SELECT
    USING (persona_id IN (
        SELECT id FROM people.personas
        WHERE owner_user_id = auth.uid()
           OR is_public = true
           OR id IN (SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid())
    ));

DROP POLICY IF EXISTS "Write style profiles" ON people.persona_style_profile;
CREATE POLICY "Write style profiles"
    ON people.persona_style_profile FOR INSERT
    WITH CHECK (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()));

DROP POLICY IF EXISTS "Update style profiles" ON people.persona_style_profile;
CREATE POLICY "Update style profiles"
    ON people.persona_style_profile FOR UPDATE
    USING (persona_id IN (
        SELECT id FROM people.personas WHERE owner_user_id = auth.uid()
        UNION
        SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid() AND role IN ('owner', 'editor')
    ));

-- ── people.world_locations policies ─────────────────────

DROP POLICY IF EXISTS "Read locations" ON people.world_locations;
CREATE POLICY "Read locations"
    ON people.world_locations FOR SELECT
    USING (persona_id IN (
        SELECT id FROM people.personas
        WHERE owner_user_id = auth.uid()
           OR is_public = true
           OR id IN (SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid())
    ));

DROP POLICY IF EXISTS "Write locations" ON people.world_locations;
CREATE POLICY "Write locations"
    ON people.world_locations FOR INSERT
    WITH CHECK (persona_id IN (
        SELECT id FROM people.personas WHERE owner_user_id = auth.uid()
        UNION
        SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid() AND role IN ('owner', 'editor')
    ));

DROP POLICY IF EXISTS "Mutate locations" ON people.world_locations;
CREATE POLICY "Mutate locations"
    ON people.world_locations FOR UPDATE
    USING (persona_id IN (
        SELECT id FROM people.personas WHERE owner_user_id = auth.uid()
        UNION
        SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid() AND role IN ('owner', 'editor')
    ));

DROP POLICY IF EXISTS "Delete locations" ON people.world_locations;
CREATE POLICY "Delete locations"
    ON people.world_locations FOR DELETE
    USING (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()));

-- ── people.world_wardrobe_items policies ────────────────

DROP POLICY IF EXISTS "Read wardrobe" ON people.world_wardrobe_items;
CREATE POLICY "Read wardrobe"
    ON people.world_wardrobe_items FOR SELECT
    USING (persona_id IN (
        SELECT id FROM people.personas
        WHERE owner_user_id = auth.uid()
           OR is_public = true
           OR id IN (SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid())
    ));

DROP POLICY IF EXISTS "Write wardrobe" ON people.world_wardrobe_items;
CREATE POLICY "Write wardrobe"
    ON people.world_wardrobe_items FOR INSERT
    WITH CHECK (persona_id IN (
        SELECT id FROM people.personas WHERE owner_user_id = auth.uid()
        UNION
        SELECT persona_id FROM people.persona_members WHERE user_id = auth.uid() AND role IN ('owner', 'editor')
    ));

DROP POLICY IF EXISTS "Delete wardrobe" ON people.world_wardrobe_items;
CREATE POLICY "Delete wardrobe"
    ON people.world_wardrobe_items FOR DELETE
    USING (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()));

-- ── people.licensing_policies ───────────────────────────

DROP POLICY IF EXISTS "Users own licensing via persona" ON people.licensing_policies;
CREATE POLICY "Users own licensing via persona"
    ON people.licensing_policies FOR ALL
    USING (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()))
    WITH CHECK (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()));

-- ── people.persona_members policies ─────────────────────

DROP POLICY IF EXISTS "Members see memberships" ON people.persona_members;
CREATE POLICY "Members see memberships"
    ON people.persona_members FOR SELECT
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS "Owners manage members" ON people.persona_members;
CREATE POLICY "Owners manage members"
    ON people.persona_members FOR ALL
    USING (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()))
    WITH CHECK (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()));

-- ── moments.user_preferences policies ───────────────────

DROP POLICY IF EXISTS "Users own preferences" ON moments.user_preferences;
CREATE POLICY "Users own preferences"
    ON moments.user_preferences FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- ── moments.content_plans policies ──────────────────────

DROP POLICY IF EXISTS "Users own plans" ON moments.content_plans;
CREATE POLICY "Users own plans"
    ON moments.content_plans FOR ALL
    USING (owner_user_id = auth.uid())
    WITH CHECK (owner_user_id = auth.uid());

-- ── moments.plan_blocks policies ────────────────────────

DROP POLICY IF EXISTS "Users own blocks via plan" ON moments.plan_blocks;
CREATE POLICY "Users own blocks via plan"
    ON moments.plan_blocks FOR ALL
    USING (plan_id IN (SELECT id FROM moments.content_plans WHERE owner_user_id = auth.uid()))
    WITH CHECK (plan_id IN (SELECT id FROM moments.content_plans WHERE owner_user_id = auth.uid()));

-- ── moments.moments policies ────────────────────────────

DROP POLICY IF EXISTS "Users own moments via plan" ON moments.moments;
CREATE POLICY "Users own moments via plan"
    ON moments.moments FOR ALL
    USING (plan_id IN (SELECT id FROM moments.content_plans WHERE owner_user_id = auth.uid()))
    WITH CHECK (plan_id IN (SELECT id FROM moments.content_plans WHERE owner_user_id = auth.uid()));

-- ── moments.moment_context policies ─────────────────────

DROP POLICY IF EXISTS "Users own moment context" ON moments.moment_context;
CREATE POLICY "Users own moment context"
    ON moments.moment_context FOR ALL
    USING (moment_id IN (
        SELECT m.id FROM moments.moments m
        JOIN moments.content_plans p ON m.plan_id = p.id
        WHERE p.owner_user_id = auth.uid()
    ))
    WITH CHECK (moment_id IN (
        SELECT m.id FROM moments.moments m
        JOIN moments.content_plans p ON m.plan_id = p.id
        WHERE p.owner_user_id = auth.uid()
    ));

-- ── moments.planner_runs policies ───────────────────────

DROP POLICY IF EXISTS "Users own planner runs via plan" ON moments.planner_runs;
CREATE POLICY "Users own planner runs via plan"
    ON moments.planner_runs FOR ALL
    USING (plan_id IN (SELECT id FROM moments.content_plans WHERE owner_user_id = auth.uid()))
    WITH CHECK (plan_id IN (SELECT id FROM moments.content_plans WHERE owner_user_id = auth.uid()));

-- ── moments.usage_stats policies ────────────────────────

DROP POLICY IF EXISTS "Users own usage stats via persona" ON moments.usage_stats;
CREATE POLICY "Users own usage stats via persona"
    ON moments.usage_stats FOR ALL
    USING (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()))
    WITH CHECK (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()));

-- ── moments.world_state policies ────────────────────────

DROP POLICY IF EXISTS "Users own world state via persona" ON moments.world_state;
CREATE POLICY "Users own world state via persona"
    ON moments.world_state FOR ALL
    USING (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()))
    WITH CHECK (persona_id IN (SELECT id FROM people.personas WHERE owner_user_id = auth.uid()));

-- ── moments.generation_jobs policies ────────────────────

DROP POLICY IF EXISTS "Users own generation jobs" ON moments.generation_jobs;
CREATE POLICY "Users own generation jobs"
    ON moments.generation_jobs FOR ALL
    USING (moment_id IN (
        SELECT m.id FROM moments.moments m
        JOIN moments.content_plans p ON m.plan_id = p.id
        WHERE p.owner_user_id = auth.uid()
    ))
    WITH CHECK (moment_id IN (
        SELECT m.id FROM moments.moments m
        JOIN moments.content_plans p ON m.plan_id = p.id
        WHERE p.owner_user_id = auth.uid()
    ));

-- ── moments.deliveries policies ─────────────────────────

DROP POLICY IF EXISTS "Users own deliveries via plan" ON moments.deliveries;
CREATE POLICY "Users own deliveries via plan"
    ON moments.deliveries FOR ALL
    USING (plan_id IN (SELECT id FROM moments.content_plans WHERE owner_user_id = auth.uid()))
    WITH CHECK (plan_id IN (SELECT id FROM moments.content_plans WHERE owner_user_id = auth.uid()));

-- ── moments.notifications policies ──────────────────────

DROP POLICY IF EXISTS "Users own notifications" ON moments.notifications;
CREATE POLICY "Users own notifications"
    ON moments.notifications FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- ── Service role bypass ─────────────────────────────────

DROP POLICY IF EXISTS "srv people.personas" ON people.personas;
CREATE POLICY "srv people.personas" ON people.personas FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv people.persona_style_profile" ON people.persona_style_profile;
CREATE POLICY "srv people.persona_style_profile" ON people.persona_style_profile FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv people.world_locations" ON people.world_locations;
CREATE POLICY "srv people.world_locations" ON people.world_locations FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv people.world_wardrobe_items" ON people.world_wardrobe_items;
CREATE POLICY "srv people.world_wardrobe_items" ON people.world_wardrobe_items FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv people.licensing_policies" ON people.licensing_policies;
CREATE POLICY "srv people.licensing_policies" ON people.licensing_policies FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv people.persona_members" ON people.persona_members;
CREATE POLICY "srv people.persona_members" ON people.persona_members FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.user_preferences" ON moments.user_preferences;
CREATE POLICY "srv moments.user_preferences" ON moments.user_preferences FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.content_plans" ON moments.content_plans;
CREATE POLICY "srv moments.content_plans" ON moments.content_plans FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.plan_blocks" ON moments.plan_blocks;
CREATE POLICY "srv moments.plan_blocks" ON moments.plan_blocks FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.moments" ON moments.moments;
CREATE POLICY "srv moments.moments" ON moments.moments FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.moment_context" ON moments.moment_context;
CREATE POLICY "srv moments.moment_context" ON moments.moment_context FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.planner_runs" ON moments.planner_runs;
CREATE POLICY "srv moments.planner_runs" ON moments.planner_runs FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.usage_stats" ON moments.usage_stats;
CREATE POLICY "srv moments.usage_stats" ON moments.usage_stats FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.world_state" ON moments.world_state;
CREATE POLICY "srv moments.world_state" ON moments.world_state FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.generation_jobs" ON moments.generation_jobs;
CREATE POLICY "srv moments.generation_jobs" ON moments.generation_jobs FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.deliveries" ON moments.deliveries;
CREATE POLICY "srv moments.deliveries" ON moments.deliveries FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv moments.notifications" ON moments.notifications;
CREATE POLICY "srv moments.notifications" ON moments.notifications FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMIT;
