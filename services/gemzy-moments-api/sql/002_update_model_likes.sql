-- Update the models schema to support per-user likes.
alter table if exists public.models
    drop column if exists role;

alter table if exists public.models
    drop column if exists liked;

create table if not exists public.model_likes (
    user_id uuid not null references public.profiles(id) on delete cascade,
    model_id uuid not null references public.models(id) on delete cascade,
    liked_at timestamptz not null default now(),
    primary key (user_id, model_id)
);
