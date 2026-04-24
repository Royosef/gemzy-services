-- Persist style trial state on the profiles table so trial usage is shared
-- across devices for the same user.

ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS on_model_style_trials JSONB;

ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS pure_jewelry_style_trials JSONB;

UPDATE public.profiles
SET on_model_style_trials = '{"pendingSelectionKeys":[],"remainingUses":3}'::jsonb
WHERE on_model_style_trials IS NULL;

UPDATE public.profiles
SET pure_jewelry_style_trials = '{"pendingSelectionKeys":[],"remainingUses":3}'::jsonb
WHERE pure_jewelry_style_trials IS NULL;

ALTER TABLE public.profiles
ALTER COLUMN on_model_style_trials SET DEFAULT '{"pendingSelectionKeys":[],"remainingUses":3}'::jsonb;

ALTER TABLE public.profiles
ALTER COLUMN pure_jewelry_style_trials SET DEFAULT '{"pendingSelectionKeys":[],"remainingUses":3}'::jsonb;

ALTER TABLE public.profiles
ALTER COLUMN on_model_style_trials SET NOT NULL;

ALTER TABLE public.profiles
ALTER COLUMN pure_jewelry_style_trials SET NOT NULL;
