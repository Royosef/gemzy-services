-- Drop redundant member tables and ordering columns.
begin;

drop index if exists public.collection_items_collection_idx;
alter table if exists public.collection_items drop column if exists sort_order;
create index if not exists collection_items_collection_idx on public.collection_items (collection_id, created_at desc);

drop index if exists public.model_gallery_model_idx;
alter table if exists public.model_gallery drop column if exists display_order;
create index if not exists model_gallery_model_idx on public.model_gallery (model_id, created_at desc);

alter table if exists public.models drop column if exists hero_order;

drop table if exists public.collection_members;
drop table if exists public.members;

commit;
