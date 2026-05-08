from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from .auth import get_current_user
from .dashboard_ai import GEMZY_CONTEXT, call_claude
from .dashboard_common import dashboard_table, ensure_dashboard_admin, iso_or_none, utc_now_iso
from .schemas import UserState
from .supabase_client import get_service_role_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard/funnel", tags=["dashboard-funnel"])
coach_stream_router = APIRouter(tags=["dashboard-funnel"])

StageKey = Literal["awareness", "consideration", "conversion", "retention"]
STAGE_ORDER: tuple[StageKey, ...] = (
    "awareness",
    "consideration",
    "conversion",
    "retention",
)
STAGE_DEFAULTS: dict[StageKey, dict[str, Any]] = {
    "awareness": {"metric": "website_visitors_or_reach", "target": 1000},
    "consideration": {"metric": "engagement_or_retargeted_reach", "target": 500},
    "conversion": {"metric": "app_installs_or_signups", "target": 10},
    "retention": {"metric": "active_paying_subscribers", "target": 50},
}
STALE_DAYS = 14
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
ASSETS_BUCKET = "dashboard-assets"
SIGNED_URL_TTL_SECONDS = 3600
MAX_ATTACHMENTS_PER_MESSAGE = 4
PRICE_INPUT_PER_M = 15
PRICE_OUTPUT_PER_M = 75
PRICE_CACHE_READ_PER_M = 1.5
PRICE_CACHE_WRITE_PER_M = 18.75

REPLY_TAG_OPEN = "{{REPLY}}"
REPLY_TAG_CLOSE = "{{/REPLY}}"
META_TAG_OPEN = "{{META}}"
META_TAG_CLOSE = "{{/META}}"

STEP_SCHEMA_REFERENCE = """STEP SCHEMAS (suggestedPanelUpdate.data shape by step):
  step 1 audience:    {"interests": string[], "ageMin": number, "ageMax": number, "gender": "all"|"female"|"male", "audienceSizeEstimate": number | null}
  step 2 creative:    {"format"?: string, "whatToShow"?: string, "hasCreativeReady"?: boolean, "variantUpdates"?: Array<{"variant": "A"|"B"|"C"|"D"|"E", "field": "hookAngle"|"primaryText"|"headline"|"cta", "value": string}>}
  step 3 campaign:    {"objective"?: string, "performanceGoal"?: string, "dailyBudget"?: number | null, "audienceType"?: "interest"|"custom"|"lookalike", "placements"?: string[], "ctaButton"?: string, "campaignName"?: string}
  step 4 launch:      {"campaignCreatedInMeta": boolean, "metaCampaignId"?: string | null}
"""

COACH_SYSTEM_PROMPT = f"""{GEMZY_CONTEXT}

YOU ARE THE GEMZY FUNNEL COACH
Neo is running a Meta ads funnel through four stages: Awareness, Consideration, Conversion, Retention. Each stage has a 4-step flow:
  1. Define audience
  2. Brief creative
  3. Set up campaign in Meta
  4. Launch

HARD RULES
- When the user says something that can be structured into a step field, emit a panel update with the parsed data and explain briefly what you are suggesting.
- If the user asks about something outside the current step, answer briefly and steer back to the current step.
- Currency is always ₪. Never $.
- Voice: period-ended, no em dashes, no "Please", confident, editorial, "we" not "I".
- If information is not in the data, say so plainly. Do not fabricate.
- Reference prior stages' decisions when they are relevant.

FORMATTING
- Break content into short paragraphs separated by blank lines.
- Use markdown bullet lists when listing 3 or more items.
- Use **bold** to highlight key decisions or specific numbers.

OUTPUT FORMAT
Return your response in two tagged blocks, in this order, and nothing else.

{{REPLY}}
<markdown reply>
{{/REPLY}}
{{META}}
{{"suggestedPanelUpdate": null | {{"step": 1|2|3|4, "data": {{ ... }}}}, "stepReady": false | true}}
{{/META}}

{STEP_SCHEMA_REFERENCE}
"""

REVIEW_SYSTEM_PROMPT = f"""{GEMZY_CONTEXT}

You are reviewing a manual panel edit Neo just made in the funnel builder.

Only respond when the change is clearly off-strategy or internally inconsistent.
If the change is fine or debatable, return null.
Keep the message under 50 words.
Reference the field name and the new value specifically.

Return ONLY this JSON object:
{{"message": null | "<message>"}}
"""


def _normalize_utc_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None

THRESHOLD_SUGGESTION_SYSTEM_PROMPT = f"""{GEMZY_CONTEXT}

You are picking a realistic threshold target for one stage of a Meta ads funnel.

Principles:
1. Reachability beats industry numbers. The target should be reachable in 7 to 21 days.
2. For conversion-style metrics, account for Meta's learning-phase floor.
3. Use account benchmarks when present. Otherwise use reasonable Gemzy defaults.
4. Round to a clean intentional number.

Return ONLY this JSON object:
{{"value": <positive integer>, "rationale": "<one concise sentence under 18 words>"}}
"""


def _dashboard_storage_bucket():
    return get_service_role_client().storage.from_(ASSETS_BUCKET)


