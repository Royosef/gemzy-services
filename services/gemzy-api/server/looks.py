"""Saved look persistence endpoints."""

from __future__ import annotations

import os
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .auth import get_current_user
from .content import _generate_signed_image_url, _normalize_storage_path
from .schemas import (
    CreateSavedLookPayload,
    CreationLookPreset,
    DeleteSavedLookResponse,
    SavedLook,
    UpdateSavedLookPayload,
    UserState,
)
from .storage import build_public_url, maybe_get_bucket
from .supabase_client import get_client

router = APIRouter(prefix="/looks", tags=["looks"])
creation_look_presets_router = APIRouter(
    prefix="/creation-look-presets",
    tags=["creation-look-presets"],
)

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _feature_path(value: object) -> str:
    return str(value or "").strip().replace("_", "-")


def _look_path_name(value: object) -> str:
    return str(value or "").strip().strip("/")


def _public_assets_bucket_config() -> tuple[str | None, str | None, str | None]:
    return (
        os.getenv("GCS_COLLECTIONS_PUBLIC_BUCKET"),
        os.getenv("GCS_COLLECTIONS_PROJECT"),
        os.getenv("GCS_PUBLIC_HOST"),
    )


def _public_host_for_bucket(bucket_name: str | None, public_host: str | None) -> str | None:
    if public_host and public_host.strip().startswith(("http://", "https://")):
        return public_host.strip()
    return None


def _build_public_asset_url(object_path: str) -> str | None:
    bucket_name, _, public_host = _public_assets_bucket_config()
    if not bucket_name and not public_host:
        return None
    url = build_public_url(
        object_path,
        bucket_name,
        public_host=_public_host_for_bucket(bucket_name, public_host),
    )
    return quote(url, safe=":/?#[]@!$&'()*+,;=%")


def _strip_configured_bucket_prefix(path: str, netloc: str = "") -> str:
    bucket_name, _, _ = _public_assets_bucket_config()
    if bucket_name and netloc == "storage.googleapis.com" and path.startswith(f"{bucket_name}/"):
        return path.removeprefix(f"{bucket_name}/")
    return path


def _derive_preset_directory(row: dict, preview_storage_path: str | None) -> str:
    if preview_storage_path and "/" in preview_storage_path:
        return preview_storage_path.rsplit("/", 1)[0]

    preview_url = row.get("preview_url")
    if isinstance(preview_url, str) and preview_url.strip():
        candidate = preview_url.strip()
        if not candidate.startswith(("http://", "https://")):
            candidate = f"https://{candidate.lstrip('/')}"
        parsed = urlparse(candidate)
        path = _strip_configured_bucket_prefix(unquote(parsed.path).lstrip("/"), parsed.netloc)
        if path.endswith("/Imgs"):
            return path.removesuffix("/Imgs")
        if path.lower().endswith(_IMAGE_EXTENSIONS) and "/" in path:
            return path.rsplit("/", 1)[0]
        if path.startswith("looks/"):
            return path.rstrip("/")

    feature = _feature_path(row.get("task_key"))
    look_name = _look_path_name(row.get("name"))
    return f"looks/{feature}/{look_name}"


def _list_preset_media_urls(row: dict, preview_storage_path: str | None) -> list[str]:
    bucket_name, project, _ = _public_assets_bucket_config()
    bucket = maybe_get_bucket(bucket_name, project)
    if bucket is None:
        return []

    directory = _derive_preset_directory(row, preview_storage_path)
    prefix = f"{directory.rstrip('/')}/Imgs/"
    try:
        blobs = bucket.list_blobs(prefix=prefix)
        object_paths = sorted(
            blob.name
            for blob in blobs
            if blob.name.lower().endswith(_IMAGE_EXTENSIONS)
        )
    except Exception:
        return []

    return [
        url
        for object_path in object_paths
        if (url := _build_public_asset_url(object_path))
    ]


def _map_creation_look_preset(row: dict) -> CreationLookPreset:
    preview_storage_path = _normalize_storage_path(row.get("preview_storage_path"))
    directory = _derive_preset_directory(row, preview_storage_path)
    preview_url = _build_public_asset_url(preview_storage_path or f"{directory.rstrip('/')}/Cover.jpg")

    return CreationLookPreset(
        id=str(row.get("id") or ""),
        taskKey=str(row.get("task_key") or ""),
        engineId=str(row.get("engine_id") or ""),
        name=str(row.get("name") or "Untitled look"),
        style=row.get("style") if isinstance(row.get("style"), dict) else {},
        previewUrl=preview_url,
        previewStoragePath=preview_storage_path,
        mediaUrls=_list_preset_media_urls(row, preview_storage_path),
        requiredPlan=row.get("required_plan"),
        sortOrder=row.get("sort_order"),
        createdAt=row.get("created_at"),
        updatedAt=row.get("updated_at"),
    )


