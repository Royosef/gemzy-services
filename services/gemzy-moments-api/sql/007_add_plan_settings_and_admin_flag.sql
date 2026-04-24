-- Create plan settings table for configurable credit allocations and add
-- an administrative flag to user profiles.
begin;

create table if not exists public.plan_settings (
  plan public.plan_tier primary key,
  initial_credits integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

insert into public.plan_settings (plan, initial_credits) values
  ('Free', 100),
  ('Pro', 500),
  ('Designer', 1000)
on conflict (plan) do update set initial_credits = excluded.initial_credits;

alter table if exists public.profiles
  add column if not exists is_admin boolean not null default false;

-- Ensure the plan settings table keeps updated_at fresh.
do $$
begin
  if not exists (
    select 1 from pg_trigger where tgname = 'plan_settings_set_updated_at'
  ) then
    create trigger plan_settings_set_updated_at
      before update on public.plan_settings
      for each row
      execute function public.set_updated_at();
  end if;
end$$;

commit;
