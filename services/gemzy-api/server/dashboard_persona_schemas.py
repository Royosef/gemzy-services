from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


PersonaLifecycleStatus = Literal["draft", "active", "paused", "archived"]
PersonaVisibility = Literal["private", "public", "exclusive"]
AutonomyMode = Literal["QUEUE_DRAFTS", "AUTO_PUBLISH", "MIXED_RULES"]
QueueStatus = Literal["draft", "approved", "rejected", "published", "held"]
RunStatus = Literal["ready", "blocked", "needs_campaign_brief", "failed"]
WorldAdditionStatus = Literal["suggested", "approved", "rejected", "moment_only"]
WorldAdditionAction = Literal["approve", "reject", "moment_only"]


class DashboardPersonaCreatePayload(BaseModel):
    displayName: str
    bio: str | None = None
    avatarUrl: str | None = None
    isPublic: bool = False
    fullName: str | None = None
    publicBio: str | None = None
    internalBio: str | None = None
    socialHandle: str | None = None
    cityRegion: str | None = None
    occupation: str | None = None


class DashboardPersonaUpdatePayload(BaseModel):
    displayName: str | None = None
    bio: str | None = None
    avatarUrl: str | None = None
    isPublic: bool | None = None
    lifecycleStatus: PersonaLifecycleStatus | None = None
    visibility: PersonaVisibility | None = None
    socialHandle: str | None = None
    cityRegion: str | None = None
    occupation: str | None = None


class DashboardPersonaProfilePayload(BaseModel):
    fullName: str | None = None
    socialHandle: str | None = None
    ageRange: str | None = None
    genderExpression: str | None = None
    culturalBackground: str | None = None
    languages: list[str] = Field(default_factory=list)
    cityRegion: str | None = None
    occupation: str | None = None
    publicBio: str | None = None
    internalBio: str | None = None
    lifecycleStatus: PersonaLifecycleStatus = "draft"
    visibility: PersonaVisibility = "private"
    brandContext: dict[str, Any] = Field(default_factory=dict)


class DashboardPersonaPersonalityPayload(BaseModel):
    personalitySummary: str | None = None
    dominantTraits: list[str] = Field(default_factory=list)
    secondaryTraits: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    ambitions: list[str] = Field(default_factory=list)
    vulnerabilities: str | None = None
    humorStyle: str | None = None
    socialEnergy: str | None = None
    confidenceLevel: str | None = None
    communicationStyle: str | None = None
    emotionalRange: list[str] = Field(default_factory=list)
    stateRules: dict[str, Any] = Field(default_factory=dict)


class DashboardPersonaRoutinePayload(BaseModel):
    wakeUpTime: str | None = None
    workingHours: dict[str, Any] = Field(default_factory=dict)
    morningRituals: list[str] = Field(default_factory=list)
    exerciseHabits: list[str] = Field(default_factory=list)
    eveningPatterns: list[str] = Field(default_factory=list)
    weekendBehavior: list[str] = Field(default_factory=list)
    postingRhythm: dict[str, Any] = Field(default_factory=dict)
    travelFrequency: str | None = None


class DashboardPersonaInterestsPayload(BaseModel):
    strongInterests: list[str] = Field(default_factory=list)
    occasionalInterests: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    hobbies: list[str] = Field(default_factory=list)
    culturalTastes: list[str] = Field(default_factory=list)
    wellnessHabits: list[str] = Field(default_factory=list)
    foodPreferences: list[str] = Field(default_factory=list)
    travelPreferences: list[str] = Field(default_factory=list)
    shoppingBehavior: list[str] = Field(default_factory=list)


class DashboardPersonaLocationPayload(BaseModel):
    name: str
    tags: list[str] = Field(default_factory=list)
    tier: Literal["ANCHOR", "SEMI_STABLE", "FLEX"] = "SEMI_STABLE"
    reuseWeight: float = 1.0
    cooldownHours: int = 0
    maxPerWeek: int | None = None
    description: str | None = None
    visualNotes: str | None = None
    lightingNotes: str | None = None
    emotionalAssociation: str | None = None


