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
    redirectUri: str | None = None

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
    editModeTrialEditsRemaining: int = Field(default=2, ge=0, le=2)


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
    metadata: dict[str, object] | None = None
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
    gender: str = "female"
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
    gender: str | None = None
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


GenerationAspect = Literal[
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "9:16",
    "16:9",
    "21:9",
]
GenerationQuality = Literal["1080p", "2K", "4K"]


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
    aspect: GenerationAspect
    dims: GenerationDimensions
    looks: int
    quality: GenerationQuality
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
    metadata: dict[str, Any] | None = None


class ImageEditSourcePayload(BaseModel):
    """Source image metadata for a follow-up edit request."""

    sourceKey: str | None = None
    url: str | None = None
    previewUrl: str | None = None
    storagePath: str | None = None
    collectionId: str | None = None
    collectionItemId: str | None = None
    generationJobId: str | None = None
    modelId: str | None = None
    modelSlug: str | None = None
    modelName: str | None = None
    modelImageUri: str | None = None
    modelImageBase64: str | None = None
    style: dict[str, str] | None = None
    aspect: GenerationAspect | None = None
    dims: GenerationDimensions | None = None
    quality: GenerationQuality | None = None
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
    aspect: GenerationAspect = "1:1"
    dims: GenerationDimensions = Field(
        default_factory=lambda: GenerationDimensions(w=1080, h=1080)
    )
    quality: GenerationQuality = "1080p"


class ImageEditFeedbackRequest(BaseModel):
    """Feedback submitted from the review edit screen."""

    rating: Literal["awesome", "good", "okay", "bad", "very_bad"]
    comment: str | None = None
    sourceKey: str | None = None
    editOptionIds: list[str] = Field(default_factory=list)
    editLabels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageEditFeedbackResponse(BaseModel):
    """Persisted feedback response."""

    id: str
    createdAt: str | None = None


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
    editTrialApplied: bool | None = None
    editModeTrialEditsRemaining: int | None = Field(default=None, ge=0, le=2)


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


class GenerationUiEditOptionResponse(BaseModel):
    """Single edit option rendered by the image-edit flow."""

    id: str
    label: str
    description: str
    category: str
    parentId: str | None = None
    parentLabel: str | None = None
    exclusiveGroup: str | None = None
    conflictsWith: list[str] = Field(default_factory=list)


class GenerationUiEditCategoryResponse(BaseModel):
    """Edit mode category and its option/group ids."""

    id: str
    label: str
    options: list[str] = Field(default_factory=list)
    disabled: bool = False
    disabledReason: str | None = None


class GenerationUiEditConfigResponse(BaseModel):
    """DB-managed image-edit configuration for an edit engine version."""

    categories: list[GenerationUiEditCategoryResponse] = Field(default_factory=list)
    options: list[GenerationUiEditOptionResponse] = Field(default_factory=list)


class GenerationUiStyleResponse(BaseModel):
    """Pure-jewelry style card and its editable parameters."""

    id: str
    title: str
    imageKey: str
    parameters: list[GenerationUiSectionResponse] = Field(default_factory=list)


class GenerationUiSurfaceEngineResponse(BaseModel):
    """Renderable engine configuration for a specific creation surface."""

    surface: str
    taskKey: str | None = None
    engineId: str
    publicEngineKey: str | None = None
    engineSlug: str
    publicVersionKey: str | None = None
    isDefault: bool = False
    isUserSelectable: bool = True
    selector: GenerationUiEngineSelectorResponse
    trialTaskLabel: str | None = None
    trialPopupImageKey: str | None = None
    itemTypes: list[GenerationUiOptionResponse] = Field(default_factory=list)
    itemSizes: list[GenerationUiOptionResponse] = Field(default_factory=list)
    defaultStyleId: str | None = None
    sections: list[GenerationUiSectionResponse] = Field(default_factory=list)
    styles: list[GenerationUiStyleResponse] = Field(default_factory=list)
    editConfig: GenerationUiEditConfigResponse | None = None


class GenerationUiSurfaceResponse(BaseModel):
    """Server-driven config for a single creation surface."""

    defaultEngineId: str | None = None
    engines: list[GenerationUiSurfaceEngineResponse] = Field(default_factory=list)


class GenerationUiTaskResponse(BaseModel):
    """Task-scoped generation UI metadata for dynamic clients."""

    key: str
    name: str
    description: str | None = None
    surface: str | None = None
    parentTaskKey: str | None = None
    displayDefaults: dict[str, Any] = Field(default_factory=dict)
    defaultEngineId: str | None = None
    engines: list[GenerationUiSurfaceEngineResponse] = Field(default_factory=list)


