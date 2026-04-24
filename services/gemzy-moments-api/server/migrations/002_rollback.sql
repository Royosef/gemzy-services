-- ============================================================
-- Billing — ROLLBACK Migration
-- Reverses 002_billing_shared.sql
-- WARNING: This will DROP all billing data across ALL apps.
-- Only run if you want to completely remove the billing system.
-- ============================================================

BEGIN;

DROP TABLE IF EXISTS public.app_plans CASCADE;
DROP TABLE IF EXISTS public.user_entitlements CASCADE;
DROP TABLE IF EXISTS public.credit_ledger CASCADE;
DROP TABLE IF EXISTS public.user_wallets CASCADE;
DROP TABLE IF EXISTS public.apps CASCADE;

COMMIT;