def _sanitize_file_name(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    raw_stem = stem if dot else name
    raw_ext = ext if dot else ""
    clean_stem = (
        "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in raw_stem.lower()).strip("-")[:60]
        or "file"
    )
    clean_ext = "".join(ch for ch in raw_ext.lower() if ch.isalnum())[:8]
    return f"{clean_stem}.{clean_ext}" if clean_ext else clean_stem


def _create_signed_url(storage_path: str, expires_in: int = SIGNED_URL_TTL_SECONDS) -> str:
    payload = _dashboard_storage_bucket().create_signed_url(storage_path, expires_in)
    signed_url = payload.get("signedURL") or payload.get("signedUrl")
    if not signed_url:
        raise RuntimeError(f"Could not create signed URL for {storage_path}.")
    return signed_url


def _upload_dashboard_image(*, buffer: bytes, file_name: str, mime_type: str, funnel_id: str, stage: str) -> dict[str, str]:
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type.")
    if not buffer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty.")
    if len(buffer) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds 5MB limit.")
    safe_name = _sanitize_file_name(file_name)
    storage_path = f"funnels/{funnel_id}/stages/{stage}/{uuid4()}-{safe_name}"
    _dashboard_storage_bucket().upload(
        storage_path,
        buffer,
        {"content-type": mime_type, "upsert": "false"},
    )
    return {"storagePath": storage_path, "signedUrl": _create_signed_url(storage_path)}


def _delete_dashboard_image(storage_path: str) -> None:
    _dashboard_storage_bucket().remove([storage_path])


def _priority_cost(u: dict[str, int]) -> float:
    base_input = max(0, u["input"] - u["cacheRead"])
    usd = (
        (base_input * PRICE_INPUT_PER_M) / 1_000_000
        + (u["cacheRead"] * PRICE_CACHE_READ_PER_M) / 1_000_000
        + (u["output"] * PRICE_OUTPUT_PER_M) / 1_000_000
        + (u["cacheCreation"] * PRICE_CACHE_WRITE_PER_M) / 1_000_000
    )
    return round(usd, 5)


def _metric_label(metric: str | None) -> str:
    labels = {
        "reach": "Reach (unique people)",
        "impressions": "Impressions",
        "website_visitors": "Website visitors",
        "link_clicks": "Link clicks",
        "engagement_events": "Engagement events",
        "video_views": "Video views",
        "app_installs": "App installs",
        "app_events": "App events",
        "leads": "Leads",
        "sign_ups": "Sign-ups",
        "conversions": "Conversions",
        "purchases": "Purchases",
        "active_subscribers": "Active subscribers",
        "active_paying_subscribers": "Active paying subscribers",
    }
    return labels.get(metric or "", metric or "unset")


def _objectives_for_metric(metric: str) -> list[str]:
    mapping = {
        "app_installs": ["OUTCOME_APP_PROMOTION"],
        "app_events": ["OUTCOME_APP_PROMOTION"],
        "leads": ["OUTCOME_LEADS"],
        "sign_ups": ["OUTCOME_LEADS", "OUTCOME_APP_PROMOTION", "OUTCOME_SALES"],
        "purchases": ["OUTCOME_SALES"],
        "conversions": ["OUTCOME_LEADS", "OUTCOME_SALES", "OUTCOME_APP_PROMOTION"],
        "link_clicks": ["OUTCOME_TRAFFIC"],
        "website_visitors": ["OUTCOME_TRAFFIC", "OUTCOME_AWARENESS"],
        "engagement_events": ["OUTCOME_ENGAGEMENT"],
        "video_views": ["OUTCOME_ENGAGEMENT"],
        "reach": ["OUTCOME_AWARENESS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT"],
        "impressions": ["OUTCOME_AWARENESS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT"],
    }
    return list(mapping.get(metric, []))


def _is_conversion_metric(metric: str) -> bool:
    return metric in {"app_installs", "app_events", "leads", "sign_ups", "conversions", "purchases"}


def _suggest_stage_from_objective(objective: str | None) -> StageKey | None:
    if objective in {"OUTCOME_AWARENESS", "OUTCOME_TRAFFIC"}:
        return "awareness"
    if objective == "OUTCOME_ENGAGEMENT":
        return "consideration"
    if objective in {"OUTCOME_LEADS", "OUTCOME_APP_PROMOTION"}:
        return "conversion"
    if objective == "OUTCOME_SALES":
        return "retention"
    return None


def _default_stage_progress(stage: StageKey, metrics: dict[str, int]) -> tuple[int | None, str, str]:
    if stage == "awareness":
        return metrics["landingPageViews"], "landing_page_views", "ok"
    if stage == "consideration":
        return metrics["engagements"], "engagements", "ok"
    if stage == "conversion":
        return metrics["conversions"], "conversions", "ok"
    return None, "revenuecat_subscribers", "unavailable_revenuecat"


def _resolve_stage_progress(
    threshold_metric: str | None,
    stage: StageKey,
    metrics: dict[str, int],
    campaigns: list[dict[str, Any]],
) -> tuple[int | None, str, str]:
    if threshold_metric == "website_visitors":
        return metrics["landingPageViews"], "landing_page_views", "ok"
    if threshold_metric == "reach":
        return metrics["reach"], "reach", "ok"
    if threshold_metric == "impressions":
        return metrics["impressions"], "impressions", "ok"
    if threshold_metric == "engagement_events":
        return metrics["engagements"], "engagements", "ok"
    if threshold_metric == "link_clicks":
        return metrics["landingPageViews"], "landing_page_views", "ok"
    if threshold_metric in {"app_installs", "app_events"}:
        installs = sum(
            int(c.get("results") or 0)
            for c in campaigns
            if c.get("objective") == "OUTCOME_APP_PROMOTION"
        )
        return installs, threshold_metric, "ok"
    if threshold_metric in {"leads", "sign_ups", "conversions", "purchases"}:
        return metrics["results"], threshold_metric, "ok"
    if threshold_metric == "video_views":
        return metrics["engagements"], "engagements", "ok"
    if threshold_metric in {"active_subscribers", "active_paying_subscribers"}:
        return None, "revenuecat_subscribers", "unavailable_revenuecat"
    return _default_stage_progress(stage, metrics)


def _build_stage_health_summary(
    *,
    stage: StageKey,
    effective_status: str,
    campaign_count: int,
    current_progress: int | None,
    threshold_target: int | None,
    progress_data_status: str,
    age_days: int,
) -> str:
    label = stage.capitalize()
    if progress_data_status == "unavailable_revenuecat":
        return f"{label} progress arrives once RevenueCat is wired up."
    if campaign_count == 0 and effective_status != "unlockable":
        return f"No campaigns assigned to {label}."
    if effective_status == "goal_met":
        return f"{label} met its target. Ready to advance."
    if effective_status == "needs_attention":
        if (current_progress or 0) == 0:
            return f"{label} has been running for {age_days} days with no recorded progress."
        return f"{label} is behind its target. Review campaigns."
    if effective_status == "unlockable":
        return f"{label} is ready to start. Click Unlock to begin."
    if effective_status == "locked":
        return f"{label} is locked. Advance a prior stage to unlock."
    if threshold_target is not None and current_progress is not None and threshold_target > 0:
        pct = min(100, round((current_progress / threshold_target) * 100))
        return f"{label} at {pct}% of target."
    return f"{label} in progress, no target set."


def _compute_health_score(*, stages: list[dict[str, Any]], total_spend: float, total_results: int, total_impressions: int) -> int:
    score = 0.0
    stage_weights: dict[StageKey, int] = {
        "awareness": 20,
        "consideration": 20,
        "conversion": 20,
        "retention": 10,
    }
    for stage in stages:
        weight = stage_weights[stage["stage"]]
        if stage["effectiveStatus"] == "locked":
            continue
        if stage["effectiveStatus"] == "goal_met":
            score += weight
            continue
        threshold_target = stage.get("thresholdTarget")
        current_progress = stage.get("currentProgress")
        if threshold_target and current_progress is not None and threshold_target > 0:
            ratio = max(0.0, min(1.0, current_progress / threshold_target))
            score += weight * ratio
    active_stages = [
        stage
        for stage in stages
        if stage["effectiveStatus"] in {"in_progress", "goal_met"}
    ]
    if active_stages:
        covered = sum(
            1
            for stage in active_stages
            if any(c.get("status") == "ACTIVE" for c in stage.get("campaigns", []))
        )
        score += 10 * (covered / len(active_stages))
    stagnation_penalty = 0.0
    stagnatable = [
        stage
        for stage in stages
        if stage["effectiveStatus"] in {"in_progress", "needs_attention"}
    ]
    for stage in stagnatable:
        if stage["ageDays"] >= STALE_DAYS and (stage.get("currentProgress") or 0) == 0:
            stagnation_penalty += 10 / max(1, len(stagnatable))
    score += max(0.0, 10 - stagnation_penalty)
    if total_impressions > 0:
        score += 10
    return max(0, min(100, round(score)))


def _build_next_best_action(stages: list[dict[str, Any]], total_campaigns: int) -> dict[str, str] | None:
    if total_campaigns == 0:
        return {
            "action": "Assign campaigns to this funnel.",
            "reasoning": "A funnel needs at least one campaign to coach against. Open Manage assignments to connect Meta campaigns to each stage.",
        }
    first_unlockable = next((stage for stage in stages if stage["effectiveStatus"] == "unlockable"), None)
    if first_unlockable:
        label = first_unlockable["stage"].capitalize()
        return {
            "action": f"Unlock {label}.",
            "reasoning": f"The prior stage hit its target. Click Unlock on the {label} card to start it.",
        }
    needs_attention = next((stage for stage in stages if stage["effectiveStatus"] == "needs_attention"), None)
    if needs_attention:
        label = needs_attention["stage"].capitalize()
        return {
            "action": f"Review {label} stage.",
            "reasoning": f"{label} has been running without progress for more than {STALE_DAYS} days. Check budgets, creative, and targeting.",
        }
    return {
        "action": "All stages on track.",
        "reasoning": "Every assigned stage is progressing. Keep campaigns running and check back tomorrow.",
    }


def _merge_step_data(step: int, prior: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if step != 2:
        return {**prior, **incoming}
    next_state = {**prior, **incoming}
    next_state.pop("variantUpdates", None)
    updates = incoming.get("variantUpdates")
    if not isinstance(updates, list):
        return next_state
    variants = list(prior.get("variants") or [])
    for update in updates:
        if not isinstance(update, dict):
            continue
        variant = str(update.get("variant") or "").upper()
        if variant < "A" or variant > "E":
            continue
        idx = ord(variant) - 65
        field = str(update.get("field") or "").strip()
        if not field:
            continue
        while len(variants) <= idx:
            variants.append({})
        base = variants[idx] if isinstance(variants[idx], dict) else {}
        variants[idx] = {**base, field: update.get("value")}
    next_state["variants"] = variants
    return next_state


def _parse_coach_response(text: str) -> dict[str, Any]:
    reply_start = text.find(REPLY_TAG_OPEN)
    reply_end = text.find(REPLY_TAG_CLOSE)
    if reply_start >= 0 and reply_end > reply_start:
        reply = text[reply_start + len(REPLY_TAG_OPEN) : reply_end].strip()
        meta_start = text.find(META_TAG_OPEN, reply_end)
        meta_end = text.find(META_TAG_CLOSE, meta_start)
        meta = {"suggestedPanelUpdate": None, "stepReady": False}
        if meta_start >= 0 and meta_end > meta_start:
            raw_meta = text[meta_start + len(META_TAG_OPEN) : meta_end].strip()
            try:
                parsed_meta = json.loads(raw_meta)
                if isinstance(parsed_meta, dict):
                    meta = {
                        "suggestedPanelUpdate": parsed_meta.get("suggestedPanelUpdate"),
                        "stepReady": bool(parsed_meta.get("stepReady")),
                    }
            except Exception:
                pass
        return {
            "reply": reply,
            "suggestedPanelUpdate": meta["suggestedPanelUpdate"],
            "stepReady": meta["stepReady"],
        }
    stripped = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("Coach response was not an object")
    return {
        "reply": str(parsed.get("reply") or ""),
        "suggestedPanelUpdate": parsed.get("suggestedPanelUpdate"),
        "stepReady": bool(parsed.get("stepReady")),
    }


def _load_campaigns() -> list[dict[str, Any]]:
    return dashboard_table("campaigns").select("*").execute().data or []


def _load_ads() -> list[dict[str, Any]]:
    return dashboard_table("ads").select("*").execute().data or []


def _load_stages_for_funnel(funnel_id: str) -> list[dict[str, Any]]:
    return (
        dashboard_table("funnel_stages")
        .select("*")
        .eq("funnel_id", funnel_id)
        .order("display_order")
        .execute()
        .data
        or []
    )


def _load_assignments_for_funnel(funnel_id: str) -> list[dict[str, Any]]:
    return dashboard_table("funnel_campaigns").select("*").eq("funnel_id", funnel_id).execute().data or []


def _campaign_aggregates_for_ids(campaign_ids: list[str]) -> dict[str, dict[str, int | float]]:
    ads = _load_ads()
    aggregates: dict[str, dict[str, int | float]] = {}
    for row in ads:
        campaign_id = row.get("campaign_id")
        if campaign_id not in set(campaign_ids):
            continue
        current = aggregates.setdefault(
            campaign_id,
            {
                "spend": 0.0,
                "impressions": 0,
                "reach": 0,
                "results": 0,
                "landingPageViews": 0,
                "engagements": 0,
                "conversions": 0,
            },
        )
        current["spend"] += float(row.get("spend") or 0)
        current["impressions"] += int(row.get("impressions") or 0)
        current["reach"] += int(row.get("reach") or 0)
        current["results"] += int(row.get("results") or 0)
        current["landingPageViews"] += int(row.get("landing_page_views") or 0)
        current["engagements"] += int(row.get("engagements") or 0)
        current["conversions"] += int(row.get("conversions") or 0)
    return aggregates


def _get_funnel_detail_payload(funnel_id: str) -> dict[str, Any]:
    funnel_rows = dashboard_table("funnels").select("*").eq("id", funnel_id).limit(1).execute().data or []
    if not funnel_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funnel not found.")
    funnel = funnel_rows[0]
    stages = _load_stages_for_funnel(funnel_id)
    assignments = _load_assignments_for_funnel(funnel_id)
    campaigns = _load_campaigns()
    campaign_map = {row["id"]: row for row in campaigns}
    campaign_ids = [row.get("campaign_id") for row in assignments if row.get("campaign_id")]
    aggregates = _campaign_aggregates_for_ids([str(cid) for cid in campaign_ids])
    by_stage: dict[str, list[dict[str, Any]]] = {row["id"]: [] for row in stages}
    for assignment in assignments:
        campaign = campaign_map.get(assignment.get("campaign_id"))
        aggregate = aggregates.get(assignment.get("campaign_id"), {})
        enriched = {
            "id": assignment["id"],
            "funnelStageId": assignment.get("funnel_stage_id"),
            "campaignId": assignment.get("campaign_id"),
            "assignedAt": iso_or_none(assignment.get("assigned_at")),
            "name": campaign.get("name") if campaign else None,
            "status": campaign.get("status") if campaign else None,
            "objective": campaign.get("objective") if campaign else None,
            "spend": f"{float(aggregate.get('spend') or 0):.2f}",
            "impressions": int(aggregate.get("impressions") or 0),
            "reach": int(aggregate.get("reach") or 0),
            "results": int(aggregate.get("results") or 0),
            "landingPageViews": int(aggregate.get("landingPageViews") or 0),
            "engagements": int(aggregate.get("engagements") or 0),
            "conversions": int(aggregate.get("conversions") or 0),
        }
        stage_id = assignment.get("funnel_stage_id")
        if stage_id in by_stage:
            by_stage[stage_id].append(enriched)

    now = datetime.now(timezone.utc)
    stage_details: list[dict[str, Any]] = []
    updates: list[tuple[str, str]] = []
    for idx, stage in enumerate(stages):
        bucket = by_stage.get(stage["id"], [])
        metrics = {
            "spend": round(sum(float(row.get("spend") or 0) for row in bucket), 2),
            "impressions": sum(int(row.get("impressions") or 0) for row in bucket),
            "reach": sum(int(row.get("reach") or 0) for row in bucket),
            "results": sum(int(row.get("results") or 0) for row in bucket),
            "landingPageViews": sum(int(row.get("landingPageViews") or 0) for row in bucket),
            "engagements": sum(int(row.get("engagements") or 0) for row in bucket),
            "conversions": sum(int(row.get("conversions") or 0) for row in bucket),
        }
        current_progress, progress_metric, progress_data_status = _resolve_stage_progress(
            stage.get("threshold_metric"),
            stage["stage"],
            metrics,
            bucket,
        )
        threshold_target = stage.get("threshold_target")
        threshold_met = (
            current_progress is not None
            and threshold_target is not None
            and int(current_progress) >= int(threshold_target)
        )
        if threshold_met and stage.get("status") != "goal_met":
            updates.append((stage["id"], "goal_met"))
            stage["status"] = "goal_met"
            if idx + 1 < len(stages):
                next_stage = stages[idx + 1]
                if next_stage.get("status") == "locked":
                    updates.append((next_stage["id"], "unlockable"))
                    next_stage["status"] = "unlockable"
        created_dt = _normalize_utc_datetime(stage.get("created_at"))
        age_days = max(0, int((now - created_dt).total_seconds() // 86400)) if created_dt else 0
        stale = age_days >= STALE_DAYS
        status_value = stage.get("status")
        if status_value == "goal_met" or threshold_met:
            effective_status = "goal_met"
        elif status_value == "locked":
            effective_status = "locked"
        elif status_value == "unlockable":
            effective_status = "unlockable"
        elif stale and bucket and (current_progress or 0) == 0 and progress_data_status == "ok":
            effective_status = "needs_attention"
        else:
            effective_status = "in_progress"
        stage_details.append(
            {
                "id": stage["id"],
                "stage": stage["stage"],
                "displayOrder": stage.get("display_order"),
                "thresholdMetric": stage.get("threshold_metric"),
                "thresholdTarget": threshold_target,
                "currentProgress": current_progress,
                "progressDataStatus": progress_data_status,
                "progressMetric": progress_metric,
                "status": stage.get("status"),
                "effectiveStatus": effective_status,
                "notes": stage.get("notes"),
                "createdAt": iso_or_none(stage.get("created_at")),
                "ageDays": age_days,
                "campaigns": [
                    {
                        "id": row.get("campaignId"),
                        "name": row.get("name"),
                        "status": row.get("status"),
                        "objective": row.get("objective"),
                        "spend": float(row.get("spend") or 0),
                        "results": int(row.get("results") or 0),
                    }
                    for row in bucket
                ],
                "metrics": metrics,
                "healthSummary": _build_stage_health_summary(
                    stage=stage["stage"],
                    effective_status=effective_status,
                    campaign_count=len(bucket),
                    current_progress=current_progress,
                    threshold_target=threshold_target,
                    progress_data_status=progress_data_status,
                    age_days=age_days,
                ),
            }
        )
    for stage_id, status_value in updates:
        dashboard_table("funnel_stages").update({"status": status_value}).eq("id", stage_id).execute()
    total_campaigns = len(assignments)
    total_spend = round(sum(stage["metrics"]["spend"] for stage in stage_details), 2)
    total_results = sum(stage["metrics"]["results"] for stage in stage_details)
    total_impressions = sum(stage["metrics"]["impressions"] for stage in stage_details)
    health_score = _compute_health_score(
        stages=stage_details,
        total_spend=total_spend,
        total_results=total_results,
        total_impressions=total_impressions,
    )
    funnel["health_score"] = health_score
    funnel["health_updated_at"] = utc_now_iso()
    dashboard_table("funnels").update(
        {"health_score": health_score, "health_updated_at": funnel["health_updated_at"]}
    ).eq("id", funnel_id).execute()
    return {
        "funnel": {
            **funnel,
            "createdAt": iso_or_none(funnel.get("created_at")),
            "updatedAt": iso_or_none(funnel.get("updated_at")),
            "archivedAt": iso_or_none(funnel.get("archived_at")),
            "healthUpdatedAt": iso_or_none(funnel.get("health_updated_at")),
            "healthScore": funnel.get("health_score"),
        },
        "stages": stage_details,
        "totalCampaigns": total_campaigns,
        "totalSpend": total_spend,
        "totalResults": total_results,
        "totalImpressions": total_impressions,
        "nextBestAction": _build_next_best_action(stage_details, total_campaigns),
    }


def _build_coach_context(funnel_id: str, stage: StageKey) -> dict[str, Any]:
    detail = _get_funnel_detail_payload(funnel_id)
    sessions = (
        dashboard_table("funnel_stage_sessions")
        .select("*")
        .eq("funnel_id", funnel_id)
        .eq("stage", stage)
        .limit(1)
        .execute()
        .data
        or []
    )
    session = sessions[0] if sessions else None
    prior_stage_rows = (
        dashboard_table("funnel_stage_sessions").select("*").eq("funnel_id", funnel_id).execute().data or []
    )
    prior_stage_states = {
        row.get("stage"): (row.get("step_states") or {})
        for row in prior_stage_rows
        if row.get("stage") != stage
    }
    chat_history: list[dict[str, Any]] = []
    if session:
        messages = (
            dashboard_table("funnel_chat_messages")
            .select("*")
            .eq("session_id", session["id"])
            .order("created_at", desc=True)
            .limit(20)
            .execute()
            .data
            or []
        )
        chat_history = list(reversed(messages))
    assigned_campaigns = []
    for stage_row in detail["stages"]:
        if stage_row["stage"] == stage:
            for campaign in stage_row["campaigns"]:
                assigned_campaigns.append(campaign)
    return {
        "funnel": {
            "id": detail["funnel"]["id"],
            "name": detail["funnel"]["name"],
            "description": detail["funnel"].get("description"),
            "healthScore": detail["funnel"].get("healthScore"),
        },
        "stages": detail["stages"],
        "currentStage": stage,
        "currentStep": int(session.get("current_step") or 1) if session else 1,
        "stepStates": (session.get("step_states") or {}) if session else {},
        "priorStageStates": prior_stage_states,
        "chatHistory": [
            {
                "role": row.get("role"),
                "content": row.get("content"),
                "step": row.get("step_at_time_of_message"),
            }
            for row in chat_history
        ],
        "assignedCampaigns": assigned_campaigns,
    }


async def _generate_coach_response(funnel_id: str, stage: StageKey, user_message: str) -> dict[str, Any]:
    context = _build_coach_context(funnel_id, stage)
    chat_text = (
        "\n".join(
            f"[{turn['role']}, step {turn['step']}] {turn['content']}"
            for turn in context["chatHistory"]
        )
        if context["chatHistory"]
        else "(no prior messages in this session)"
    )
    prior_stages_text = (
        "\n".join(f"- {key}: {json.dumps(value)}" for key, value in context["priorStageStates"].items())
        if context["priorStageStates"]
        else "(no prior stage sessions on this funnel)"
    )
    payload = {
        "funnel": context["funnel"],
        "stages": context["stages"],
        "currentStage": context["currentStage"],
        "currentStep": context["currentStep"],
        "stepStates": context["stepStates"],
        "assignedCampaigns": context["assignedCampaigns"],
    }
    prompt_user_message = f"""CONTEXT: funnel_coach_chat

FUNNEL STATE:
{json.dumps(payload, indent=2, default=str)}

PRIOR STAGE SESSIONS ON THIS FUNNEL:
{prior_stages_text}

RECENT CHAT IN THIS SESSION:
{chat_text}

USER MESSAGE (just arrived, step {context['currentStep']}):
{user_message}

Respond as the Funnel Coach. Use the tagged output format."""
    result = await call_claude(COACH_SYSTEM_PROMPT, prompt_user_message, max_tokens=2000)
    parsed = _parse_coach_response(result["text"])
    token_usage = {
        "input": int(result.get("inputTokens") or 0),
        "output": int(result.get("outputTokens") or 0),
        "cacheRead": int(result.get("cacheReadTokens") or 0),
        "cacheCreation": int(result.get("cacheCreationTokens") or 0),
    }
    return {
        **parsed,
        "tokenUsage": token_usage,
        "costUsd": _priority_cost(token_usage),
    }


async def _review_manual_edit(funnel_id: str, stage: StageKey, step: int, field: str, value: Any) -> dict[str, Any]:
    context = _build_coach_context(funnel_id, stage)
    payload = {
        "funnelName": context["funnel"]["name"],
        "stage": stage,
        "step": step,
        "field": field,
        "newValue": value,
        "stepStates": context["stepStates"],
        "priorStages": context["priorStageStates"],
        "assignedCampaigns": context["assignedCampaigns"],
    }
    user_message = f"""CONTEXT: funnel_coach_manual_edit_review

Neo just manually set:
  step={step}
  field={field}
  newValue={json.dumps(value)}

FUNNEL SNAPSHOT:
{json.dumps(payload, indent=2, default=str)}

Decide: is this change clearly off-strategy. Return the JSON object per the format rules."""
    result = await call_claude(REVIEW_SYSTEM_PROMPT, user_message, max_tokens=400)
    stripped = result["text"].strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(stripped)
        message = parsed.get("message") if isinstance(parsed, dict) else None
        if message is not None and not isinstance(message, str):
            message = None
    except Exception:
        message = None
    token_usage = {
        "input": int(result.get("inputTokens") or 0),
        "output": int(result.get("outputTokens") or 0),
        "cacheRead": int(result.get("cacheReadTokens") or 0),
        "cacheCreation": int(result.get("cacheCreationTokens") or 0),
    }
    return {
        "message": message,
        "tokenUsage": token_usage,
        "costUsd": _priority_cost(token_usage),
    }


async def _suggest_threshold_target(funnel_id: str, stage: StageKey, metric: str) -> dict[str, Any]:
    detail = _get_funnel_detail_payload(funnel_id)
    stage_row = next((row for row in detail["stages"] if row["stage"] == stage), None)
    payload = {
        "funnelName": detail["funnel"]["name"],
        "stage": stage,
        "metric": metric,
        "metricLabel": _metric_label(metric),
        "isConversionMetric": _is_conversion_metric(metric),
        "currentTarget": stage_row.get("thresholdTarget") if stage_row else None,
        "currentProgress": stage_row.get("currentProgress") if stage_row else 0,
        "assignedCampaignsThisStage": stage_row.get("campaigns") if stage_row else [],
        "benchmarkObjectives": _objectives_for_metric(metric),
    }
    user_message = f"""CONTEXT: funnel_threshold_suggestion

{json.dumps(payload, indent=2, default=str)}

Pick a realistic target for the chosen metric. Return ONLY this JSON object:
{{"value": <positive integer>, "rationale": "<one concise sentence, under 18 words>"}}"""
    result = await call_claude(THRESHOLD_SUGGESTION_SYSTEM_PROMPT, user_message, max_tokens=300)
    stripped = result["text"].strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(stripped)
    value = round(float(parsed["value"]))
    rationale = str(parsed.get("rationale") or "")
    token_usage = {
        "input": int(result.get("inputTokens") or 0),
        "output": int(result.get("outputTokens") or 0),
        "cacheRead": int(result.get("cacheReadTokens") or 0),
        "cacheCreation": int(result.get("cacheCreationTokens") or 0),
    }
    return {"value": value, "rationale": rationale, "costUsd": _priority_cost(token_usage)}


def _parse_attachments(raw: Any) -> tuple[list[dict[str, Any]], str | None]:
    if raw is None or raw == []:
        return [], None
    if not isinstance(raw, list):
        return [], "attachments must be an array."
    if len(raw) > MAX_ATTACHMENTS_PER_MESSAGE:
        return [], f"At most {MAX_ATTACHMENTS_PER_MESSAGE} attachments per message."
    parsed: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            return [], "Invalid attachment shape."
        storage_path = item.get("storagePath")
        file_name = item.get("fileName")
        mime_type = item.get("mimeType")
        file_size = item.get("fileSize")
        if not all(isinstance(value, str) for value in [storage_path, file_name, mime_type]) or not isinstance(file_size, int):
            return [], "Attachment missing required fields."
        if mime_type not in ALLOWED_MIME_TYPES:
            return [], "Unsupported attachment type."
        if file_size <= 0 or file_size > MAX_FILE_SIZE_BYTES:
            return [], "Attachment size out of range."
        parsed.append(
            {
                "storagePath": storage_path,
                "fileName": file_name,
                "mimeType": mime_type,
                "fileSize": file_size,
                "width": item.get("width"),
                "height": item.get("height"),
            }
        )
    return parsed, None


@router.get("/funnels")
def list_funnels(current: UserState = Depends(get_current_user)) -> list[dict[str, Any]]:
    ensure_dashboard_admin(current)
    funnels = dashboard_table("funnels").select("*").order("created_at", desc=True).execute().data or []
    stages = dashboard_table("funnel_stages").select("*").execute().data or []
    assignments = dashboard_table("funnel_campaigns").select("*").execute().data or []
    stage_to_funnel = {row["id"]: row.get("funnel_id") for row in stages}
    bucket: dict[str, dict[str, int]] = {
        row["id"]: {"awareness": 0, "consideration": 0, "conversion": 0, "retention": 0}
        for row in funnels
    }
    for assignment in assignments:
        stage_id = assignment.get("funnel_stage_id")
        stage_row = next((row for row in stages if row["id"] == stage_id), None)
        funnel_id = stage_to_funnel.get(stage_id)
        if not stage_row or not funnel_id or funnel_id not in bucket:
            continue
        bucket[funnel_id][stage_row["stage"]] += 1
    response = []
    for row in funnels:
        counts = bucket.get(row["id"], {"awareness": 0, "consideration": 0, "conversion": 0, "retention": 0})
        response.append(
            {
                "id": row["id"],
                "name": row.get("name"),
                "description": row.get("description"),
                "status": row.get("status"),
                "createdAt": iso_or_none(row.get("created_at")),
                "updatedAt": iso_or_none(row.get("updated_at")),
                "archivedAt": iso_or_none(row.get("archived_at")),
                "healthScore": row.get("health_score"),
                "healthUpdatedAt": iso_or_none(row.get("health_updated_at")),
                "stageCounts": counts,
                "totalCampaigns": sum(counts.values()),
            }
        )
    return response


@router.post("/funnels", status_code=status.HTTP_201_CREATED)
def create_funnel(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required.")
    description = payload.get("description")
    inserted = (
        dashboard_table("funnels")
        .insert(
            {
                "name": name,
                "description": description if isinstance(description, str) and description.strip() else None,
                "status": "active",
                "created_at": utc_now_iso(),
                "updated_at": utc_now_iso(),
            }
        )
        .execute()
        .data
        or []
    )
    funnel = inserted[0]
    stages = []
    for idx, stage in enumerate(STAGE_ORDER):
        stage_rows = (
            dashboard_table("funnel_stages")
            .insert(
                {
                    "funnel_id": funnel["id"],
                    "stage": stage,
                    "display_order": idx + 1,
                    "status": "in_progress" if idx == 0 else "locked",
                    "threshold_metric": STAGE_DEFAULTS[stage]["metric"],
                    "threshold_target": STAGE_DEFAULTS[stage]["target"],
                    "created_at": utc_now_iso(),
                }
            )
            .execute()
            .data
            or []
        )
        if stage_rows:
            stages.append(stage_rows[0])
    return {"funnel": funnel, "stages": stages}


@router.patch("/funnels/{funnel_id}")
def update_funnel(funnel_id: str, payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    patch: dict[str, Any] = {"updated_at": utc_now_iso()}
    if "name" in payload:
        patch["name"] = str(payload.get("name") or "").strip()
    if "description" in payload:
        desc = payload.get("description")
        patch["description"] = desc if isinstance(desc, str) and desc.strip() else None
    if "status" in payload:
        patch["status"] = payload.get("status")
        patch["archived_at"] = utc_now_iso() if payload.get("status") == "archived" else None
    updated = dashboard_table("funnels").update(patch).eq("id", funnel_id).execute().data or []
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funnel not found.")
    return updated[0]


@router.post("/funnels/{funnel_id}/archive")
def archive_funnel(funnel_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    updated = (
        dashboard_table("funnels")
        .update({"status": "archived", "archived_at": utc_now_iso(), "updated_at": utc_now_iso()})
        .eq("id", funnel_id)
        .execute()
        .data
        or []
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funnel not found.")
    return updated[0]


@router.post("/funnels/{funnel_id}/unarchive")
def unarchive_funnel(funnel_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    updated = (
        dashboard_table("funnels")
        .update({"status": "active", "archived_at": None, "updated_at": utc_now_iso()})
        .eq("id", funnel_id)
        .execute()
        .data
        or []
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funnel not found.")
    return updated[0]


@router.delete("/funnels/{funnel_id}")
def delete_funnel(funnel_id: str, current: UserState = Depends(get_current_user)) -> dict[str, str]:
    ensure_dashboard_admin(current)
    deleted = dashboard_table("funnels").delete().eq("id", funnel_id).execute().data or []
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funnel not found.")
    return {"id": deleted[0]["id"]}


@router.get("/unassigned-campaigns")
def list_unassigned_campaigns(current: UserState = Depends(get_current_user)) -> list[dict[str, Any]]:
    ensure_dashboard_admin(current)
    campaigns = _load_campaigns()
    assignments = dashboard_table("funnel_campaigns").select("*").execute().data or []
    assigned_ids = {row.get("campaign_id") for row in assignments}
    aggregates = _campaign_aggregates_for_ids([row["id"] for row in campaigns])
    rows = []
    for row in campaigns:
        if row["id"] in assigned_ids:
            continue
        aggregate = aggregates.get(row["id"], {})
        rows.append(
            {
                "id": row["id"],
                "name": row.get("name"),
                "status": row.get("status"),
                "objective": row.get("objective"),
                "spend": f"{float(aggregate.get('spend') or 0):.2f}",
                "results": int(aggregate.get("results") or 0),
                "suggestedStage": _suggest_stage_from_objective(row.get("objective")),
            }
        )
    rows.sort(key=lambda row: float(row["spend"]), reverse=True)
    return rows


@router.get("/assignable-campaigns")
def list_assignable_campaigns(
    funnelId: str = Query(...),
    current: UserState = Depends(get_current_user),
) -> list[dict[str, Any]]:
    ensure_dashboard_admin(current)
    campaigns = _load_campaigns()
    assignments = dashboard_table("funnel_campaigns").select("*").execute().data or []
    aggregates = _campaign_aggregates_for_ids([row["id"] for row in campaigns])
    rows = []
    for campaign in campaigns:
        conflict = next(
            (
                row
                for row in assignments
                if row.get("campaign_id") == campaign["id"] and row.get("funnel_id") != funnelId
            ),
            None,
        )
        if conflict:
            continue
        current_stage = next(
            (
                stage_row.get("stage")
                for assignment in assignments
                if assignment.get("campaign_id") == campaign["id"] and assignment.get("funnel_id") == funnelId
                for stage_row in _load_stages_for_funnel(funnelId)
                if stage_row["id"] == assignment.get("funnel_stage_id")
            ),
            None,
        )
        aggregate = aggregates.get(campaign["id"], {})
        rows.append(
            {
                "id": campaign["id"],
                "name": campaign.get("name"),
                "status": campaign.get("status"),
                "objective": campaign.get("objective"),
                "spend": f"{float(aggregate.get('spend') or 0):.2f}",
                "results": int(aggregate.get("results") or 0),
                "currentStage": current_stage,
                "suggestedStage": _suggest_stage_from_objective(campaign.get("objective")),
            }
        )
    rows.sort(key=lambda row: float(row["spend"]), reverse=True)
    return rows


@router.post("/assign-campaign")
def assign_campaign_to_stage(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    funnel_id = str(payload.get("funnelId") or "")
    funnel_stage_id = str(payload.get("funnelStageId") or "")
    campaign_id = str(payload.get("campaignId") or "")
    assignments = dashboard_table("funnel_campaigns").select("*").execute().data or []
    conflict = next(
        (
            row
            for row in assignments
            if row.get("campaign_id") == campaign_id and row.get("funnel_id") != funnel_id
        ),
        None,
    )
    if conflict:
        funnels = dashboard_table("funnels").select("*").eq("id", conflict.get("funnel_id")).limit(1).execute().data or []
        funnel_name = funnels[0].get("name") if funnels else "unknown"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Campaign is already assigned to funnel "{funnel_name}". One campaign can belong to only one funnel.',
        )
    stage_rows = dashboard_table("funnel_stages").select("*").eq("id", funnel_stage_id).limit(1).execute().data or []
    if not stage_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funnel stage not found.")
    stage = stage_rows[0]
    if stage.get("funnel_id") != funnel_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Stage does not belong to the specified funnel.")
    inserted = (
        dashboard_table("funnel_campaigns")
        .insert({"funnel_id": funnel_id, "funnel_stage_id": funnel_stage_id, "campaign_id": campaign_id, "assigned_at": utc_now_iso()})
        .execute()
        .data
        or []
    )
    if not inserted:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to assign campaign.")
    return inserted[0]


@router.post("/assignments/bulk")
def assign_campaigns(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, int]:
    ensure_dashboard_admin(current)
    funnel_id = str(payload.get("funnelId") or "")
    assignments_payload = payload.get("assignments")
    if not isinstance(assignments_payload, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="assignments must be an array.")
    stage_rows = _load_stages_for_funnel(funnel_id)
    if not stage_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funnel not found.")
    stage_by_key = {row["stage"]: row for row in stage_rows}
    existing = dashboard_table("funnel_campaigns").select("*").execute().data or []
    campaign_ids = [str(item.get("campaignId") or "") for item in assignments_payload]
    for row in existing:
        if row.get("campaign_id") in campaign_ids and row.get("funnel_id") != funnel_id:
            funnels = dashboard_table("funnels").select("*").eq("id", row.get("funnel_id")).limit(1).execute().data or []
            funnel_name = funnels[0].get("name") if funnels else "unknown"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'Campaign {row.get("campaign_id")} is already in funnel "{funnel_name}". One campaign can belong to only one funnel.',
            )
    dashboard_table("funnel_campaigns").delete().eq("funnel_id", funnel_id).execute()
    count = 0
    for assignment in assignments_payload:
        stage = stage_by_key.get(assignment.get("stage"))
        if not stage:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Stage "{assignment.get("stage")}" not found on this funnel.')
        dashboard_table("funnel_campaigns").insert(
            {
                "funnel_id": funnel_id,
                "funnel_stage_id": stage["id"],
                "campaign_id": assignment.get("campaignId"),
                "assigned_at": utc_now_iso(),
            }
        ).execute()
        count += 1
    return {"count": count}


@router.post("/unassign")
def unassign_campaign(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, str]:
    ensure_dashboard_admin(current)
    funnel_id = str(payload.get("funnelId") or "")
    campaign_id = str(payload.get("campaignId") or "")
    deleted = (
        dashboard_table("funnel_campaigns")
        .delete()
        .eq("funnel_id", funnel_id)
        .eq("campaign_id", campaign_id)
        .execute()
        .data
        or []
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found.")
    return {"id": deleted[0]["id"]}


@router.patch("/stages/{stage_id}/threshold")
def update_stage_threshold(stage_id: str, payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    updated = (
        dashboard_table("funnel_stages")
        .update({"threshold_metric": payload.get("thresholdMetric"), "threshold_target": payload.get("thresholdTarget")})
        .eq("id", stage_id)
        .execute()
        .data
        or []
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found.")
    return updated[0]


@router.get("/funnels/{funnel_id}/with-stages")
def get_funnel_with_stages(funnel_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    return _get_funnel_detail_payload(funnel_id)


@router.get("/snapshots")
def get_last_snapshot(
    funnelId: str = Query(...),
    userId: str = Query(...),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any] | None:
    ensure_dashboard_admin(current)
    rows = (
        dashboard_table("funnel_view_snapshots")
        .select("*")
        .eq("funnel_id", funnelId)
        .eq("user_id", userId)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


@router.put("/snapshots")
def save_snapshot(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any] | None:
    ensure_dashboard_admin(current)
    funnel_id = str(payload.get("funnelId") or "")
    user_id = str(payload.get("userId") or "")
    stage_states = payload.get("stageStates") or []
    existing = (
        dashboard_table("funnel_view_snapshots")
        .select("*")
        .eq("funnel_id", funnel_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        updated = (
            dashboard_table("funnel_view_snapshots")
            .update({"stage_states": stage_states, "viewed_at": utc_now_iso()})
            .eq("id", existing[0]["id"])
            .execute()
            .data
            or []
        )
        return updated[0] if updated else None
    inserted = (
        dashboard_table("funnel_view_snapshots")
        .insert({"funnel_id": funnel_id, "user_id": user_id, "stage_states": stage_states, "viewed_at": utc_now_iso()})
        .execute()
        .data
        or []
    )
    return inserted[0] if inserted else None


@router.get("/stage-session")
def get_stage_session(
    funnelId: str = Query(...),
    stage: StageKey = Query(...),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    session_rows = (
        dashboard_table("funnel_stage_sessions")
        .select("*")
        .eq("funnel_id", funnelId)
        .eq("stage", stage)
        .limit(1)
        .execute()
        .data
        or []
    )
    if session_rows:
        session = session_rows[0]
    else:
        inserted = (
            dashboard_table("funnel_stage_sessions")
            .insert(
                {
                    "funnel_id": funnelId,
                    "stage": stage,
                    "current_step": 1,
                    "step_states": {},
                    "decisions": [],
                    "status": "active",
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                }
            )
            .execute()
            .data
            or []
        )
        if not inserted:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create stage session.")
        session = inserted[0]
    messages = (
        dashboard_table("funnel_chat_messages")
        .select("*")
        .eq("session_id", session["id"])
        .order("created_at", desc=True)
        .limit(50)
        .execute()
        .data
        or []
    )
    return {"session": session, "messages": list(reversed(messages))}


@router.post("/coach-message")
async def send_coach_message(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    session_id = str(payload.get("sessionId") or "")
    message = str(payload.get("message") or "").strip()
    session_rows = dashboard_table("funnel_stage_sessions").select("*").eq("id", session_id).limit(1).execute().data or []
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    session = session_rows[0]
    user_rows = (
        dashboard_table("funnel_chat_messages")
        .insert(
            {
                "session_id": session["id"],
                "role": "user",
                "content": message,
                "step_at_time_of_message": session.get("current_step") or 1,
                "created_at": utc_now_iso(),
            }
        )
        .execute()
        .data
        or []
    )
    if not user_rows:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save user message.")
    response = await _generate_coach_response(session["funnel_id"], session["stage"], message)
    metadata: dict[str, Any] = {
        "costUsd": response["costUsd"],
        "tokenUsage": response["tokenUsage"],
        "stepReady": response["stepReady"],
    }
    if response.get("suggestedPanelUpdate") is not None:
        metadata["suggestedPanelUpdate"] = response["suggestedPanelUpdate"]
    assistant_rows = (
        dashboard_table("funnel_chat_messages")
        .insert(
            {
                "session_id": session["id"],
                "role": "assistant",
                "content": response["reply"],
                "step_at_time_of_message": session.get("current_step") or 1,
                "metadata": metadata,
                "created_at": utc_now_iso(),
            }
        )
        .execute()
        .data
        or []
    )
    dashboard_table("funnel_stage_sessions").update({"updated_at": utc_now_iso()}).eq("id", session["id"]).execute()
    return {
        "userMessage": user_rows[0],
        "assistantMessage": assistant_rows[0] if assistant_rows else None,
        "suggestedPanelUpdate": response.get("suggestedPanelUpdate"),
        "stepReady": response["stepReady"],
        "costUsd": response["costUsd"],
    }


@router.post("/panel-update/accept")
def accept_panel_update(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    session_id = str(payload.get("sessionId") or "")
    step = int(payload.get("step") or 0)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="data must be an object.")
    session_rows = dashboard_table("funnel_stage_sessions").select("*").eq("id", session_id).limit(1).execute().data or []
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    session = session_rows[0]
    states = session.get("step_states") or {}
    step_key = str(step)
    prior_step = states.get(step_key) or {}
    next_step = _merge_step_data(step, prior_step, data)
    next_states = {**states, step_key: next_step}
    decisions = list(session.get("decisions") or [])
    decisions.append(
        {
            "timestamp": utc_now_iso(),
            "step": step,
            "decision": payload.get("summary") or "Accepted chat suggestion",
            "source": "chat",
            "details": data,
        }
    )
    updated = (
        dashboard_table("funnel_stage_sessions")
        .update({"step_states": next_states, "decisions": decisions, "updated_at": utc_now_iso()})
        .eq("id", session_id)
        .execute()
        .data
        or []
    )
    message_id = payload.get("messageId")
    if message_id:
        message_rows = dashboard_table("funnel_chat_messages").select("*").eq("id", message_id).limit(1).execute().data or []
        if message_rows:
            metadata = message_rows[0].get("metadata") if isinstance(message_rows[0].get("metadata"), dict) else {}
            dashboard_table("funnel_chat_messages").update({"metadata": {**metadata, "suggestionApplied": True}}).eq("id", message_id).execute()
    return updated[0] if updated else {}


@router.post("/panel-update/dismiss")
def dismiss_panel_update(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    message_id = str(payload.get("messageId") or "")
    rows = dashboard_table("funnel_chat_messages").select("*").eq("id", message_id).limit(1).execute().data or []
    if rows:
        metadata = rows[0].get("metadata") if isinstance(rows[0].get("metadata"), dict) else {}
        dashboard_table("funnel_chat_messages").update({"metadata": {**metadata, "suggestionApplied": False}}).eq("id", message_id).execute()
    return {"ok": True}


@router.post("/step-field")
def update_step_field(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    session_id = str(payload.get("sessionId") or "")
    step = int(payload.get("step") or 0)
    field = str(payload.get("field") or "").strip()
    session_rows = dashboard_table("funnel_stage_sessions").select("*").eq("id", session_id).limit(1).execute().data or []
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    session = session_rows[0]
    states = session.get("step_states") or {}
    step_key = str(step)
    prior_step = states.get(step_key) or {}
    next_step = {**prior_step, field: payload.get("value")}
    next_states = {**states, step_key: next_step}
    decisions = list(session.get("decisions") or [])
    decisions.append(
        {
            "timestamp": utc_now_iso(),
            "step": step,
            "decision": f"Edited {field}",
            "source": "panel_edit",
            "details": {"field": field, "value": payload.get("value")},
        }
    )
    updated = (
        dashboard_table("funnel_stage_sessions")
        .update({"step_states": next_states, "decisions": decisions, "updated_at": utc_now_iso()})
        .eq("id", session_id)
        .execute()
        .data
        or []
    )
    return updated[0] if updated else {}


@router.post("/steps/complete")
def complete_step(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    session_id = str(payload.get("sessionId") or "")
    step = int(payload.get("step") or 0)
    next_step = min(4, step + 1)
    updated = (
        dashboard_table("funnel_stage_sessions")
        .update({"current_step": next_step, "updated_at": utc_now_iso()})
        .eq("id", session_id)
        .execute()
        .data
        or []
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return updated[0]


@router.post("/manual-edit/review")
async def review_manual_edit(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    session_id = str(payload.get("sessionId") or "")
    step = int(payload.get("step") or 0)
    field = str(payload.get("field") or "")
    session_rows = dashboard_table("funnel_stage_sessions").select("*").eq("id", session_id).limit(1).execute().data or []
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    session = session_rows[0]
    result = await _review_manual_edit(session["funnel_id"], session["stage"], step, field, payload.get("value"))
    if not result["message"]:
        return {"assistantMessage": None, "costUsd": result["costUsd"]}
    assistant_rows = (
        dashboard_table("funnel_chat_messages")
        .insert(
            {
                "session_id": session_id,
                "role": "assistant",
                "content": result["message"],
                "step_at_time_of_message": step,
                "metadata": {
                    "manualEditResponse": True,
                    "field": field,
                    "costUsd": result["costUsd"],
                    "tokenUsage": result["tokenUsage"],
                },
                "created_at": utc_now_iso(),
            }
        )
        .execute()
        .data
        or []
    )
    dashboard_table("funnel_stage_sessions").update({"updated_at": utc_now_iso()}).eq("id", session_id).execute()
    return {"assistantMessage": assistant_rows[0] if assistant_rows else None, "costUsd": result["costUsd"]}


@router.post("/current-step")
def set_current_step(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    session_id = str(payload.get("sessionId") or "")
    step = int(payload.get("step") or 1)
    updated = (
        dashboard_table("funnel_stage_sessions")
        .update({"current_step": step, "updated_at": utc_now_iso()})
        .eq("id", session_id)
        .execute()
        .data
        or []
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return updated[0]


@router.post("/stages/complete")
def complete_stage(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    session_id = str(payload.get("sessionId") or "")
    updated = (
        dashboard_table("funnel_stage_sessions")
        .update({"status": "completed", "updated_at": utc_now_iso()})
        .eq("id", session_id)
        .execute()
        .data
        or []
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return updated[0]


@router.get("/stages/{stage_id}/threshold-suggestion")
async def suggest_stage_threshold(stage_id: str, metric: str, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    rows = dashboard_table("funnel_stages").select("*").eq("id", stage_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found.")
    row = rows[0]
    return await _suggest_threshold_target(row["funnel_id"], row["stage"], metric)


@router.post("/stages/{stage_id}/unlock")
def unlock_stage(stage_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    rows = dashboard_table("funnel_stages").select("*").eq("id", stage_id).limit(1).execute().data or []
    if not rows or rows[0].get("status") != "unlockable":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This stage is not currently unlockable.")
    updated = dashboard_table("funnel_stages").update({"status": "in_progress"}).eq("id", stage_id).execute().data or []
    return updated[0]


@router.get("/digest")
def get_funnel_digest(
    funnelId: str = Query(...),
    hours: int = Query(default=24),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    detail = _get_funnel_detail_payload(funnelId)
    items: list[dict[str, str]] = []
    if detail["totalSpend"] > 0 or detail["totalResults"] > 0 or detail["totalImpressions"] > 0:
        items.append(
            {
                "text": f"{detail['totalResults']} results today, {int(detail['totalImpressions']):,} impressions."
            }
        )
    for row in detail["stages"]:
        spend = float(row["metrics"]["spend"] or 0)
        results = int(row["metrics"]["results"] or 0)
        if spend <= 0 and results <= 0:
            continue
        label = str(row["stage"]).capitalize()
        items.append(
            {
                "text": f"{label} spent {spend:,.2f}, {results} results."
            }
        )
    note = None if items else "No changes in the last 24 hours. Check back tomorrow."
    return {
        "funnelId": funnelId,
        "hours": hours,
        "totalSpend": detail["totalSpend"],
        "totalResults": detail["totalResults"],
        "totalImpressions": detail["totalImpressions"],
        "stages": [
            {
                "stage": row["stage"],
                "spend": row["metrics"]["spend"],
                "results": row["metrics"]["results"],
                "impressions": row["metrics"]["impressions"],
                "status": row["effectiveStatus"],
            }
            for row in detail["stages"]
        ],
        "items": items,
        "note": note,
    }


@router.post("/chat-image")
def upload_chat_image(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, str]:
    ensure_dashboard_admin(current)
    session_id = str(payload.get("sessionId") or "")
    file_b64 = str(payload.get("file") or "")
    file_name = str(payload.get("fileName") or "")
    mime_type = str(payload.get("mimeType") or "")
    session_rows = dashboard_table("funnel_stage_sessions").select("*").eq("id", session_id).limit(1).execute().data or []
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    try:
        buffer = base64.b64decode(file_b64)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File payload is not valid base64.") from exc
    session = session_rows[0]
    return _upload_dashboard_image(
        buffer=buffer,
        file_name=file_name,
        mime_type=mime_type,
        funnel_id=session["funnel_id"],
        stage=session["stage"],
    )


@router.post("/message-attachments")
def attach_image_to_message(payload: dict[str, Any], current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    message_id = str(payload.get("messageId") or "")
    attachments = payload.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="attachments must be a non-empty array.")
    message_rows = dashboard_table("funnel_chat_messages").select("*").eq("id", message_id).limit(1).execute().data or []
    if not message_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")
    inserted: list[dict[str, Any]] = []
    for item in attachments[:MAX_ATTACHMENTS_PER_MESSAGE]:
        rows = (
            dashboard_table("chat_message_attachments")
            .insert(
                {
                    "message_id": message_id,
                    "storage_path": item.get("storagePath"),
                    "file_name": item.get("fileName"),
                    "mime_type": item.get("mimeType"),
                    "file_size": item.get("fileSize"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "uploaded_by": current.id,
                    "uploaded_at": utc_now_iso(),
                }
            )
            .execute()
            .data
            or []
        )
        inserted.extend(rows)
    return {"attachments": inserted}


@router.get("/message-attachments")
def get_message_attachments(
    sessionId: str | None = Query(default=None),
    messageId: str | None = Query(default=None),
    current: UserState = Depends(get_current_user),
) -> list[dict[str, Any]]:
    ensure_dashboard_admin(current)
    if not sessionId and not messageId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sessionId or messageId required.")
    attachments = dashboard_table("chat_message_attachments").select("*").execute().data or []
    messages = dashboard_table("funnel_chat_messages").select("*").execute().data or []
    filtered: list[dict[str, Any]] = []
    for row in attachments:
        if messageId and row.get("message_id") == messageId:
            filtered.append(row)
            continue
        if sessionId:
            message = next((msg for msg in messages if msg["id"] == row.get("message_id")), None)
            if message and message.get("session_id") == sessionId:
                filtered.append(row)
    filtered.sort(key=lambda row: str(row.get("uploaded_at") or ""))
    return [
        {
            "id": row["id"],
            "messageId": row.get("message_id"),
            "storagePath": row.get("storage_path"),
            "fileName": row.get("file_name"),
            "mimeType": row.get("mime_type"),
            "fileSize": row.get("file_size"),
            "width": row.get("width"),
            "height": row.get("height"),
            "uploadedAt": iso_or_none(row.get("uploaded_at")),
            "uploadedBy": row.get("uploaded_by"),
            "signedUrl": _create_signed_url(str(row.get("storage_path"))),
        }
        for row in filtered
    ]


@router.get("/funnel-attachments")
def list_funnel_attachments(
    funnelId: str = Query(...),
    stage: StageKey | None = Query(default=None),
    current: UserState = Depends(get_current_user),
) -> list[dict[str, Any]]:
    ensure_dashboard_admin(current)
    attachments = dashboard_table("chat_message_attachments").select("*").execute().data or []
    messages = dashboard_table("funnel_chat_messages").select("*").execute().data or []
    sessions = dashboard_table("funnel_stage_sessions").select("*").execute().data or []
    message_map = {row["id"]: row for row in messages}
    session_map = {row["id"]: row for row in sessions}
    rows: list[dict[str, Any]] = []
    for attachment in attachments:
        message = message_map.get(attachment.get("message_id"))
        if not message:
            continue
        session_row = session_map.get(message.get("session_id"))
        if not session_row or session_row.get("funnel_id") != funnelId:
            continue
        if stage and session_row.get("stage") != stage:
            continue
        rows.append(
            {
                "id": attachment["id"],
                "messageId": attachment.get("message_id"),
                "storagePath": attachment.get("storage_path"),
                "fileName": attachment.get("file_name"),
                "mimeType": attachment.get("mime_type"),
                "fileSize": attachment.get("file_size"),
                "width": attachment.get("width"),
                "height": attachment.get("height"),
                "uploadedAt": iso_or_none(attachment.get("uploaded_at")),
                "uploadedBy": attachment.get("uploaded_by"),
                "messageContent": message.get("content"),
                "messageCreatedAt": iso_or_none(message.get("created_at")),
                "stage": session_row.get("stage"),
                "sessionId": session_row.get("id"),
                "signedUrl": _create_signed_url(str(attachment.get("storage_path"))),
            }
        )
    rows.sort(key=lambda row: row.get("uploadedAt") or "", reverse=True)
    return rows


@router.delete("/attachments/{attachment_id}")
def delete_attachment(attachment_id: str, current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    rows = dashboard_table("chat_message_attachments").select("*").eq("id", attachment_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    storage_path = rows[0].get("storage_path")
    if storage_path:
        try:
            _delete_dashboard_image(str(storage_path))
        except Exception:
            logger.warning("deleteAttachment: storage delete failed, removing DB row anyway", exc_info=True)
    dashboard_table("chat_message_attachments").delete().eq("id", attachment_id).execute()
    return {"ok": True}


@coach_stream_router.post("/api/coach/stream")
async def coach_stream(
    payload: dict[str, Any],
    current: UserState = Depends(get_current_user),
) -> StreamingResponse:
    ensure_dashboard_admin(current)
    session_id = str(payload.get("sessionId") or "")
    message = str(payload.get("message") or "").strip()
    if not session_id or not message or len(message) > 4000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sessionId or message.")
    attachments, error = _parse_attachments(payload.get("attachments"))
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    session_rows = dashboard_table("funnel_stage_sessions").select("*").eq("id", session_id).limit(1).execute().data or []
    if not session_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    session = session_rows[0]
    user_rows = (
        dashboard_table("funnel_chat_messages")
        .insert(
            {
                "session_id": session["id"],
                "role": "user",
                "content": message,
                "step_at_time_of_message": session.get("current_step") or 1,
                "created_at": utc_now_iso(),
            }
        )
        .execute()
        .data
        or []
    )
    user_message = user_rows[0]
    for attachment in attachments:
        dashboard_table("chat_message_attachments").insert(
            {
                "message_id": user_message["id"],
                "storage_path": attachment["storagePath"],
                "file_name": attachment["fileName"],
                "mime_type": attachment["mimeType"],
                "file_size": attachment["fileSize"],
                "width": attachment.get("width"),
                "height": attachment.get("height"),
                "uploaded_by": current.id,
                "uploaded_at": utc_now_iso(),
            }
        ).execute()
    response = await _generate_coach_response(session["funnel_id"], session["stage"], message)
    metadata: dict[str, Any] = {
        "costUsd": response["costUsd"],
        "tokenUsage": response["tokenUsage"],
        "stepReady": response["stepReady"],
        "streamed": True,
        "attachmentCount": len(attachments),
    }
    if response.get("suggestedPanelUpdate") is not None:
        metadata["suggestedPanelUpdate"] = response["suggestedPanelUpdate"]
    assistant_rows = (
        dashboard_table("funnel_chat_messages")
        .insert(
            {
                "session_id": session["id"],
                "role": "assistant",
                "content": response["reply"],
                "step_at_time_of_message": session.get("current_step") or 1,
                "metadata": metadata,
                "created_at": utc_now_iso(),
            }
        )
        .execute()
        .data
        or []
    )
    assistant_message = assistant_rows[0] if assistant_rows else None
    dashboard_table("funnel_stage_sessions").update({"updated_at": utc_now_iso()}).eq("id", session["id"]).execute()

    async def _event_stream():
        yield f"data: {json.dumps({'type': 'delta', 'text': response['reply']})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'userMessage': user_message, 'assistantMessage': assistant_message, 'suggestedPanelUpdate': response.get('suggestedPanelUpdate'), 'stepReady': response['stepReady'], 'costUsd': response['costUsd']})}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
