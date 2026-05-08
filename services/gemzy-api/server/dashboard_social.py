from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from .auth import get_current_user
from .dashboard_ai import GEMZY_CONTEXT, call_claude
from .dashboard_common import dashboard_table, ensure_dashboard_admin, iso_or_none
from .schemas import (
    DashboardGenerateDailyActionsResponse,
    DashboardSocialActionResultResponse,
    DashboardSocialAccountResponse,
    DashboardSocialGenerateStatsResponse,
    DashboardSocialRecommendationResponse,
    DashboardSocialRecordActionPayload,
    DashboardSocialStatsResponse,
    DashboardSocialUndoPayload,
    DashboardUndoResponse,
    UserState,
)

router = APIRouter(prefix="/dashboard/social", tags=["dashboard-social"])
logger = logging.getLogger(__name__)

DAILY_ACTIONS_SCHEMA = """[
  {
    "accountId": "<handle from the payload, exact match>",
    "actionType": "Comment" | "Follow" | "DM_Cold",
    "reasoning": "<1-2 sentences grounded in the account payload>",
    "priority": "high" | "medium" | "low",
    "postTypes": [{"label": "product_closeup", "template": "<comment>"}],
    "suggestedMove": "<follow motion>",
    "dmTemplate": "<cold DM>"
  }
]"""


def _priority_rank(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 3)


def _account_payload(row: dict[str, Any] | None) -> DashboardSocialAccountResponse | None:
    if not row:
        return None
    return DashboardSocialAccountResponse(
        id=row.get("id"),
        username=row.get("username"),
        followerCount=row.get("follower_count"),
        niche=row.get("niche"),
        location=row.get("location"),
        fitScore=row.get("fit_score"),
        sourceUrl=row.get("source_url"),
        discoveredViaQuery=row.get("discovered_via_query"),
    )


def _recommendation_payload(row: dict[str, Any], account: dict[str, Any] | None) -> DashboardSocialRecommendationResponse:
    details = row.get("details")
    if details is not None and not isinstance(details, dict):
        details = {}
    return DashboardSocialRecommendationResponse(
        id=row["id"],
        accountId=row.get("account_id") or "",
        actionType=row.get("action_type") or "",
        suggestedText=row.get("suggested_text"),
        details=details,
        reasoning=row.get("reasoning") or "",
        priority=row.get("priority") or "low",
        status=row.get("status") or "active",
        generatedAt=iso_or_none(row.get("generated_at")),
        actedAt=iso_or_none(row.get("acted_at")),
        account=_account_payload(account),
    )


def _parse_daily_actions(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    stripped = stripped.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, list):
        raise ValueError("Claude response was not a JSON array")
    output: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        action_type = item.get("actionType")
        if action_type not in {"Comment", "Follow", "DM_Cold"}:
            continue
        priority = item.get("priority")
        if priority not in {"high", "medium", "low"}:
            continue
        output.append(item)
    return output


