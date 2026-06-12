-- Humanized persona system foundation for gemzy-api + gemzy-dashboard.
-- Reuses the existing people/moments domains when present and adds the
-- richer canonical + automation tables needed by the dashboard.

create schema if not exists people;
create schema if not exists moments;

alter table if exists people.personas
  add column if not exists updated_at timestamptz not null default now();

alter table if exists people.world_locations
  add column if not exists description text,
  add column if not exists visual_notes text,
  add column if not exists lighting_notes text,
  add column if not exists emotional_association text;

alter table if exists people.world_wardrobe_items
  add column if not exists description text,
  add column if not exists suitability_tags jsonb not null default '[]'::jsonb,
  add column if not exists signature_item boolean not null default false,
  add column if not exists favorite_item boolean not null default false;

create table if not exists people.persona_profiles (
  persona_id uuid primary key references people.personas(id) on delete cascade,
  full_name text,
  social_handle text,
  age_range text,
  gender_expression text,
  cultural_background text,
  languages jsonb not null default '[]'::jsonb,
  city_region text,
  occupation text,
  public_bio text,
  internal_bio text,
  lifecycle_status text not null default 'draft'
    check (lifecycle_status in ('draft', 'active', 'paused', 'archived')),
  visibility text not null default 'private'
    check (visibility in ('private', 'public', 'exclusive')),
  brand_context jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists people.persona_personality (
  persona_id uuid primary key references people.personas(id) on delete cascade,
  personality_summary text,
  dominant_traits jsonb not null default '[]'::jsonb,
  secondary_traits jsonb not null default '[]'::jsonb,
  values jsonb not null default '[]'::jsonb,
  ambitions jsonb not null default '[]'::jsonb,
  vulnerabilities text,
  humor_style text,
  social_energy text,
  confidence_level text,
  communication_style text,
  emotional_range jsonb not null default '[]'::jsonb,
  state_rules jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists people.persona_outfits (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references people.personas(id) on delete cascade,
  name text not null,
  description text,
  wardrobe_item_ids jsonb not null default '[]'::jsonb,
  suitable_occasions jsonb not null default '[]'::jsonb,
  season_tags jsonb not null default '[]'::jsonb,
  mood_tags jsonb not null default '[]'::jsonb,
  reference_image_url text,
  reuse_cooldown_hours integer not null default 0,
  signature_look boolean not null default false,
  last_used_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_persona_outfits_persona
  on people.persona_outfits(persona_id, created_at desc);

create table if not exists people.persona_home_spaces (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references people.personas(id) on delete cascade,
  name text not null,
  room_type text,
  description text,
  visual_traits jsonb not null default '[]'::jsonb,
  lighting_notes text,
  signature_use_cases jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists people.persona_objects (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references people.personas(id) on delete cascade,
  name text not null,
  object_type text,
  description text,
  visual_traits jsonb not null default '[]'::jsonb,
  emotional_role text,
  recurring_contexts jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists people.persona_relationships (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references people.personas(id) on delete cascade,
  name text,
  relationship_type text not null default 'friend',
  summary text,
  visibility text not null default 'internal',
  emotional_tone text,
  recurring_contexts jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table if exists people.persona_home_spaces
  add column if not exists room_type text,
  add column if not exists visual_traits jsonb not null default '[]'::jsonb,
  add column if not exists signature_use_cases jsonb not null default '[]'::jsonb;

alter table if exists people.persona_objects
  add column if not exists visual_traits jsonb not null default '[]'::jsonb,
  add column if not exists emotional_role text,
  add column if not exists recurring_contexts jsonb not null default '[]'::jsonb;

alter table if exists people.persona_relationships
  add column if not exists summary text,
  add column if not exists visibility text not null default 'internal',
  add column if not exists emotional_tone text,
  add column if not exists recurring_contexts jsonb not null default '[]'::jsonb;

create table if not exists people.persona_routines (
  persona_id uuid primary key references people.personas(id) on delete cascade,
  wake_up_time text,
  working_hours jsonb not null default '{}'::jsonb,
  morning_rituals jsonb not null default '[]'::jsonb,
  exercise_habits jsonb not null default '[]'::jsonb,
  evening_patterns jsonb not null default '[]'::jsonb,
  weekend_behavior jsonb not null default '[]'::jsonb,
  posting_rhythm jsonb not null default '{}'::jsonb,
  travel_frequency text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists people.persona_interests (
  persona_id uuid primary key references people.personas(id) on delete cascade,
  strong_interests jsonb not null default '[]'::jsonb,
  occasional_interests jsonb not null default '[]'::jsonb,
  skills jsonb not null default '[]'::jsonb,
  hobbies jsonb not null default '[]'::jsonb,
  cultural_tastes jsonb not null default '[]'::jsonb,
  wellness_habits jsonb not null default '[]'::jsonb,
  food_preferences jsonb not null default '[]'::jsonb,
  travel_preferences jsonb not null default '[]'::jsonb,
  shopping_behavior jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists people.persona_canonical_memories (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references people.personas(id) on delete cascade,
  title text not null,
  memory_type text not null default 'canonical',
  summary text not null,
  importance_score integer not null default 3 check (importance_score between 1 and 5),
  occurred_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_persona_memories_persona
  on people.persona_canonical_memories(persona_id, created_at desc);

create table if not exists people.persona_world_addition_requests (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references people.personas(id) on delete cascade,
  source_kind text,
  source_id uuid,
  item_type text not null,
  proposed_name text,
  proposed_payload jsonb not null default '{}'::jsonb,
  status text not null default 'suggested'
    check (status in ('suggested', 'approved', 'rejected', 'moment_only')),
  reviewer_user_id uuid,
  review_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_persona_world_additions_persona
  on people.persona_world_addition_requests(persona_id, created_at desc);

create table if not exists moments.persona_automation_settings (
  persona_id uuid primary key references people.personas(id) on delete cascade,
  enabled boolean not null default false,
  autonomy_mode text not null default 'QUEUE_DRAFTS'
    check (autonomy_mode in ('QUEUE_DRAFTS', 'AUTO_PUBLISH', 'MIXED_RULES')),
  cadence_hours integer not null default 24,
  spontaneity numeric(4,3) not null default 0.350,
  novelty_rate numeric(4,3) not null default 0.150,
  allowed_content_types jsonb not null default '["story","post"]'::jsonb,
  boundaries jsonb not null default '{}'::jsonb,
  campaign_override_policy text not null default 'require_brief',
  require_manual_publish boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists moments.persona_runtime_state (
  persona_id uuid primary key references people.personas(id) on delete cascade,
  current_mode text not null default 'idle',
  last_run_at timestamptz,
  next_run_at timestamptz,
  pause_reason text,
  pending_approval_count integer not null default 0,
  active_campaign_context jsonb not null default '{}'::jsonb,
  last_error text,
  updated_at timestamptz not null default now()
);

create table if not exists moments.persona_automation_runs (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references people.personas(id) on delete cascade,
  trigger_source text,
  status text not null default 'ready'
    check (status in ('ready', 'blocked', 'needs_campaign_brief', 'failed')),
  context_summary text,
  input_prompt text,
  output_payload jsonb not null default '{}'::jsonb,
  blocked_reason text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists idx_persona_automation_runs_persona
  on moments.persona_automation_runs(persona_id, created_at desc);

create table if not exists moments.persona_content_queue (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references people.personas(id) on delete cascade,
  run_id uuid references moments.persona_automation_runs(id) on delete set null,
  title text not null,
  content_type text not null,
  status text not null default 'draft'
    check (status in ('draft', 'approved', 'rejected', 'published', 'held')),
  scheduled_for timestamptz,
  caption text,
  visual_direction text,
  continuity_reason text,
  novelty boolean not null default false,
  queue_payload jsonb not null default '{}'::jsonb,
  requires_approval boolean not null default true,
  campaign_id text,
  approved_by_user_id uuid,
  approved_at timestamptz,
  published_at timestamptz,
  rejection_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_persona_content_queue_persona
  on moments.persona_content_queue(persona_id, created_at desc);

create index if not exists idx_persona_content_queue_status
  on moments.persona_content_queue(persona_id, status, requires_approval);

create table if not exists moments.persona_audit_events (
  id uuid primary key default gen_random_uuid(),
  persona_id uuid not null references people.personas(id) on delete cascade,
  event_type text not null,
  actor_type text not null,
  actor_id text,
  summary text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_persona_audit_events_persona
  on moments.persona_audit_events(persona_id, created_at desc);
