-- Add avatar URL and notification preference storage to profiles.
begin;

alter table if exists public.profiles
  add column if not exists avatar_url text;

alter table if exists public.profiles
  add column if not exists notification_preferences jsonb;

update public.profiles
set notification_preferences = jsonb_build_object(
  'gemzyUpdates', true,
  'personalUpdates', true,
  'email', true
)
where notification_preferences is null;

alter table if exists public.profiles
  alter column notification_preferences set default jsonb_build_object(
    'gemzyUpdates', true,
    'personalUpdates', true,
    'email', true
  );

alter table if exists public.profiles
  alter column notification_preferences set not null;

commit;