class DashboardPersonaWardrobePayload(BaseModel):
    category: str
    name: str
    tags: list[str] = Field(default_factory=list)
    tier: Literal["ANCHOR", "SEMI_STABLE", "FLEX"] = "SEMI_STABLE"
    reuseWeight: float = 1.0
    seasonTags: list[str] = Field(default_factory=list)
    description: str | None = None
    suitabilityTags: list[str] = Field(default_factory=list)
    signatureItem: bool = False
    favoriteItem: bool = False


class DashboardPersonaOutfitPayload(BaseModel):
    name: str
    description: str | None = None
    wardrobeItemIds: list[str] = Field(default_factory=list)
    suitableOccasions: list[str] = Field(default_factory=list)
    seasonTags: list[str] = Field(default_factory=list)
    moodTags: list[str] = Field(default_factory=list)
    referenceImageUrl: str | None = None
    reuseCooldownHours: int = 0
    signatureLook: bool = False


class DashboardPersonaHomeSpacePayload(BaseModel):
    name: str
    description: str | None = None
    roomType: str | None = None
    visualTraits: list[str] = Field(default_factory=list)
    lightingNotes: str | None = None
    signatureUseCases: list[str] = Field(default_factory=list)


class DashboardPersonaObjectPayload(BaseModel):
    name: str
    description: str | None = None
    objectType: str | None = None
    visualTraits: list[str] = Field(default_factory=list)
    emotionalRole: str | None = None
    recurringContexts: list[str] = Field(default_factory=list)


class DashboardPersonaRelationshipPayload(BaseModel):
    name: str
    relationshipType: str
    summary: str | None = None
    visibility: str = "internal"
    emotionalTone: str | None = None
    recurringContexts: list[str] = Field(default_factory=list)


class DashboardPersonaMemoryPayload(BaseModel):
    title: str
    memoryType: str = "canonical"
    summary: str
    importanceScore: int = Field(default=3, ge=1, le=5)
    occurredAt: str | None = None


class DashboardPersonaAutomationPayload(BaseModel):
    enabled: bool = False
    autonomyMode: AutonomyMode = "QUEUE_DRAFTS"
    cadenceHours: int = Field(default=24, ge=1, le=168)
    spontaneity: float = Field(default=0.35, ge=0.0, le=1.0)
    noveltyRate: float = Field(default=0.15, ge=0.0, le=1.0)
    allowedContentTypes: list[str] = Field(default_factory=lambda: ["story", "post"])
    boundaries: dict[str, Any] = Field(default_factory=dict)
    campaignOverridePolicy: str = "require_brief"
    requireManualPublish: bool = True


class DashboardPersonaRunPayload(BaseModel):
    prompt: str | None = None
    campaignId: str | None = None
    campaignName: str | None = None
    targetDate: str | None = None
    force: bool = False


class DashboardPersonaQueueActionPayload(BaseModel):
    action: Literal["approve", "reject", "publish", "hold", "retry_generation", "regenerate"]
    note: str | None = None


class DashboardPersonaWorldAdditionActionPayload(BaseModel):
    action: WorldAdditionAction
    note: str | None = None


