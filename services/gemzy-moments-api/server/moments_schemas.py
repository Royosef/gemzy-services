"""Pydantic schemas for Gemzy Moments + People API.

Organized by schema boundary:
  - people.*  = Persona identity, world catalog, style profiles
  - moments.* = Plans, blocks, moments, context, usage, deliveries
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
#  PEOPLE SCHEMA
# ═══════════════════════════════════════════════════════════

# ── Persona ──────────────────────────────────────────────

class PersonaCreate(BaseModel):
    display_name: str
    bio: str | None = None
    avatar_url: str | None = None
    is_public: bool = False


class PersonaUpdate(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    is_public: bool | None = None


class PersonaResponse(BaseModel):
    id: str
    owner_user_id: str | None = None
    is_gemzy_owned: bool = False
    is_public: bool = False
    display_name: str
    bio: str | None = None
    avatar_url: str | None = None
    created_at: str
    updated_at: str


# ── Style Profile ────────────────────────────────────────

RealismLevel = Literal["low", "medium", "high", "hyper"]


class StyleProfileUpsert(BaseModel):
    realism_level: RealismLevel = "high"
    camera_style_tags: list[str] = Field(default_factory=list)
    color_palette_tags: list[str] = Field(default_factory=list)
    negative_rules: list[str] = Field(default_factory=list)


class StyleProfileResponse(BaseModel):
    persona_id: str
    realism_level: RealismLevel = "high"
    camera_style_tags: list[Any] = []
    color_palette_tags: list[Any] = []
    negative_rules: list[Any] = []
    created_at: str
    updated_at: str


# ── World Location ───────────────────────────────────────

Tier = Literal["ANCHOR", "SEMI_STABLE", "FLEX"]


class WorldLocationCreate(BaseModel):
    name: str
    tags: list[str] = Field(default_factory=list)
    tier: Tier = "SEMI_STABLE"
    reuse_weight: float = 1.0
    cooldown_hours: int = 0
    max_per_week: int | None = None


class WorldLocationResponse(BaseModel):
    id: str
    persona_id: str
    name: str
    tags: list[Any] = []
    tier: Tier = "SEMI_STABLE"
    reuse_weight: float = 1.0
    cooldown_hours: int = 0
    max_per_week: int | None = None
    ref_asset_id: str | None = None
    created_at: str


# ── World Wardrobe ───────────────────────────────────────

WardrobeCategory = Literal["top", "bottom", "dress", "shoes", "accessory", "set", "outerwear"]


class WorldWardrobeCreate(BaseModel):
    category: WardrobeCategory
    name: str
    tags: list[str] = Field(default_factory=list)
    tier: Tier = "SEMI_STABLE"
    reuse_weight: float = 1.0
    season_tags: list[str] = Field(default_factory=list)


class WorldWardrobeResponse(BaseModel):
    id: str
    persona_id: str
    category: WardrobeCategory
    name: str
    tags: list[Any] = []
    tier: Tier = "SEMI_STABLE"
    reuse_weight: float = 1.0
    season_tags: list[Any] = []
    ref_asset_id: str | None = None
    created_at: str


# ═══════════════════════════════════════════════════════════
#  MOMENTS SCHEMA
# ═══════════════════════════════════════════════════════════

# ── User Preferences ─────────────────────────────────────

class UserPreferencesUpsert(BaseModel):
    default_posts_per_day: int = 1
    default_stories_per_day: int = 3
    distribution_profile: dict[str, float] | None = None
    novelty_rate: float = 0.15


class UserPreferencesResponse(BaseModel):
    user_id: str
    default_posts_per_day: int = 1
    default_stories_per_day: int = 3
    distribution_profile: dict[str, Any] | None = None
    novelty_rate: float = 0.15
    created_at: str
    updated_at: str


# ── Content Plan ─────────────────────────────────────────

PlanType = Literal["DAY", "WEEK", "MONTH"]
PlanStatus = Literal[
    "DRAFT", "AWAITING_CONFIRMATION", "CONFIRMED",
    "GENERATING", "READY", "PARTIAL_READY", "FAILED",
]
TimeOfDay = Literal["morning", "midday", "afternoon", "evening", "late_night"]
MomentType = Literal["STORY", "POST"]
MomentStatus = Literal["PLANNED", "APPROVED", "GENERATING", "READY", "FAILED"]
JobStatus = Literal["queued", "running", "done", "failed"]


class ContentPlanCreate(BaseModel):
    persona_id: str
    plan_type: PlanType = "DAY"
    date_start: date
    date_end: date | None = None  # defaults to date_start for DAY
    source_prompt: str | None = None


class ContentPlanUpdate(BaseModel):
    source_prompt: str | None = None
    status: PlanStatus | None = None


class ContentPlanResponse(BaseModel):
    id: str
    persona_id: str
    owner_user_id: str
    plan_type: PlanType = "DAY"
    date_start: str
    date_end: str
    status: PlanStatus = "DRAFT"
    source_prompt: str | None = None
    created_at: str
    updated_at: str
    blocks: list[PlanBlockResponse] | None = None


# ── Plan Block ───────────────────────────────────────────

class PlanBlockCreate(BaseModel):
    time_of_day: TimeOfDay
    target_posts: int = 0
    target_stories: int = 1
    notes: str | None = None


class PlanBlockResponse(BaseModel):
    id: str
    plan_id: str
    time_of_day: TimeOfDay
    target_posts: int = 0
    target_stories: int = 1
    notes: str | None = None
    created_at: str
    moments: list[MomentResponse] | None = None


# ── Moment ───────────────────────────────────────────────

class MomentCreate(BaseModel):
    block_id: str | None = None
    moment_type: MomentType = "STORY"
    image_count: int = 1
    caption_hint: str | None = None


class MomentUpdate(BaseModel):
    moment_type: MomentType | None = None
    image_count: int | None = None
    caption_hint: str | None = None
    status: MomentStatus | None = None
    scheduled_at: str | None = None


class MomentResponse(BaseModel):
    id: str
    plan_id: str
    block_id: str | None = None
    moment_type: MomentType = "STORY"
    image_count: int = 1
    caption_hint: str | None = None
    status: MomentStatus = "PLANNED"
    scheduled_at: str | None = None
    created_at: str
    updated_at: str
    context: MomentContextResponse | None = None


# ── Moment Context ───────────────────────────────────────

class MomentContextUpsert(BaseModel):
    location_id: str | None = None
    wardrobe_item_ids: list[str] = Field(default_factory=list)
    outfit_composition: dict[str, Any] = Field(default_factory=dict)
    food_theme: dict[str, Any] | None = None
    mood_tags: list[str] = Field(default_factory=list)
    continuity_notes: str | None = None


class MomentContextResponse(BaseModel):
    moment_id: str
    location_id: str | None = None
    wardrobe_item_ids: list[str] = []
    outfit_composition: dict[str, Any] = {}
    food_theme: dict[str, Any] | None = None
    mood_tags: list[Any] = []
    continuity_notes: str | None = None


# ── Generation Job ───────────────────────────────────────

class GenerationJobResponse(BaseModel):
    id: str
    moment_id: str
    generation_provider: str | None = None
    status: JobStatus = "queued"
    cost_estimate: float | None = None
    attempts: int = 0
    result_urls: list[str] = []
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str


# ── Delivery ─────────────────────────────────────────────

class DeliveryResponse(BaseModel):
    id: str
    plan_id: str
    status: Literal["building", "ready", "failed"] = "building"
    zip_asset_id: str | None = None
    created_at: str


# ── Usage Stats ──────────────────────────────────────────

class UsageStatResponse(BaseModel):
    id: str
    persona_id: str
    item_type: str
    item_id: str
    last_used_at: str | None = None
    uses_7d: int = 0
    uses_30d: int = 0
    fatigue_score: float = 0.0
    updated_at: str


# ── World State ──────────────────────────────────────────

class WorldStateResponse(BaseModel):
    persona_id: str
    recent_location_ids: list[str] = []
    recent_outfit_hashes: list[str] = []
    cooldown_map: dict[str, Any] = {}
    updated_at: str


# ── Planner Output ───────────────────────────────────────

class PlannerSuggestedBlock(BaseModel):
    """A time-of-day block suggested by the planner."""
    time_of_day: TimeOfDay
    target_posts: int = 0
    target_stories: int = 1
    moments: list[PlannerSuggestedMoment]


class PlannerSuggestedMoment(BaseModel):
    """A single moment suggested by the planner."""
    moment_type: MomentType
    image_count: int = 1
    caption_hint: str
    context: MomentContextUpsert


class PlannerRunResponse(BaseModel):
    """Response from planner endpoint."""
    plan_id: str
    run_id: str
    version: int
    blocks: list[PlannerSuggestedBlock]



# Forward ref rebuilds
ContentPlanResponse.model_rebuild()
PlanBlockResponse.model_rebuild()
MomentResponse.model_rebuild()
PlannerSuggestedBlock.model_rebuild()


# ═══════════════════════════════════════════════════════════
#  BILLING (public schema)
# ═══════════════════════════════════════════════════════════

AppId = Literal["core", "moments", "people"]
EntitlementTier = Literal["free", "pro", "creator", "agency"]
EntitlementStatus = Literal["active", "inactive", "expired"]
LedgerReason = Literal[
    "purchase", "generation", "refund", "bonus",
    "subscription", "plan_confirmed", "moment_generated",
]


class WalletResponse(BaseModel):
    user_id: str
    app_id: AppId
    credit_balance: int = 0
    updated_at: str


class CreditLedgerResponse(BaseModel):
    id: str
    user_id: str
    app_id: AppId
    delta: int
    reason: LedgerReason
    ref_type: str | None = None
    ref_id: str | None = None
    created_at: str


class EntitlementResponse(BaseModel):
    user_id: str
    app_id: AppId
    entitlement: EntitlementTier = "free"
    status: EntitlementStatus = "active"
    expires_at: str | None = None
    source: str | None = None
    updated_at: str


class AppPlanResponse(BaseModel):
    id: str | None = None
    app_id: AppId
    entitlement: EntitlementTier
    monthly_credits: int = 0
    max_personas: int | None = None
    max_days_planned: int | None = None
    max_rerolls: int | None = None
    features: dict[str, Any] = {}


# ═══════════════════════════════════════════════════════════
#  PERSONA MEMBERS (people schema)
# ═══════════════════════════════════════════════════════════

MemberRole = Literal["owner", "editor", "viewer"]


class PersonaMemberAdd(BaseModel):
    user_id: str
    role: MemberRole = "viewer"


class PersonaMemberResponse(BaseModel):
    persona_id: str
    user_id: str
    role: MemberRole = "viewer"
    created_at: str

