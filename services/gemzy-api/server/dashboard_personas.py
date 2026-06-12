from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status

from . import storage
from .auth import get_current_user
from .dashboard_ai import call_claude
from .dashboard_common import dashboard_table, ensure_dashboard_admin, iso_or_none
from .dashboard_persona_schemas import (
    DashboardPersonaAuditEventResponse,
    DashboardPersonaAutomationPayload,
    DashboardPersonaAutomationRunResponse,
    DashboardPersonaAutomationSettingsResponse,
    DashboardPersonaCampaignContextResponse,
    DashboardPersonaCreatePayload,
    DashboardPersonaDetailResponse,
    DashboardPersonaHomeSpacePayload,
    DashboardPersonaHomeSpaceResponse,
    DashboardPersonaInterestsPayload,
    DashboardPersonaInterestsResponse,
    DashboardPersonaLocationPayload,
    DashboardPersonaLocationResponse,
    DashboardPersonaMemoryPayload,
    DashboardPersonaMemoryResponse,
    DashboardPersonaObjectPayload,
    DashboardPersonaObjectResponse,
    DashboardPersonaOutfitPayload,
    DashboardPersonaOutfitResponse,
    DashboardPersonaPersonalityPayload,
    DashboardPersonaPersonalityResponse,
    DashboardPersonaProfilePayload,
    DashboardPersonaProfileResponse,
    DashboardPersonaQueueActionPayload,
    DashboardPersonaQueueItemResponse,
    DashboardPersonaRelationshipPayload,
    DashboardPersonaRelationshipResponse,
    DashboardPersonaRoutinePayload,
    DashboardPersonaRoutineResponse,
    DashboardPersonaRunPayload,
    DashboardPersonaRuntimeStateResponse,
    DashboardPersonaSummaryResponse,
    DashboardPersonaUpdatePayload,
    DashboardPersonaWardrobePayload,
    DashboardPersonaWardrobeResponse,
    DashboardPersonaWorldAdditionActionPayload,
    DashboardPersonaWorldAdditionResponse,
)
from .schemas import UserState
from .supabase_client import get_client, get_service_role_client

router = APIRouter(prefix="/dashboard/personas", tags=["dashboard-personas"])
logger = logging.getLogger(__name__)

PEOPLE_SCHEMA = "people"
MOMENTS_SCHEMA = "moments"
DASHBOARD_ASSETS_BUCKET = "dashboard-assets"
SIGNED_URL_TTL_SECONDS = 3600

PERSONA_AUTOMATION_SCHEMA = """{
  "status": "ready | blocked | needs_campaign_brief | failed",
  "summary": "One short paragraph.",
  "pauseReason": "null or brief string",
  "queueItems": [
    {
      "title": "Morning coffee planning story",
      "contentType": "story | post",
      "scheduledFor": "ISO-8601 datetime",
      "locationName": "Optional exact canonical location name",
      "outfitName": "Optional exact canonical outfit name",
      "homeSpaceName": "Optional exact canonical home space name",
      "relationshipNames": ["Optional exact canonical relationship names"],
      "caption": "Draft caption",
      "visualDirection": "Camera and styling guidance",
      "continuityReason": "Why this fits the persona",
      "novelty": false,
      "requiresApproval": true,
      "campaignId": "optional dashboard campaign id",
      "socialGoal": "optional business goal",
      "prompt": "Optional generation-ready prompt layer summary"
    }
  ],
  "worldAdditions": [
    {
      "itemType": "location | wardrobe | outfit | home_space | object | relationship | habit",
      "proposedName": "Optional label",
      "summary": "Why this addition appeared",
      "payload": {}
    }
  ]
}"""

PERSONA_AUTOMATION_CONTEXT = """You are the persona automation brain for the Gemzy internal dashboard.

Your job is to plan believable social content for a fictional recurring persona.

Rules:
- Preserve persona identity and continuity over novelty.
- Use dashboard campaign and social context only when it is relevant to the persona.
- Default to Queue Drafts behavior, do not assume auto-publish.
- If a specific campaign brief is required and missing, return status "needs_campaign_brief".
- If the request conflicts with persona rules, return status "blocked" and explain why.
- Output strict JSON only, no markdown fences.
- Stories should feel lightweight and timely. Posts should feel more deliberate and higher-effort.
- Avoid repetitive outfits, locations, and activities when recent history suggests fatigue.
- When using recurring locations, outfits, home spaces, or relationships, prefer exact canonical names from the persona context.
- Only invent a new recurring world element when it is genuinely justified. Otherwise reuse the existing canonical world.
"""


def _people_table(name: str):
    return get_client().schema(PEOPLE_SCHEMA).table(name)


def _moments_table(name: str):
    return get_client().schema(MOMENTS_SCHEMA).table(name)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _normalize_dashboard_storage_path(raw: str) -> str:
    candidate = raw.strip().lstrip("/")
    if candidate.startswith(f"{DASHBOARD_ASSETS_BUCKET}/"):
        return candidate[len(DASHBOARD_ASSETS_BUCKET) + 1 :]
    return candidate


def _sign_gcs_avatar_url(candidate: str) -> str | None:
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc != "storage.googleapis.com":
        return None
    object_path = parsed.path.lstrip("/")
    bucket_name, separator, blob_name = object_path.partition("/")
    if not bucket_name or not separator or not blob_name:
        return None
    bucket = storage.get_bucket(bucket_name, None)
    blob = bucket.blob(blob_name)
    return storage.generate_signed_read_url_v4(blob, seconds=SIGNED_URL_TTL_SECONDS)