@creation_look_presets_router.get("", response_model=list[CreationLookPreset])
@creation_look_presets_router.get(
    "/",
    response_model=list[CreationLookPreset],
    include_in_schema=False,
)
def list_creation_look_presets(
    taskKey: str | None = Query(None),
    engineId: str | None = Query(None),
) -> list[CreationLookPreset]:
    query = (
        get_client()
        .table("creation_look_presets")
        .select("*")
        .eq("is_active", True)
        .order("sort_order")
        .order("name")
    )
    if taskKey:
        query = query.eq("task_key", taskKey)
    if engineId:
        query = query.eq("engine_id", engineId)
    response = query.execute()
    return [_map_creation_look_preset(row) for row in (response.data or [])]


def _map_saved_look(row: dict) -> SavedLook:
    preview_storage_path = _normalize_storage_path(row.get("preview_storage_path"))
    preview_uri = (
        _generate_signed_image_url(preview_storage_path)
        if preview_storage_path
        else row.get("preview_url")
    )
    return SavedLook(
        id=str(row.get("id") or ""),
        name=str(row.get("name") or "Untitled look"),
        surface=str(row.get("surface") or "on-model"),
        engineId=row.get("engine_id"),
        style=row.get("style") if isinstance(row.get("style"), dict) else {},
        previewUri=preview_uri,
        previewStoragePath=preview_storage_path,
        requiredPlan=row.get("required_plan"),
        createdAt=row.get("created_at"),
        updatedAt=row.get("updated_at"),
    )


def _fetch_owned_look(look_id: str, user_id: str) -> dict:
    response = (
        get_client()
        .table("saved_looks")
        .select("*")
        .eq("id", look_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Look not found")
    return rows[0]


@router.get("", response_model=list[SavedLook])
@router.get(
    "/",
    response_model=list[SavedLook],
    include_in_schema=False,
)
def list_saved_looks(
    surface: str = Query("on-model"),
    current: UserState = Depends(get_current_user),
) -> list[SavedLook]:
    response = (
        get_client()
        .table("saved_looks")
        .select("*")
        .eq("user_id", current.id)
        .eq("surface", surface)
        .order("updated_at", desc=True)
        .execute()
    )
    return [_map_saved_look(row) for row in (response.data or [])]


@router.post(
    "",
    response_model=SavedLook,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/",
    response_model=SavedLook,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_saved_look(
    payload: CreateSavedLookPayload,
    current: UserState = Depends(get_current_user),
) -> SavedLook:
    look_id = uuid4().hex
    preview_storage_path = _normalize_storage_path(payload.previewStoragePath)
    row = {
        "id": look_id,
        "user_id": current.id,
        "name": payload.name.strip(),
        "surface": payload.surface,
        "engine_id": payload.engineId,
        "style": payload.style,
        "preview_url": payload.previewUri,
        "preview_storage_path": preview_storage_path,
        "required_plan": payload.requiredPlan,
    }
    get_client().table("saved_looks").insert(row).execute()
    return _map_saved_look(_fetch_owned_look(look_id, current.id))


@router.patch("/{look_id}", response_model=SavedLook)
def update_saved_look(
    look_id: str,
    payload: UpdateSavedLookPayload,
    current: UserState = Depends(get_current_user),
) -> SavedLook:
    _fetch_owned_look(look_id, current.id)
    updates: dict[str, object | None] = {}
    if payload.name is not None:
        trimmed_name = payload.name.strip()
        if not trimmed_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Look name is required",
            )
        updates["name"] = trimmed_name
    if payload.engineId is not None:
        updates["engine_id"] = payload.engineId
    if payload.style is not None:
        updates["style"] = payload.style
    if payload.previewUri is not None:
        updates["preview_url"] = payload.previewUri
    if payload.previewStoragePath is not None:
        updates["preview_storage_path"] = _normalize_storage_path(payload.previewStoragePath)
    if payload.requiredPlan is not None:
        updates["required_plan"] = payload.requiredPlan
    if updates:
        get_client().table("saved_looks").update(updates).eq("id", look_id).eq("user_id", current.id).execute()
    return _map_saved_look(_fetch_owned_look(look_id, current.id))


@router.delete("/{look_id}", response_model=DeleteSavedLookResponse)
def delete_saved_look(
    look_id: str,
    current: UserState = Depends(get_current_user),
) -> DeleteSavedLookResponse:
    _fetch_owned_look(look_id, current.id)
    get_client().table("saved_looks").delete().eq("id", look_id).eq("user_id", current.id).execute()
    return DeleteSavedLookResponse(ok=True)
