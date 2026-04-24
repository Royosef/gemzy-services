"""Pydantic models for the generation worker API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class GenerationUpload(BaseModel):
    id: str
    uri: str
    base64: str
    mimeType: Optional[str] = None
    fileSize: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    name: Optional[str] = None


class GenerationModel(BaseModel):
    id: str
    slug: str
    name: str
    planTier: str
    highlight: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    spotlightTag: Optional[str] = None
    imageUri: Optional[str] = None
    imageBase64: Optional[str] = None


class GenerationDimensions(BaseModel):
    w: int
    h: int


class GenerationItem(BaseModel):
    """Metadata for a single item being generated."""
    id: str
    type: str
    size: str
    uploadId: str


class GenerationRequest(BaseModel):
    uploads: list[GenerationUpload]
    items: list[GenerationItem] = Field(default_factory=list)
    model: GenerationModel
    style: dict[str, str] = Field(default_factory=dict)
    mode: Literal["SIMPLE", "ADVANCED"]
    aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"]
    dims: GenerationDimensions
    looks: int
    quality: Literal["1k", "2k", "4k"]
    plan: str
    creditsNeeded: int
    promptOverrides: list[str] = Field(default_factory=list)


class UserState(BaseModel):
    id: str
    name: Optional[str] = None
    plan: Optional[str] = None
    credits: int


class JobMetadata(BaseModel):
    id: str
    userId: str
    callbackUrl: str
    looks: int


class GenerationJobPayload(BaseModel):
    job: JobMetadata
    user: UserState
    request: GenerationRequest


class GenerationResult(BaseModel):
    url: Optional[str] = None
    base64: Optional[str] = None


class CallbackEvent(BaseModel):
    type: Literal["started", "progress", "result", "completed", "failed"]
    result: Optional[GenerationResult] = None
    progress: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    completedLooks: Optional[int] = Field(default=None, ge=0)
    error: Optional[str] = None


class WorkerResponse(BaseModel):
    id: str
    status: str
    progress: float = 0.0
    results: list[GenerationResult] = Field(default_factory=list)
    completedLooks: int = 0
    totalLooks: int = 0
    errors: list[str] = Field(default_factory=list)

# ---------------------------------------------------------
# Models for Gemzy Moments (Synchronous / AI Integrations)
# ---------------------------------------------------------

class GenerateSyncRequest(BaseModel):
    prompt: str
    num_images: int = 1
    aspect_ratio: str = "9:16"
    quality: str = "high"
    model_image_base64: str | None = None
    model_image_mime_type: str = "image/png"
    reference_images_base64: list[str] = Field(default_factory=list)
    reference_image_mime_types: list[str] = Field(default_factory=list)

class GenerateSyncResponse(BaseModel):
    urls: list[str] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)

class PlannerPersona(BaseModel):
    display_name: str
    bio: Optional[str] = None

class PlannerStyleProfile(BaseModel):
    realism_level: str = "high"
    camera_style_tags: list[str] = Field(default_factory=list)
    color_palette_tags: list[str] = Field(default_factory=list)

class PlannerPreferences(BaseModel):
    stories_per_day: int = 3
    posts_per_day: int = 1

class PlannerWorldSummary(BaseModel):
    location_tags: list[str] = Field(default_factory=list)
    wardrobe_tags: list[str] = Field(default_factory=list)
    location_tiers: dict[str, str] = Field(default_factory=dict)

class PlannerEnrichRequest(BaseModel):
    prompt: str
    persona: PlannerPersona
    style_profile: PlannerStyleProfile
    preferences: PlannerPreferences
    world_summary: PlannerWorldSummary

class PlannerEnrichedMoment(BaseModel):
    description: str
    time_slot: str
    priority: str
    desired_location_tags: list[str] = Field(default_factory=list)
    desired_outfit_tags: list[str] = Field(default_factory=list)
    mood_tags: list[str] = Field(default_factory=list)

class PlannerEnrichResponse(BaseModel):
    intent: str
    tone: str
    day_arc: list[str] = Field(default_factory=list)
    moments: list[PlannerEnrichedMoment] = Field(default_factory=list)

class PlannerRankMomentInput(BaseModel):
    description: str
    time_slot: str
    priority: str
    mood_tags: list[str] = Field(default_factory=list)
    location_name: Optional[str] = None
    location_tags: list[str] = Field(default_factory=list)
    outfit_items: list[str] = Field(default_factory=list)

class PlannerRankRequest(BaseModel):
    persona_name: str
    intent: str
    tone: str
    moments: list[PlannerRankMomentInput]

class PlannerRankedMoment(BaseModel):
    index: int
    format: Literal["STORY", "POST"]
    hero_score: float
    reasoning: str

class PlannerRankResponse(BaseModel):
    rankings: list[PlannerRankedMoment] = Field(default_factory=list)