def _resolve_avatar_url(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    lowered = candidate.lower()
    if lowered.startswith(("data:", "blob:")):
        return candidate
    if lowered.startswith(("http://", "https://")):
        try:
            signed_gcs = _sign_gcs_avatar_url(candidate)
            return signed_gcs or candidate
        except Exception:
            logger.warning("Failed to sign GCS persona avatar URL for %s", candidate, exc_info=True)
            return candidate
    storage_path = _normalize_dashboard_storage_path(candidate)
    try:
        payload = (
            get_service_role_client()
            .storage.from_(DASHBOARD_ASSETS_BUCKET)
            .create_signed_url(storage_path, SIGNED_URL_TTL_SECONDS)
        )
        signed_url = payload.get("signedURL") or payload.get("signedUrl")
        return signed_url or candidate
    except Exception:
        logger.warning("Failed to sign persona avatar URL for path %s", candidate, exc_info=True)
        return candidate


def _resolve_location_id_for_queue_item(*, persona_id: str, queue_payload: dict[str, Any]) -> str | None:
    location_name = str(queue_payload.get("locationName") or "").strip()
    if location_name:
        row = (
            _people_table("world_locations")
            .select("id")
            .eq("persona_id", persona_id)
            .ilike("name", location_name)
            .limit(1)
            .execute()
            .data
            or []
        )
        if row:
            return row[0]["id"]
    return None


def _resolve_wardrobe_ids_for_queue_item(*, persona_id: str, queue_payload: dict[str, Any]) -> list[str]:
    outfit_name = str(queue_payload.get("outfitName") or "").strip()
    if not outfit_name:
        return []
    outfit_rows = (
        _people_table("persona_outfits")
        .select("item_ids")
        .eq("persona_id", persona_id)
        .ilike("name", outfit_name)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not outfit_rows:
        return []
    return [str(item_id) for item_id in _coerce_list(outfit_rows[0].get("item_ids")) if str(item_id).strip()]


def _queue_time_of_day(queue_row: dict[str, Any]) -> str:
    scheduled = _parse_iso_datetime(queue_row.get("scheduled_for"))
    if scheduled is not None:
        hour = scheduled.hour
        if hour < 11:
            return "morning"
        if hour < 15:
            return "midday"
        if hour < 19:
            return "afternoon"
        if hour < 23:
            return "evening"
        return "late_night"
    title = str(queue_row.get("title") or "").lower()
    if "morning" in title:
        return "morning"
    if "midday" in title or "noon" in title:
        return "midday"
    if "afternoon" in title:
        return "afternoon"
    if "night" in title or "late" in title:
        return "late_night"
    return "evening"


def _queue_item_has_live_moments_sync(
    *,
    persona_id: str,
    owner_user_id: str,
    queue_payload: dict[str, Any],
) -> bool:
    plan_id = str(queue_payload.get("contentPlanId") or "").strip()
    moment_id = str(queue_payload.get("momentId") or "").strip()
    if not plan_id or not moment_id:
        return False

    plan_rows = (
        _moments_table("content_plans")
        .select("id, persona_id, owner_user_id")
        .eq("id", plan_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not plan_rows:
        return False
    plan_row = plan_rows[0]
    if str(plan_row.get("persona_id") or "") != persona_id:
        return False
    if str(plan_row.get("owner_user_id") or "") != owner_user_id:
        return False

    moment_rows = (
        _moments_table("moments")
        .select("id, plan_id")
        .eq("id", moment_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not moment_rows:
        return False
    return str(moment_rows[0].get("plan_id") or "") == plan_id


def _get_or_create_daily_plan(
    *,
    persona_id: str,
    owner_user_id: str,
    target_date: str,
    source_prompt: str | None,
) -> dict[str, Any]:
    existing_rows = (
        _moments_table("content_plans")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("owner_user_id", owner_user_id)
        .eq("plan_type", "DAY")
        .eq("date_start", target_date)
        .eq("date_end", target_date)
        .order("created_at", desc=False)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing_rows:
        return existing_rows[0]

    now_iso = _iso_now()
    created_rows = (
        _moments_table("content_plans")
        .insert(
            {
                "persona_id": persona_id,
                "owner_user_id": owner_user_id,
                "plan_type": "DAY",
                "date_start": target_date,
                "date_end": target_date,
                "source_prompt": source_prompt,
                "status": "DRAFT",
                "updated_at": now_iso,
            }
        )
        .execute()
        .data
        or []
    )
    if not created_rows:
        raise RuntimeError("Failed to create canonical Moments day plan")
    return created_rows[0]


def _get_or_create_plan_block(
    *,
    plan_id: str,
    time_of_day: str,
    notes: str | None,
    moment_type: str,
) -> dict[str, Any]:
    existing_rows = (
        _moments_table("plan_blocks")
        .select("*")
        .eq("plan_id", plan_id)
        .eq("time_of_day", time_of_day)
        .order("created_at", desc=False)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing_rows:
        return existing_rows[0]

    created_rows = (
        _moments_table("plan_blocks")
        .insert(
            {
                "plan_id": plan_id,
                "time_of_day": time_of_day,
                "target_posts": 1 if moment_type == "POST" else 0,
                "target_stories": 1 if moment_type == "STORY" else 0,
                "notes": notes,
            }
        )
        .execute()
        .data
        or []
    )
    if not created_rows:
        raise RuntimeError("Failed to create canonical Moments plan block")
    return created_rows[0]


def _sync_queue_rows_to_moments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    synced_rows: list[dict[str, Any]] = []
    for row in rows:
        try:
            synced_rows.append(_sync_queue_item_to_moments_draft(row))
        except Exception:
            logger.exception("Failed to sync dashboard queue item %s into Moments draft", row.get("id"))
            synced_rows.append(row)
    return synced_rows


def _sync_queue_item_to_moments_draft(queue_row: dict[str, Any]) -> dict[str, Any]:
    queue_payload = _coerce_dict(queue_row.get("queue_payload"))

    persona_id = str(queue_row["persona_id"])
    persona = _require_persona(persona_id)
    owner_user_id = str(persona.get("owner_user_id") or "").strip()
    if not owner_user_id:
        return queue_row
    if _queue_item_has_live_moments_sync(
        persona_id=persona_id,
        owner_user_id=owner_user_id,
        queue_payload=queue_payload,
    ):
        target_date = (_parse_iso_datetime(queue_row.get("scheduled_for")) or datetime.now(timezone.utc)).date().isoformat()
        canonical_plan = _get_or_create_daily_plan(
            persona_id=persona_id,
            owner_user_id=owner_user_id,
            target_date=target_date,
            source_prompt=queue_payload.get("prompt") or queue_row.get("caption") or queue_row.get("title"),
        )
        current_plan_id = str(queue_payload.get("contentPlanId") or "").strip()
        if current_plan_id == str(canonical_plan.get("id") or ""):
            return queue_row

    target_date = (_parse_iso_datetime(queue_row.get("scheduled_for")) or datetime.now(timezone.utc)).date().isoformat()
    now_iso = _iso_now()
    content_type = str(queue_row.get("content_type") or "story").lower()
    time_of_day = _queue_time_of_day(queue_row)
    moment_type = "POST" if content_type == "post" else "STORY"
    canonical_plan = _get_or_create_daily_plan(
        persona_id=persona_id,
        owner_user_id=owner_user_id,
        target_date=target_date,
        source_prompt=queue_payload.get("prompt") or queue_row.get("caption") or queue_row.get("title"),
    )
    plan_id = canonical_plan["id"]
    _moments_table("content_plans").update(
        {
            "updated_at": now_iso,
            "source_prompt": canonical_plan.get("source_prompt")
            or queue_payload.get("prompt")
            or queue_row.get("caption")
            or queue_row.get("title"),
        }
    ).eq("id", plan_id).execute()
    block_row = _get_or_create_plan_block(
        plan_id=plan_id,
        time_of_day=time_of_day,
        notes=queue_row.get("title") or queue_row.get("caption"),
        moment_type=moment_type,
    )
    block_id = block_row["id"]

    existing_moment_id = str(queue_payload.get("momentId") or "").strip()
    moment_rows: list[dict[str, Any]] = []
    if existing_moment_id:
        moment_rows = (
            _moments_table("moments")
            .select("*")
            .eq("id", existing_moment_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    if moment_rows:
        _moments_table("moments").update(
            {
                "plan_id": plan_id,
                "block_id": block_id,
                "moment_type": moment_type,
                "caption_hint": queue_row.get("caption") or queue_row.get("title"),
                "scheduled_at": queue_row.get("scheduled_for"),
                "updated_at": now_iso,
            }
        ).eq("id", existing_moment_id).execute()
        moment_id = existing_moment_id
    else:
        created_moment_rows = (
            _moments_table("moments")
            .insert(
                {
                    "plan_id": plan_id,
                    "block_id": block_id,
                    "moment_type": moment_type,
                    "image_count": 1,
                    "caption_hint": queue_row.get("caption") or queue_row.get("title"),
                    "status": "PLANNED",
                    "scheduled_at": queue_row.get("scheduled_for"),
                    "updated_at": now_iso,
                }
            )
            .execute()
            .data
            or []
        )
        if not created_moment_rows:
            return queue_row
        moment_id = created_moment_rows[0]["id"]

    continuity_parts = [
        str(queue_row.get("continuity_reason") or "").strip(),
        str(queue_payload.get("homeSpaceName") or "").strip(),
    ]
    relationship_names = [str(value).strip() for value in _coerce_list(queue_payload.get("relationshipNames")) if str(value).strip()]
    if relationship_names:
        continuity_parts.append(f"Relationships: {', '.join(relationship_names)}")

    _moments_table("moment_context").upsert(
        {
            "moment_id": moment_id,
            "location_id": _resolve_location_id_for_queue_item(persona_id=persona_id, queue_payload=queue_payload),
            "wardrobe_item_ids": _resolve_wardrobe_ids_for_queue_item(persona_id=persona_id, queue_payload=queue_payload),
            "outfit_composition": {
                "outfitName": queue_payload.get("outfitName"),
                "homeSpaceName": queue_payload.get("homeSpaceName"),
            },
            "food_theme": None,
            "mood_tags": [],
            "continuity_notes": " | ".join(part for part in continuity_parts if part),
        }
    ).execute()

    updated_payload = {
        **queue_payload,
        "contentPlanId": plan_id,
        "planBlockId": block_id,
        "momentId": moment_id,
        "ownerUserId": owner_user_id,
        "targetDate": target_date,
    }
    _moments_table("persona_content_queue").update(
        {
            "queue_payload": updated_payload,
            "updated_at": now_iso,
        }
    ).eq("id", queue_row["id"]).execute()
    updated_rows = (
        _moments_table("persona_content_queue")
        .select("*")
        .eq("id", queue_row["id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    return updated_rows[0] if updated_rows else {**queue_row, "queue_payload": updated_payload}


def _enqueue_generation_for_queue_item(queue_row: dict[str, Any]) -> dict[str, Any]:
    synced_row = _sync_queue_item_to_moments_draft(queue_row)
    queue_payload = _coerce_dict(synced_row.get("queue_payload"))
    moment_id = str(queue_payload.get("momentId") or "").strip()
    plan_id = str(queue_payload.get("contentPlanId") or "").strip()
    if not moment_id or not plan_id:
        return synced_row

    existing_jobs = (
        _moments_table("generation_jobs")
        .select("*")
        .eq("moment_id", moment_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing_jobs and str(existing_jobs[0].get("status") or "").lower() in {"queued", "running", "done"}:
        existing_job = existing_jobs[0]
        updated_payload = {
            **queue_payload,
            "generationJobId": existing_job.get("id"),
            "resultUrls": _coerce_list(existing_job.get("result_urls")),
        }
        _moments_table("persona_content_queue").update(
            {"queue_payload": updated_payload, "updated_at": _iso_now()}
        ).eq("id", synced_row["id"]).execute()
        synced_row["queue_payload"] = updated_payload
        return synced_row

    now_iso = _iso_now()
    _moments_table("moments").update(
        {"status": "GENERATING", "updated_at": now_iso}
    ).eq("id", moment_id).execute()
    _moments_table("content_plans").update(
        {"status": "GENERATING", "updated_at": now_iso}
    ).eq("id", plan_id).execute()
    job_rows = (
        _moments_table("generation_jobs")
        .insert({"moment_id": moment_id, "status": "queued"})
        .execute()
        .data
        or []
    )
    job_id = job_rows[0]["id"] if job_rows else None
    updated_payload = {
        **queue_payload,
        "generationJobId": job_id,
    }
    _moments_table("persona_content_queue").update(
        {"queue_payload": updated_payload, "updated_at": now_iso}
    ).eq("id", synced_row["id"]).execute()
    updated_rows = (
        _moments_table("persona_content_queue")
        .select("*")
        .eq("id", synced_row["id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    return updated_rows[0] if updated_rows else {**synced_row, "queue_payload": updated_payload}


def _regenerate_queue_item(queue_row: dict[str, Any]) -> dict[str, Any]:
    synced_row = _sync_queue_item_to_moments_draft(queue_row)
    queue_payload = _coerce_dict(synced_row.get("queue_payload"))
    moment_id = str(queue_payload.get("momentId") or "").strip()
    plan_id = str(queue_payload.get("contentPlanId") or "").strip()
    if not moment_id or not plan_id:
        return synced_row

    latest_jobs = (
        _moments_table("generation_jobs")
        .select("*")
        .eq("moment_id", moment_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if latest_jobs and str(latest_jobs[0].get("status") or "").lower() in {"queued", "running"}:
        return synced_row

    now_iso = _iso_now()
    _moments_table("moments").update(
        {"status": "GENERATING", "updated_at": now_iso}
    ).eq("id", moment_id).execute()
    _moments_table("content_plans").update(
        {"status": "GENERATING", "updated_at": now_iso}
    ).eq("id", plan_id).execute()
    job_rows = (
        _moments_table("generation_jobs")
        .insert({"moment_id": moment_id, "status": "queued"})
        .execute()
        .data
        or []
    )
    job_id = job_rows[0]["id"] if job_rows else None
    previous_urls = _coerce_list(queue_payload.get("resultUrls"))
    updated_payload = {
        **queue_payload,
        "generationJobId": job_id,
        "generationStatus": "queued",
        "generationError": None,
        "retryRequestedAt": None,
        "regeneratedAt": now_iso,
        "previousResultUrls": previous_urls,
        "resultUrls": [],
    }
    _moments_table("persona_content_queue").update(
        {"queue_payload": updated_payload, "updated_at": now_iso}
    ).eq("id", synced_row["id"]).execute()
    updated_rows = (
        _moments_table("persona_content_queue")
        .select("*")
        .eq("id", synced_row["id"])
        .limit(1)
        .execute()
        .data
        or []
    )
    return updated_rows[0] if updated_rows else {**synced_row, "queue_payload": updated_payload}


def _require_persona(persona_id: str) -> dict[str, Any]:
    row = (
        _people_table("personas")
        .select("*")
        .eq("id", persona_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not row:
        raise HTTPException(status_code=404, detail="Persona not found")
    return row[0]


def _maybe_single(schema: str, table: str, column: str, value: str) -> dict[str, Any] | None:
    query = get_client().schema(schema).table(table).select("*").eq(column, value).limit(1).execute()
    rows = query.data or []
    return rows[0] if rows else None


def _queue_status_counts(rows: list[dict[str, Any]]) -> tuple[int, int]:
    draft_count = 0
    approval_count = 0
    for row in rows:
        status_value = str(row.get("status") or "draft")
        if status_value == "draft":
            draft_count += 1
        if row.get("requires_approval") and status_value in {"draft", "held"}:
            approval_count += 1
    return draft_count, approval_count


def _persona_summary_response(
    persona: dict[str, Any],
    profile: dict[str, Any] | None,
    automation: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
    queue_rows: list[dict[str, Any]],
) -> DashboardPersonaSummaryResponse:
    draft_count, approval_count = _queue_status_counts(queue_rows)
    avatar_url = persona.get("avatar_url")
    return DashboardPersonaSummaryResponse(
        id=persona["id"],
        displayName=persona.get("display_name") or "Untitled Persona",
        bio=persona.get("bio"),
        avatarUrl=avatar_url,
        avatarSignedUrl=_resolve_avatar_url(avatar_url),
        isPublic=bool(persona.get("is_public")),
        lifecycleStatus=(profile or {}).get("lifecycle_status") or "draft",
        visibility=(profile or {}).get("visibility") or "private",
        socialHandle=(profile or {}).get("social_handle"),
        cityRegion=(profile or {}).get("city_region"),
        occupation=(profile or {}).get("occupation"),
        automationEnabled=bool((automation or {}).get("enabled")),
        automationMode=(automation or {}).get("autonomy_mode") or "QUEUE_DRAFTS",
        queueDraftCount=draft_count,
        pendingApprovalCount=approval_count,
        lastRunAt=iso_or_none((runtime or {}).get("last_run_at")),
        updatedAt=iso_or_none(persona.get("updated_at")),
    )


def _profile_response(persona_id: str, row: dict[str, Any] | None) -> DashboardPersonaProfileResponse | None:
    if not row:
        return None
    return DashboardPersonaProfileResponse(
        personaId=persona_id,
        fullName=row.get("full_name"),
        socialHandle=row.get("social_handle"),
        ageRange=row.get("age_range"),
        genderExpression=row.get("gender_expression"),
        culturalBackground=row.get("cultural_background"),
        languages=_coerce_list(row.get("languages")),
        cityRegion=row.get("city_region"),
        occupation=row.get("occupation"),
        publicBio=row.get("public_bio"),
        internalBio=row.get("internal_bio"),
        lifecycleStatus=row.get("lifecycle_status") or "draft",
        visibility=row.get("visibility") or "private",
        brandContext=_coerce_dict(row.get("brand_context")),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _personality_response(persona_id: str, row: dict[str, Any] | None) -> DashboardPersonaPersonalityResponse | None:
    if not row:
        return None
    return DashboardPersonaPersonalityResponse(
        personaId=persona_id,
        personalitySummary=row.get("personality_summary"),
        dominantTraits=_coerce_list(row.get("dominant_traits")),
        secondaryTraits=_coerce_list(row.get("secondary_traits")),
        values=_coerce_list(row.get("values")),
        ambitions=_coerce_list(row.get("ambitions")),
        vulnerabilities=row.get("vulnerabilities"),
        humorStyle=row.get("humor_style"),
        socialEnergy=row.get("social_energy"),
        confidenceLevel=row.get("confidence_level"),
        communicationStyle=row.get("communication_style"),
        emotionalRange=_coerce_list(row.get("emotional_range")),
        stateRules=_coerce_dict(row.get("state_rules")),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _routine_response(persona_id: str, row: dict[str, Any] | None) -> DashboardPersonaRoutineResponse | None:
    if not row:
        return None
    return DashboardPersonaRoutineResponse(
        personaId=persona_id,
        wakeUpTime=row.get("wake_up_time"),
        workingHours=_coerce_dict(row.get("working_hours")),
        morningRituals=_coerce_list(row.get("morning_rituals")),
        exerciseHabits=_coerce_list(row.get("exercise_habits")),
        eveningPatterns=_coerce_list(row.get("evening_patterns")),
        weekendBehavior=_coerce_list(row.get("weekend_behavior")),
        postingRhythm=_coerce_dict(row.get("posting_rhythm")),
        travelFrequency=row.get("travel_frequency"),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _interests_response(persona_id: str, row: dict[str, Any] | None) -> DashboardPersonaInterestsResponse | None:
    if not row:
        return None
    return DashboardPersonaInterestsResponse(
        personaId=persona_id,
        strongInterests=_coerce_list(row.get("strong_interests")),
        occasionalInterests=_coerce_list(row.get("occasional_interests")),
        skills=_coerce_list(row.get("skills")),
        hobbies=_coerce_list(row.get("hobbies")),
        culturalTastes=_coerce_list(row.get("cultural_tastes")),
        wellnessHabits=_coerce_list(row.get("wellness_habits")),
        foodPreferences=_coerce_list(row.get("food_preferences")),
        travelPreferences=_coerce_list(row.get("travel_preferences")),
        shoppingBehavior=_coerce_list(row.get("shopping_behavior")),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _location_response(row: dict[str, Any]) -> DashboardPersonaLocationResponse:
    return DashboardPersonaLocationResponse(
        id=row["id"],
        personaId=row["persona_id"],
        name=row.get("name") or "",
        tags=_coerce_list(row.get("tags")),
        tier=row.get("tier") or "SEMI_STABLE",
        reuseWeight=float(row.get("reuse_weight") or 1.0),
        cooldownHours=int(row.get("cooldown_hours") or 0),
        maxPerWeek=row.get("max_per_week"),
        description=row.get("description"),
        visualNotes=row.get("visual_notes"),
        lightingNotes=row.get("lighting_notes"),
        emotionalAssociation=row.get("emotional_association"),
        createdAt=iso_or_none(row.get("created_at")),
    )


def _wardrobe_response(row: dict[str, Any]) -> DashboardPersonaWardrobeResponse:
    return DashboardPersonaWardrobeResponse(
        id=row["id"],
        personaId=row["persona_id"],
        category=row.get("category") or "set",
        name=row.get("name") or "",
        tags=_coerce_list(row.get("tags")),
        tier=row.get("tier") or "SEMI_STABLE",
        reuseWeight=float(row.get("reuse_weight") or 1.0),
        seasonTags=_coerce_list(row.get("season_tags")),
        description=row.get("description"),
        suitabilityTags=_coerce_list(row.get("suitability_tags")),
        signatureItem=bool(row.get("signature_item")),
        favoriteItem=bool(row.get("favorite_item")),
        createdAt=iso_or_none(row.get("created_at")),
    )


def _outfit_response(row: dict[str, Any]) -> DashboardPersonaOutfitResponse:
    return DashboardPersonaOutfitResponse(
        id=row["id"],
        personaId=row["persona_id"],
        name=row.get("name") or "",
        description=row.get("description"),
        wardrobeItemIds=_coerce_list(row.get("wardrobe_item_ids")),
        suitableOccasions=_coerce_list(row.get("suitable_occasions")),
        seasonTags=_coerce_list(row.get("season_tags")),
        moodTags=_coerce_list(row.get("mood_tags")),
        referenceImageUrl=row.get("reference_image_url"),
        reuseCooldownHours=int(row.get("reuse_cooldown_hours") or 0),
        signatureLook=bool(row.get("signature_look")),
        lastUsedAt=iso_or_none(row.get("last_used_at")),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _home_space_response(row: dict[str, Any]) -> DashboardPersonaHomeSpaceResponse:
    return DashboardPersonaHomeSpaceResponse(
        id=row["id"],
        personaId=row["persona_id"],
        name=row.get("name") or "",
        description=row.get("description"),
        roomType=row.get("room_type"),
        visualTraits=_coerce_list(row.get("visual_traits")),
        lightingNotes=row.get("lighting_notes"),
        signatureUseCases=_coerce_list(row.get("signature_use_cases")),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _object_response(row: dict[str, Any]) -> DashboardPersonaObjectResponse:
    return DashboardPersonaObjectResponse(
        id=row["id"],
        personaId=row["persona_id"],
        name=row.get("name") or "",
        description=row.get("description"),
        objectType=row.get("object_type"),
        visualTraits=_coerce_list(row.get("visual_traits")),
        emotionalRole=row.get("emotional_role"),
        recurringContexts=_coerce_list(row.get("recurring_contexts")),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _relationship_response(row: dict[str, Any]) -> DashboardPersonaRelationshipResponse:
    return DashboardPersonaRelationshipResponse(
        id=row["id"],
        personaId=row["persona_id"],
        name=row.get("name") or "",
        relationshipType=row.get("relationship_type") or "unknown",
        summary=row.get("summary"),
        visibility=row.get("visibility") or "internal",
        emotionalTone=row.get("emotional_tone"),
        recurringContexts=_coerce_list(row.get("recurring_contexts")),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _memory_response(row: dict[str, Any]) -> DashboardPersonaMemoryResponse:
    return DashboardPersonaMemoryResponse(
        id=row["id"],
        personaId=row["persona_id"],
        title=row.get("title") or "",
        memoryType=row.get("memory_type") or "canonical",
        summary=row.get("summary") or "",
        importanceScore=int(row.get("importance_score") or 3),
        occurredAt=iso_or_none(row.get("occurred_at")),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _world_addition_response(row: dict[str, Any]) -> DashboardPersonaWorldAdditionResponse:
    return DashboardPersonaWorldAdditionResponse(
        id=row["id"],
        personaId=row["persona_id"],
        sourceKind=row.get("source_kind"),
        sourceId=row.get("source_id"),
        itemType=row.get("item_type") or "unknown",
        proposedName=row.get("proposed_name"),
        proposedPayload=_coerce_dict(row.get("proposed_payload")),
        status=row.get("status") or "suggested",
        reviewerUserId=row.get("reviewer_user_id"),
        reviewNote=row.get("review_note"),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _automation_response(persona_id: str, row: dict[str, Any] | None) -> DashboardPersonaAutomationSettingsResponse | None:
    if not row:
        return None
    return DashboardPersonaAutomationSettingsResponse(
        personaId=persona_id,
        enabled=bool(row.get("enabled")),
        autonomyMode=row.get("autonomy_mode") or "QUEUE_DRAFTS",
        cadenceHours=int(row.get("cadence_hours") or 24),
        spontaneity=float(row.get("spontaneity") or 0.35),
        noveltyRate=float(row.get("novelty_rate") or 0.15),
        allowedContentTypes=_coerce_list(row.get("allowed_content_types")),
        boundaries=_coerce_dict(row.get("boundaries")),
        campaignOverridePolicy=row.get("campaign_override_policy") or "require_brief",
        requireManualPublish=bool(row.get("require_manual_publish")),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _runtime_response(persona_id: str, row: dict[str, Any] | None) -> DashboardPersonaRuntimeStateResponse | None:
    if not row:
        return None
    return DashboardPersonaRuntimeStateResponse(
        personaId=persona_id,
        currentMode=row.get("current_mode") or "idle",
        lastRunAt=iso_or_none(row.get("last_run_at")),
        nextRunAt=iso_or_none(row.get("next_run_at")),
        pauseReason=row.get("pause_reason"),
        pendingApprovalCount=int(row.get("pending_approval_count") or 0),
        activeCampaignContext=_coerce_dict(row.get("active_campaign_context")),
        lastError=row.get("last_error"),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _run_response(row: dict[str, Any]) -> DashboardPersonaAutomationRunResponse:
    return DashboardPersonaAutomationRunResponse(
        id=row["id"],
        personaId=row["persona_id"],
        triggerSource=row.get("trigger_source"),
        status=row.get("status") or "ready",
        contextSummary=row.get("context_summary"),
        inputPrompt=row.get("input_prompt"),
        outputPayload=_coerce_dict(row.get("output_payload")),
        blockedReason=row.get("blocked_reason"),
        createdAt=iso_or_none(row.get("created_at")),
        completedAt=iso_or_none(row.get("completed_at")),
    )


def _queue_response(row: dict[str, Any]) -> DashboardPersonaQueueItemResponse:
    queue_payload = _coerce_dict(row.get("queue_payload"))
    moment_id = str(queue_payload.get("momentId") or "").strip()
    if moment_id:
        moment_rows = (
            _moments_table("moments")
            .select("status")
            .eq("id", moment_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if moment_rows:
            queue_payload["momentStatus"] = moment_rows[0].get("status")
        job_rows = (
            _moments_table("generation_jobs")
            .select("id,status,result_urls,error,completed_at")
            .eq("moment_id", moment_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if job_rows:
            latest_job = job_rows[0]
            queue_payload["generationJobId"] = latest_job.get("id")
            queue_payload["generationStatus"] = latest_job.get("status")
            queue_payload["resultUrls"] = _coerce_list(latest_job.get("result_urls"))
            queue_payload["generationError"] = latest_job.get("error")
            queue_payload["generationCompletedAt"] = iso_or_none(latest_job.get("completed_at"))
    return DashboardPersonaQueueItemResponse(
        id=row["id"],
        personaId=row["persona_id"],
        runId=row.get("run_id"),
        title=row.get("title") or "",
        contentType=row.get("content_type") or "story",
        status=row.get("status") or "draft",
        scheduledFor=iso_or_none(row.get("scheduled_for")),
        caption=row.get("caption"),
        visualDirection=row.get("visual_direction"),
        continuityReason=row.get("continuity_reason"),
        novelty=bool(row.get("novelty")),
        queuePayload=queue_payload,
        requiresApproval=bool(row.get("requires_approval")),
        campaignId=row.get("campaign_id"),
        approvedByUserId=row.get("approved_by_user_id"),
        approvedAt=iso_or_none(row.get("approved_at")),
        publishedAt=iso_or_none(row.get("published_at")),
        rejectionReason=row.get("rejection_reason"),
        createdAt=iso_or_none(row.get("created_at")),
        updatedAt=iso_or_none(row.get("updated_at")),
    )


def _campaign_response(row: dict[str, Any]) -> DashboardPersonaCampaignContextResponse:
    return DashboardPersonaCampaignContextResponse(
        id=row["id"],
        name=row.get("name"),
        status=row.get("status"),
        objective=row.get("objective"),
        syncedAt=iso_or_none(row.get("synced_at")),
    )


def _audit_response(row: dict[str, Any]) -> DashboardPersonaAuditEventResponse:
    return DashboardPersonaAuditEventResponse(
        id=row["id"],
        personaId=row["persona_id"],
        eventType=row.get("event_type") or "unknown",
        actorType=row.get("actor_type") or "system",
        actorId=row.get("actor_id"),
        summary=row.get("summary") or "",
        payload=_coerce_dict(row.get("payload")),
        createdAt=iso_or_none(row.get("created_at")),
    )


def _strip_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    stripped = stripped.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("Claude response was not a JSON object")
    return parsed


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = iso_or_none(value)
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _count_open_queue_rows(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if str(row.get("status") or "draft") in {"draft", "approved", "held"})


def _normalize_social_handle(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.lstrip("@").strip().lower()


def _normalize_entity_name(value: Any) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    return text


def _log_audit_event(
    persona_id: str,
    *,
    event_type: str,
    actor_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    actor_id: str | None = None,
) -> None:
    _moments_table("persona_audit_events").insert(
        {
            "persona_id": persona_id,
            "event_type": event_type,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "summary": summary,
            "payload": payload or {},
        }
    ).execute()


def _queue_reference_timestamp(row: dict[str, Any]) -> datetime | None:
    for key in ("published_at", "scheduled_for", "created_at", "updated_at"):
        parsed = _parse_iso_datetime(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _most_recent_entity_use(
    recent_queue: list[dict[str, Any]],
    *,
    payload_key: str,
    entity_name: str,
) -> datetime | None:
    normalized_target = _normalize_entity_name(entity_name)
    if not normalized_target:
        return None
    latest: datetime | None = None
    for row in recent_queue:
        payload = _coerce_dict(row.get("queue_payload"))
        raw_value = payload.get(payload_key)
        candidates = raw_value if isinstance(raw_value, list) else [raw_value]
        if not any(_normalize_entity_name(candidate) == normalized_target for candidate in candidates):
            continue
        stamp = _queue_reference_timestamp(row)
        if stamp is None:
            continue
        if latest is None or stamp > latest:
            latest = stamp
    return latest


def _sync_runtime_counts(persona_id: str) -> None:
    queue_rows = (
        _moments_table("persona_content_queue")
        .select("id,status,requires_approval")
        .eq("persona_id", persona_id)
        .execute()
        .data
        or []
    )
    open_count = _count_open_queue_rows(queue_rows)
    _, approval_count = _queue_status_counts(queue_rows)
    runtime = _maybe_single(MOMENTS_SCHEMA, "persona_runtime_state", "persona_id", persona_id) or {}
    current_mode = str(runtime.get("current_mode") or "idle")
    if open_count and current_mode == "idle":
        current_mode = "queued"
    if not open_count and current_mode == "queued":
        current_mode = "idle"
    _upsert_runtime_state(
        persona_id,
        current_mode=current_mode,
        pause_reason=runtime.get("pause_reason"),
        pending_approval_count=approval_count,
        active_campaign_context=_coerce_dict(runtime.get("active_campaign_context")),
        last_error=runtime.get("last_error"),
        last_run_at=iso_or_none(runtime.get("last_run_at")),
        next_run_at=iso_or_none(runtime.get("next_run_at")),
    )


def _promote_world_addition(addition: dict[str, Any]) -> None:
    persona_id = addition["persona_id"]
    payload = _coerce_dict(addition.get("proposed_payload"))
    item_type = str(addition.get("item_type") or "").lower()
    proposed_name = addition.get("proposed_name")

    if item_type == "location":
        _people_table("world_locations").insert(
            {
                "persona_id": persona_id,
                "name": proposed_name or payload.get("name") or "Untitled location",
                "tags": _coerce_list(payload.get("tags")),
                "tier": payload.get("tier") or "SEMI_STABLE",
                "reuse_weight": float(payload.get("reuseWeight") or 1.0),
                "cooldown_hours": int(payload.get("cooldownHours") or 0),
                "max_per_week": payload.get("maxPerWeek"),
                "description": payload.get("description") or payload.get("summary"),
                "visual_notes": payload.get("visualNotes"),
                "lighting_notes": payload.get("lightingNotes"),
                "emotional_association": payload.get("emotionalAssociation"),
            }
        ).execute()
        return
    if item_type == "wardrobe":
        _people_table("world_wardrobe_items").insert(
            {
                "persona_id": persona_id,
                "category": payload.get("category") or "set",
                "name": proposed_name or payload.get("name") or "Untitled item",
                "tags": _coerce_list(payload.get("tags")),
                "tier": payload.get("tier") or "SEMI_STABLE",
                "reuse_weight": float(payload.get("reuseWeight") or 1.0),
                "season_tags": _coerce_list(payload.get("seasonTags")),
                "description": payload.get("description") or payload.get("summary"),
                "suitability_tags": _coerce_list(payload.get("suitabilityTags")),
                "signature_item": bool(payload.get("signatureItem")),
                "favorite_item": bool(payload.get("favoriteItem")),
            }
        ).execute()
        return
    if item_type == "outfit":
        _people_table("persona_outfits").insert(
            {
                "persona_id": persona_id,
                "name": proposed_name or payload.get("name") or "Untitled outfit",
                "description": payload.get("description") or payload.get("summary"),
                "wardrobe_item_ids": _coerce_list(payload.get("wardrobeItemIds")),
                "suitable_occasions": _coerce_list(payload.get("suitableOccasions")),
                "season_tags": _coerce_list(payload.get("seasonTags")),
                "mood_tags": _coerce_list(payload.get("moodTags")),
                "reference_image_url": payload.get("referenceImageUrl"),
                "reuse_cooldown_hours": int(payload.get("reuseCooldownHours") or 0),
                "signature_look": bool(payload.get("signatureLook")),
                "updated_at": _iso_now(),
            }
        ).execute()
        return
    if item_type == "home_space":
        _people_table("persona_home_spaces").insert(
            {
                "persona_id": persona_id,
                "name": proposed_name or payload.get("name") or "Untitled home space",
                "description": payload.get("description") or payload.get("summary"),
                "room_type": payload.get("roomType"),
                "visual_traits": _coerce_list(payload.get("visualTraits")),
                "lighting_notes": payload.get("lightingNotes"),
                "signature_use_cases": _coerce_list(payload.get("signatureUseCases")),
                "updated_at": _iso_now(),
            }
        ).execute()
        return
    if item_type == "object":
        _people_table("persona_objects").insert(
            {
                "persona_id": persona_id,
                "name": proposed_name or payload.get("name") or "Untitled object",
                "description": payload.get("description") or payload.get("summary"),
                "object_type": payload.get("objectType"),
                "visual_traits": _coerce_list(payload.get("visualTraits")),
                "emotional_role": payload.get("emotionalRole"),
                "recurring_contexts": _coerce_list(payload.get("recurringContexts")),
                "updated_at": _iso_now(),
            }
        ).execute()
        return
    if item_type == "relationship":
        _people_table("persona_relationships").insert(
            {
                "persona_id": persona_id,
                "name": proposed_name or payload.get("name") or "Untitled relationship",
                "relationship_type": payload.get("relationshipType") or "unknown",
                "summary": payload.get("summary"),
                "visibility": payload.get("visibility") or "internal",
                "emotional_tone": payload.get("emotionalTone"),
                "recurring_contexts": _coerce_list(payload.get("recurringContexts")),
                "updated_at": _iso_now(),
            }
        ).execute()
        return
    if item_type in {"habit", "routine"}:
        existing = _maybe_single(PEOPLE_SCHEMA, "persona_routines", "persona_id", persona_id) or {
            "persona_id": persona_id
        }
        rituals = _coerce_list(existing.get("morning_rituals"))
        label = proposed_name or payload.get("name") or payload.get("summary")
        if label and label not in rituals:
            rituals.append(label)
        existing.update(
            {
                "morning_rituals": rituals,
                "updated_at": _iso_now(),
            }
        )
        _people_table("persona_routines").upsert(existing, on_conflict="persona_id").execute()



def _publish_queue_item_to_dashboard_social(queue_row: dict[str, Any]) -> str:
    persona_id = queue_row["persona_id"]
    persona = _require_persona(persona_id)
    profile = _maybe_single(PEOPLE_SCHEMA, "persona_profiles", "persona_id", persona_id) or {}
    queue_payload = _coerce_dict(queue_row.get("queue_payload"))
    now_iso = _iso_now()

    social_handle = _normalize_social_handle(profile.get("social_handle"))
    account_id = social_handle or f"persona-{str(persona_id)[:8]}"
    dashboard_table("social_accounts").upsert(
        [
            {
                "id": account_id,
                "username": account_id,
                "account_type": "PERSONA",
                "is_verified": False,
                "location": profile.get("city_region"),
                "niche": profile.get("occupation") or persona.get("bio"),
                "source": "persona_dashboard",
                "discovery_source": "persona_dashboard",
                "first_seen_at": now_iso,
                "synced_at": now_iso,
            }
        ],
        on_conflict="id",
    ).execute()

    content_type = str(queue_row.get("content_type") or "story").lower()
    media_type = "VIDEO" if content_type in {"reel", "video"} else "IMAGE"
    social_post_id = str(queue_payload.get("socialPostId") or f"persona-{queue_row['id']}")
    dashboard_table("social_posts").upsert(
        [
            {
                "id": social_post_id,
                "account_id": account_id,
                "caption": queue_row.get("caption"),
                "media_type": media_type,
                "permalink": queue_payload.get("publishedUrl"),
                "like_count": None,
                "comment_count": None,
                "published_at": now_iso,
                "synced_at": now_iso,
            }
        ],
        on_conflict="id",
    ).execute()
    return social_post_id


def _should_auto_publish(settings: dict[str, Any]) -> bool:
    return (
        str(settings.get("autonomy_mode") or "QUEUE_DRAFTS") == "AUTO_PUBLISH"
        and not bool(settings.get("require_manual_publish", True))
    )


def _auto_publish_queue_rows(
    *,
    persona_id: str,
    rows: list[dict[str, Any]],
    settings: dict[str, Any],
    trigger_source: str,
) -> tuple[list[dict[str, Any]], int]:
    if not _should_auto_publish(settings):
        return rows, 0

    updated_rows: list[dict[str, Any]] = []
    auto_published_count = 0
    for row in rows:
        if bool(row.get("requires_approval")):
            updated_rows.append(row)
            continue
        row = _enqueue_generation_for_queue_item(row)
        queue_payload = _coerce_dict(row.get("queue_payload"))
        social_post_id = _publish_queue_item_to_dashboard_social(row)
        patch = {
            "status": "published",
            "queue_payload": {
                **queue_payload,
                "socialPostId": social_post_id,
                "publishedByAutomation": True,
            },
            "approved_at": _iso_now(),
            "published_at": _iso_now(),
            "rejection_reason": None,
            "updated_at": _iso_now(),
        }
        _moments_table("persona_content_queue").update(patch).eq("id", row["id"]).execute()
        updated = (
            _moments_table("persona_content_queue")
            .select("*")
            .eq("id", row["id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        updated_row = updated[0] if updated else {**row, **patch}
        updated_rows.append(updated_row)
        auto_published_count += 1
        _log_audit_event(
            persona_id,
            event_type="persona.queue.auto_published",
            actor_type="system",
            actor_id=trigger_source,
            summary=f"Queue item auto-published: {row.get('title') or 'Untitled draft'}",
            payload={
                "queueId": row["id"],
                "socialPostId": social_post_id,
            },
        )
    return updated_rows, auto_published_count


def _dedupe_world_additions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("itemType") or "unknown").strip().lower()
        proposed_name = str(item.get("proposedName") or "").strip().lower()
        key = (item_type, proposed_name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _apply_queue_guardrails(
    *,
    queue_items: list[dict[str, Any]],
    settings: dict[str, Any],
    recent_queue: list[dict[str, Any]],
    persona_context: dict[str, Any],
    now: datetime,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    warnings: list[str] = []
    sanitized: list[dict[str, Any]] = []
    inferred_world_additions: list[dict[str, Any]] = []
    allowed_types = {
        str(item).strip().lower()
        for item in _coerce_list(settings.get("allowed_content_types"))
        if str(item).strip()
    } or {"story", "post"}
    novelty_rate = float(settings.get("novelty_rate") or 0.0)
    novelty_limit = 0 if novelty_rate <= 0 else max(1, int(len(queue_items) * novelty_rate + 0.9999))
    novelty_used = 0
    recent_titles = {
        str(row.get("title") or "").strip().lower()
        for row in recent_queue
        if str(row.get("status") or "draft") != "rejected"
    }
    locations_by_name = {
        _normalize_entity_name(row.get("name")): row
        for row in _coerce_list(persona_context.get("locations"))
        if isinstance(row, dict) and _normalize_entity_name(row.get("name"))
    }
    outfits_by_name = {
        _normalize_entity_name(row.get("name")): row
        for row in _coerce_list(persona_context.get("outfits"))
        if isinstance(row, dict) and _normalize_entity_name(row.get("name"))
    }
    home_spaces_by_name = {
        _normalize_entity_name(row.get("name")): row
        for row in _coerce_list(persona_context.get("homeSpaces"))
        if isinstance(row, dict) and _normalize_entity_name(row.get("name"))
    }
    relationships_by_name = {
        _normalize_entity_name(row.get("name")): row
        for row in _coerce_list(persona_context.get("relationships"))
        if isinstance(row, dict) and _normalize_entity_name(row.get("name"))
    }

    for index, raw_item in enumerate(queue_items):
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        content_type = str(item.get("contentType") or "story").strip().lower()
        if content_type not in allowed_types:
            warnings.append(f"Filtered unsupported content type '{content_type}'.")
            continue
        scheduled_for_dt = _parse_iso_datetime(item.get("scheduledFor"))
        if scheduled_for_dt is None or scheduled_for_dt < now:
            scheduled_for_dt = now + timedelta(hours=index)
            item["scheduledFor"] = scheduled_for_dt.isoformat()
            warnings.append(f"Adjusted schedule for '{item.get('title') or 'untitled draft'}' to a future slot.")
        title_key = str(item.get("title") or "").strip().lower()
        if title_key and title_key in recent_titles:
            item["requiresApproval"] = True
            warnings.append(f"Marked '{item.get('title')}' for approval because a similar draft already exists.")
        if bool(item.get("novelty")):
            if novelty_used >= novelty_limit:
                item["novelty"] = False
                warnings.append(f"Reduced novelty on '{item.get('title') or 'untitled draft'}' to stay within persona limits.")
            else:
                novelty_used += 1

        location_name = str(item.get("locationName") or "").strip()
        if location_name:
            canonical_location = locations_by_name.get(_normalize_entity_name(location_name))
            if canonical_location is None:
                item["requiresApproval"] = True
                warnings.append(f"Marked '{item.get('title') or 'untitled draft'}' for approval because location '{location_name}' is not canonical yet.")
                inferred_world_additions.append(
                    {
                        "itemType": "location",
                        "proposedName": location_name,
                        "summary": f"Automation referenced a new location in '{item.get('title') or 'untitled draft'}'.",
                        "payload": {
                            "name": location_name,
                            "description": item.get("continuityReason"),
                        },
                    }
                )
            else:
                last_used = _most_recent_entity_use(
                    recent_queue,
                    payload_key="locationName",
                    entity_name=location_name,
                )
                cooldown_hours = int(canonical_location.get("cooldown_hours") or 0)
                if last_used is not None and cooldown_hours > 0 and last_used + timedelta(hours=cooldown_hours) > scheduled_for_dt:
                    item["requiresApproval"] = True
                    warnings.append(
                        f"Marked '{item.get('title') or 'untitled draft'}' for approval because location '{location_name}' is inside its cooldown window."
                    )

        outfit_name = str(item.get("outfitName") or "").strip()
        if outfit_name:
            canonical_outfit = outfits_by_name.get(_normalize_entity_name(outfit_name))
            if canonical_outfit is None:
                item["requiresApproval"] = True
                warnings.append(f"Marked '{item.get('title') or 'untitled draft'}' for approval because outfit '{outfit_name}' is not canonical yet.")
                inferred_world_additions.append(
                    {
                        "itemType": "outfit",
                        "proposedName": outfit_name,
                        "summary": f"Automation referenced a new outfit in '{item.get('title') or 'untitled draft'}'.",
                        "payload": {
                            "name": outfit_name,
                            "description": item.get("visualDirection"),
                        },
                    }
                )
            else:
                last_used = _most_recent_entity_use(
                    recent_queue,
                    payload_key="outfitName",
                    entity_name=outfit_name,
                )
                cooldown_hours = int(canonical_outfit.get("reuse_cooldown_hours") or 0)
                if last_used is not None and cooldown_hours > 0 and last_used + timedelta(hours=cooldown_hours) > scheduled_for_dt:
                    item["requiresApproval"] = True
                    warnings.append(
                        f"Marked '{item.get('title') or 'untitled draft'}' for approval because outfit '{outfit_name}' is inside its cooldown window."
                    )

        home_space_name = str(item.get("homeSpaceName") or "").strip()
        if home_space_name and _normalize_entity_name(home_space_name) not in home_spaces_by_name:
            item["requiresApproval"] = True
            warnings.append(f"Marked '{item.get('title') or 'untitled draft'}' for approval because home space '{home_space_name}' is not canonical yet.")
            inferred_world_additions.append(
                {
                    "itemType": "home_space",
                    "proposedName": home_space_name,
                    "summary": f"Automation referenced a new home space in '{item.get('title') or 'untitled draft'}'.",
                    "payload": {
                        "name": home_space_name,
                        "description": item.get("continuityReason"),
                    },
                }
            )

        relationship_names = [
            str(name).strip()
            for name in _coerce_list(item.get("relationshipNames"))
            if str(name).strip()
        ]
        validated_relationships: list[str] = []
        for relationship_name in relationship_names:
            if _normalize_entity_name(relationship_name) not in relationships_by_name:
                item["requiresApproval"] = True
                warnings.append(
                    f"Marked '{item.get('title') or 'untitled draft'}' for approval because relationship '{relationship_name}' is not canonical yet."
                )
                inferred_world_additions.append(
                    {
                        "itemType": "relationship",
                        "proposedName": relationship_name,
                        "summary": f"Automation referenced a new relationship in '{item.get('title') or 'untitled draft'}'.",
                        "payload": {
                            "name": relationship_name,
                            "summary": item.get("continuityReason"),
                        },
                    }
                )
            else:
                validated_relationships.append(relationship_name)
        if validated_relationships:
            item["relationshipNames"] = validated_relationships
        sanitized.append(item)
    return sanitized, warnings, _dedupe_world_additions(inferred_world_additions)


def _dashboard_business_context(limit: int = 5) -> dict[str, Any]:
    campaigns = (
        dashboard_table("campaigns")
        .select("id,name,status,objective,synced_at")
        .order("synced_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    recent_social_posts = (
        dashboard_table("social_posts")
        .select("id,account_id,caption,media_type,published_at")
        .order("published_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return {
        "campaigns": campaigns,
        "recentSocialPosts": recent_social_posts,
    }


def _persona_generation_context(persona_id: str) -> dict[str, Any]:
    persona = _require_persona(persona_id)
    profile = _maybe_single(PEOPLE_SCHEMA, "persona_profiles", "persona_id", persona_id)
    personality = _maybe_single(PEOPLE_SCHEMA, "persona_personality", "persona_id", persona_id)
    routine = _maybe_single(PEOPLE_SCHEMA, "persona_routines", "persona_id", persona_id)
    interests = _maybe_single(PEOPLE_SCHEMA, "persona_interests", "persona_id", persona_id)
    automation = _maybe_single(MOMENTS_SCHEMA, "persona_automation_settings", "persona_id", persona_id)
    style = _maybe_single(PEOPLE_SCHEMA, "persona_style_profile", "persona_id", persona_id)
    locations = (
        _people_table("world_locations")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    wardrobe = (
        _people_table("world_wardrobe_items")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    outfits = (
        _people_table("persona_outfits")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    home_spaces = (
        _people_table("persona_home_spaces")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    objects = (
        _people_table("persona_objects")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    relationships = (
        _people_table("persona_relationships")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )
    memories = (
        _people_table("persona_canonical_memories")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=True)
        .limit(8)
        .execute()
        .data
        or []
    )
    recent_queue = (
        _moments_table("persona_content_queue")
        .select("*")
        .eq("persona_id", persona_id)
        .order("created_at", desc=True)
        .limit(8)
        .execute()
        .data
        or []
    )
    return {
        "persona": persona,
        "profile": profile or {},
        "personality": personality or {},
        "routine": routine or {},
        "interests": interests or {},
        "automation": automation or {},
        "style": style or {},
        "locations": locations,
        "wardrobe": wardrobe,
        "outfits": outfits,
        "homeSpaces": home_spaces,
        "objects": objects,
        "relationships": relationships,
        "memories": memories,
        "recentQueue": recent_queue,
    }


def _upsert_runtime_state(
    persona_id: str,
    *,
    current_mode: str,
    pause_reason: str | None = None,
    pending_approval_count: int = 0,
    active_campaign_context: dict[str, Any] | None = None,
    last_error: str | None = None,
    last_run_at: str | None = None,
    next_run_at: str | None = None,
) -> None:
    now = _iso_now()
    payload = {
        "persona_id": persona_id,
        "current_mode": current_mode,
        "pause_reason": pause_reason,
        "pending_approval_count": pending_approval_count,
        "active_campaign_context": active_campaign_context or {},
        "last_error": last_error,
        "updated_at": now,
    }
    if last_run_at is not None:
        payload["last_run_at"] = last_run_at
    if next_run_at is not None:
        payload["next_run_at"] = next_run_at
    _moments_table("persona_runtime_state").upsert(payload, on_conflict="persona_id").execute()


def _build_persona_detail(persona_id: str) -> DashboardPersonaDetailResponse:
    persona = _require_persona(persona_id)
    profile = _maybe_single(PEOPLE_SCHEMA, "persona_profiles", "persona_id", persona_id)
    personality = _maybe_single(PEOPLE_SCHEMA, "persona_personality", "persona_id", persona_id)
    routine = _maybe_single(PEOPLE_SCHEMA, "persona_routines", "persona_id", persona_id)
    interests = _maybe_single(PEOPLE_SCHEMA, "persona_interests", "persona_id", persona_id)
    style = _maybe_single(PEOPLE_SCHEMA, "persona_style_profile", "persona_id", persona_id)
    automation = _maybe_single(MOMENTS_SCHEMA, "persona_automation_settings", "persona_id", persona_id)
    runtime = _maybe_single(MOMENTS_SCHEMA, "persona_runtime_state", "persona_id", persona_id)
    locations = _people_table("world_locations").select("*").eq("persona_id", persona_id).execute().data or []
    wardrobe = _people_table("world_wardrobe_items").select("*").eq("persona_id", persona_id).execute().data or []
    outfits = _people_table("persona_outfits").select("*").eq("persona_id", persona_id).order("created_at", desc=True).execute().data or []
    home_spaces = _people_table("persona_home_spaces").select("*").eq("persona_id", persona_id).order("created_at", desc=True).execute().data or []
    objects = _people_table("persona_objects").select("*").eq("persona_id", persona_id).order("created_at", desc=True).execute().data or []
    relationships = _people_table("persona_relationships").select("*").eq("persona_id", persona_id).order("created_at", desc=True).execute().data or []
    memories = _people_table("persona_canonical_memories").select("*").eq("persona_id", persona_id).order("created_at", desc=True).execute().data or []
    additions = _people_table("persona_world_addition_requests").select("*").eq("persona_id", persona_id).order("created_at", desc=True).execute().data or []
    queue = _moments_table("persona_content_queue").select("*").eq("persona_id", persona_id).order("created_at", desc=True).execute().data or []
    queue = _sync_queue_rows_to_moments(queue)
    runs = _moments_table("persona_automation_runs").select("*").eq("persona_id", persona_id).order("created_at", desc=True).limit(10).execute().data or []
    campaigns = dashboard_table("campaigns").select("id,name,status,objective,synced_at").order("synced_at", desc=True).limit(5).execute().data or []
    audit_events = _moments_table("persona_audit_events").select("*").eq("persona_id", persona_id).order("created_at", desc=True).limit(12).execute().data or []
    return DashboardPersonaDetailResponse(
        persona=_persona_summary_response(persona, profile, automation, runtime, queue),
        profile=_profile_response(persona_id, profile),
        personality=_personality_response(persona_id, personality),
        routine=_routine_response(persona_id, routine),
        interests=_interests_response(persona_id, interests),
        styleProfile=style or None,
        locations=[_location_response(row) for row in locations],
        wardrobe=[_wardrobe_response(row) for row in wardrobe],
        outfits=[_outfit_response(row) for row in outfits],
        homeSpaces=[_home_space_response(row) for row in home_spaces],
        objects=[_object_response(row) for row in objects],
        relationships=[_relationship_response(row) for row in relationships],
        memories=[_memory_response(row) for row in memories],
        worldAdditions=[_world_addition_response(row) for row in additions],
        automation=_automation_response(persona_id, automation),
        runtime=_runtime_response(persona_id, runtime),
        queue=[_queue_response(row) for row in queue],
        automationRuns=[_run_response(row) for row in runs],
        campaigns=[_campaign_response(row) for row in campaigns],
        auditEvents=[_audit_response(row) for row in audit_events],
    )


@router.get("", response_model=list[DashboardPersonaSummaryResponse])
def list_personas(current: UserState = Depends(get_current_user)) -> list[DashboardPersonaSummaryResponse]:
    ensure_dashboard_admin(current)
    personas = _people_table("personas").select("*").order("updated_at", desc=True).execute().data or []
    summaries: list[DashboardPersonaSummaryResponse] = []
    for persona in personas:
        persona_id = persona["id"]
        profile = _maybe_single(PEOPLE_SCHEMA, "persona_profiles", "persona_id", persona_id)
        automation = _maybe_single(MOMENTS_SCHEMA, "persona_automation_settings", "persona_id", persona_id)
        runtime = _maybe_single(MOMENTS_SCHEMA, "persona_runtime_state", "persona_id", persona_id)
        queue_rows = _moments_table("persona_content_queue").select("id,status,requires_approval").eq("persona_id", persona_id).execute().data or []
        summaries.append(_persona_summary_response(persona, profile, automation, runtime, queue_rows))
    return summaries


@router.post("", response_model=DashboardPersonaDetailResponse, status_code=status.HTTP_201_CREATED)
def create_persona(
    payload: DashboardPersonaCreatePayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaDetailResponse:
    ensure_dashboard_admin(current)
    now = _iso_now()
    created = (
        _people_table("personas")
        .insert(
            {
                "owner_user_id": current.id,
                "display_name": payload.displayName,
                "bio": payload.bio,
                "avatar_url": payload.avatarUrl,
                "is_public": payload.isPublic,
                "updated_at": now,
            }
        )
        .execute()
        .data
        or []
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create persona")
    persona_id = created[0]["id"]
    _people_table("persona_profiles").upsert(
        {
            "persona_id": persona_id,
            "full_name": payload.fullName,
            "social_handle": payload.socialHandle,
            "city_region": payload.cityRegion,
            "occupation": payload.occupation,
            "public_bio": payload.publicBio or payload.bio,
            "internal_bio": payload.internalBio,
            "lifecycle_status": "draft",
            "visibility": "public" if payload.isPublic else "private",
            "updated_at": now,
        },
        on_conflict="persona_id",
    ).execute()
    _moments_table("persona_automation_settings").upsert(
        {
            "persona_id": persona_id,
            "enabled": False,
            "autonomy_mode": "QUEUE_DRAFTS",
            "cadence_hours": 24,
            "spontaneity": 0.35,
            "novelty_rate": 0.15,
            "allowed_content_types": ["story", "post"],
            "boundaries": {},
            "campaign_override_policy": "require_brief",
            "require_manual_publish": True,
            "updated_at": now,
        },
        on_conflict="persona_id",
    ).execute()
    _upsert_runtime_state(persona_id, current_mode="idle", pending_approval_count=0)
    _log_audit_event(
        persona_id,
        event_type="persona.created",
        actor_type="admin",
        actor_id=current.id,
        summary="Persona created from dashboard",
        payload={"displayName": payload.displayName},
    )
    return _build_persona_detail(persona_id)


@router.get("/{persona_id}", response_model=DashboardPersonaDetailResponse)
def get_persona_detail(
    persona_id: str,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaDetailResponse:
    ensure_dashboard_admin(current)
    return _build_persona_detail(persona_id)


@router.patch("/{persona_id}", response_model=DashboardPersonaDetailResponse)
def update_persona(
    persona_id: str,
    payload: DashboardPersonaUpdatePayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaDetailResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    now = _iso_now()
    persona_patch: dict[str, Any] = {"updated_at": now}
    profile_patch: dict[str, Any] = {"persona_id": persona_id, "updated_at": now}
    if payload.displayName is not None:
        persona_patch["display_name"] = payload.displayName
    if payload.bio is not None:
        persona_patch["bio"] = payload.bio
    if payload.avatarUrl is not None:
        persona_patch["avatar_url"] = payload.avatarUrl
    if payload.isPublic is not None:
        persona_patch["is_public"] = payload.isPublic
    if len(persona_patch) > 1:
        _people_table("personas").update(persona_patch).eq("id", persona_id).execute()
    if payload.lifecycleStatus is not None:
        profile_patch["lifecycle_status"] = payload.lifecycleStatus
    if payload.visibility is not None:
        profile_patch["visibility"] = payload.visibility
    if payload.socialHandle is not None:
        profile_patch["social_handle"] = payload.socialHandle
    if payload.cityRegion is not None:
        profile_patch["city_region"] = payload.cityRegion
    if payload.occupation is not None:
        profile_patch["occupation"] = payload.occupation
    if len(profile_patch) > 2:
        _people_table("persona_profiles").upsert(profile_patch, on_conflict="persona_id").execute()
    _log_audit_event(
        persona_id,
        event_type="persona.updated",
        actor_type="admin",
        actor_id=current.id,
        summary="Persona identity updated",
        payload={
            "displayName": payload.displayName,
            "visibility": payload.visibility,
            "lifecycleStatus": payload.lifecycleStatus,
        },
    )
    return _build_persona_detail(persona_id)


@router.put("/{persona_id}/profile", response_model=DashboardPersonaProfileResponse)
def upsert_persona_profile(
    persona_id: str,
    payload: DashboardPersonaProfilePayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaProfileResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    now = _iso_now()
    row = {
        "persona_id": persona_id,
        "full_name": payload.fullName,
        "social_handle": payload.socialHandle,
        "age_range": payload.ageRange,
        "gender_expression": payload.genderExpression,
        "cultural_background": payload.culturalBackground,
        "languages": payload.languages,
        "city_region": payload.cityRegion,
        "occupation": payload.occupation,
        "public_bio": payload.publicBio,
        "internal_bio": payload.internalBio,
        "lifecycle_status": payload.lifecycleStatus,
        "visibility": payload.visibility,
        "brand_context": payload.brandContext,
        "updated_at": now,
    }
    _people_table("persona_profiles").upsert(row, on_conflict="persona_id").execute()
    _log_audit_event(
        persona_id,
        event_type="persona.profile.updated",
        actor_type="admin",
        actor_id=current.id,
        summary="Persona profile updated",
        payload={"fullName": payload.fullName, "socialHandle": payload.socialHandle},
    )
    return _profile_response(persona_id, _maybe_single(PEOPLE_SCHEMA, "persona_profiles", "persona_id", persona_id))


@router.put("/{persona_id}/personality", response_model=DashboardPersonaPersonalityResponse)
def upsert_persona_personality(
    persona_id: str,
    payload: DashboardPersonaPersonalityPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaPersonalityResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    now = _iso_now()
    row = {
        "persona_id": persona_id,
        "personality_summary": payload.personalitySummary,
        "dominant_traits": payload.dominantTraits,
        "secondary_traits": payload.secondaryTraits,
        "values": payload.values,
        "ambitions": payload.ambitions,
        "vulnerabilities": payload.vulnerabilities,
        "humor_style": payload.humorStyle,
        "social_energy": payload.socialEnergy,
        "confidence_level": payload.confidenceLevel,
        "communication_style": payload.communicationStyle,
        "emotional_range": payload.emotionalRange,
        "state_rules": payload.stateRules,
        "updated_at": now,
    }
    _people_table("persona_personality").upsert(row, on_conflict="persona_id").execute()
    _log_audit_event(
        persona_id,
        event_type="persona.personality.updated",
        actor_type="admin",
        actor_id=current.id,
        summary="Persona personality updated",
        payload={"dominantTraits": payload.dominantTraits},
    )
    return _personality_response(persona_id, _maybe_single(PEOPLE_SCHEMA, "persona_personality", "persona_id", persona_id))


@router.put("/{persona_id}/routine", response_model=DashboardPersonaRoutineResponse)
def upsert_persona_routine(
    persona_id: str,
    payload: DashboardPersonaRoutinePayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaRoutineResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    row = {
        "persona_id": persona_id,
        "wake_up_time": payload.wakeUpTime,
        "working_hours": payload.workingHours,
        "morning_rituals": payload.morningRituals,
        "exercise_habits": payload.exerciseHabits,
        "evening_patterns": payload.eveningPatterns,
        "weekend_behavior": payload.weekendBehavior,
        "posting_rhythm": payload.postingRhythm,
        "travel_frequency": payload.travelFrequency,
        "updated_at": _iso_now(),
    }
    _people_table("persona_routines").upsert(row, on_conflict="persona_id").execute()
    _log_audit_event(
        persona_id,
        event_type="persona.routine.updated",
        actor_type="admin",
        actor_id=current.id,
        summary="Persona routine updated",
        payload={"wakeUpTime": payload.wakeUpTime},
    )
    return _routine_response(persona_id, _maybe_single(PEOPLE_SCHEMA, "persona_routines", "persona_id", persona_id))


@router.put("/{persona_id}/interests", response_model=DashboardPersonaInterestsResponse)
def upsert_persona_interests(
    persona_id: str,
    payload: DashboardPersonaInterestsPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaInterestsResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    row = {
        "persona_id": persona_id,
        "strong_interests": payload.strongInterests,
        "occasional_interests": payload.occasionalInterests,
        "skills": payload.skills,
        "hobbies": payload.hobbies,
        "cultural_tastes": payload.culturalTastes,
        "wellness_habits": payload.wellnessHabits,
        "food_preferences": payload.foodPreferences,
        "travel_preferences": payload.travelPreferences,
        "shopping_behavior": payload.shoppingBehavior,
        "updated_at": _iso_now(),
    }
    _people_table("persona_interests").upsert(row, on_conflict="persona_id").execute()
    _log_audit_event(
        persona_id,
        event_type="persona.interests.updated",
        actor_type="admin",
        actor_id=current.id,
        summary="Persona interests updated",
        payload={"strongInterests": payload.strongInterests},
    )
    return _interests_response(persona_id, _maybe_single(PEOPLE_SCHEMA, "persona_interests", "persona_id", persona_id))


@router.post("/{persona_id}/locations", response_model=DashboardPersonaLocationResponse, status_code=status.HTTP_201_CREATED)
def add_persona_location(
    persona_id: str,
    payload: DashboardPersonaLocationPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaLocationResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    row = {
        "persona_id": persona_id,
        "name": payload.name,
        "tags": payload.tags,
        "tier": payload.tier,
        "reuse_weight": payload.reuseWeight,
        "cooldown_hours": payload.cooldownHours,
        "max_per_week": payload.maxPerWeek,
        "description": payload.description,
        "visual_notes": payload.visualNotes,
        "lighting_notes": payload.lightingNotes,
        "emotional_association": payload.emotionalAssociation,
    }
    created = _people_table("world_locations").insert(row).execute().data or []
    if not created:
        raise HTTPException(status_code=500, detail="Failed to add location")
    _log_audit_event(
        persona_id,
        event_type="persona.world.location.added",
        actor_type="admin",
        actor_id=current.id,
        summary=f"Added location '{payload.name}'",
        payload={"name": payload.name, "tier": payload.tier},
    )
    return _location_response(created[0])


@router.post("/{persona_id}/wardrobe", response_model=DashboardPersonaWardrobeResponse, status_code=status.HTTP_201_CREATED)
def add_persona_wardrobe(
    persona_id: str,
    payload: DashboardPersonaWardrobePayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaWardrobeResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    row = {
        "persona_id": persona_id,
        "category": payload.category,
        "name": payload.name,
        "tags": payload.tags,
        "tier": payload.tier,
        "reuse_weight": payload.reuseWeight,
        "season_tags": payload.seasonTags,
        "description": payload.description,
        "suitability_tags": payload.suitabilityTags,
        "signature_item": payload.signatureItem,
        "favorite_item": payload.favoriteItem,
    }
    created = _people_table("world_wardrobe_items").insert(row).execute().data or []
    if not created:
        raise HTTPException(status_code=500, detail="Failed to add wardrobe item")
    _log_audit_event(
        persona_id,
        event_type="persona.world.wardrobe.added",
        actor_type="admin",
        actor_id=current.id,
        summary=f"Added wardrobe item '{payload.name}'",
        payload={"name": payload.name, "category": payload.category},
    )
    return _wardrobe_response(created[0])


@router.post("/{persona_id}/outfits", response_model=DashboardPersonaOutfitResponse, status_code=status.HTTP_201_CREATED)
def add_persona_outfit(
    persona_id: str,
    payload: DashboardPersonaOutfitPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaOutfitResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    row = {
        "persona_id": persona_id,
        "name": payload.name,
        "description": payload.description,
        "wardrobe_item_ids": payload.wardrobeItemIds,
        "suitable_occasions": payload.suitableOccasions,
        "season_tags": payload.seasonTags,
        "mood_tags": payload.moodTags,
        "reference_image_url": payload.referenceImageUrl,
        "reuse_cooldown_hours": payload.reuseCooldownHours,
        "signature_look": payload.signatureLook,
        "updated_at": _iso_now(),
    }
    created = _people_table("persona_outfits").insert(row).execute().data or []
    if not created:
        raise HTTPException(status_code=500, detail="Failed to add outfit")
    _log_audit_event(
        persona_id,
        event_type="persona.world.outfit.added",
        actor_type="admin",
        actor_id=current.id,
        summary=f"Added outfit '{payload.name}'",
        payload={"name": payload.name},
    )
    return _outfit_response(created[0])


@router.post("/{persona_id}/home-spaces", response_model=DashboardPersonaHomeSpaceResponse, status_code=status.HTTP_201_CREATED)
def add_persona_home_space(
    persona_id: str,
    payload: DashboardPersonaHomeSpacePayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaHomeSpaceResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    created = (
        _people_table("persona_home_spaces")
        .insert(
            {
                "persona_id": persona_id,
                "name": payload.name,
                "description": payload.description,
                "room_type": payload.roomType,
                "visual_traits": payload.visualTraits,
                "lighting_notes": payload.lightingNotes,
                "signature_use_cases": payload.signatureUseCases,
                "updated_at": _iso_now(),
            }
        )
        .execute()
        .data
        or []
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to add home space")
    _log_audit_event(
        persona_id,
        event_type="persona.world.home_space.added",
        actor_type="admin",
        actor_id=current.id,
        summary=f"Added home space '{payload.name}'",
        payload={"name": payload.name, "roomType": payload.roomType},
    )
    return _home_space_response(created[0])


@router.post("/{persona_id}/objects", response_model=DashboardPersonaObjectResponse, status_code=status.HTTP_201_CREATED)
def add_persona_object(
    persona_id: str,
    payload: DashboardPersonaObjectPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaObjectResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    created = (
        _people_table("persona_objects")
        .insert(
            {
                "persona_id": persona_id,
                "name": payload.name,
                "description": payload.description,
                "object_type": payload.objectType,
                "visual_traits": payload.visualTraits,
                "emotional_role": payload.emotionalRole,
                "recurring_contexts": payload.recurringContexts,
                "updated_at": _iso_now(),
            }
        )
        .execute()
        .data
        or []
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to add object")
    _log_audit_event(
        persona_id,
        event_type="persona.world.object.added",
        actor_type="admin",
        actor_id=current.id,
        summary=f"Added object '{payload.name}'",
        payload={"name": payload.name, "objectType": payload.objectType},
    )
    return _object_response(created[0])


@router.post("/{persona_id}/relationships", response_model=DashboardPersonaRelationshipResponse, status_code=status.HTTP_201_CREATED)
def add_persona_relationship(
    persona_id: str,
    payload: DashboardPersonaRelationshipPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaRelationshipResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    created = (
        _people_table("persona_relationships")
        .insert(
            {
                "persona_id": persona_id,
                "name": payload.name,
                "relationship_type": payload.relationshipType,
                "summary": payload.summary,
                "visibility": payload.visibility,
                "emotional_tone": payload.emotionalTone,
                "recurring_contexts": payload.recurringContexts,
                "updated_at": _iso_now(),
            }
        )
        .execute()
        .data
        or []
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to add relationship")
    _log_audit_event(
        persona_id,
        event_type="persona.world.relationship.added",
        actor_type="admin",
        actor_id=current.id,
        summary=f"Added relationship '{payload.name}'",
        payload={"name": payload.name, "relationshipType": payload.relationshipType},
    )
    return _relationship_response(created[0])


@router.post("/{persona_id}/memories", response_model=DashboardPersonaMemoryResponse, status_code=status.HTTP_201_CREATED)
def add_persona_memory(
    persona_id: str,
    payload: DashboardPersonaMemoryPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaMemoryResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    row = {
        "persona_id": persona_id,
        "title": payload.title,
        "memory_type": payload.memoryType,
        "summary": payload.summary,
        "importance_score": payload.importanceScore,
        "occurred_at": payload.occurredAt,
        "updated_at": _iso_now(),
    }
    created = _people_table("persona_canonical_memories").insert(row).execute().data or []
    if not created:
        raise HTTPException(status_code=500, detail="Failed to add memory")
    _log_audit_event(
        persona_id,
        event_type="persona.memory.added",
        actor_type="admin",
        actor_id=current.id,
        summary=f"Added memory '{payload.title}'",
        payload={"title": payload.title, "memoryType": payload.memoryType},
    )
    return _memory_response(created[0])


@router.put("/{persona_id}/automation", response_model=DashboardPersonaAutomationSettingsResponse)
def upsert_persona_automation(
    persona_id: str,
    payload: DashboardPersonaAutomationPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaAutomationSettingsResponse:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    row = {
        "persona_id": persona_id,
        "enabled": payload.enabled,
        "autonomy_mode": payload.autonomyMode,
        "cadence_hours": payload.cadenceHours,
        "spontaneity": payload.spontaneity,
        "novelty_rate": payload.noveltyRate,
        "allowed_content_types": payload.allowedContentTypes,
        "boundaries": payload.boundaries,
        "campaign_override_policy": payload.campaignOverridePolicy,
        "require_manual_publish": payload.requireManualPublish,
        "updated_at": _iso_now(),
    }
    _moments_table("persona_automation_settings").upsert(row, on_conflict="persona_id").execute()
    if not payload.enabled:
        _upsert_runtime_state(persona_id, current_mode="paused", pause_reason="Automation disabled by admin")
    _log_audit_event(
        persona_id,
        event_type="persona.automation.updated",
        actor_type="admin",
        actor_id=current.id,
        summary="Automation settings updated",
        payload={
            "enabled": payload.enabled,
            "autonomyMode": payload.autonomyMode,
            "cadenceHours": payload.cadenceHours,
        },
    )
    return _automation_response(persona_id, _maybe_single(MOMENTS_SCHEMA, "persona_automation_settings", "persona_id", persona_id))


async def _run_persona_automation_impl(
    persona_id: str,
    *,
    prompt: str | None = None,
    campaign_id: str | None = None,
    campaign_name: str | None = None,
    target_date: str | None = None,
    force: bool = False,
    trigger_source: str = "manual_dashboard_run",
) -> DashboardPersonaAutomationRunResponse:
    persona_context = _persona_generation_context(persona_id)
    settings = persona_context.get("automation") or {}
    recent_queue = (
        persona_context.get("recentQueue")
        if isinstance(persona_context.get("recentQueue"), list)
        else []
    )
    business_context = _dashboard_business_context()
    if not settings.get("enabled") and not force:
        raise HTTPException(status_code=400, detail="Automation is disabled for this persona")

    run_row = (
        _moments_table("persona_automation_runs")
        .insert(
            {
                "persona_id": persona_id,
                "trigger_source": trigger_source,
                "status": "ready",
                "context_summary": "Dashboard-triggered automation run",
                "input_prompt": prompt,
                "output_payload": {},
            }
        )
        .execute()
        .data
        or []
    )
    if not run_row:
        raise HTTPException(status_code=500, detail="Failed to create automation run")
    run_id = run_row[0]["id"]
    _log_audit_event(
        persona_id,
        event_type="persona.automation.run.started",
        actor_type="system" if trigger_source == "scheduled_worker" else "admin",
        actor_id=trigger_source,
        summary="Persona automation run started",
        payload={"runId": run_id, "triggerSource": trigger_source},
    )
    now = datetime.now(timezone.utc)
    user_message = f"""CONTEXT: persona_automation

TARGET DATE: {target_date or now.date().isoformat()}
OPTIONAL HUMAN PROMPT: {prompt or ""}
CAMPAIGN OVERRIDE:
{json.dumps({"campaignId": campaign_id, "campaignName": campaign_name}, indent=2)}

PERSONA:
{json.dumps(persona_context, indent=2, default=str)}

DASHBOARD BUSINESS CONTEXT:
{json.dumps(business_context, indent=2, default=str)}

Return a JSON object with this exact shape:
{PERSONA_AUTOMATION_SCHEMA}"""

    try:
        result = await call_claude(PERSONA_AUTOMATION_CONTEXT, user_message, max_tokens=5000)
        parsed = _strip_json(result["text"])
    except Exception as exc:
        _moments_table("persona_automation_runs").update(
            {
                "status": "failed",
                "blocked_reason": str(exc),
                "completed_at": _iso_now(),
            }
        ).eq("id", run_id).execute()
        _upsert_runtime_state(persona_id, current_mode="error", pause_reason="Automation run failed", last_error=str(exc))
        _log_audit_event(
            persona_id,
            event_type="persona.automation.run.failed",
            actor_type="system",
            actor_id=trigger_source,
            summary="Persona automation run failed",
            payload={"runId": run_id, "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail=f"Persona automation failed: {exc}") from exc

    status_value = str(parsed.get("status") or "ready")
    summary = str(parsed.get("summary") or "").strip()
    pause_reason = parsed.get("pauseReason")
    queue_items = parsed.get("queueItems") if isinstance(parsed.get("queueItems"), list) else []
    world_additions = parsed.get("worldAdditions") if isinstance(parsed.get("worldAdditions"), list) else []
    queue_items, guardrail_warnings, inferred_world_additions = _apply_queue_guardrails(
        queue_items=queue_items,
        settings=settings,
        recent_queue=recent_queue,
        persona_context=persona_context,
        now=now,
    )
    if guardrail_warnings:
        parsed["guardrailWarnings"] = guardrail_warnings
    if inferred_world_additions:
        parsed["inferredWorldAdditions"] = inferred_world_additions
    if not queue_items and status_value == "ready":
        status_value = "blocked"
        pause_reason = "Guardrails filtered every proposed draft"
        summary = summary or "No drafts passed persona guardrails."

    created_queue_rows: list[dict[str, Any]] = []
    for item in queue_items:
        if not isinstance(item, dict):
            continue
        created = (
            _moments_table("persona_content_queue")
            .insert(
                {
                    "persona_id": persona_id,
                    "run_id": run_id,
                    "title": item.get("title") or "Untitled draft",
                    "content_type": str(item.get("contentType") or "story").lower(),
                    "status": "draft",
                    "scheduled_for": item.get("scheduledFor"),
                    "caption": item.get("caption"),
                    "visual_direction": item.get("visualDirection"),
                    "continuity_reason": item.get("continuityReason"),
                    "novelty": bool(item.get("novelty")),
                    "queue_payload": {
                        "socialGoal": item.get("socialGoal"),
                        "prompt": item.get("prompt"),
                        "locationName": item.get("locationName"),
                        "outfitName": item.get("outfitName"),
                        "homeSpaceName": item.get("homeSpaceName"),
                        "relationshipNames": _coerce_list(item.get("relationshipNames")),
                    },
                    "requires_approval": bool(item.get("requiresApproval", True)),
                    "campaign_id": item.get("campaignId"),
                    "updated_at": _iso_now(),
                }
            )
            .execute()
            .data
            or []
        )
        if created:
            created_queue_rows.append(_sync_queue_item_to_moments_draft(created[0]))

    for addition in _dedupe_world_additions(world_additions + inferred_world_additions):
        if not isinstance(addition, dict):
            continue
        _people_table("persona_world_addition_requests").insert(
            {
                "persona_id": persona_id,
                "source_kind": "automation_run",
                "source_id": run_id,
                "item_type": addition.get("itemType") or "unknown",
                "proposed_name": addition.get("proposedName"),
                "proposed_payload": {
                    "summary": addition.get("summary"),
                    **_coerce_dict(addition.get("payload")),
                },
                "status": "suggested",
                "updated_at": _iso_now(),
            }
        ).execute()

    created_queue_rows, auto_published_count = _auto_publish_queue_rows(
        persona_id=persona_id,
        rows=created_queue_rows,
        settings=settings,
        trigger_source=trigger_source,
    )

    next_run_at = now + timedelta(hours=int(settings.get("cadence_hours") or 24))
    queue_rows_for_runtime = (
        _moments_table("persona_content_queue")
        .select("id,status,requires_approval")
        .eq("persona_id", persona_id)
        .execute()
        .data
        or []
    )
    _, approval_count = _queue_status_counts(queue_rows_for_runtime)
    open_queue_count = _count_open_queue_rows(queue_rows_for_runtime)
    if auto_published_count:
        parsed["autoPublishedCount"] = auto_published_count
    _moments_table("persona_automation_runs").update(
        {
            "status": status_value,
            "context_summary": summary,
            "output_payload": parsed,
            "blocked_reason": pause_reason if status_value != "ready" else None,
            "completed_at": _iso_now(),
        }
    ).eq("id", run_id).execute()
    _log_audit_event(
        persona_id,
        event_type="persona.automation.run.completed",
        actor_type="system" if trigger_source == "scheduled_worker" else "admin",
        actor_id=trigger_source,
        summary="Persona automation run completed",
        payload={
            "runId": run_id,
            "status": status_value,
            "queuedDrafts": len(created_queue_rows),
            "guardrailWarnings": guardrail_warnings,
            "autoPublishedCount": auto_published_count,
        },
    )
    _upsert_runtime_state(
        persona_id,
        current_mode="queued" if open_queue_count else ("idle" if status_value == "ready" else "paused"),
        pause_reason=str(pause_reason) if pause_reason else None,
        pending_approval_count=approval_count,
        active_campaign_context={
            "campaignId": campaign_id,
            "campaignName": campaign_name,
        },
        last_error=None,
        last_run_at=_iso_now(),
        next_run_at=next_run_at.isoformat(),
    )
    run = _maybe_single(MOMENTS_SCHEMA, "persona_automation_runs", "id", run_id)
    return _run_response(run or run_row[0])


@router.post("/{persona_id}/automation/run", response_model=DashboardPersonaAutomationRunResponse)
async def run_persona_automation(
    persona_id: str,
    payload: DashboardPersonaRunPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaAutomationRunResponse:
    ensure_dashboard_admin(current)
    return await _run_persona_automation_impl(
        persona_id,
        prompt=payload.prompt,
        campaign_id=payload.campaignId,
        campaign_name=payload.campaignName,
        target_date=payload.targetDate,
        force=payload.force,
        trigger_source="manual_dashboard_run",
    )


@router.get("/{persona_id}/queue", response_model=list[DashboardPersonaQueueItemResponse])
def list_persona_queue(
    persona_id: str,
    current: UserState = Depends(get_current_user),
) -> list[DashboardPersonaQueueItemResponse]:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    rows = _moments_table("persona_content_queue").select("*").eq("persona_id", persona_id).order("created_at", desc=True).execute().data or []
    rows = _sync_queue_rows_to_moments(rows)
    return [_queue_response(row) for row in rows]


@router.get("/{persona_id}/world-additions", response_model=list[DashboardPersonaWorldAdditionResponse])
def list_world_additions(
    persona_id: str,
    current: UserState = Depends(get_current_user),
) -> list[DashboardPersonaWorldAdditionResponse]:
    ensure_dashboard_admin(current)
    _require_persona(persona_id)
    rows = _people_table("persona_world_addition_requests").select("*").eq("persona_id", persona_id).order("created_at", desc=True).execute().data or []
    return [_world_addition_response(row) for row in rows]


@router.post("/world-additions/{addition_id}/actions", response_model=DashboardPersonaWorldAdditionResponse)
def act_on_world_addition(
    addition_id: str,
    payload: DashboardPersonaWorldAdditionActionPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaWorldAdditionResponse:
    ensure_dashboard_admin(current)
    rows = (
        _people_table("persona_world_addition_requests")
        .select("*")
        .eq("id", addition_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="World addition not found")
    existing = rows[0]
    patch = {
        "status": "approved" if payload.action == "approve" else payload.action,
        "reviewer_user_id": current.id,
        "review_note": payload.note,
        "updated_at": _iso_now(),
    }
    if payload.action == "approve":
        _promote_world_addition(existing)
    _people_table("persona_world_addition_requests").update(patch).eq("id", addition_id).execute()
    _log_audit_event(
        existing["persona_id"],
        event_type="persona.world_addition.reviewed",
        actor_type="admin",
        actor_id=current.id,
        summary=f"World addition {payload.action}",
        payload={
            "additionId": addition_id,
            "itemType": existing.get("item_type"),
            "proposedName": existing.get("proposed_name"),
            "action": payload.action,
        },
    )
    updated = (
        _people_table("persona_world_addition_requests")
        .select("*")
        .eq("id", addition_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return _world_addition_response(updated[0])


@router.post("/queue/{queue_id}/actions", response_model=DashboardPersonaQueueItemResponse)
def act_on_queue_item(
    queue_id: str,
    payload: DashboardPersonaQueueActionPayload,
    current: UserState = Depends(get_current_user),
) -> DashboardPersonaQueueItemResponse:
    ensure_dashboard_admin(current)
    rows = _moments_table("persona_content_queue").select("*").eq("id", queue_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Queue item not found")
    row = rows[0]
    status_map = {
        "approve": "approved",
        "reject": "rejected",
        "publish": "published",
        "hold": "held",
        "retry_generation": str(row.get("status") or "approved"),
        "regenerate": str(row.get("status") or "approved"),
    }
    patch: dict[str, Any] = {
        "status": status_map[payload.action],
        "updated_at": _iso_now(),
    }
    if payload.action == "approve":
        row = _enqueue_generation_for_queue_item(row)
        patch["approved_by_user_id"] = current.id
        patch["approved_at"] = _iso_now()
        patch["queue_payload"] = _coerce_dict(row.get("queue_payload"))
        patch["rejection_reason"] = None
    elif payload.action == "reject":
        patch["rejection_reason"] = payload.note
    elif payload.action == "publish":
        row = _enqueue_generation_for_queue_item(row)
        queue_payload = _coerce_dict(row.get("queue_payload"))
        social_post_id = _publish_queue_item_to_dashboard_social(row)
        patch["queue_payload"] = {
            **queue_payload,
            "socialPostId": social_post_id,
        }
        patch["approved_by_user_id"] = current.id
        patch["approved_at"] = row.get("approved_at") or _iso_now()
        patch["published_at"] = _iso_now()
        patch["rejection_reason"] = None
    elif payload.action == "hold":
        patch["rejection_reason"] = payload.note
    elif payload.action == "retry_generation":
        row = _enqueue_generation_for_queue_item(row)
        queue_payload = _coerce_dict(row.get("queue_payload"))
        queue_payload.pop("generationError", None)
        queue_payload["retryRequestedAt"] = _iso_now()
        patch["queue_payload"] = queue_payload
        patch["rejection_reason"] = None
    elif payload.action == "regenerate":
        row = _regenerate_queue_item(row)
        queue_payload = _coerce_dict(row.get("queue_payload"))
        patch["queue_payload"] = queue_payload
        patch["rejection_reason"] = None
    persona_id = row["persona_id"]
    _moments_table("persona_content_queue").update(patch).eq("id", queue_id).execute()
    _log_audit_event(
        persona_id,
        event_type="persona.queue.action",
        actor_type="admin",
        actor_id=current.id,
        summary=f"Queue item {payload.action}",
        payload={
            "queueId": queue_id,
            "action": payload.action,
            "title": row.get("title"),
            "status": status_map[payload.action],
        },
    )
    queue_rows = _moments_table("persona_content_queue").select("id,status,requires_approval").eq("persona_id", persona_id).execute().data or []
    _, approval_count = _queue_status_counts(queue_rows)
    runtime = _maybe_single(MOMENTS_SCHEMA, "persona_runtime_state", "persona_id", persona_id)
    _upsert_runtime_state(
        persona_id,
        current_mode=(runtime or {}).get("current_mode") or "queued",
        pause_reason=(runtime or {}).get("pause_reason"),
        pending_approval_count=approval_count,
        active_campaign_context=_coerce_dict((runtime or {}).get("active_campaign_context")),
        last_error=(runtime or {}).get("last_error"),
        last_run_at=iso_or_none((runtime or {}).get("last_run_at")),
        next_run_at=iso_or_none((runtime or {}).get("next_run_at")),
    )
    updated = _moments_table("persona_content_queue").select("*").eq("id", queue_id).limit(1).execute().data or []
    return _queue_response(updated[0])


async def process_due_persona_automation_runs(*, limit: int = 10) -> int:
    settings_rows = (
        _moments_table("persona_automation_settings")
        .select("*")
        .eq("enabled", True)
        .order("updated_at", desc=False)
        .limit(limit * 3)
        .execute()
        .data
        or []
    )
    if not settings_rows:
        return 0

    now = datetime.now(timezone.utc)
    processed = 0
    for settings in settings_rows:
        if processed >= limit:
            break
        persona_id = settings.get("persona_id")
        if not persona_id:
            continue
        runtime = _maybe_single(MOMENTS_SCHEMA, "persona_runtime_state", "persona_id", persona_id) or {}
        current_mode = str(runtime.get("current_mode") or "idle")
        if current_mode in {"paused", "error"}:
            continue
        due_at = _parse_iso_datetime(runtime.get("next_run_at"))
        if due_at is not None and due_at > now:
            continue

        queue_rows = (
            _moments_table("persona_content_queue")
            .select("id,status,requires_approval")
            .eq("persona_id", persona_id)
            .execute()
            .data
            or []
        )
        open_queue_count = _count_open_queue_rows(queue_rows)
        if open_queue_count:
            _, approval_count = _queue_status_counts(queue_rows)
            _upsert_runtime_state(
                persona_id,
                current_mode="queued",
                pause_reason="Waiting for draft review before the next automated run",
                pending_approval_count=approval_count,
                active_campaign_context=_coerce_dict(runtime.get("active_campaign_context")),
                last_error=None,
                last_run_at=iso_or_none(runtime.get("last_run_at")),
                next_run_at=iso_or_none(runtime.get("next_run_at")) or now.isoformat(),
            )
            continue

        try:
            await _run_persona_automation_impl(
                persona_id,
                force=True,
                trigger_source="scheduled_worker",
            )
            processed += 1
        except Exception:
            logger.exception("Scheduled persona automation run failed for %s", persona_id)
    return processed
