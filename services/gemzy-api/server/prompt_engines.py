"""Admin APIs for managing prompt engines, versions, and routing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from prompting.registry import ensure_default_prompt_registry, render_engine_version

from .auth import get_current_user
from .schemas import (
    CreatePromptEnginePayload,
    CreatePromptEngineVersionPayload,
    CreatePromptTaskRoutePayload,
    PromptEngineDetailResponse,
    PromptEnginePreviewPayload,
    PromptEnginePreviewResponse,
    PromptEngineResponse,
    PromptEngineVersionResponse,
    PromptTaskRouteResponse,
    UpdatePromptEnginePayload,
    UpdatePromptEngineVersionPayload,
    UpdatePromptTaskRoutePayload,
    UserState,
)
from .supabase_client import get_client

router = APIRouter(prefix="/prompt-engines", tags=["prompt-engines"])


def _ensure_admin(current: UserState) -> None:
    if current.isAdmin:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


def _require_engine_ref(engine_ref: str) -> dict[str, Any]:
    sb = get_client()
    rows = sb.table("prompt_engines").select("*").eq("id", engine_ref).limit(1).execute().data or []
    if rows:
        return rows[0]
    rows = sb.table("prompt_engines").select("*").eq("slug", engine_ref).limit(1).execute().data or []
    if rows:
        return rows[0]
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt engine not found")


def _require_version(engine_id: str, version_id: str) -> dict[str, Any]:
    rows = (
        get_client()
        .table("prompt_engine_versions")
        .select("*")
        .eq("id", version_id)
        .eq("engine_id", engine_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if rows:
        return rows[0]
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt engine version not found")


def _require_route(route_id: str) -> dict[str, Any]:
    rows = (
        get_client().table("prompt_task_routes").select("*").eq("id", route_id).limit(1).execute().data
        or []
    )
    if rows:
        return rows[0]
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt route not found")


def _serialize_version(row: dict[str, Any]) -> PromptEngineVersionResponse:
    return PromptEngineVersionResponse(
        id=row["id"],
        engineId=row["engine_id"],
        versionNumber=int(row.get("version_number") or 0),
        status=str(row.get("status") or "draft"),
        changeNote=row.get("change_note"),
        definition=row.get("definition") or {},
        sampleInput=row.get("sample_input") or {},
        createdAt=row.get("created_at"),
    )


def _serialize_engine(row: dict[str, Any], *, versions: list[dict[str, Any]] | None = None) -> PromptEngineResponse:
    versions = versions or []
    published_version_id = row.get("published_version_id")
    published_version = next((item for item in versions if item.get("id") == published_version_id), None)
    return PromptEngineResponse(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        description=row.get("description"),
        taskType=row["task_type"],
        rendererKey=row["renderer_key"],
        inputSchema=row.get("input_schema") or {},
        outputSchema=row.get("output_schema") or {},
        labels=row.get("labels") or {},
        publishedVersionId=published_version_id,
        publishedVersionNumber=(
            int(published_version.get("version_number") or 0)
            if published_version is not None
            else None
        ),
        createdAt=row.get("created_at"),
        updatedAt=row.get("updated_at"),
    )


def _serialize_route(row: dict[str, Any], *, engine_slug: str | None = None) -> PromptTaskRouteResponse:
    return PromptTaskRouteResponse(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        taskType=row["task_type"],
        priority=int(row.get("priority") or 100),
        isActive=bool(row.get("is_active", True)),
        matchRules=row.get("match_rules") or {},
        engineId=row["engine_id"],
        engineSlug=engine_slug,
        pinnedVersionId=row.get("pinned_version_id"),
        notes=row.get("notes"),
        createdAt=row.get("created_at"),
        updatedAt=row.get("updated_at"),
    )


def _list_versions(engine_id: str) -> list[dict[str, Any]]:
    return (
        get_client()
        .table("prompt_engine_versions")
        .select("*")
        .eq("engine_id", engine_id)
        .order("version_number", desc=True)
        .execute()
        .data
        or []
    )


def _detail_response(engine: dict[str, Any]) -> PromptEngineDetailResponse:
    versions = _list_versions(engine["id"])
    base = _serialize_engine(engine, versions=versions)
    return PromptEngineDetailResponse(**base.model_dump(), versions=[_serialize_version(row) for row in versions])


def _next_version_number(engine_id: str) -> int:
    versions = _list_versions(engine_id)
    highest = max((int(row.get("version_number") or 0) for row in versions), default=0)
    return highest + 1


def _validate_version_reference(engine_id: str, version_id: str | None) -> None:
    if not version_id:
        return
    _require_version(engine_id, version_id)


@router.get("", response_model=list[PromptEngineResponse])
def list_prompt_engines(current: UserState = Depends(get_current_user)) -> list[PromptEngineResponse]:
    """List prompt engines for the admin UI."""

    _ensure_admin(current)
    ensure_default_prompt_registry(client=get_client())
    engines = get_client().table("prompt_engines").select("*").order("slug").execute().data or []
    if not engines:
        return []

    engine_ids = [row["id"] for row in engines]
    versions = (
        get_client().table("prompt_engine_versions").select("*").in_("engine_id", engine_ids).execute().data
        or []
    )
    versions_by_engine: dict[str, list[dict[str, Any]]] = {}
    for row in versions:
        versions_by_engine.setdefault(row["engine_id"], []).append(row)
    return [_serialize_engine(row, versions=versions_by_engine.get(row["id"], [])) for row in engines]


@router.post("", response_model=PromptEngineDetailResponse, status_code=status.HTTP_201_CREATED)
def create_prompt_engine(
    data: CreatePromptEnginePayload,
    current: UserState = Depends(get_current_user),
) -> PromptEngineDetailResponse:
    """Create a prompt engine and its initial draft version."""

    _ensure_admin(current)
    sb = get_client()
    existing = sb.table("prompt_engines").select("id").eq("slug", data.slug).limit(1).execute().data or []
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Prompt engine slug already exists")

    created_engine = (
        sb.table("prompt_engines")
        .insert(
            {
                "slug": data.slug.strip(),
                "name": data.name.strip(),
                "description": data.description,
                "task_type": data.taskType.strip(),
                "renderer_key": data.rendererKey.strip(),
                "input_schema": data.inputSchema,
                "output_schema": data.outputSchema,
                "labels": data.labels,
                "created_by": current.id,
                "updated_by": current.id,
            }
        )
        .execute()
        .data
        or []
    )
    if not created_engine:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Prompt engine creation failed")

    engine = created_engine[0]
    version_data = data.initialVersion or CreatePromptEngineVersionPayload()
    created_version = (
        sb.table("prompt_engine_versions")
        .insert(
            {
                "engine_id": engine["id"],
                "version_number": 1,
                "status": "draft",
                "change_note": version_data.changeNote,
                "definition": version_data.definition,
                "sample_input": version_data.sampleInput,
                "created_by": current.id,
            }
        )
        .execute()
        .data
        or []
    )
    if not created_version:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Prompt engine version creation failed")
    return _detail_response(_require_engine_ref(engine["id"]))


@router.get("/routes", response_model=list[PromptTaskRouteResponse])
def list_prompt_routes(current: UserState = Depends(get_current_user)) -> list[PromptTaskRouteResponse]:
    """List prompt routing rules for the admin UI."""

    _ensure_admin(current)
    ensure_default_prompt_registry(client=get_client())
    routes = (
        get_client()
        .table("prompt_task_routes")
        .select("*")
        .order("task_type")
        .order("priority")
        .execute()
        .data
        or []
    )
    if not routes:
        return []

    engine_ids = sorted({row["engine_id"] for row in routes})
    engines = get_client().table("prompt_engines").select("id,slug").in_("id", engine_ids).execute().data or []
    slugs_by_engine_id = {row["id"]: row["slug"] for row in engines}
    return [_serialize_route(row, engine_slug=slugs_by_engine_id.get(row["engine_id"])) for row in routes]


@router.post("/routes", response_model=PromptTaskRouteResponse, status_code=status.HTTP_201_CREATED)
def create_prompt_route(
    data: CreatePromptTaskRoutePayload,
    current: UserState = Depends(get_current_user),
) -> PromptTaskRouteResponse:
    """Create a new prompt-task route."""

    _ensure_admin(current)
    sb = get_client()
    existing = sb.table("prompt_task_routes").select("id").eq("slug", data.slug).limit(1).execute().data or []
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Prompt route slug already exists")
    _require_engine_ref(data.engineId)
    _validate_version_reference(data.engineId, data.pinnedVersionId)

    created = (
        sb.table("prompt_task_routes")
        .insert(
            {
                "slug": data.slug.strip(),
                "name": data.name.strip(),
                "task_type": data.taskType.strip(),
                "priority": data.priority,
                "is_active": data.isActive,
                "match_rules": data.matchRules,
                "engine_id": data.engineId,
                "pinned_version_id": data.pinnedVersionId,
                "notes": data.notes,
                "created_by": current.id,
                "updated_by": current.id,
            }
        )
        .execute()
        .data
        or []
    )
    if not created:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Prompt route creation failed")

    engine = _require_engine_ref(data.engineId)
    return _serialize_route(created[0], engine_slug=engine["slug"])


@router.patch("/routes/{route_id}", response_model=PromptTaskRouteResponse)
def update_prompt_route(
    route_id: str,
    data: UpdatePromptTaskRoutePayload,
    current: UserState = Depends(get_current_user),
) -> PromptTaskRouteResponse:
    """Update a prompt-task route."""

    _ensure_admin(current)
    route = _require_route(route_id)
    updates: dict[str, Any] = {"updated_by": current.id}

    if data.slug is not None:
        slug_rows = get_client().table("prompt_task_routes").select("id").eq("slug", data.slug).limit(1).execute().data or []
        if slug_rows and slug_rows[0]["id"] != route_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Prompt route slug already exists")
        updates["slug"] = data.slug.strip()
    if data.name is not None:
        updates["name"] = data.name.strip()
    if data.taskType is not None:
        updates["task_type"] = data.taskType.strip()
    if data.priority is not None:
        updates["priority"] = data.priority
    if data.isActive is not None:
        updates["is_active"] = data.isActive
    if data.matchRules is not None:
        updates["match_rules"] = data.matchRules
    engine_id = data.engineId or route["engine_id"]
    if data.engineId is not None:
        _require_engine_ref(data.engineId)
        updates["engine_id"] = data.engineId
    if data.pinnedVersionId is not None:
        _validate_version_reference(engine_id, data.pinnedVersionId)
        updates["pinned_version_id"] = data.pinnedVersionId
    if data.notes is not None:
        updates["notes"] = data.notes

    get_client().table("prompt_task_routes").update(updates).eq("id", route_id).execute()
    updated = _require_route(route_id)
    engine = _require_engine_ref(updated["engine_id"])
    return _serialize_route(updated, engine_slug=engine["slug"])


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt_route(
    route_id: str,
    current: UserState = Depends(get_current_user),
) -> Response:
    """Soft-delete a prompt route by deactivating it."""

    _ensure_admin(current)
    _require_route(route_id)
    get_client().table("prompt_task_routes").update(
        {"is_active": False, "updated_by": current.id}
    ).eq("id", route_id).execute()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{engine_ref}", response_model=PromptEngineDetailResponse)
def get_prompt_engine(
    engine_ref: str,
    current: UserState = Depends(get_current_user),
) -> PromptEngineDetailResponse:
    """Return engine metadata plus all version rows."""

    _ensure_admin(current)
    ensure_default_prompt_registry(client=get_client())
    return _detail_response(_require_engine_ref(engine_ref))


@router.patch("/{engine_ref}", response_model=PromptEngineDetailResponse)
def update_prompt_engine(
    engine_ref: str,
    data: UpdatePromptEnginePayload,
    current: UserState = Depends(get_current_user),
) -> PromptEngineDetailResponse:
    """Update prompt-engine metadata."""

    _ensure_admin(current)
    engine = _require_engine_ref(engine_ref)
    updates: dict[str, Any] = {"updated_by": current.id}

    if data.slug is not None:
        slug_rows = get_client().table("prompt_engines").select("id").eq("slug", data.slug).limit(1).execute().data or []
        if slug_rows and slug_rows[0]["id"] != engine["id"]:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Prompt engine slug already exists")
        updates["slug"] = data.slug.strip()
    if data.name is not None:
        updates["name"] = data.name.strip()
    if data.description is not None:
        updates["description"] = data.description
    if data.taskType is not None:
        updates["task_type"] = data.taskType.strip()
    if data.rendererKey is not None:
        updates["renderer_key"] = data.rendererKey.strip()
    if data.inputSchema is not None:
        updates["input_schema"] = data.inputSchema
    if data.outputSchema is not None:
        updates["output_schema"] = data.outputSchema
    if data.labels is not None:
        updates["labels"] = data.labels
    if data.publishedVersionId is not None:
        _validate_version_reference(engine["id"], data.publishedVersionId)
        updates["published_version_id"] = data.publishedVersionId

    get_client().table("prompt_engines").update(updates).eq("id", engine["id"]).execute()
    return _detail_response(_require_engine_ref(engine["id"]))


@router.post("/{engine_ref}/versions", response_model=PromptEngineVersionResponse, status_code=status.HTTP_201_CREATED)
def create_prompt_engine_version(
    engine_ref: str,
    data: CreatePromptEngineVersionPayload,
    current: UserState = Depends(get_current_user),
) -> PromptEngineVersionResponse:
    """Create a new draft version for a prompt engine."""

    _ensure_admin(current)
    engine = _require_engine_ref(engine_ref)
    created = (
        get_client()
        .table("prompt_engine_versions")
        .insert(
            {
                "engine_id": engine["id"],
                "version_number": _next_version_number(engine["id"]),
                "status": "draft",
                "change_note": data.changeNote,
                "definition": data.definition,
                "sample_input": data.sampleInput,
                "created_by": current.id,
            }
        )
        .execute()
        .data
        or []
    )
    if not created:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Prompt engine version creation failed")
    return _serialize_version(created[0])


@router.patch("/{engine_ref}/versions/{version_id}", response_model=PromptEngineVersionResponse)
def update_prompt_engine_version(
    engine_ref: str,
    version_id: str,
    data: UpdatePromptEngineVersionPayload,
    current: UserState = Depends(get_current_user),
) -> PromptEngineVersionResponse:
    """Update a draft prompt-engine version."""

    _ensure_admin(current)
    engine = _require_engine_ref(engine_ref)
    version = _require_version(engine["id"], version_id)
    if version.get("status") != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft prompt engine versions can be edited",
        )
    updates: dict[str, Any] = {}
    if data.changeNote is not None:
        updates["change_note"] = data.changeNote
    if data.definition is not None:
        updates["definition"] = data.definition
    if data.sampleInput is not None:
        updates["sample_input"] = data.sampleInput
    get_client().table("prompt_engine_versions").update(updates).eq("id", version_id).execute()
    return _serialize_version(_require_version(engine["id"], version_id))


@router.post("/{engine_ref}/versions/{version_id}/publish", response_model=PromptEngineDetailResponse)
def publish_prompt_engine_version(
    engine_ref: str,
    version_id: str,
    current: UserState = Depends(get_current_user),
) -> PromptEngineDetailResponse:
    """Publish a version and mark it as the active engine revision."""

    _ensure_admin(current)
    engine = _require_engine_ref(engine_ref)
    _require_version(engine["id"], version_id)
    sb = get_client()
    sb.table("prompt_engine_versions").update({"status": "archived"}).eq("engine_id", engine["id"]).eq(
        "status", "published"
    ).execute()
    sb.table("prompt_engine_versions").update({"status": "published"}).eq("id", version_id).execute()
    sb.table("prompt_engines").update(
        {"published_version_id": version_id, "updated_by": current.id}
    ).eq("id", engine["id"]).execute()
    return _detail_response(_require_engine_ref(engine["id"]))


@router.post(
    "/{engine_ref}/versions/{version_id}/preview",
    response_model=PromptEnginePreviewResponse,
)
def preview_prompt_engine_version(
    engine_ref: str,
    version_id: str,
    data: PromptEnginePreviewPayload,
    current: UserState = Depends(get_current_user),
) -> PromptEnginePreviewResponse:
    """Render a version using arbitrary preview input."""

    _ensure_admin(current)
    engine = _require_engine_ref(engine_ref)
    version = _require_version(engine["id"], version_id)
    try:
        output = render_engine_version(engine, version, data.input)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Prompt preview failed: {exc}",
        ) from exc
    return PromptEnginePreviewResponse(output=output)
