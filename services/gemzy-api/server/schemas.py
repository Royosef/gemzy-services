"""Pydantic schemas for the backend API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

try:  # pragma: no cover - dependency optional for tests
    from pydantic import EmailStr as _EmailStr
    import email_validator as _email_validator  # noqa: F401

    EmailStr = _EmailStr
except ImportError:  # pragma: no cover - fallback when email-validator is missing
    EmailStr = str  # type: ignore[misc, assignment]


class MagicLinkRequest(BaseModel):
    """Request payload to send a magic link."""
    email: EmailStr


class VerifyRequest(BaseModel):
    """Payload to verify an emailed one-time code."""
    email: EmailStr
    token: str


class OAuthRequest(BaseModel):
    provider: Literal["google", "apple"]
    token: str
    nonce: str | None = None
    name: str | None = None

class NotificationPreferences(BaseModel):
    """Notification preferences stored for a user."""

    gemzyUpdates: bool = True
    personalUpdates: bool = True
    email: bool = True


class AppNotificationAction(BaseModel):
    """Navigation payload for an in-app notification."""

    pathname: str | None = None
    params: dict[str, str] | None = None
    url: str | None = None


class AppNotification(BaseModel):
    """Notification payload synced to the mobile app."""

    id: str
    entityKey: str | None = None
    category: Literal["general", "personal"]
    kind: str
    title: str
    body: str
    createdAt: str
    expiresAt: str | None = None
    action: AppNotificationAction | None = None


class PublishAppNotificationRequest(BaseModel):
    """Admin-authored notification to publish for the app."""

    entityKey: str | None = None
    category: Literal["general", "personal"] = "general"
    kind: str
    title: str
    body: str
    expiresAt: str | None = None
    targetUserId: str | None = None
    action: AppNotificationAction | None = None


class PushTokenRegistrationRequest(BaseModel):
    """Expo push token registration for the authenticated device."""

    token: str
    platform: Literal["ios", "android"]
    appVersion: str | None = None


class ProfileUpdate(BaseModel):
    """Payload to update mutable profile fields."""

    name: str | None = None
    avatarUrl: str | None = None
    notifications: NotificationPreferences | None = None

class RefreshRequest(BaseModel):
    """Payload containing a refresh token."""
    refresh: str


class Token(BaseModel):
    """Access and refresh tokens."""
    access: str
    refresh: str


class UserState(BaseModel):
    """User state returned to the mobile app."""

    id: str
    email: str | None = None
    name: str | None = None
    plan: str | None = None
    credits: int = 0
    monthlyCredits: int = 0
    purchasedCredits: int = 0
    createdAt: str | None = None
    avatarUrl: str | None = None
    notificationPreferences: NotificationPreferences | None = None
    isAdmin: bool = False
    reactivatedAt: str | None = None
    retentionOfferUsed: bool = False
    retentionOfferUsedAt: str | None = None
    onboardingCompleted: bool = False
    styleTrials: dict[str, dict[str, object]] | None = None


class StyleTrialState(BaseModel):
    pendingSelectionKeys: list[str] = Field(default_factory=list)
    remainingUses: int = Field(default=3, ge=0, le=3)


class StyleTrialsUpdate(BaseModel):
    onModel: StyleTrialState | None = None
    pureJewelry: StyleTrialState | None = None


class AuthResponse(BaseModel):
    """Response returned after login or registration."""
    token: Token
    user: UserState
    is_new: bool = False


class CollectionImage(BaseModel):
    """Single asset inside a collection."""

    id: str
    uri: str
    previewUri: str | None = None
    category: str | None = None
    isNew: bool = False
    isFavorite: bool = False
    metadata: dict[str, object] | None = None
    modelId: str | None = None
    modelName: str | None = None
    storagePath: str | None = None


class CollectionLeadModel(BaseModel):
    """Lead model summary for a collection."""

    id: str | None = None
    name: str | None = None
    avatarUrl: str | None = None


class Collection(BaseModel):
    """Full collection payload returned to the client."""

    id: str
    name: str
    cover: str | None = None
    coverPreview: str | None = None
    createdAt: str
    curatedBy: str | None = None
    liked: bool = False
    tags: list[str] = []
    description: str | None = None
    items: list[CollectionImage] | None = None
    leadModel: CollectionLeadModel | None = None


class CollectionImageInput(BaseModel):
    """Inbound image payload when creating or updating a collection."""

    uri: str
    storagePath: str | None = None
    contentType: str | None = None
    size: int | None = None
    width: int | None = None
    height: int | None = None
    hash: str | None = None
    name: str | None = None
    category: str | None = None
    modelId: str | None = None
    modelName: str | None = None


class CreateCollectionPayload(BaseModel):
    """Request payload for creating a collection."""

    name: str
    images: list[CollectionImageInput]


class AddCollectionItemsPayload(BaseModel):
    """Request payload for appending items to an existing collection."""

    images: list[CollectionImageInput]


class CollectionUploadRequest(BaseModel):
    """Request upload authorization for collection media."""

    contentType: str | None = None
    size: int | None = None
    fileName: str | None = None


class CollectionUploadAuthorization(BaseModel):
    """Signed upload details for the client to use."""

    uploadUrl: str
    storagePath: str
    publicUrl: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str] = {}
    expiresAt: str

class CollectionItemsPage(BaseModel):
    items: list[CollectionImage]
    nextCursor: str | None = None
    
class SignedUrlResponse(BaseModel):
    """Short-lived signed URL returned for secure asset access."""

    url: str
    previewUrl: str | None = None
    expiresAt: str | None = None


class UpdateCollectionPayload(BaseModel):
    """Mutable fields for a collection."""

    name: str | None = None
    cover: str | None = None
    liked: bool | None = None


class MoveImagesPayload(BaseModel):
    """Payload describing a move between collections."""

    sourceId: str
    targetId: str
    imageIds: list[str]


class DeleteImagesPayload(BaseModel):
    """Payload describing images to delete."""

    collectionId: str
    imageIds: list[str]


class MoveImagesResponse(BaseModel):
    """Simple counter after moving images."""

    moved: int


class DeleteImagesResponse(BaseModel):
    """Simple counter after deleting images."""

    deleted: int


class ModelGalleryImage(BaseModel):
    """Image inside the model gallery."""

    id: str
    uri: str
    thumbnail: str | None = None
    order: int = 0


class Model(BaseModel):
    """Gemzy model payload returned to the client."""

    id: str
    slug: str
    name: str
    PlanTier: str
    highlight: str | None = None
    description: str | None = None
    img: str
    gallery: list[ModelGalleryImage] = []
    liked: bool = False
    tags: list[str] = []
    spotlightTag: str | None = None


class UpdateModelPayload(BaseModel):
    """Mutable fields for a model record."""

    liked: bool | None = None


class GenerationUploadPayload(BaseModel):
    """Uploaded asset included in a generation request."""

    id: str
    uri: str
    base64: str
    mimeType: str | None = None
    fileSize: int | None = None
    width: int | None = None
    height: int | None = None
    name: str | None = None


class GenerationModelPayload(BaseModel):
    """Model metadata selected for a generation."""

    id: str
    slug: str
    name: str
    planTier: str
    highlight: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    spotlightTag: str | None = None
    imageUri: str | None = None
    imageBase64: str | None = None


class GenerationDimensions(BaseModel):
    """Requested output dimensions for a generation."""

    w: int
    h: int


class ItemPayload(BaseModel):
    """Metadata for an item being generated."""

    id: str
    type: str
    size: str
    uploadId: str


class CreateGenerationPayload(BaseModel):
    """Payload sent by the client to start a generation job."""

    generationServerUrl: str | None = None
    uploads: list[GenerationUploadPayload]
    items: list[ItemPayload] = Field(default_factory=list)
    model: GenerationModelPayload
    style: dict[str, str] = Field(default_factory=dict)
    mode: Literal["SIMPLE", "ADVANCED"]
    aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"]
    dims: GenerationDimensions
    looks: int
    quality: Literal["1080p", "2K", "4K"]
    plan: str
    creditsNeeded: int
    promptOverrides: list[str] = Field(default_factory=list)


class GenerationResultPayload(BaseModel):
    """Result asset returned from the generation service."""

    url: str | None = None
    previewUrl: str | None = None
    base64: str | None = None
    storagePath: str | None = None
    collectionId: str | None = None
    collectionItemId: str | None = None
    modelId: str | None = None
    modelName: str | None = None
    createdAt: str | None = None


class ImageEditSourcePayload(BaseModel):
    """Source image metadata for a follow-up edit request."""

    sourceKey: str | None = None
    url: str | None = None
    previewUrl: str | None = None
    storagePath: str | None = None
    collectionId: str | None = None
    collectionItemId: str | None = None
    generationJobId: str | None = None
    modelSlug: str | None = None
    modelName: str | None = None
    createdAt: str | None = None


class ImageEditInstructionPayload(BaseModel):
    """Resolved edit instruction returned to the client for review."""

    id: str
    label: str
    category: str
    prompt: str | None = None


class CreateImageEditPayload(BaseModel):
    """Payload sent by the client to start an image edit job."""

    generationServerUrl: str | None = None
    sourceImage: GenerationUploadPayload
    source: ImageEditSourcePayload
    edits: list[str]
    aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"] = "1:1"
    dims: GenerationDimensions = Field(default_factory=lambda: GenerationDimensions(w=1080, h=1080))
    quality: Literal["1080p", "2K", "4K"] = "1080p"


class CreateGenerationResponse(BaseModel):
    """Response envelope returned after creating a generation."""

    id: str
    status: str | None = None
    results: list[GenerationResultPayload] = Field(default_factory=list)
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    totalLooks: int | None = Field(default=None, ge=0)
    completedLooks: int | None = Field(default=None, ge=0)
    errors: list[str] = Field(default_factory=list)
    remainingCredits: int | None = Field(default=None, ge=0)
    jobType: str | None = None
    editSource: ImageEditSourcePayload | None = None
    editInstructions: list[ImageEditInstructionPayload] = Field(default_factory=list)
    editCreditCost: int | None = Field(default=None, ge=0)


class GenerationJobEvent(BaseModel):
    """Event payload sent from the generation server to report updates."""

    type: Literal["started", "progress", "result", "completed", "failed"]
    result: GenerationResultPayload | None = None
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    completedLooks: int | None = Field(default=None, ge=0)
    error: str | None = None


class GenerationUiOptionResponse(BaseModel):
    """Single selectable option in the server-driven generation UI."""

    id: str
    label: str
    hasColor: bool = False
    colorLabel: str | None = None


class GenerationUiSectionResponse(BaseModel):
    """Config for a section/parameter rendered by the mobile generation UI."""

    id: str
    label: str
    description: str | None = None
    iconKey: str | None = None
    editTier: str | None = None
    supportsRandom: bool = False
    freeOptionLabels: list[str] = Field(default_factory=list)
    options: list[GenerationUiOptionResponse] = Field(default_factory=list)


class GenerationUiEngineSelectorResponse(BaseModel):
    """Selector metadata for a generation engine option."""

    id: str
    pillLabel: str
    title: str
    description: str
    badge: str | None = None
    imageKey: str | None = None
    badgeImageKey: str | None = None
    sortOrder: int = 100


class GenerationUiStyleResponse(BaseModel):
    """Pure-jewelry style card and its editable parameters."""

    id: str
    title: str
    imageKey: str
    parameters: list[GenerationUiSectionResponse] = Field(default_factory=list)


class GenerationUiSurfaceEngineResponse(BaseModel):
    """Renderable engine configuration for a specific creation surface."""

    surface: str
    engineId: str
    engineSlug: str
    promptVersion: str | None = None
    isDefault: bool = False
    selector: GenerationUiEngineSelectorResponse
    trialTaskLabel: str | None = None
    trialPopupImageKey: str | None = None
    itemTypes: list[GenerationUiOptionResponse] = Field(default_factory=list)
    itemSizes: list[GenerationUiOptionResponse] = Field(default_factory=list)
    defaultStyleId: str | None = None
    sections: list[GenerationUiSectionResponse] = Field(default_factory=list)
    styles: list[GenerationUiStyleResponse] = Field(default_factory=list)


class GenerationUiSurfaceResponse(BaseModel):
    """Server-driven config for a single creation surface."""

    defaultEngineId: str | None = None
    engines: list[GenerationUiSurfaceEngineResponse] = Field(default_factory=list)


class GenerationUiCatalogResponse(BaseModel):
    """Public catalog used by the app to render generation screens."""

    version: str
    fetchedAt: str | None = None
    onModel: GenerationUiSurfaceResponse
    pureJewelry: GenerationUiSurfaceResponse


class PromptEngineVersionEditor(BaseModel):
    """Editable fields for a prompt-engine version definition."""

    changeNote: str | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    sampleInput: dict[str, Any] = Field(default_factory=dict)


class CreatePromptEnginePayload(BaseModel):
    """Create a prompt engine and optionally seed its first version."""

    slug: str
    name: str
    description: str | None = None
    taskType: str
    rendererKey: str
    inputSchema: dict[str, Any] = Field(default_factory=dict)
    outputSchema: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, Any] = Field(default_factory=dict)
    initialVersion: PromptEngineVersionEditor | None = None


class UpdatePromptEnginePayload(BaseModel):
    """Mutable metadata fields for a prompt engine."""

    slug: str | None = None
    name: str | None = None
    description: str | None = None
    taskType: str | None = None
    rendererKey: str | None = None
    inputSchema: dict[str, Any] | None = None
    outputSchema: dict[str, Any] | None = None
    labels: dict[str, Any] | None = None
    publishedVersionId: str | None = None


class CreatePromptEngineVersionPayload(PromptEngineVersionEditor):
    """Create a new version for an existing prompt engine."""


class UpdatePromptEngineVersionPayload(BaseModel):
    """Update a draft prompt-engine version."""

    changeNote: str | None = None
    definition: dict[str, Any] | None = None
    sampleInput: dict[str, Any] | None = None


class PromptEngineVersionResponse(BaseModel):
    """Version metadata returned to the admin client."""

    id: str
    engineId: str
    versionNumber: int
    status: str
    changeNote: str | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    sampleInput: dict[str, Any] = Field(default_factory=dict)
    createdAt: str | None = None


class PromptEngineResponse(BaseModel):
    """Prompt-engine metadata returned to the admin client."""

    id: str
    slug: str
    name: str
    description: str | None = None
    taskType: str
    rendererKey: str
    inputSchema: dict[str, Any] = Field(default_factory=dict)
    outputSchema: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, Any] = Field(default_factory=dict)
    publishedVersionId: str | None = None
    publishedVersionNumber: int | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class PromptEngineDetailResponse(PromptEngineResponse):
    """Prompt-engine detail including all versions and routes."""

    versions: list[PromptEngineVersionResponse] = Field(default_factory=list)


class CreatePromptTaskRoutePayload(BaseModel):
    """Create a new prompt-task route."""

    slug: str
    name: str
    taskType: str
    priority: int = 100
    isActive: bool = True
    matchRules: dict[str, Any] = Field(default_factory=dict)
    engineId: str
    pinnedVersionId: str | None = None
    notes: str | None = None


class UpdatePromptTaskRoutePayload(BaseModel):
    """Mutable fields for a prompt-task route."""

    slug: str | None = None
    name: str | None = None
    taskType: str | None = None
    priority: int | None = None
    isActive: bool | None = None
    matchRules: dict[str, Any] | None = None
    engineId: str | None = None
    pinnedVersionId: str | None = None
    notes: str | None = None


class PromptTaskRouteResponse(BaseModel):
    """Task-route metadata returned to the admin client."""

    id: str
    slug: str
    name: str
    taskType: str
    priority: int
    isActive: bool = True
    matchRules: dict[str, Any] = Field(default_factory=dict)
    engineId: str
    engineSlug: str | None = None
    pinnedVersionId: str | None = None
    notes: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class PromptEnginePreviewPayload(BaseModel):
    """Preview input for rendering a specific prompt-engine version."""

    input: dict[str, Any] = Field(default_factory=dict)


class PromptEnginePreviewResponse(BaseModel):
    """Preview result for the admin prompt-engine editor."""

    output: dict[str, Any] = Field(default_factory=dict)

