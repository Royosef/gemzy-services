-- ============================================================
-- Gemzy Ecosystem — Billing & Entitlements (Shared)
-- This migration is SHARED between Gemzy Core and Gemzy Moments.
-- It creates app-scoped billing tables in the public schema.
-- Safe to re-run: fully idempotent.
-- ============================================================

BEGIN;

-- ── App Definitions ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.apps (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL
);

INSERT INTO public.apps (id, name) VALUES
    ('core', 'Gemzy Core'),
    ('moments', 'Gemzy Moments'),
    ('people', 'Gemzy People')
ON CONFLICT (id) DO NOTHING;

-- ── User Wallets (credits per app) ──────────────────────

CREATE TABLE IF NOT EXISTS public.user_wallets (
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    app_id          TEXT NOT NULL REFERENCES public.apps(id),
    credit_balance  INT NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, app_id)
);

CREATE INDEX IF NOT EXISTS idx_wallets_user ON public.user_wallets(user_id);

-- ── Credit Ledger (auditable transaction log) ───────────

CREATE TABLE IF NOT EXISTS public.credit_ledger (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    app_id      TEXT NOT NULL REFERENCES public.apps(id),
    delta       INT NOT NULL,
    reason      TEXT NOT NULL
                CHECK (reason IN ('purchase', 'generation', 'refund', 'bonus', 'subscription', 'plan_confirmed', 'moment_generated')),
    ref_type    TEXT,
    ref_id      UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ledger_user_app ON public.credit_ledger(user_id, app_id);
CREATE INDEX IF NOT EXISTS idx_ledger_created ON public.credit_ledger(created_at DESC);

-- ── User Entitlements (subscriptions per app) ───────────

CREATE TABLE IF NOT EXISTS public.user_entitlements (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    app_id          TEXT NOT NULL REFERENCES public.apps(id),
    entitlement     TEXT NOT NULL DEFAULT 'free'
                    CHECK (entitlement IN ('free', 'pro', 'creator', 'agency')),
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'inactive', 'expired')),
    expires_at      TIMESTAMPTZ,
    source          TEXT
                    CHECK (source IS NULL OR source IN ('revenuecat', 'appstore', 'play', 'stripe', 'manual')),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, app_id)
);

CREATE INDEX IF NOT EXISTS idx_entitlements_user ON public.user_entitlements(user_id);
CREATE INDEX IF NOT EXISTS idx_entitlements_active ON public.user_entitlements(user_id, app_id) WHERE status = 'active';

-- ── App Plans (entitlement limits per app tier) ─────────

CREATE TABLE IF NOT EXISTS public.app_plans (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id              TEXT NOT NULL REFERENCES public.apps(id),
    entitlement         TEXT NOT NULL
                        CHECK (entitlement IN ('free', 'pro', 'creator', 'agency')),
    monthly_credits     INT NOT NULL DEFAULT 0,
    max_personas        INT,
    max_days_planned    INT,
    max_rerolls         INT,
    features            JSONB DEFAULT '{}',
    UNIQUE (app_id, entitlement)
);

-- Seed default plan configs
INSERT INTO public.app_plans (app_id, entitlement, monthly_credits, max_personas, max_days_planned, max_rerolls, features) VALUES
    ('moments', 'free',    10,   1,  3,   2,  '{"basic_templates": true}'),
    ('moments', 'pro',     100,  5,  30,  10, '{"basic_templates": true, "custom_styles": true, "priority_generation": true}'),
    ('moments', 'creator', 500,  20, 90,  50, '{"basic_templates": true, "custom_styles": true, "priority_generation": true, "api_access": true}'),
    ('core',    'free',    5,    NULL, NULL, 2,  '{"basic_generation": true}'),
    ('core',    'pro',     50,   NULL, NULL, 20, '{"basic_generation": true, "hd_generation": true, "video": true}'),
    ('core',    'creator', 200,  NULL, NULL, 100,'{"basic_generation": true, "hd_generation": true, "video": true, "api_access": true}')
ON CONFLICT (app_id, entitlement) DO NOTHING;


-- ============================================================
-- RLS POLICIES (idempotent)
-- ============================================================

ALTER TABLE public.apps                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_wallets        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.credit_ledger       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_entitlements   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_plans           ENABLE ROW LEVEL SECURITY;

-- Apps: anyone can read
DROP POLICY IF EXISTS "Anyone can read apps" ON public.apps;
CREATE POLICY "Anyone can read apps" ON public.apps FOR SELECT USING (true);

-- Wallets: users own their wallets
DROP POLICY IF EXISTS "Users own wallets" ON public.user_wallets;
CREATE POLICY "Users own wallets" ON public.user_wallets FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Ledger: users can read their own; only service role writes
DROP POLICY IF EXISTS "Users read own ledger" ON public.credit_ledger;
CREATE POLICY "Users read own ledger" ON public.credit_ledger FOR SELECT
    USING (user_id = auth.uid());

-- Entitlements: users can read their own
DROP POLICY IF EXISTS "Users read own entitlements" ON public.user_entitlements;
CREATE POLICY "Users read own entitlements" ON public.user_entitlements FOR SELECT
    USING (user_id = auth.uid());

-- App plans: anyone can read (public config)
DROP POLICY IF EXISTS "Anyone can read app plans" ON public.app_plans;
CREATE POLICY "Anyone can read app plans" ON public.app_plans FOR SELECT USING (true);

-- Service role bypass
DROP POLICY IF EXISTS "srv public.apps" ON public.apps;
CREATE POLICY "srv public.apps" ON public.apps FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv public.user_wallets" ON public.user_wallets;
CREATE POLICY "srv public.user_wallets" ON public.user_wallets FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv public.credit_ledger" ON public.credit_ledger;
CREATE POLICY "srv public.credit_ledger" ON public.credit_ledger FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv public.user_entitlements" ON public.user_entitlements;
CREATE POLICY "srv public.user_entitlements" ON public.user_entitlements FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "srv public.app_plans" ON public.app_plans;
CREATE POLICY "srv public.app_plans" ON public.app_plans FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMIT;
