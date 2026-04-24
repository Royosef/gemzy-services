alter table public.collection_items
    add column if not exists metadata jsonb;