class DashboardPersonaSummaryResponse(BaseModel):
    id: str
    displayName: str
    bio: str | None = None
    avatarUrl: str | None = None
    avatarSignedUrl: str | None = None
    isPublic: bool = False
    lifecycleStatus: PersonaLifecycleStatus = "draft"
    visibility: PersonaVisibility = "private"
    socialHandle: str | None = None
    cityRegion: str | None = None
    occupation: str | None = None
    automationEnabled: bool = False
    automationMode: AutonomyMode = "QUEUE_DRAFTS"
    queueDraftCount: int = 0
    pendingApprovalCount: int = 0
    lastRunAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaProfileResponse(BaseModel):
    personaId: str
    fullName: str | None = None
    socialHandle: str | None = None
    ageRange: str | None = None
    genderExpression: str | None = None
    culturalBackground: str | None = None
    languages: list[str] = Field(default_factory=list)
    cityRegion: str | None = None
    occupation: str | None = None
    publicBio: str | None = None
    internalBio: str | None = None
    lifecycleStatus: PersonaLifecycleStatus = "draft"
    visibility: PersonaVisibility = "private"
    brandContext: dict[str, Any] = Field(default_factory=dict)
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaPersonalityResponse(BaseModel):
    personaId: str
    personalitySummary: str | None = None
    dominantTraits: list[str] = Field(default_factory=list)
    secondaryTraits: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    ambitions: list[str] = Field(default_factory=list)
    vulnerabilities: str | None = None
    humorStyle: str | None = None
    socialEnergy: str | None = None
    confidenceLevel: str | None = None
    communicationStyle: str | None = None
    emotionalRange: list[str] = Field(default_factory=list)
    stateRules: dict[str, Any] = Field(default_factory=dict)
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaRoutineResponse(BaseModel):
    personaId: str
    wakeUpTime: str | None = None
    workingHours: dict[str, Any] = Field(default_factory=dict)
    morningRituals: list[str] = Field(default_factory=list)
    exerciseHabits: list[str] = Field(default_factory=list)
    eveningPatterns: list[str] = Field(default_factory=list)
    weekendBehavior: list[str] = Field(default_factory=list)
    postingRhythm: dict[str, Any] = Field(default_factory=dict)
    travelFrequency: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaInterestsResponse(BaseModel):
    personaId: str
    strongInterests: list[str] = Field(default_factory=list)
    occasionalInterests: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    hobbies: list[str] = Field(default_factory=list)
    culturalTastes: list[str] = Field(default_factory=list)
    wellnessHabits: list[str] = Field(default_factory=list)
    foodPreferences: list[str] = Field(default_factory=list)
    travelPreferences: list[str] = Field(default_factory=list)
    shoppingBehavior: list[str] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaLocationResponse(BaseModel):
    id: str
    personaId: str
    name: str
    tags: list[str] = Field(default_factory=list)
    tier: str = "SEMI_STABLE"
    reuseWeight: float = 1.0
    cooldownHours: int = 0
    maxPerWeek: int | None = None
    description: str | None = None
    visualNotes: str | None = None
    lightingNotes: str | None = None
    emotionalAssociation: str | None = None
    createdAt: str | None = None


class DashboardPersonaWardrobeResponse(BaseModel):
    id: str
    personaId: str
    category: str
    name: str
    tags: list[str] = Field(default_factory=list)
    tier: str = "SEMI_STABLE"
    reuseWeight: float = 1.0
    seasonTags: list[str] = Field(default_factory=list)
    description: str | None = None
    suitabilityTags: list[str] = Field(default_factory=list)
    signatureItem: bool = False
    favoriteItem: bool = False
    createdAt: str | None = None


class DashboardPersonaOutfitResponse(BaseModel):
    id: str
    personaId: str
    name: str
    description: str | None = None
    wardrobeItemIds: list[str] = Field(default_factory=list)
    suitableOccasions: list[str] = Field(default_factory=list)
    seasonTags: list[str] = Field(default_factory=list)
    moodTags: list[str] = Field(default_factory=list)
    referenceImageUrl: str | None = None
    reuseCooldownHours: int = 0
    signatureLook: bool = False
    lastUsedAt: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaHomeSpaceResponse(BaseModel):
    id: str
    personaId: str
    name: str
    description: str | None = None
    roomType: str | None = None
    visualTraits: list[str] = Field(default_factory=list)
    lightingNotes: str | None = None
    signatureUseCases: list[str] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaObjectResponse(BaseModel):
    id: str
    personaId: str
    name: str
    description: str | None = None
    objectType: str | None = None
    visualTraits: list[str] = Field(default_factory=list)
    emotionalRole: str | None = None
    recurringContexts: list[str] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaRelationshipResponse(BaseModel):
    id: str
    personaId: str
    name: str
    relationshipType: str
    summary: str | None = None
    visibility: str = "internal"
    emotionalTone: str | None = None
    recurringContexts: list[str] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaMemoryResponse(BaseModel):
    id: str
    personaId: str
    title: str
    memoryType: str
    summary: str
    importanceScore: int = 3
    occurredAt: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaWorldAdditionResponse(BaseModel):
    id: str
    personaId: str
    sourceKind: str | None = None
    sourceId: str | None = None
    itemType: str
    proposedName: str | None = None
    proposedPayload: dict[str, Any] = Field(default_factory=dict)
    status: WorldAdditionStatus = "suggested"
    reviewerUserId: str | None = None
    reviewNote: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaAutomationSettingsResponse(BaseModel):
    personaId: str
    enabled: bool = False
    autonomyMode: AutonomyMode = "QUEUE_DRAFTS"
    cadenceHours: int = 24
    spontaneity: float = 0.35
    noveltyRate: float = 0.15
    allowedContentTypes: list[str] = Field(default_factory=list)
    boundaries: dict[str, Any] = Field(default_factory=dict)
    campaignOverridePolicy: str = "require_brief"
    requireManualPublish: bool = True
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaRuntimeStateResponse(BaseModel):
    personaId: str
    currentMode: str = "idle"
    lastRunAt: str | None = None
    nextRunAt: str | None = None
    pauseReason: str | None = None
    pendingApprovalCount: int = 0
    activeCampaignContext: dict[str, Any] = Field(default_factory=dict)
    lastError: str | None = None
    updatedAt: str | None = None


