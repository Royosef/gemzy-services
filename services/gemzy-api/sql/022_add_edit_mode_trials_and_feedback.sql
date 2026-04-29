create extension if not exists pgcrypto;

alter table public.profiles
add column if not exists edit_mode_trial_edits_remaining integer;

update public.profiles
set edit_mode_trial_edits_remaining = 2
where edit_mode_trial_edits_remaining is null;

alter table public.profiles
alter column edit_mode_trial_edits_remaining set default 2;

alter table public.profiles
alter column edit_mode_trial_edits_remaining set not null;

alter table public.profiles
drop constraint if exists profiles_edit_mode_trial_edits_remaining_check;

alter table public.profiles
add constraint profiles_edit_mode_trial_edits_remaining_check
check (edit_mode_trial_edits_remaining >= 0 and edit_mode_trial_edits_remaining <= 2);

create table if not exists public.image_edit_feedback (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  edit_job_id text not null,
  source_key text,
  rating text not null check (rating in ('awesome', 'good', 'okay', 'bad', 'very_bad')),
  comment text,
  edit_option_ids text[] not null default '{}',
  edit_labels text[] not null default '{}',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

do $$
begin
  if not exists (
    select 1 from pg_trigger where tgname = 'image_edit_feedback_set_updated_at'
  ) then
    create trigger image_edit_feedback_set_updated_at
      before update on public.image_edit_feedback
      for each row
      execute function public.set_updated_at();
  end if;
end$$;

create index if not exists image_edit_feedback_user_created_idx
  on public.image_edit_feedback (user_id, created_at desc);

create index if not exists image_edit_feedback_edit_job_idx
  on public.image_edit_feedback (edit_job_id);

create index if not exists image_edit_feedback_rating_idx
  on public.image_edit_feedback (rating);