async def _generate_daily_actions_impl() -> DashboardGenerateDailyActionsResponse:
    actions_cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    dismiss_cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

    recent_actions = dashboard_table("social_actions").select("*").execute().data or []
    excluded_ids: set[str] = set()
    for row in recent_actions:
        account_id = row.get("account_id")
        if not account_id:
            continue
        created_at = iso_or_none(row.get("created_at")) or ""
        action_type = row.get("action_type")
        if action_type == "Dismissed" and created_at > dismiss_cutoff:
            excluded_ids.add(account_id)
        elif action_type != "Dismissed" and created_at > actions_cutoff:
            excluded_ids.add(account_id)

    candidates = (
        dashboard_table("social_accounts")
        .select("id,username,follower_count,niche,location,fit_score,discovered_via_query,source_url,bad_fit_flag,discovery_source")
        .eq("discovery_source", "tavily_search")
        .eq("bad_fit_flag", False)
        .order("fit_score", desc=True)
        .limit(30)
        .execute()
        .data
        or []
    )
    candidates = [row for row in candidates if row.get("id") not in excluded_ids]

    recent_recommendations = (
        dashboard_table("social_recommendations")
        .select("account_id,action_type,reasoning,status,generated_at")
        .order("generated_at", desc=True)
        .limit(50)
        .execute()
        .data
        or []
    )

    candidate_payload = [
        {
            "accountId": row.get("id"),
            "handle": f"@{row.get('username')}",
            "followerCount": row.get("follower_count"),
            "niche": row.get("niche"),
            "location": row.get("location"),
            "fitScore": row.get("fit_score"),
            "discoveredViaQuery": row.get("discovered_via_query"),
            "sourceUrl": row.get("source_url"),
        }
        for row in candidates
    ]
    recent_log = [
        {
            "accountId": row.get("account_id"),
            "actionType": row.get("action_type"),
            "reasoning": row.get("reasoning"),
            "status": row.get("status"),
            "generatedAt": iso_or_none(row.get("generated_at")),
        }
        for row in recent_recommendations
    ]
    user_message = f"""CONTEXT: daily_actions

Produce outreach actions for @gemzy_co. Every recommendation here targets a cold account discovered via Tavily. Use only accountIds from the payload. No duplicate accountIds. Comments should include exactly four templates: product_closeup, styled_lifestyle, process_bts, universal. Follows should use suggestedMove. DMs should use dmTemplate. Keep the output JSON only.

CANDIDATES:
{json.dumps(candidate_payload, indent=2)}

RECENT RECOMMENDATIONS:
{json.dumps(recent_log, indent=2)}

Return a JSON array in this shape:
{DAILY_ACTIONS_SCHEMA}"""
    result = await call_claude(GEMZY_CONTEXT, user_message, max_tokens=3500)
    parsed = _parse_daily_actions(result["text"])
    if not parsed:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Claude did not return usable daily actions")

    by_id = {row["id"]: row for row in candidates if row.get("id")}
    saved_rows = []
    seen_account_ids: set[str] = set()
    for item in parsed:
        account_id = item.get("accountId")
        if account_id not in by_id or account_id in seen_account_ids:
            continue
        seen_account_ids.add(account_id)
        details: dict[str, Any] | None = None
        suggested_text: str | None = None
        if item["actionType"] == "Comment":
            details = {"postTypes": item.get("postTypes") or []}
        elif item["actionType"] == "Follow":
            suggested_text = item.get("suggestedMove")
            details = {"suggestedMove": suggested_text}
        elif item["actionType"] == "DM_Cold":
            suggested_text = item.get("dmTemplate")
            details = {"dmTemplate": suggested_text}
        created = (
            dashboard_table("social_recommendations")
            .insert(
                {
                    "account_id": account_id,
                    "action_type": item["actionType"],
                    "suggested_text": suggested_text,
                    "details": details,
                    "context": "daily_actions",
                    "reasoning": item.get("reasoning") or "",
                    "priority": item.get("priority") or "low",
                    "status": "active",
                }
            )
            .execute()
            .data
            or []
        )
        if created:
            saved_rows.append(created[0])

    recommendations = [
        _recommendation_payload(row, by_id.get(row.get("account_id")))
        for row in saved_rows
    ]
    return DashboardGenerateDailyActionsResponse(
        recommendations=recommendations,
        stats=DashboardSocialGenerateStatsResponse(
            candidatesSelected=len(candidates),
            recentRecommendationCount=len(recent_recommendations),
            generatedCount=len(recommendations),
        ),
    )


@router.post("/generate-daily-actions", response_model=DashboardGenerateDailyActionsResponse)
async def generate_daily_actions(current: UserState = Depends(get_current_user)) -> DashboardGenerateDailyActionsResponse:
    ensure_dashboard_admin(current)
    return await _generate_daily_actions_impl()