class DashboardPersonaAutomationRunResponse(BaseModel):
    id: str
    personaId: str
    triggerSource: str | None = None
    status: RunStatus = "ready"
    contextSummary: str | None = None
    inputPrompt: str | None = None
    outputPayload: dict[str, Any] = Field(default_factory=dict)
    blockedReason: str | None = None
    createdAt: str | None = None
    completedAt: str | None = None


class DashboardPersonaQueueItemResponse(BaseModel):
    id: str
    personaId: str
    runId: str | None = None
    title: str
    contentType: str
    status: QueueStatus = "draft"
    scheduledFor: str | None = None
    caption: str | None = None
    visualDirection: str | None = None
    continuityReason: str | None = None
    novelty: bool = False
    queuePayload: dict[str, Any] = Field(default_factory=dict)
    requiresApproval: bool = True
    campaignId: str | None = None
    approvedByUserId: str | None = None
    approvedAt: str | None = None
    publishedAt: str | None = None
    rejectionReason: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class DashboardPersonaCampaignContextResponse(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    objective: str | None = None
    syncedAt: str | None = None


class DashboardPersonaAuditEventResponse(BaseModel):
    id: str
    personaId: str
    eventType: str
    actorType: str
    actorId: str | None = None
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    createdAt: str | None = None


class DashboardPersonaDetailResponse(BaseModel):
    persona: DashboardPersonaSummaryResponse
    profile: DashboardPersonaProfileResponse | None = None
    personality: DashboardPersonaPersonalityResponse | None = None
    routine: DashboardPersonaRoutineResponse | None = None
    interests: DashboardPersonaInterestsResponse | None = None
    styleProfile: dict[str, Any] | None = None
    locations: list[DashboardPersonaLocationResponse] = Field(default_factory=list)
    wardrobe: list[DashboardPersonaWardrobeResponse] = Field(default_factory=list)
    outfits: list[DashboardPersonaOutfitResponse] = Field(default_factory=list)
    homeSpaces: list[DashboardPersonaHomeSpaceResponse] = Field(default_factory=list)
    objects: list[DashboardPersonaObjectResponse] = Field(default_factory=list)
    relationships: list[DashboardPersonaRelationshipResponse] = Field(default_factory=list)
    memories: list[DashboardPersonaMemoryResponse] = Field(default_factory=list)
    worldAdditions: list[DashboardPersonaWorldAdditionResponse] = Field(default_factory=list)
    automation: DashboardPersonaAutomationSettingsResponse | None = None
    runtime: DashboardPersonaRuntimeStateResponse | None = None
    queue: list[DashboardPersonaQueueItemResponse] = Field(default_factory=list)
    automationRuns: list[DashboardPersonaAutomationRunResponse] = Field(default_factory=list)
    campaigns: list[DashboardPersonaCampaignContextResponse] = Field(default_factory=list)
    auditEvents: list[DashboardPersonaAuditEventResponse] = Field(default_factory=list)
