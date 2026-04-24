alter table public.collection_items
    add column if not exists user_id uuid;

-- align the uniqueness constraint to be per collection
alter table public.collection_items
    drop constraint if exists collection_items_external_id_key;

create unique index if not exists collection_items_external_idx
    on public.collection_items (collection_id, external_id);

update public.collection_items as ci
set user_id = c.user_id
from public.collections as c
where ci.collection_id = c.id
  and (ci.user_id is null or ci.user_id <> c.user_id);

alter table public.collection_items
    alter column user_id set not null;

alter table public.collection_items
    drop constraint if exists collection_items_user_id_fkey;

alter table public.collection_items
    add constraint collection_items_user_id_fkey
        foreign key (user_id) references public.profiles(id) on delete cascade;

create index if not exists collection_items_user_created_idx
    on public.collection_items (user_id, created_at desc);
