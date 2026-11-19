"""Saved Explore inspirations, synced across the user's devices."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, field_validator

from .auth import get_current_user
from .schemas import UserState
from .supabase_client import get_client

router = APIRouter(prefix="/inspirations", tags=["inspirations"])

MAX_INSPIRATIONS = 500
_COLUMNS = "media_id,look_id,look_name,task_key,engine_id,kind,uri,preview_uri,created_at"


def _https_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned.lower().startswith("https://"):
        raise ValueError("Must be an https URL")
    return cleaned


class Inspiration(BaseModel):
    id: str
    lookId: str
    lookName: str
    taskKey: str
    engineId: str | None = None
    kind: Literal["image", "video"] = "image"
    uri: str
    previewUri: str | None = None
    createdAt: str


class SaveInspirationPayload(BaseModel):
    lookId: str = Field(min_length=1, max_length=200)
    lookName: str = Field(min_length=1, max_length=200)
    taskKey: str = Field(min_length=1, max_length=100)
    engineId: str | None = Field(default=None, max_length=200)
    kind: Literal["image", "video"] = "image"
    uri: str = Field(max_length=2048)
    previewUri: str | None = Field(default=None, max_length=2048)
    # Kept when importing likes saved on a device before sync existed.
    createdAt: datetime | None = None

    _uri = field_validator("uri")(_https_url)
    _preview = field_validator("previewUri")(_https_url)


class InspirationListResponse(BaseModel):
    inspirations: list[Inspiration] = Field(default_factory=list)


def _to_model(row: dict) -> Inspiration:
    return Inspiration(
        id=row["media_id"],
        lookId=row["look_id"],
        lookName=row["look_name"],
        taskKey=row["task_key"],
        engineId=row.get("engine_id"),
        kind=row.get("kind") or "image",
        uri=row["uri"],
        previewUri=row.get("preview_uri"),
        createdAt=str(row["created_at"]),
    )


@router.get("", response_model=InspirationListResponse)
def list_inspirations(user: UserState = Depends(get_current_user)) -> InspirationListResponse:
    """The user's saved inspirations, newest first."""

    rows = (
        get_client()
        .table("user_inspirations")
        .select(_COLUMNS)
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .limit(MAX_INSPIRATIONS)
        .execute()
    ).data or []
    return InspirationListResponse(inspirations=[_to_model(row) for row in rows])


@router.put("/{media_id}", response_model=Inspiration)
def save_inspiration(
    media_id: str,
    payload: SaveInspirationPayload,
    user: UserState = Depends(get_current_user),
) -> Inspiration:
    """Save (or re-save) one Explore image or video. Idempotent."""

    created_at = payload.createdAt or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    row = {
        "user_id": user.id,
        "media_id": media_id[:300],
        "look_id": payload.lookId,
        "look_name": payload.lookName,
        "task_key": payload.taskKey,
        "engine_id": payload.engineId,
        "kind": payload.kind,
        "uri": payload.uri,
        "preview_uri": payload.previewUri,
        "created_at": created_at.isoformat(),
    }
    get_client().table("user_inspirations").upsert(
        row, on_conflict="user_id,media_id"
    ).execute()
    return _to_model(row)


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inspiration(
    media_id: str,
    user: UserState = Depends(get_current_user),
) -> Response:
    """Remove a saved inspiration (no error if it wasn't saved)."""

    get_client().table("user_inspirations").delete().eq("user_id", user.id).eq(
        "media_id", media_id
    ).execute()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
