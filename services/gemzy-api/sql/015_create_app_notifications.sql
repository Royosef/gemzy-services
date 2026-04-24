create extension if not exists pgcrypto;

create table if not exists public.app_notifications (
  id uuid primary key default gen_random_uuid(),
  entity_key text not null unique,
  category text not null check (category in ('general', 'personal')),
  kind text not null,
  title text not null,
  body text not null,
  action_pathname text,
  action_params jsonb,
  action_url text,
  target_user_id uuid references public.profiles(id) on delete cascade,
  published_by uuid references public.profiles(id) on delete set null,
  is_active boolean not null default true,
  expires_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists app_notifications_created_at_idx
  on public.app_notifications (created_at desc);

create index if not exists app_notifications_target_user_id_idx
  on public.app_notifications (target_user_id);

create index if not exists app_notifications_is_active_idx
  on public.app_notifications (is_active);