class GenerationUiCatalogResponse(BaseModel):
    """Public catalog used by the app to render generation screens."""

    version: str
    fetchedAt: str | None = None
    onModel: GenerationUiSurfaceResponse
    pureJewelry: GenerationUiSurfaceResponse
    tasks: list[GenerationUiTaskResponse] = Field(default_factory=list)


class PromptEngineVersionEditor(BaseModel):
    """Editable fields for a prompt-engine version definition."""

    versionName: str | None = None
    publicVersionKey: str | None = None
    changeNote: str | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    sampleInput: dict[str, Any] = Field(default_factory=dict)


class CreatePromptEnginePayload(BaseModel):
    """Create a prompt engine and optionally seed its first version."""

    slug: str
    name: str
    description: str | None = None
    managementTask: str | None = None
    taskType: str
    rendererKey: str
    publicEngineKey: str | None = None
    isUserSelectable: bool = False
    sortOrder: int = 100
    selectorPillLabel: str | None = None
    selectorTitle: str | None = None
    selectorDescription: str | None = None
    selectorBadge: str | None = None
    selectorImageKey: str | None = None
    selectorBadgeImageKey: str | None = None
    inputSchema: dict[str, Any] = Field(default_factory=dict)
    outputSchema: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, Any] = Field(default_factory=dict)
    initialVersion: PromptEngineVersionEditor | None = None


class UpdatePromptEnginePayload(BaseModel):
    """Mutable metadata fields for a prompt engine."""

    slug: str | None = None
    name: str | None = None
    description: str | None = None
    managementTask: str | None = None
    taskType: str | None = None
    rendererKey: str | None = None
    publicEngineKey: str | None = None
    isUserSelectable: bool | None = None
    sortOrder: int | None = None
    selectorPillLabel: str | None = None
    selectorTitle: str | None = None
    selectorDescription: str | None = None
    selectorBadge: str | None = None
    selectorImageKey: str | None = None
    selectorBadgeImageKey: str | None = None
    inputSchema: dict[str, Any] | None = None
    outputSchema: dict[str, Any] | None = None
    labels: dict[str, Any] | None = None
    publishedVersionId: str | None = None


class CreatePromptEngineVersionPayload(PromptEngineVersionEditor):
    """Create a new version for an existing prompt engine."""


class UpdatePromptEngineVersionPayload(BaseModel):
    """Update a draft prompt-engine version."""

    versionName: str | None = None
    publicVersionKey: str | None = None
    changeNote: str | None = None
    definition: dict[str, Any] | None = None
    sampleInput: dict[str, Any] | None = None


class PromptEngineVersionResponse(BaseModel):
    """Version metadata returned to the admin client."""

    id: str
    engineId: str
    versionNumber: int
    status: str
    versionName: str | None = None
    publicVersionKey: str | None = None
    changeNote: str | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    components: list[str] = Field(default_factory=list)
    sampleInput: dict[str, Any] = Field(default_factory=dict)
    createdAt: str | None = None


class PromptEngineResponse(BaseModel):
    """Prompt-engine metadata returned to the admin client."""

    id: str
    slug: str
    name: str
    description: str | None = None
    taskId: str | None = None
    managementTask: str | None = None
    taskType: str
    rendererKey: str
    publicEngineKey: str | None = None
    isUserSelectable: bool = False
    sortOrder: int = 100
    selectorPillLabel: str | None = None
    selectorTitle: str | None = None
    selectorDescription: str | None = None
    selectorBadge: str | None = None
    selectorImageKey: str | None = None
    selectorBadgeImageKey: str | None = None
    activeVersionId: str | None = None
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
    taskId: str | None = None
    taskType: str
    managementTask: str | None = None
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


class PromptManagementTaskResponse(BaseModel):
    """Task-scoped prompt management payload for the admin dashboard."""

    id: str | None = None
    key: str
    title: str
    description: str | None = None
    surface: str | None = None
    parentTaskKey: str | None = None
    displayDefaults: dict[str, Any] = Field(default_factory=dict)
    engines: list[PromptEngineDetailResponse] = Field(default_factory=list)
    routes: list[PromptTaskRouteResponse] = Field(default_factory=list)


class PromptEnginePreviewResponse(BaseModel):
    """Preview result for the admin prompt-engine editor."""

    output: dict[str, Any] = Field(default_factory=dict)


class DashboardOverviewMetricsResponse(BaseModel):
    totalSpend: str = "0"
    totalImpressions: int = 0
    totalResults: int = 0
    avgRoas: str = "0"
    lastSyncedAt: str | None = None


class DashboardTopAdResponse(BaseModel):
    id: str
    adName: str
    campaignName: str | None = None
    spend: str = "0"
    results: int = 0
    costPerResult: str = "0"


class DashboardMetaSpendPointResponse(BaseModel):
    date: str
    spend: float = 0


