"""Persona CRUD + World Catalog management + Collaboration.

Operates against the `people` schema:
  - personas, persona_style_profile
  - world_locations, world_wardrobe_items
  - persona_members (collaboration)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
import os

from . import storage
from .auth import require_user
from .moments_schemas import (
    PersonaCreate,
    PersonaMemberAdd,
    PersonaMemberResponse,
    PersonaResponse,
    PersonaUpdate,
    StyleProfileResponse,
    StyleProfileUpsert,
    WorldLocationCreate,
    WorldLocationResponse,
    WorldWardrobeCreate,
    WorldWardrobeResponse,
)
from .supabase_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/personas", tags=["personas"])

SCHEMA = "people"


def _db():
    return get_client()


def _sign_avatar_url(url: str | None) -> str | None:
    if not url or "storage.googleapis.com" not in url:
        return url
    
    parts = url.split("storage.googleapis.com/")
    if len(parts) != 2:
        return url
        
    path_parts = parts[1].split("/", 1)
    if len(path_parts) != 2:
        return url
        
    bucket_name, blob_name = path_parts[0], path_parts[1]
    
    try:
        bucket = storage.get_bucket(bucket_name, None)
        blob = bucket.blob(blob_name)
        return storage.generate_signed_read_url_v4(blob, seconds=3600)
    except Exception as e:
        logger.warning(f"Failed to sign avatar URL: {e}")
        return url


# ═══════════════════════════════════════════════════════════
#  PERSONAS
# ═══════════════════════════════════════════════════════════

@router.post("", response_model=PersonaResponse, status_code=201)
async def create_persona(body: PersonaCreate, user=Depends(require_user)):
    row = {
        "owner_user_id": user.id,
        "display_name": body.display_name,
        "bio": body.bio,
        "is_public": body.is_public,
        "avatar_url": getattr(body, "avatar_url", None),
    }
    result = _db().schema(SCHEMA).table("personas").insert(row).execute()
    persona = result.data[0]

    # Auto-add owner as member
    _db().schema(SCHEMA).table("persona_members").insert({
        "persona_id": persona["id"],
        "user_id": user.id,
        "role": "owner",
    }).execute()

    return persona


@router.post("/{persona_id}/image", response_model=PersonaResponse)
async def upload_persona_image(
    persona_id: str,
    file: UploadFile = File(...),
    user=Depends(require_user)
):
    """Upload a persona avatar image."""
    await get_persona(persona_id, user)

    bucket_name = os.getenv("GCS_COLLECTIONS_APP_BUCKET", "app.gemzy.co")
    bucket = storage.get_bucket(bucket_name, None)

    # Use a timestamp or UUID to avoid caching issues if replaced
    prefix = storage.user_storage_prefix(user.id)
    blob_name = f"{prefix}/personas/{persona_id}/avatar-{file.filename}"
    blob = bucket.blob(blob_name)
    blob.upload_from_file(file.file, content_type=file.content_type)

    public_url = storage.build_public_url(blob_name, bucket_name)

    # Update DB
    result = (
        _db()
        .schema(SCHEMA)
        .table("personas")
        .update({"avatar_url": public_url, "updated_at": "now()"})
        .eq("id", persona_id)
        .execute()
    )
    return result.data[0]


@router.get("", response_model=list[PersonaResponse])
async def list_personas(user=Depends(require_user)):
    result = (
        _db()
        .schema(SCHEMA)
        .table("personas")
        .select("*")
        .eq("owner_user_id", user.id)
        .order("created_at", desc=True)
        .execute()
    )
    for p in result.data:
        p["avatar_url"] = _sign_avatar_url(p.get("avatar_url"))
    return result.data


@router.get("/discover", response_model=list[PersonaResponse])
async def discover_public_personas(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Browse public personas — no auth required. View is free, usage costs credits."""
    result = (
        _db()
        .schema(SCHEMA)
        .table("personas")
        .select("*")
        .eq("is_public", True)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    for p in result.data:
        p["avatar_url"] = _sign_avatar_url(p.get("avatar_url"))
    return result.data


@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(persona_id: str, user=Depends(require_user)):
    # Try owner first, then member, then public
    result = (
        _db()
        .schema(SCHEMA)
        .table("personas")
        .select("*")
        .eq("id", persona_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Persona not found")

    persona = result.data
    is_owner = persona["owner_user_id"] == user.id
    is_public = persona.get("is_public", False)

    if not is_owner and not is_public:
        # Check membership
        member = (
            _db()
            .schema(SCHEMA)
            .table("persona_members")
            .select("role")
            .eq("persona_id", persona_id)
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )
        if not member.data:
            raise HTTPException(403, "Not authorized to access this persona")

    persona["avatar_url"] = _sign_avatar_url(persona.get("avatar_url"))
    return persona


@router.put("/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    persona_id: str, body: PersonaUpdate, user=Depends(require_user)
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "Nothing to update")
    result = (
        _db()
        .schema(SCHEMA)
        .table("personas")
        .update(updates)
        .eq("id", persona_id)
        .eq("owner_user_id", user.id)
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Persona not found")
    return result.data[0]


@router.delete("/{persona_id}", status_code=204)
async def delete_persona(persona_id: str, user=Depends(require_user)):
    _db().schema(SCHEMA).table("personas").delete().eq(
        "id", persona_id
    ).eq("owner_user_id", user.id).execute()


# ═══════════════════════════════════════════════════════════
#  STYLE PROFILE
# ═══════════════════════════════════════════════════════════

@router.get("/{persona_id}/style", response_model=StyleProfileResponse | None)
async def get_style_profile(persona_id: str, user=Depends(require_user)):
    await get_persona(persona_id, user)
    result = (
        _db()
        .schema(SCHEMA)
        .table("persona_style_profile")
        .select("*")
        .eq("persona_id", persona_id)
        .maybe_single()
        .execute()
    )
    return result.data


@router.put("/{persona_id}/style", response_model=StyleProfileResponse)
async def upsert_style_profile(
    persona_id: str, body: StyleProfileUpsert, user=Depends(require_user)
):
    await get_persona(persona_id, user)
    row = {
        "persona_id": persona_id,
        **body.model_dump(),
    }
    result = (
        _db()
        .schema(SCHEMA)
        .table("persona_style_profile")
        .upsert(row)
        .execute()
    )
    return result.data[0]


# ═══════════════════════════════════════════════════════════
#  WORLD LOCATIONS
# ═══════════════════════════════════════════════════════════

@router.get("/{persona_id}/locations", response_model=list[WorldLocationResponse])
async def list_locations(persona_id: str, user=Depends(require_user)):
    await get_persona(persona_id, user)
    result = (
        _db()
        .schema(SCHEMA)
        .table("world_locations")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.post(
    "/{persona_id}/locations",
    response_model=WorldLocationResponse,
    status_code=201,
)
async def add_location(
    persona_id: str, body: WorldLocationCreate, user=Depends(require_user)
):
    await get_persona(persona_id, user)
    row = {"persona_id": persona_id, **body.model_dump()}
    result = (
        _db().schema(SCHEMA).table("world_locations").insert(row).execute()
    )
    return result.data[0]


@router.delete("/{persona_id}/locations/{location_id}", status_code=204)
async def delete_location(
    persona_id: str, location_id: str, user=Depends(require_user)
):
    await get_persona(persona_id, user)
    _db().schema(SCHEMA).table("world_locations").delete().eq(
        "id", location_id
    ).eq("persona_id", persona_id).execute()


# ═══════════════════════════════════════════════════════════
#  WORLD WARDROBE
# ═══════════════════════════════════════════════════════════

@router.get(
    "/{persona_id}/wardrobe", response_model=list[WorldWardrobeResponse]
)
async def list_wardrobe(persona_id: str, user=Depends(require_user)):
    await get_persona(persona_id, user)
    result = (
        _db()
        .schema(SCHEMA)
        .table("world_wardrobe_items")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.post(
    "/{persona_id}/wardrobe",
    response_model=WorldWardrobeResponse,
    status_code=201,
)
async def add_wardrobe_item(
    persona_id: str, body: WorldWardrobeCreate, user=Depends(require_user)
):
    await get_persona(persona_id, user)
    row = {"persona_id": persona_id, **body.model_dump()}
    result = (
        _db()
        .schema(SCHEMA)
        .table("world_wardrobe_items")
        .insert(row)
        .execute()
    )
    return result.data[0]


@router.delete("/{persona_id}/wardrobe/{item_id}", status_code=204)
async def delete_wardrobe_item(
    persona_id: str, item_id: str, user=Depends(require_user)
):
    await get_persona(persona_id, user)
    _db().schema(SCHEMA).table("world_wardrobe_items").delete().eq(
        "id", item_id
    ).eq("persona_id", persona_id).execute()


# ═══════════════════════════════════════════════════════════
#  PERSONA MEMBERS (collaboration)
# ═══════════════════════════════════════════════════════════

@router.get(
    "/{persona_id}/members", response_model=list[PersonaMemberResponse]
)
async def list_members(persona_id: str, user=Depends(require_user)):
    """List members of a persona. Must be owner or member to view."""
    await get_persona(persona_id, user)
    result = (
        _db()
        .schema(SCHEMA)
        .table("persona_members")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at")
        .execute()
    )
    return result.data


@router.post(
    "/{persona_id}/members",
    response_model=PersonaMemberResponse,
    status_code=201,
)
async def add_member(
    persona_id: str, body: PersonaMemberAdd, user=Depends(require_user)
):
    """Add a member to a persona. Only the owner can add members."""
    # Verify ownership (not just membership)
    persona = (
        _db()
        .schema(SCHEMA)
        .table("personas")
        .select("owner_user_id")
        .eq("id", persona_id)
        .single()
        .execute()
    )
    if not persona.data or persona.data["owner_user_id"] != user.id:
        raise HTTPException(403, "Only the persona owner can add members")

    row = {
        "persona_id": persona_id,
        "user_id": body.user_id,
        "role": body.role,
    }
    result = (
        _db().schema(SCHEMA).table("persona_members").upsert(row).execute()
    )
    return result.data[0]


@router.delete("/{persona_id}/members/{member_user_id}", status_code=204)
async def remove_member(
    persona_id: str, member_user_id: str, user=Depends(require_user)
):
    """Remove a member. Only the owner can remove others."""
    persona = (
        _db()
        .schema(SCHEMA)
        .table("personas")
        .select("owner_user_id")
        .eq("id", persona_id)
        .single()
        .execute()
    )
    if not persona.data or persona.data["owner_user_id"] != user.id:
        raise HTTPException(403, "Only the persona owner can remove members")

    if member_user_id == user.id:
        raise HTTPException(400, "Cannot remove yourself as owner")

    _db().schema(SCHEMA).table("persona_members").delete().eq(
        "persona_id", persona_id
    ).eq("user_id", member_user_id).execute()

