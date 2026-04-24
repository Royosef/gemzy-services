create table if not exists public.push_tokens (
  token text primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  platform text not null check (platform in ('ios', 'android')),
  app_version text,
  is_active boolean not null default true,
  last_registered_at timestamptz not null default timezone('utc', now()),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists push_tokens_user_id_idx
  on public.push_tokens (user_id);

create index if not exists push_tokens_is_active_idx
  on public.push_tokens (is_active);
