"""Moment CRUD + Context + Generation Jobs.

Operates against `moments.moments`, `moments.moment_context`,
and `moments.generation_jobs`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from .auth import require_user
from .moments_schemas import (
    GenerationJobResponse,
    MomentContextResponse,
    MomentContextUpsert,
    MomentCreate,
    MomentResponse,
    MomentUpdate,
)
from .supabase_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/moments", tags=["moments"])

SCHEMA = "moments"


def _db():
    return get_client()


def _verify_plan_ownership(plan_id: str, user_id: str):
    """Verify the user owns the plan."""
    result = (
        _db()
        .schema(SCHEMA)
        .table("content_plans")
        .select("id")
        .eq("id", plan_id)
        .eq("owner_user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Plan not found")


def _verify_moment_ownership(moment_id: str, user_id: str) -> dict:
    """Verify the user owns the moment (via plan)."""
    result = (
        _db()
        .schema(SCHEMA)
        .table("moments")
        .select("*, content_plans!inner(owner_user_id)")
        .eq("id", moment_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Moment not found")
    plan = result.data.get("content_plans", {})
    if plan.get("owner_user_id") != user_id:
        raise HTTPException(403, "Not your moment")
    return result.data


# ═══════════════════════════════════════════════════════════
#  MOMENTS
# ═══════════════════════════════════════════════════════════

@router.post("/{plan_id}/create", response_model=MomentResponse, status_code=201)
async def create_moment(
    plan_id: str, body: MomentCreate, user=Depends(require_user)
):
    _verify_plan_ownership(plan_id, user.id)
    row = {
        "plan_id": plan_id,
        "block_id": body.block_id,
        "moment_type": body.moment_type,
        "image_count": body.image_count,
        "caption_hint": body.caption_hint,
        "status": "PLANNED",
    }
    result = _db().schema(SCHEMA).table("moments").insert(row).execute()
    return result.data[0]


@router.get("/by-plan/{plan_id}", response_model=list[MomentResponse])
async def list_moments_for_plan(plan_id: str, user=Depends(require_user)):
    _verify_plan_ownership(plan_id, user.id)
    result = (
        _db()
        .schema(SCHEMA)
        .table("moments")
        .select("*")
        .eq("plan_id", plan_id)
        .order("created_at")
        .execute()
    )
    return result.data


@router.get("/{moment_id}", response_model=MomentResponse)
async def get_moment(moment_id: str, user=Depends(require_user)):
    data = _verify_moment_ownership(moment_id, user.id)
    # Strip the join data
    data.pop("content_plans", None)

    # Fetch context
    ctx = (
        _db()
        .schema(SCHEMA)
        .table("moment_context")
        .select("*")
        .eq("moment_id", moment_id)
        .maybe_single()
        .execute()
    )
    data["context"] = ctx.data
    return data


@router.put("/{moment_id}", response_model=MomentResponse)
async def update_moment(
    moment_id: str, body: MomentUpdate, user=Depends(require_user)
):
    _verify_moment_ownership(moment_id, user.id)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "Nothing to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = (
        _db()
        .schema(SCHEMA)
        .table("moments")
        .update(updates)
        .eq("id", moment_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Moment not found")
    return result.data[0]


@router.delete("/{moment_id}", status_code=204)
async def delete_moment(moment_id: str, user=Depends(require_user)):
    _verify_moment_ownership(moment_id, user.id)
    _db().schema(SCHEMA).table("moments").delete().eq(
        "id", moment_id
    ).execute()


# ═══════════════════════════════════════════════════════════
#  MOMENT CONTEXT
# ═══════════════════════════════════════════════════════════

@router.put("/{moment_id}/context", response_model=MomentContextResponse)
async def upsert_moment_context(
    moment_id: str, body: MomentContextUpsert, user=Depends(require_user)
):
    _verify_moment_ownership(moment_id, user.id)
    row = {"moment_id": moment_id, **body.model_dump()}
    result = (
        _db()
        .schema(SCHEMA)
        .table("moment_context")
        .upsert(row)
        .execute()
    )
    return result.data[0]


@router.get("/{moment_id}/context", response_model=MomentContextResponse | None)
async def get_moment_context(moment_id: str, user=Depends(require_user)):
    _verify_moment_ownership(moment_id, user.id)
    result = (
        _db()
        .schema(SCHEMA)
        .table("moment_context")
        .select("*")
        .eq("moment_id", moment_id)
        .maybe_single()
        .execute()
    )
    return result.data


# ═══════════════════════════════════════════════════════════
#  REGENERATION + GENERATION JOBS
# ═══════════════════════════════════════════════════════════

@router.post("/{moment_id}/regenerate", response_model=GenerationJobResponse)
async def regenerate_moment(moment_id: str, user=Depends(require_user)):
    """Queue a new generation job for this moment."""
    _verify_moment_ownership(moment_id, user.id)

    # Reset moment status
    _db().schema(SCHEMA).table("moments").update({
        "status": "GENERATING",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", moment_id).execute()

    # Create new job
    job = {
        "moment_id": moment_id,
        "status": "queued",
    }
    result = (
        _db().schema(SCHEMA).table("generation_jobs").insert(job).execute()
    )
    return result.data[0]


@router.get("/{moment_id}/jobs", response_model=list[GenerationJobResponse])
async def list_moment_jobs(moment_id: str, user=Depends(require_user)):
    _verify_moment_ownership(moment_id, user.id)
    result = (
        _db()
        .schema(SCHEMA)
        .table("generation_jobs")
        .select("*")
        .eq("moment_id", moment_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data
