-- Enable required extensions
create extension if not exists "uuid-ossp";
create extension if not exists pgcrypto;

-- User collections
create table if not exists public.collections (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    slug text unique not null,
    name text not null,
    cover_url text,
    curated_by text,
    description text,
    tags text[] not null default '{}',
    liked boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists collections_user_id_created_at_idx
    on public.collections(user_id, created_at desc);

-- Individual assets inside a collection
create table if not exists public.collection_items (
    id uuid primary key default uuid_generate_v4(),
    collection_id uuid not null references public.collections(id) on delete cascade,
    user_id uuid not null references public.profiles(id) on delete cascade,
    external_id text not null,
    image_url text not null,
    category text,
    model_id text,
    model_name text,
    is_new boolean not null default false,
    is_favorite boolean not null default false,
    metadata jsonb,
    created_at timestamptz not null default now()
);

create index if not exists collection_items_collection_idx
    on public.collection_items(collection_id, created_at desc);

create index if not exists collection_items_user_created_idx
    on public.collection_items(user_id, created_at desc);

create unique index if not exists collection_items_external_idx
    on public.collection_items(collection_id, external_id);

-- Gemzy model catalog
create table if not exists public.models (
    id uuid primary key default uuid_generate_v4(),
    slug text unique not null,
    name text not null,
    plan text not null,
    highlight text,
    description text,
    image_url text not null,
    tags text[] not null default '{}',
    spotlight_tag text,
    created_at timestamptz not null default now()
);

create table if not exists public.model_likes (
    user_id uuid not null references public.profiles(id) on delete cascade,
    model_id uuid not null references public.models(id) on delete cascade,
    liked_at timestamptz not null default now(),
    primary key (user_id, model_id)
);

create table if not exists public.model_gallery (
    id uuid primary key default uuid_generate_v4(),
    model_id uuid not null references public.models(id) on delete cascade,
    image_url text not null,
    created_at timestamptz not null default now()
);

create index if not exists model_gallery_model_idx
    on public.model_gallery(model_id, created_at desc);

-- --------------------------------------------
-- Seed data used by the mobile client
-- --------------------------------------------
-- Default demo user (matches onboarding mocks)
insert into public.profiles (id, name, plan, credits)
values (
    '00000000-0000-0000-0000-000000000001',
    'Zaya Amune',
    'Free',
    480
)
on conflict (id) do update set
    name = excluded.name,
    plan = excluded.plan,
    credits = excluded.credits;

-- Collections
insert into public.collections (id, user_id, slug, name, cover_url, curated_by, description, tags, liked, created_at)
values
    ('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-000000000001', 'dan-earrings', 'Dan Earrings', NULL, 'Zaya Amune', 'Premium earrings and necklaces captured for the spring campaign.', array['New collection'], false, '2025-03-22T10:00:00Z'),
    ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-000000000001', 'neo-collection', 'Neo''s collection', NULL, 'Neo Lapah', 'Studio portraits focused on light experimentation.', array['Trending'], true, '2025-02-18T14:00:00Z'),
    ('33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-000000000001', 'john-shoot', 'John''s collection', NULL, 'John Snow', 'You know nothing.', array['Editor''s pick'], true, '2025-06-23T09:00:00Z'),
    ('44444444-4444-4444-4444-444444444444', '00000000-0000-0000-0000-000000000001', 'drafts', 'Draft Images', NULL, 'Sofia Muller', 'Experiments waiting for review before the final upload.', array['Draft Images'], false, '2025-01-03T08:00:00Z')
on conflict (slug) do update set
    name = excluded.name,
    curated_by = excluded.curated_by,
    description = excluded.description,
    tags = excluded.tags,
    liked = excluded.liked,
    created_at = excluded.created_at;

with data(collection_slug, external_id, image_url, category, is_new, is_favorite) as (
    values
        ('dan-earrings', 'dan-1', 'https://picsum.photos/seed/6521326541216541561234_1/800/800', NULL, false, false),
        ('dan-earrings', 'dan-2', 'https://picsum.photos/seed/652146584564_1/800/800', 'Necklaces', true, false),
        ('dan-earrings', 'dan-3', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop', 'Earrings', false, false),
        ('dan-earrings', 'dan-4', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop', 'Necklaces', true, false),
        ('dan-earrings', 'dan-5', 'https://images.unsplash.com/photo-1522312346375-d1a52e2b99b3?w=800&auto=format&fit=crop', 'Bracelets', false, false),
        ('dan-earrings', 'dan-6', 'https://images.unsplash.com/photo-1462396881884-de2c07cb95ed?w=800&auto=format&fit=crop', 'Earrings', false, false),
        ('dan-earrings', 'dan-7', 'https://images.unsplash.com/photo-1520962918287-7448c2878f65?w=800&auto=format&fit=crop', 'Necklaces', false, true),
        ('dan-earrings', 'dan-8', 'https://images.unsplash.com/photo-1514996937319-344454492b37?w=800&auto=format&fit=crop', 'Rings', false, false),
        ('dan-earrings', 'dan-9', 'https://images.unsplash.com/photo-1487412720507-e7ab37603c6f?w=800&auto=format&fit=crop', 'Bracelets', false, false),
        ('dan-earrings', 'dan-10', 'https://images.unsplash.com/photo-1522312346375-d1a52e2b99b3?w=800&auto=format&fit=crop', 'Bracelets', false, true),
        ('dan-earrings', 'dan-11', 'https://images.unsplash.com/photo-1543294001-f7cd5d7fb516?w=800&auto=format&fit=crop', 'Necklaces', false, false),
        ('dan-earrings', 'dan-12', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop', 'Necklaces', true, true),
        ('neo-collection', 'neo-1', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop', 'Necklaces', false, true),
        ('neo-collection', 'neo-2', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop', NULL, false, false),
        ('neo-collection', 'neo-3', 'https://images.unsplash.com/photo-1516637090014-cb1ab0d08fc7?w=800&auto=format&fit=crop', 'Earrings', true, false),
        ('neo-collection', 'neo-4', 'https://images.unsplash.com/photo-1543294001-f7cd5d7fb516?w=800&auto=format&fit=crop', NULL, false, false),
        ('neo-collection', 'neo-5', 'https://images.unsplash.com/photo-1520962918287-7448c2878f65?w=800&auto=format&fit=crop', NULL, false, false),
        ('neo-collection', 'neo-6', 'https://images.unsplash.com/photo-1504595403659-9088ce801e29?w=800&auto=format&fit=crop', 'Rings', false, false),
        ('neo-collection', 'neo-7', 'https://images.unsplash.com/photo-1462396881884-de2c07cb95ed?w=800&auto=format&fit=crop', NULL, false, false),
        ('neo-collection', 'neo-8', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop', 'Earrings', false, false),
        ('john-shoot', 'john-1', 'https://picsum.photos/seed/6521326541216541561234_1/800/800', NULL, false, false),
        ('john-shoot', 'john-2', 'https://picsum.photos/seed/652146584564_1/800/800', 'Necklaces', true, false),
        ('john-shoot', 'john-3', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop', 'Earrings', false, false),
        ('john-shoot', 'john-4', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop', 'Necklaces', true, false),
        ('john-shoot', 'john-5', 'https://images.unsplash.com/photo-1522312346375-d1a52e2b99b3?w=800&auto=format&fit=crop', 'Bracelets', false, false),
        ('john-shoot', 'john-6', 'https://images.unsplash.com/photo-1462396881884-de2c07cb95ed?w=800&auto=format&fit=crop', 'Earrings', false, false),
        ('john-shoot', 'john-7', 'https://images.unsplash.com/photo-1520962918287-7448c2878f65?w=800&auto=format&fit=crop', 'Necklaces', false, true),
        ('john-shoot', 'john-8', 'https://images.unsplash.com/photo-1514996937319-344454492b37?w=800&auto=format&fit=crop', 'Rings', false, false),
        ('john-shoot', 'john-9', 'https://images.unsplash.com/photo-1487412720507-e7ab37603c6f?w=800&auto=format&fit=crop', 'Bracelets', false, false),
        ('john-shoot', 'john-10', 'https://images.unsplash.com/photo-1522312346375-d1a52e2b99b3?w=800&auto=format&fit=crop', 'Bracelets', false, true),
        ('john-shoot', 'john-11', 'https://images.unsplash.com/photo-1543294001-f7cd5d7fb516?w=800&auto=format&fit=crop', 'Necklaces', false, false),
        ('john-shoot', 'john-12', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop', 'Necklaces', true, true),
        ('drafts', 'unsaved-1', 'https://images.unsplash.com/photo-1504595403659-9088ce801e29?w=800&auto=format&fit=crop', NULL, false, false),
        ('drafts', 'unsaved-2', 'https://images.unsplash.com/photo-1522312346375-d1a52e2b99b3?w=800&auto=format&fit=crop', NULL, false, false),
        ('drafts', 'unsaved-3', 'https://images.unsplash.com/photo-1514996937319-344454492b37?w=800&auto=format&fit=crop', NULL, false, false),
        ('drafts', 'unsaved-4', 'https://images.unsplash.com/photo-1520962918287-7448c2878f65?w=800&auto=format&fit=crop', NULL, false, false)
)
insert into public.collection_items (collection_id, user_id, external_id, image_url, category, is_new, is_favorite)
select
    (select id from public.collections where slug = data.collection_slug),
    (select user_id from public.collections where slug = data.collection_slug),
    data.external_id,
    data.image_url,
    data.category,
    data.is_new,
    data.is_favorite
from data
on conflict (collection_id, external_id) do update set
    user_id = excluded.user_id,
    image_url = excluded.image_url,
    category = excluded.category,
    is_new = excluded.is_new,
    is_favorite = excluded.is_favorite;

-- Update collection cover image from first item
update public.collections c
set cover_url = ci.image_url
from (
    select distinct on (collection_id) collection_id, image_url
    from public.collection_items
    order by collection_id, created_at desc
) as ci
where ci.collection_id = c.id;

-- Models catalog seed
insert into public.models (id, slug, name, plan, highlight, description, image_url, tags, spotlight_tag)
values
    ('aaaa1111-1111-1111-1111-111111111111', 'zaya-free', 'Zaya Amune', 'Free', 'Rising Star', 'Elegant and poised, this model exudes quiet confidence with her sleek features and timeless stare.', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop', array['discover','spotlight','portrait'], 'Rising Star'),
    ('bbbb2222-2222-2222-2222-222222222222', 'zaya-pro', 'Zaya Amune', 'Pro', 'Top Model', 'Refined lighting brings out the soft sheen of jewelry while preserving a natural expression.', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop', array['favorite','portrait'], 'Top Model'),
    ('cccc3333-3333-3333-3333-333333333333', 'zaya-designer', 'Zaya Amune', 'Designer', 'Designer’s Choice', 'High contrast styling with editorial posing for hero campaign imagery.', 'https://images.unsplash.com/photo-1520962918287-7448c2878f65?w=800&auto=format&fit=crop', array['discover','editorial'], 'Designer’s Choice'),
    ('dddd4444-4444-4444-4444-444444444444', 'sofia-pro', 'Sofia Muller', 'Pro', 'All-Round Talent', 'Movement-driven capture that balances flowy silhouettes with product focus.', 'https://images.unsplash.com/photo-1517841905240-472988babdf9?w=800&auto=format&fit=crop', array['runway','portrait'], 'All-Round Talent'),
    ('eeee5555-5555-5555-5555-555555555555', 'neo-free', 'Neo Lapah', 'Free', 'Creative Partner', 'Playful experimentation with lighting and angles to spotlight accessories.', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop', array['studio','portrait'], null),
    ('ffff6666-6666-6666-6666-666666666666', 'noa-designer', 'Noa Rivers', 'Designer', 'All-Round Talent', 'Bold editorial presence made for premium catalog spreads.', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop', array['editorial','favorite'], 'All-Round Talent')
on conflict (slug) do update set
    name = excluded.name,
    plan = excluded.plan,
    highlight = excluded.highlight,
    description = excluded.description,
    image_url = excluded.image_url,
    tags = excluded.tags,
    spotlight_tag = excluded.spotlight_tag;

with gallery(model_slug, image_url) as (
    values
        ('zaya-free', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop'),
        ('zaya-free', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop'),
        ('zaya-free', 'https://images.unsplash.com/photo-1522312346375-d1a52e2b99b3?w=800&auto=format&fit=crop'),
        ('zaya-free', 'https://images.unsplash.com/photo-1504595403659-9088ce801e29?w=800&auto=format&fit=crop'),
        ('zaya-pro', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop'),
        ('zaya-pro', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop'),
        ('zaya-pro', 'https://images.unsplash.com/photo-1522312346375-d1a52e2b99b3?w=800&auto=format&fit=crop'),
        ('zaya-pro', 'https://images.unsplash.com/photo-1504595403659-9088ce801e29?w=800&auto=format&fit=crop'),
        ('zaya-designer', 'https://images.unsplash.com/photo-1520962918287-7448c2878f65?w=800&auto=format&fit=crop'),
        ('zaya-designer', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop'),
        ('zaya-designer', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop'),
        ('zaya-designer', 'https://images.unsplash.com/photo-1517841905240-472988babdf9?w=800&auto=format&fit=crop'),
        ('sofia-pro', 'https://images.unsplash.com/photo-1517841905240-472988babdf9?w=800&auto=format&fit=crop'),
        ('sofia-pro', 'https://images.unsplash.com/photo-1522312346375-d1a52e2b99b3?w=800&auto=format&fit=crop'),
        ('sofia-pro', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop'),
        ('sofia-pro', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop'),
        ('neo-free', 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop'),
        ('neo-free', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop'),
        ('neo-free', 'https://images.unsplash.com/photo-1516637090014-cb1ab0d08fc7?w=800&auto=format&fit=crop'),
        ('neo-free', 'https://images.unsplash.com/photo-1504595403659-9088ce801e29?w=800&auto=format&fit=crop'),
        ('noa-designer', 'https://images.unsplash.com/photo-1522312346375-d1a52e2b99b3?w=800&auto=format&fit=crop'),
        ('noa-designer', 'https://images.unsplash.com/photo-1520962918287-7448c2878f65?w=800&auto=format&fit=crop'),
        ('noa-designer', 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=800&auto=format&fit=crop'),
        ('noa-designer', 'https://images.unsplash.com/photo-1504595403659-9088ce801e29?w=800&auto=format&fit=crop')
)
insert into public.model_gallery (model_id, image_url)
select
    (select id from public.models where slug = gallery.model_slug),
    gallery.image_url
from gallery
on conflict do nothing;

