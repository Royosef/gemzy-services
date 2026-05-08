from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .auth import get_current_user
from .dashboard_ai import GEMZY_CONTEXT, call_claude
from .dashboard_common import dashboard_table, ensure_dashboard_admin, iso_or_none
from .schemas import (
    DashboardCoachActionResponse,
    DashboardCoachRecordActionPayload,
    DashboardCoachRecommendationResponse,
    DashboardCoachUndoPayload,
    DashboardUndoResponse,
    UserState,
)

router = APIRouter(prefix="/dashboard/coach", tags=["dashboard-coach"])
logger = logging.getLogger(__name__)
SNOOZE_DAYS = 7

RECOMMENDATION_SCHEMA = """[
  {
    "action": "<one-sentence action>",
    "reasoning": "<1-3 sentences grounded in the numbers, currency in ₪>",
    "executionNotes": "<under 80 words, where to make the change and what to watch>",
    "priority": "high" | "medium" | "low"
  }
]"""


def _priority_rank(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 3)


def _status_rank(status: str) -> int:
    return {"active": 0, "snoozed": 1}.get(status, 2)


def _parse_recommendations(text: str) -> list[dict[str, str]]:
    stripped = text.strip()
    stripped = stripped.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, list):
        raise ValueError("Claude response was not a JSON array")
    out: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("Recommendation was not an object")
        priority = item.get("priority")
        if priority not in {"high", "medium", "low"}:
            raise ValueError(f"Invalid priority: {priority}")
        out.append(
            {
                "action": str(item.get("action") or "").strip(),
                "reasoning": str(item.get("reasoning") or "").strip(),
                "executionNotes": str(item.get("executionNotes") or "").strip(),
                "priority": priority,
            }
        )
    return [item for item in out if item["action"] and item["reasoning"]]