@router.get("/actions", response_model=list[DashboardSocialRecommendationResponse])
def list_active_daily_actions(
    current: UserState = Depends(get_current_user),
) -> list[DashboardSocialRecommendationResponse]:
    ensure_dashboard_admin(current)
    recommendations = (
        dashboard_table("social_recommendations")
        .select("*")
        .eq("context", "daily_actions")
        .eq("status", "active")
        .execute()
        .data
        or []
    )
    recommendations.sort(key=lambda row: iso_or_none(row.get("generated_at")) or "", reverse=True)
    recommendations.sort(key=lambda row: _priority_rank(str(row.get("priority") or "")))
    account_ids = [row.get("account_id") for row in recommendations if row.get("account_id")]
    accounts = (
        dashboard_table("social_accounts").select("*").in_("id", account_ids).execute().data or []
        if account_ids
        else []
    )
    account_map = {row["id"]: row for row in accounts}
    return [_recommendation_payload(row, account_map.get(row.get("account_id"))) for row in recommendations]


@router.post("/actions", response_model=DashboardSocialActionResultResponse)
def record_social_action(
    payload: DashboardSocialRecordActionPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardSocialActionResultResponse:
    ensure_dashboard_admin(current)
    recommendation_rows = (
        dashboard_table("social_recommendations").select("*").eq("id", payload.recommendationId).limit(1).execute().data or []
    )
    if not recommendation_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    recommendation = recommendation_rows[0]
    inserted = (
        dashboard_table("social_actions")
        .insert(
            {
                "account_id": recommendation.get("account_id"),
                "action_type": payload.actionType,
                "note": payload.note,
                "template_used_id": payload.templateUsedId,
                "template_custom_text": payload.templateCustomText,
                "dismiss_reason": payload.dismissReason,
                "recommendation_id": payload.recommendationId,
            }
        )
        .execute()
        .data
        or []
    )
    if not inserted:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to record action")
    status_value = "dismissed" if payload.actionType == "Dismissed" else "acted"
    dashboard_table("social_recommendations").update(
        {"status": status_value, "acted_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", payload.recommendationId).execute()
    if payload.actionType == "Dismissed" and payload.dismissReason in {"doesnt_match_niche", "not_a_real_brand"}:
        dashboard_table("social_accounts").update({"bad_fit_flag": True}).eq(
            "id", recommendation.get("account_id")
        ).execute()
    return DashboardSocialActionResultResponse(actionId=inserted[0]["id"], status=status_value)


@router.post("/actions/undo", response_model=DashboardUndoResponse)
def undo_social_action(
    payload: DashboardSocialUndoPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardUndoResponse:
    ensure_dashboard_admin(current)
    rows = (
        dashboard_table("social_actions")
        .select("*")
        .eq("recommendation_id", payload.recommendationId)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No action to undo")
    row = rows[0]
    dashboard_table("social_actions").delete().eq("id", row["id"]).execute()
    dashboard_table("social_recommendations").update({"status": "active", "acted_at": None}).eq(
        "id", payload.recommendationId
    ).execute()
    if row.get("action_type") == "Dismissed" and row.get("dismiss_reason") in {"doesnt_match_niche", "not_a_real_brand"}:
        dashboard_table("social_accounts").update({"bad_fit_flag": False}).eq(
            "id", row.get("account_id")
        ).execute()
    return DashboardUndoResponse(recommendationId=payload.recommendationId)


@router.get("/stats", response_model=DashboardSocialStatsResponse)
def get_daily_stats(current: UserState = Depends(get_current_user)) -> DashboardSocialStatsResponse:
    ensure_dashboard_admin(current)
    start_of_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    actions = (
        dashboard_table("social_actions").select("action_type,created_at").gt("created_at", start_of_today).execute().data
        or []
    )
    recommendations = (
        dashboard_table("social_recommendations")
        .select("id")
        .eq("context", "daily_actions")
        .eq("status", "active")
        .execute()
        .data
        or []
    )
    counts = {"Commented": 0, "Followed": 0, "DMed": 0, "Ignored": 0, "Dismissed": 0}
    for row in actions:
        action_type = row.get("action_type")
        if action_type in counts:
            counts[action_type] += 1
    return DashboardSocialStatsResponse(
        completedToday=len(actions),
        totalActiveRecs=len(recommendations),
        actionsByType=counts,
    )
