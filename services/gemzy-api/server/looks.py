"""Saved look persistence endpoints."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .auth import get_current_user
from .content import _generate_signed_image_url, _normalize_storage_path
from .schemas import (
    CreateSavedLookPayload,
    DeleteSavedLookResponse,
    SavedLook,
    UpdateSavedLookPayload,
    UserState,
)
from .supabase_client import get_client

router = APIRouter(prefix="/looks", tags=["looks"])


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


@router.get("/", response_model=list[SavedLook])
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


@router.post("/", response_model=SavedLook, status_code=status.HTTP_201_CREATED)
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
