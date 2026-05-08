"""Admin APIs for managing prompt engines, versions, and routing."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from prompting.registry import ensure_default_prompt_registry, render_engine_version

from .auth import get_current_user
from .schemas import (
    CreatePromptEnginePayload,
    CreatePromptEngineVersionPayload,
    CreatePromptTaskRoutePayload,
    PromptEngineDetailResponse,
    PromptManagementTaskResponse,
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


def _load_prompt_tasks() -> list[dict[str, Any]]:
    try:
        return get_client().table("prompt_tasks").select("*").execute().data or []
    except Exception:
        return []


def _task_key_by_id() -> dict[str, str]:
    return {
        str(row["id"]): str(row.get("key") or "")
        for row in _load_prompt_tasks()
        if row.get("id") and row.get("key")
    }


def _task_row_by_key(task_key: str | None) -> dict[str, Any] | None:
    normalized = str(task_key or "").strip()
    if not normalized:
        return None
    rows = get_client().table("prompt_tasks").select("*").eq("key", normalized).limit(1).execute().data or []
    return rows[0] if rows else None


def _resolve_task_id(task_key: str | None) -> str | None:
    task_row = _task_row_by_key(task_key)
    return str(task_row["id"]) if task_row and task_row.get("id") else None


def _resolve_task_id_or_400(task_key: str | None) -> str:
    task_id = _resolve_task_id(task_key)
    if task_id:
        return task_id
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown prompt task")


def _active_version_id(row: dict[str, Any]) -> str | None:
    value = row.get("active_version_id") or row.get("published_version_id")
    return str(value) if value else None


def _normalize_public_version_key(value: str | None, *, version_number: int) -> str:
    normalized = str(value or "").strip()
    return normalized or f"v{version_number}"


def _normalize_public_engine_key(value: str | None, *, slug: str) -> str:
    normalized = str(value or "").strip()
    return normalized or slug


def _version_public_key(version_row: dict[str, Any]) -> str:
    stored = str(version_row.get("public_version_key") or "").strip()
    if stored:
        return stored
    return f"v{int(version_row.get('version_number') or 0)}"


def _merge_version_definition(
    *,
    definition: dict[str, Any],
) -> dict[str, Any]:
    merged_definition = deepcopy(definition or {})
    merged_definition.pop("ui", None)
    merged_definition.pop("publicVersionKey", None)
    return merged_definition


def _infer_task_key(row: dict[str, Any], *, fallback: str | None = None) -> str | None:
    task_key = _task_key_by_id().get(str(row.get("task_id") or ""))
    if task_key:
        return task_key
    labels = row.get("labels") or {}
    surface_label = str(labels.get("surface") or "").strip().lower()
    if surface_label == "on-model":
        return "on-model"
    if surface_label == "pure-jewelry":
        return "pure-jewelry"
    task_type = str(row.get("task_type") or fallback or "").strip()
    return task_type or None


def _version_components(definition: dict[str, Any]) -> list[str]:
    components: list[str] = []
    if definition.get("mapping") or definition.get("sections"):
        components.append("sections")
    if definition.get("itemTypes"):
        components.append("itemTypes")
    if definition.get("itemSizes"):
        components.append("itemSizes")
    if definition.get("styles"):
        components.append("styles")
    return components


def _serialize_version(row: dict[str, Any]) -> PromptEngineVersionResponse:
    definition = row.get("definition") or {}
    return PromptEngineVersionResponse(
        id=row["id"],
        engineId=row["engine_id"],
        versionNumber=int(row.get("version_number") or 0),
        status=str(row.get("status") or "draft"),
        versionName=(
            row.get("version_name")
            or f"v{int(row.get('version_number') or 0)}"
        ),
        publicVersionKey=_version_public_key(row),
        changeNote=row.get("change_note"),
        definition=definition,
        components=_version_components(definition),
        sampleInput=row.get("sample_input") or {},
        createdAt=row.get("created_at"),
    )


def _serialize_engine(row: dict[str, Any], *, versions: list[dict[str, Any]] | None = None) -> PromptEngineResponse:
    versions = versions or []
    active_version_id = _active_version_id(row)
    published_version_id = str(row.get("published_version_id")) if row.get("published_version_id") else None
    published_version = next(
        (item for item in versions if item.get("id") == (published_version_id or active_version_id)),
        None,
    )
    return PromptEngineResponse(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        description=row.get("description"),
        taskId=str(row.get("task_id")) if row.get("task_id") else None,
        managementTask=_infer_task_key(row),
        taskType=row["task_type"],
        rendererKey=row["renderer_key"],
        publicEngineKey=_normalize_public_engine_key(row.get("public_engine_key"), slug=str(row.get("slug") or "")),
        isUserSelectable=bool(row.get("is_user_selectable", False)),
        sortOrder=int(row.get("sort_order") or 100),
        selectorPillLabel=row.get("selector_pill_label"),
        selectorTitle=row.get("selector_title"),
        selectorDescription=row.get("selector_description"),
        selectorBadge=row.get("selector_badge"),
        selectorImageKey=row.get("selector_image_key"),
        selectorBadgeImageKey=row.get("selector_badge_image_key"),
        activeVersionId=active_version_id,
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
        taskId=str(row.get("task_id")) if row.get("task_id") else None,
        taskType=row["task_type"],
        managementTask=_task_key_by_id().get(str(row.get("task_id") or "")) or str(row.get("task_type") or ""),
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


@router.get("/tasks", response_model=list[PromptManagementTaskResponse])
def list_prompt_management_tasks(current: UserState = Depends(get_current_user)) -> list[PromptManagementTaskResponse]:
    """Return prompt engines and routes grouped by admin-facing task."""

    _ensure_admin(current)
    ensure_default_prompt_registry(client=get_client())

    task_rows = _load_prompt_tasks()
    task_key_lookup = {str(row.get("id") or ""): str(row.get("key") or "") for row in task_rows}
    tasks_by_key: dict[str, PromptManagementTaskResponse] = {}
    for row in task_rows:
        task_key = str(row.get("key") or "").strip()
        if not task_key:
            continue
        parent_task_key = task_key_lookup.get(str(row.get("parent_task_id") or "")) if row.get("parent_task_id") else None
        tasks_by_key[task_key] = PromptManagementTaskResponse(
            id=str(row.get("id") or "") or None,
            key=task_key,
            title=str(row.get("name") or task_key),
            description=row.get("description"),
            surface=row.get("surface"),
            parentTaskKey=parent_task_key,
            displayDefaults=row.get("display_defaults") or {},
            engines=[],
            routes=[],
        )

    engines = get_client().table("prompt_engines").select("*").order("slug").execute().data or []
    if engines:
        engine_ids = [row["id"] for row in engines]
        versions = (
            get_client().table("prompt_engine_versions").select("*").in_("engine_id", engine_ids).execute().data
            or []
        )
        versions_by_engine: dict[str, list[dict[str, Any]]] = {}
        for row in versions:
            versions_by_engine.setdefault(row["engine_id"], []).append(row)
        for engine in engines:
            task_key = _infer_task_key(engine)
            if not task_key:
                continue
            bucket = tasks_by_key.setdefault(
                task_key,
                PromptManagementTaskResponse(key=task_key, title=task_key, engines=[], routes=[]),
            )
            bucket.engines.append(
                PromptEngineDetailResponse(
                    **_serialize_engine(engine, versions=versions_by_engine.get(engine["id"], [])).model_dump(),
                    versions=[_serialize_version(row) for row in versions_by_engine.get(engine["id"], [])],
                )
            )

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
    if routes:
        engine_ids = sorted({row["engine_id"] for row in routes if row.get("engine_id")})
        route_engines = get_client().table("prompt_engines").select("id,slug,task_id,task_type,labels").in_("id", engine_ids).execute().data or []
        engines_by_id = {row["id"]: row for row in route_engines}
        for route in routes:
            engine_row = engines_by_id.get(route.get("engine_id")) or {}
            task_key = (
                task_key_lookup.get(str(route.get("task_id") or ""))
                or _infer_task_key(engine_row, fallback=str(route.get("task_type") or ""))
                or str(route.get("task_type") or "")
            )
            bucket = tasks_by_key.setdefault(
                task_key,
                PromptManagementTaskResponse(key=task_key, title=task_key, engines=[], routes=[]),
            )
            bucket.routes.append(_serialize_route(route, engine_slug=engine_row.get("slug")))

    return list(tasks_by_key.values())


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
    task_id = _resolve_task_id_or_400(data.managementTask) if data.managementTask is not None else None

    created_engine = (
        sb.table("prompt_engines")
        .insert(
            {
                "slug": data.slug.strip(),
                "name": data.name.strip(),
                "description": data.description,
                "task_type": data.taskType.strip(),
                "task_id": task_id,
                "renderer_key": data.rendererKey.strip(),
                "public_engine_key": _normalize_public_engine_key(
                    data.publicEngineKey,
                    slug=data.slug.strip(),
                ),
                "is_user_selectable": data.isUserSelectable,
                "sort_order": data.sortOrder,
                "selector_pill_label": data.selectorPillLabel,
                "selector_title": data.selectorTitle,
                "selector_description": data.selectorDescription,
                "selector_badge": data.selectorBadge,
                "selector_image_key": data.selectorImageKey,
                "selector_badge_image_key": data.selectorBadgeImageKey,
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
    merged_definition = _merge_version_definition(definition=version_data.definition)
    initial_version_number = 1
    created_version = (
        sb.table("prompt_engine_versions")
        .insert(
            {
                "engine_id": engine["id"],
                "version_number": initial_version_number,
                "status": "draft",
                "version_name": version_data.versionName,
                "public_version_key": _normalize_public_version_key(
                    version_data.publicVersionKey,
                    version_number=initial_version_number,
                ),
                "change_note": version_data.changeNote,
                "definition": merged_definition,
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
    engine_row = _require_engine_ref(data.engineId)
    _validate_version_reference(str(engine_row["id"]), data.pinnedVersionId)
    task_id = _resolve_task_id(data.taskType) or engine_row.get("task_id")

    created = (
        sb.table("prompt_task_routes")
        .insert(
            {
                "slug": data.slug.strip(),
                "name": data.name.strip(),
                "task_type": data.taskType.strip(),
                "task_id": task_id,
                "priority": data.priority,
                "is_active": data.isActive,
                "match_rules": data.matchRules,
                "engine_id": engine_row["id"],
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

    return _serialize_route(created[0], engine_slug=engine_row["slug"])


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
        updates["task_id"] = _resolve_task_id(data.taskType) or route.get("task_id")
    if data.priority is not None:
        updates["priority"] = data.priority
    if data.isActive is not None:
        updates["is_active"] = data.isActive
    if data.matchRules is not None:
        updates["match_rules"] = data.matchRules
    engine_id = data.engineId or route["engine_id"]
    if data.engineId is not None:
        resolved_engine = _require_engine_ref(data.engineId)
        updates["engine_id"] = resolved_engine["id"]
        if data.taskType is None:
            updates["task_id"] = resolved_engine.get("task_id")
        engine_id = str(resolved_engine["id"])
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
    if data.managementTask is not None:
        updates["task_id"] = _resolve_task_id_or_400(data.managementTask)
    if data.rendererKey is not None:
        updates["renderer_key"] = data.rendererKey.strip()
    next_slug = str(updates.get("slug") or engine.get("slug") or "").strip()
    if data.publicEngineKey is not None:
        updates["public_engine_key"] = _normalize_public_engine_key(data.publicEngineKey, slug=next_slug)
    elif data.slug is not None:
        current_public_engine_key = str(engine.get("public_engine_key") or "").strip()
        current_slug = str(engine.get("slug") or "").strip()
        if not current_public_engine_key or current_public_engine_key == current_slug:
            updates["public_engine_key"] = next_slug
    if data.isUserSelectable is not None:
        updates["is_user_selectable"] = data.isUserSelectable
    if data.sortOrder is not None:
        updates["sort_order"] = data.sortOrder
    if data.selectorPillLabel is not None:
        updates["selector_pill_label"] = data.selectorPillLabel
    if data.selectorTitle is not None:
        updates["selector_title"] = data.selectorTitle
    if data.selectorDescription is not None:
        updates["selector_description"] = data.selectorDescription
    if data.selectorBadge is not None:
        updates["selector_badge"] = data.selectorBadge
    if data.selectorImageKey is not None:
        updates["selector_image_key"] = data.selectorImageKey
    if data.selectorBadgeImageKey is not None:
        updates["selector_badge_image_key"] = data.selectorBadgeImageKey
    if data.inputSchema is not None:
        updates["input_schema"] = data.inputSchema
    if data.outputSchema is not None:
        updates["output_schema"] = data.outputSchema
    if data.labels is not None:
        updates["labels"] = data.labels
    if data.publishedVersionId is not None:
        _validate_version_reference(engine["id"], data.publishedVersionId)
        updates["published_version_id"] = data.publishedVersionId
        updates["active_version_id"] = data.publishedVersionId

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
    next_version_number = _next_version_number(engine["id"])
    merged_definition = _merge_version_definition(definition=data.definition)
    created = (
        get_client()
        .table("prompt_engine_versions")
        .insert(
            {
                "engine_id": engine["id"],
                "version_number": next_version_number,
                "status": "draft",
                "version_name": data.versionName,
                "public_version_key": _normalize_public_version_key(
                    data.publicVersionKey,
                    version_number=next_version_number,
                ),
                "change_note": data.changeNote,
                "definition": merged_definition,
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
    next_definition = version.get("definition") or {}
    if data.versionName is not None:
        updates["version_name"] = data.versionName
    if data.publicVersionKey is not None:
        updates["public_version_key"] = _normalize_public_version_key(
            data.publicVersionKey,
            version_number=int(version.get("version_number") or 0),
        )
    if data.changeNote is not None:
        updates["change_note"] = data.changeNote
    if data.definition is not None:
        next_definition = data.definition
    if data.sampleInput is not None:
        updates["sample_input"] = data.sampleInput
    if data.definition is not None:
        updates["definition"] = _merge_version_definition(definition=next_definition)
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
        {"published_version_id": version_id, "active_version_id": version_id, "updated_by": current.id}
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
