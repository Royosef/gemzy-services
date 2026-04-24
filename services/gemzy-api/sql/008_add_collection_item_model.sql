alter table if exists public.collection_items
    add column if not exists model_id text,
    add column if not exists model_name text;

create index if not exists collection_items_model_idx
    on public.collection_items (model_id)
    where model_id is not null;