class DashboardMetaSpendTimeseriesResponse(BaseModel):
    granularity: str
    currency: str = "USD"
    points: list[DashboardMetaSpendPointResponse] = Field(default_factory=list)


class DashboardCampaignPerformanceRowResponse(BaseModel):
    campaignId: str
    campaignName: str
    status: str = "UNKNOWN"
    spendUsd: float = 0
    purchases: int = 0
    revenueUsd: float = 0
    roas: float | None = None
    cacUsd: float | None = None
    hasAttribution: bool = False


class DashboardCampaignPerformanceResponse(BaseModel):
    rangeDays: int
    fetchedAt: str
    rows: list[DashboardCampaignPerformanceRowResponse] = Field(default_factory=list)
    hasAnyAttribution: bool = False


class DashboardMetaSyncResponse(BaseModel):
    campaigns: int = 0
    adSets: int = 0
    adSetsCbo: int = 0
    adSetsAbo: int = 0
    ads: int = 0
    durationMs: int = 0


class DashboardCoachRecommendationResponse(BaseModel):
    id: str
    action: str
    reasoning: str
    executionNotes: str | None = None
    priority: str
    status: str
    createdAt: str | None = None
    snoozedUntil: str | None = None


class DashboardCoachRecordActionPayload(BaseModel):
    recommendationId: str
    action: Literal["done", "dismissed", "snoozed"]
    note: str | None = None


class DashboardCoachActionResponse(BaseModel):
    id: str
    recommendationId: str
    action: str
    note: str | None = None
    createdAt: str | None = None


class DashboardCoachUndoPayload(BaseModel):
    recommendationActionId: str


class DashboardUndoResponse(BaseModel):
    recommendationId: str


class DashboardSocialAccountResponse(BaseModel):
    id: str | None = None
    username: str | None = None
    followerCount: int | None = None
    niche: str | None = None
    location: str | None = None
    fitScore: float | None = None
    sourceUrl: str | None = None
    discoveredViaQuery: str | None = None


class DashboardSocialRecommendationResponse(BaseModel):
    id: str
    accountId: str
    actionType: str
    suggestedText: str | None = None
    details: dict[str, Any] | None = None
    reasoning: str
    priority: str
    status: str
    generatedAt: str | None = None
    actedAt: str | None = None
    account: DashboardSocialAccountResponse | None = None


class DashboardSocialGenerateStatsResponse(BaseModel):
    candidatesSelected: int = 0
    recentRecommendationCount: int = 0
    generatedCount: int = 0


class DashboardGenerateDailyActionsResponse(BaseModel):
    recommendations: list[DashboardSocialRecommendationResponse] = Field(default_factory=list)
    stats: DashboardSocialGenerateStatsResponse = Field(
        default_factory=DashboardSocialGenerateStatsResponse
    )


class DashboardSocialRecordActionPayload(BaseModel):
    recommendationId: str
    actionType: Literal["Commented", "Followed", "DMed", "Ignored", "Dismissed"]
    note: str | None = None
    templateUsedId: str | None = None
    templateCustomText: str | None = None
    dismissReason: Literal[
        "doesnt_match_niche",
        "inactive_or_private",
        "not_a_real_brand",
        "wrong_action_type",
        "other",
    ] | None = None


class DashboardSocialActionResultResponse(BaseModel):
    actionId: str
    status: str


class DashboardSocialUndoPayload(BaseModel):
    recommendationId: str


class DashboardSocialStatsResponse(BaseModel):
    completedToday: int = 0
    totalActiveRecs: int = 0
    actionsByType: dict[str, int] = Field(default_factory=dict)


class DashboardSocialDiscoveryRunPayload(BaseModel):
    queries: list[str] = Field(default_factory=list)
    maxResults: int = Field(default=20, ge=1, le=50)


class DashboardSocialDiscoveryRunResponse(BaseModel):
    queriesRun: int = 0
    queriesFailed: int = 0
    totalResultsFromTavily: int = 0
    totalExtractedHandles: int = 0
    totalUniqueHandles: int = 0
    newAccountsAdded: int = 0
    alreadyKnown: int = 0
    totalResponseMs: int = 0
    errors: list[dict[str, str]] = Field(default_factory=list)


class DashboardSocialSourceSyncPayload(BaseModel):
    days: int = Field(default=30, ge=1, le=365)


class DashboardInstagramSyncResponse(BaseModel):
    engagers: dict[str, Any] = Field(default_factory=dict)
    mentioners: dict[str, Any] = Field(default_factory=dict)
    dmSenders: dict[str, Any] = Field(default_factory=dict)
    durationMs: int = 0


class DashboardInstagramInsightResponse(BaseModel):
    name: str
    total: int = 0