def _recent_recommendations(limit: int) -> list[dict[str, Any]]:
    rows = (
        dashboard_table("recommendations")
        .select("action,reasoning,priority,created_at,status")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return rows


def _list_active_recommendations(context: str) -> list[DashboardCoachRecommendationResponse]:
    rows = (
        dashboard_table("recommendations")
        .select("*")
        .eq("context", context)
        .in_("status", ["active", "snoozed"])
        .execute()
        .data
        or []
    )
    rows.sort(key=lambda row: iso_or_none(row.get("created_at")) or "", reverse=True)
    rows.sort(key=lambda row: _priority_rank(str(row.get("priority") or "")))
    rows.sort(key=lambda row: _status_rank(str(row.get("status") or "")))
    return [
        DashboardCoachRecommendationResponse(
            id=row["id"],
            action=row.get("action") or "",
            reasoning=row.get("reasoning") or "",
            executionNotes=row.get("execution_notes"),
            priority=row.get("priority") or "low",
            status=row.get("status") or "active",
            createdAt=iso_or_none(row.get("created_at")),
            snoozedUntil=iso_or_none(row.get("snoozed_until")),
        )
        for row in rows
    ]


@router.post("/generate-overview", response_model=list[DashboardCoachRecommendationResponse])
async def generate_overview_recommendations(
    current: UserState = Depends(get_current_user),
) -> list[DashboardCoachRecommendationResponse]:
    ensure_dashboard_admin(current)
    ads = (
        dashboard_table("ads")
        .select("id,name,status,campaign_id,ad_set_id,spend,impressions,reach,results,cost_per_result,cpm,synced_at")
        .order("synced_at", desc=True)
        .limit(50)
        .execute()
        .data
        or []
    )
    ad_sets = dashboard_table("ad_sets").select("*").execute().data or []
    campaigns = (
        dashboard_table("campaigns").select("*").order("synced_at", desc=True).limit(25).execute().data or []
    )
    ad_set_map = {row["id"]: row for row in ad_sets}
    current_ads = []
    for ad in ads:
        ad_set = ad_set_map.get(ad.get("ad_set_id"))
        current_ads.append(
            {
                "id": ad["id"],
                "name": ad.get("name"),
                "status": ad.get("status"),
                "campaignId": ad.get("campaign_id"),
                "adSetId": ad.get("ad_set_id"),
                "spend": ad.get("spend"),
                "impressions": ad.get("impressions"),
                "reach": ad.get("reach"),
                "results": ad.get("results"),
                "costPerResult": ad.get("cost_per_result"),
                "cpm": ad.get("cpm"),
                "adSetName": ad_set.get("name") if ad_set else None,
                "adSetBudgetMode": ad_set.get("budget_mode") if ad_set else None,
                "adSetDailyBudget": ad_set.get("daily_budget") if ad_set else None,
                "adSetLifetimeBudget": ad_set.get("lifetime_budget") if ad_set else None,
                "adSetLearningStage": ad_set.get("learning_stage") if ad_set else None,
                "adSetOptimizationGoal": ad_set.get("optimization_goal") if ad_set else None,
            }
        )

    recent = _recent_recommendations(25)
    recent_log = (
        "\n".join(
            f"- {iso_or_none(row.get('created_at'))} [{row.get('priority')}] [{row.get('status')}] {row.get('action')} // reason: {row.get('reasoning')}"
            for row in recent
        )
        if recent
        else "(no recent recommendations)"
    )
    user_message = f"""CONTEXT: overview

CURRENT DATA:
{json.dumps({'campaigns': campaigns, 'ads': current_ads}, indent=2, default=str)}

RECENT DECISION LOG (most recent first):
{recent_log}

Return recommendations in this exact JSON shape, nothing else:
{RECOMMENDATION_SCHEMA}"""
    result = await call_claude(GEMZY_CONTEXT, user_message, max_tokens=4096)
    parsed = _parse_recommendations(result["text"])
    if not parsed:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Claude did not return usable recommendations")

    rows = [
        {
            "context": "overview",
            "action": item["action"],
            "reasoning": item["reasoning"],
            "execution_notes": item["executionNotes"],
            "priority": item["priority"],
            "based_on": {"adCount": len(current_ads), "campaignCount": len(campaigns)},
        }
        for item in parsed
    ]
    saved = dashboard_table("recommendations").insert(rows).execute().data or []
    return [
        DashboardCoachRecommendationResponse(
            id=row["id"],
            action=row.get("action") or "",
            reasoning=row.get("reasoning") or "",
            executionNotes=row.get("execution_notes"),
            priority=row.get("priority") or "low",
            status=row.get("status") or "active",
            createdAt=iso_or_none(row.get("created_at")),
            snoozedUntil=iso_or_none(row.get("snoozed_until")),
        )
        for row in saved
    ]


@router.get("/recommendations", response_model=list[DashboardCoachRecommendationResponse])
def list_active_recommendations(
    context: str = Query(default="overview"),
    current: UserState = Depends(get_current_user),
) -> list[DashboardCoachRecommendationResponse]:
    ensure_dashboard_admin(current)
    return _list_active_recommendations(context)


@router.post("/actions", response_model=DashboardCoachActionResponse)
def record_recommendation_action(
    payload: DashboardCoachRecordActionPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardCoachActionResponse:
    ensure_dashboard_admin(current)
    recommendation_rows = (
        dashboard_table("recommendations").select("*").eq("id", payload.recommendationId).limit(1).execute().data or []
    )
    if not recommendation_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    inserted = (
        dashboard_table("recommendation_actions")
        .insert(
            {
                "recommendation_id": payload.recommendationId,
                "action": payload.action,
                "note": payload.note,
            }
        )
        .execute()
        .data
        or []
    )
    if not inserted:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to record action")
    snoozed_until = (
        datetime.now(timezone.utc) + timedelta(days=SNOOZE_DAYS) if payload.action == "snoozed" else None
    )
    dashboard_table("recommendations").update(
        {
            "status": payload.action,
            "completed_at": datetime.now(timezone.utc).isoformat() if payload.action == "done" else None,
            "snoozed_until": snoozed_until.isoformat() if snoozed_until else None,
        }
    ).eq("id", payload.recommendationId).execute()
    row = inserted[0]
    return DashboardCoachActionResponse(
        id=row["id"],
        recommendationId=row.get("recommendation_id") or payload.recommendationId,
        action=row.get("action") or payload.action,
        note=row.get("note"),
        createdAt=iso_or_none(row.get("created_at")),
    )


@router.post("/actions/undo", response_model=DashboardUndoResponse)
def undo_recommendation_action(
    payload: DashboardCoachUndoPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardUndoResponse:
    ensure_dashboard_admin(current)
    rows = (
        dashboard_table("recommendation_actions")
        .select("*")
        .eq("id", payload.recommendationActionId)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation action not found")
    row = rows[0]
    dashboard_table("recommendation_actions").delete().eq("id", payload.recommendationActionId).execute()
    dashboard_table("recommendations").update(
        {"status": "active", "completed_at": None, "snoozed_until": None}
    ).eq("id", row.get("recommendation_id")).execute()
    return DashboardUndoResponse(recommendationId=row.get("recommendation_id"))
