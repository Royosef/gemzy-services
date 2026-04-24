"""Content Plan CRUD + Plan Block management.

Operates against `moments.content_plans` and `moments.plan_blocks`.
Plans go through: DRAFT → AWAITING_CONFIRMATION → CONFIRMED → GENERATING → READY
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from .auth import require_user
from .moments_schemas import (
    ContentPlanCreate,
    ContentPlanResponse,
    ContentPlanUpdate,
    PlanBlockCreate,
    PlanBlockResponse,
)
from .supabase_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content-plans", tags=["content-plans"])

SCHEMA = "moments"


def _db():
    return get_client()


# ═══════════════════════════════════════════════════════════
#  CONTENT PLANS
# ═══════════════════════════════════════════════════════════

@router.post("", response_model=ContentPlanResponse, status_code=201)
async def create_plan(body: ContentPlanCreate, user=Depends(require_user)):
    row = {
        "persona_id": body.persona_id,
        "owner_user_id": user.id,
        "plan_type": body.plan_type,
        "date_start": str(body.date_start),
        "date_end": str(body.date_end or body.date_start),
        "source_prompt": body.source_prompt,
        "status": "DRAFT",
    }
    result = _db().schema(SCHEMA).table("content_plans").insert(row).execute()
    return result.data[0]


@router.get("", response_model=list[ContentPlanResponse])
async def list_plans(
    persona_id: str | None = None,
    user=Depends(require_user),
):
    q = (
        _db()
        .schema(SCHEMA)
        .table("content_plans")
        .select("*")
        .eq("owner_user_id", user.id)
    )
    if persona_id:
        q = q.eq("persona_id", persona_id)
    result = q.order("date_start", desc=True).execute()
    return result.data


@router.get("/{plan_id}", response_model=ContentPlanResponse)
async def get_plan(plan_id: str, user=Depends(require_user)):
    plan = (
        _db()
        .schema(SCHEMA)
        .table("content_plans")
        .select("*")
        .eq("id", plan_id)
        .eq("owner_user_id", user.id)
        .single()
        .execute()
    )
    if not plan.data:
        raise HTTPException(404, "Plan not found")

    # Fetch blocks with their moments
    blocks = (
        _db()
        .schema(SCHEMA)
        .table("plan_blocks")
        .select("*")
        .eq("plan_id", plan_id)
        .order("created_at")
        .execute()
    ).data or []

    for block in blocks:
        block_moments = (
            _db()
            .schema(SCHEMA)
            .table("moments")
            .select("*")
            .eq("block_id", block["id"])
            .order("created_at")
            .execute()
        ).data or []
        block["moments"] = block_moments

    data = plan.data
    data["blocks"] = blocks
    return data


@router.put("/{plan_id}", response_model=ContentPlanResponse)
async def update_plan(
    plan_id: str, body: ContentPlanUpdate, user=Depends(require_user)
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "Nothing to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = (
        _db()
        .schema(SCHEMA)
        .table("content_plans")
        .update(updates)
        .eq("id", plan_id)
        .eq("owner_user_id", user.id)
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Plan not found")
    return result.data[0]


@router.delete("/{plan_id}", status_code=204)
async def delete_plan(plan_id: str, user=Depends(require_user)):
    _db().schema(SCHEMA).table("content_plans").delete().eq(
        "id", plan_id
    ).eq("owner_user_id", user.id).execute()


# ── Plan state transitions ──────────────────────────────

@router.post("/{plan_id}/confirm", response_model=ContentPlanResponse)
async def confirm_plan(plan_id: str, user=Depends(require_user)):
    """Move plan from AWAITING_CONFIRMATION → CONFIRMED → GENERATING.

    Creates generation jobs for every APPROVED moment.
    """
    plan = (
        _db()
        .schema(SCHEMA)
        .table("content_plans")
        .select("*")
        .eq("id", plan_id)
        .eq("owner_user_id", user.id)
        .single()
        .execute()
    )
    if not plan.data:
        raise HTTPException(404, "Plan not found")

    if plan.data["status"] not in ("DRAFT", "AWAITING_CONFIRMATION"):
        raise HTTPException(
            400,
            f"Cannot confirm plan in '{plan.data['status']}' status",
        )

    # Approve all PLANNED moments
    _db().schema(SCHEMA).table("moments").update(
        {"status": "APPROVED", "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("plan_id", plan_id).eq("status", "PLANNED").execute()

    # Transition to CONFIRMED then GENERATING
    now = datetime.now(timezone.utc).isoformat()
    _db().schema(SCHEMA).table("content_plans").update(
        {"status": "GENERATING", "updated_at": now}
    ).eq("id", plan_id).execute()

    # Create generation jobs for approved moments
    approved = (
        _db()
        .schema(SCHEMA)
        .table("moments")
        .select("id")
        .eq("plan_id", plan_id)
        .eq("status", "APPROVED")
        .execute()
    ).data or []

    if approved:
        jobs = [
            {"moment_id": m["id"], "status": "queued"}
            for m in approved
        ]
        _db().schema(SCHEMA).table("generation_jobs").insert(jobs).execute()

        # Transition moments to GENERATING
        _db().schema(SCHEMA).table("moments").update(
            {"status": "GENERATING", "updated_at": now}
        ).eq("plan_id", plan_id).eq("status", "APPROVED").execute()

    # Return updated plan
    return await get_plan(plan_id, user)


# ═══════════════════════════════════════════════════════════
#  PLAN BLOCKS
# ═══════════════════════════════════════════════════════════

@router.post(
    "/{plan_id}/blocks",
    response_model=PlanBlockResponse,
    status_code=201,
)
async def add_block(
    plan_id: str, body: PlanBlockCreate, user=Depends(require_user)
):
    # Verify ownership
    plan = (
        _db()
        .schema(SCHEMA)
        .table("content_plans")
        .select("id")
        .eq("id", plan_id)
        .eq("owner_user_id", user.id)
        .single()
        .execute()
    )
    if not plan.data:
        raise HTTPException(404, "Plan not found")

    row = {"plan_id": plan_id, **body.model_dump()}
    result = (
        _db().schema(SCHEMA).table("plan_blocks").insert(row).execute()
    )
    return result.data[0]


@router.get("/{plan_id}/blocks", response_model=list[PlanBlockResponse])
async def list_blocks(plan_id: str, user=Depends(require_user)):
    # Verify ownership
    plan = (
        _db()
        .schema(SCHEMA)
        .table("content_plans")
        .select("id")
        .eq("id", plan_id)
        .eq("owner_user_id", user.id)
        .single()
        .execute()
    )
    if not plan.data:
        raise HTTPException(404, "Plan not found")

    result = (
        _db()
        .schema(SCHEMA)
        .table("plan_blocks")
        .select("*")
        .eq("plan_id", plan_id)
        .order("created_at")
        .execute()
    )
    return result.data


@router.delete("/{plan_id}/blocks/{block_id}", status_code=204)
async def delete_block(
    plan_id: str, block_id: str, user=Depends(require_user)
):
    plan = (
        _db()
        .schema(SCHEMA)
        .table("content_plans")
        .select("id")
        .eq("id", plan_id)
        .eq("owner_user_id", user.id)
        .single()
        .execute()
    )
    if not plan.data:
        raise HTTPException(404, "Plan not found")

    _db().schema(SCHEMA).table("plan_blocks").delete().eq(
        "id", block_id
    ).eq("plan_id", plan_id).execute()