class DashboardFxRateResponse(BaseModel):
    base: str = "USD"
    target: str = "ILS"
    rate: float = 0
    source: str = "fallback"
    fetchedAt: str | None = None


class DashboardRevenueOverviewResponse(BaseModel):
    mrr: float | None = None
    revenue28d: float | None = None
    activeSubscriptions: int | None = None
    activeTrials: int | None = None
    newCustomers28d: int | None = None
    activeUsers28d: int | None = None


class DashboardRevenueChartPointResponse(BaseModel):
    cohort: int
    date: str
    value: float
    incomplete: bool = False
    measure: int = 0


class DashboardRevenueChartResponse(BaseModel):
    chartName: str
    resolution: str
    values: list[DashboardRevenueChartPointResponse] = Field(default_factory=list)
    yaxisCurrency: str | None = None
    type: str | None = None


class DashboardRevenuePlanBreakdownItemResponse(BaseModel):
    plan: str
    cadence: str
    count: int = 0


class DashboardRevenuePlanBreakdownResponse(BaseModel):
    plans: list[DashboardRevenuePlanBreakdownItemResponse] = Field(default_factory=list)
    totalActiveSubscribers: int = 0


class DashboardRevenuePackBreakdownItemResponse(BaseModel):
    size: str
    revenue: float = 0
    units: int = 0


class DashboardRevenuePackBreakdownResponse(BaseModel):
    packs: list[DashboardRevenuePackBreakdownItemResponse] = Field(default_factory=list)


class DashboardRevenueSubscriberRowResponse(BaseModel):
    customerId: str
    ref: str
    plan: str | None = None
    cadence: str | None = None
    startedAt: int | None = None
    status: str
    creditsRevenueUsdLifetime: float = 0
    subscriptionsCount: int = 0
    firstSeenAt: int | None = None
    lastSeenAt: int | None = None
    country: str | None = None
    platform: str | None = None


class DashboardRevenueSubscriberListResponse(BaseModel):
    items: list[DashboardRevenueSubscriberRowResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    pageSize: int = 25


class DashboardRevenueSubscriberDetailSubscriptionResponse(BaseModel):
    productId: str
    plan: str
    cadence: str
    status: str | None = None
    startsAt: int | None = None
    endsAt: int | None = None
    givesAccess: bool = False


class DashboardRevenueSubscriberDetailPurchaseResponse(BaseModel):
    productId: str
    purchasedAt: int | None = None
    revenueUsd: float = 0
    quantity: int = 0
    pack: str | None = None


class DashboardRevenueSubscriberDetailResponse(BaseModel):
    customerId: str
    ref: str
    firstSeenAt: int | None = None
    lastSeenAt: int | None = None
    country: str | None = None
    platform: str | None = None
    creditsRevenueUsdLifetime: float = 0
    subscriptionMonthsActive: float = 0
    averageMrrContributionUsd: float | None = None
    subscriptions: list[DashboardRevenueSubscriberDetailSubscriptionResponse] = Field(
        default_factory=list
    )
    purchases: list[DashboardRevenueSubscriberDetailPurchaseResponse] = Field(
        default_factory=list
    )


class DashboardRevenueCohortPointResponse(BaseModel):
    monthIndex: int
    activeCount: int
    retentionPct: float
    incomplete: bool = False


class DashboardRevenueCohortRowResponse(BaseModel):
    cohortMonth: str
    cohortLabel: str
    cohortSize: int
    points: list[DashboardRevenueCohortPointResponse] = Field(default_factory=list)


class DashboardRevenueCohortRetentionResponse(BaseModel):
    cohorts: list[DashboardRevenueCohortRowResponse] = Field(default_factory=list)


class DashboardRevenueConversionBucketsResponse(BaseModel):
    withinOneMonth: int = 0
    oneToThree: int = 0
    threeToSix: int = 0
    sixPlus: int = 0


class DashboardRevenueMonthlyToYearlyResponse(BaseModel):
    conversions: int = 0
    monthlySubscribersInRange: int = 0
    conversionRate: float = 0
    timeToConversionBuckets: DashboardRevenueConversionBucketsResponse = Field(
        default_factory=DashboardRevenueConversionBucketsResponse
    )


class DashboardAdminBrainContextNotesResponse(BaseModel):
    revenueAvailable: bool = False
    promptShipsTimeseries: bool = False
    promptShipsSummary: bool = False


class DashboardAdminBrainContextResponse(BaseModel):
    asOf: str
    generatedInMs: int = 0
    revenue: dict[str, Any] | None = None
    revenueSummary: dict[str, Any] | None = None
    notes: DashboardAdminBrainContextNotesResponse = Field(
        default_factory=DashboardAdminBrainContextNotesResponse
    )

