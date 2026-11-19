from __future__ import annotations
"""Generation routing for dispatching create requests to the worker service."""

import asyncio
import json

import base64
import io
import os
import re
from datetime import datetime, timedelta
import logging
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from PIL import Image

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from postgrest.exceptions import APIError
from tenacity import retry, stop_after_attempt, wait_exponential

from prompting.registry import ensure_default_prompt_registry, resolve_prompt_task_row
from prompting.ui_catalog import resolve_generation_ui_catalog

from .analytics import generation_context
from .auth import get_current_user, get_optional_current_user
from .content import (
    COLLECTIONS_CACHE_CONTROL,
    COLLECTIONS_OWNER_METADATA_KEY,
    _generate_public_collection_variants,
    _refresh_collection_cover,
    _ensure_collections_belong,
    ensure_unsaved_collection,
    _get_collections_bucket,
    _normalize_storage_path,
    _resolve_collection_image_variants,
    _user_storage_prefix,
)
from .generation_state import (
    GenerationJob,
    add_result,
    create_job,
    delete_job,
    get_job,
    mark_completed,
    mark_failed,
    mark_started,
    to_response,
    update_progress,
)
from .notifications import publish_app_notification
from .schemas import (
    CancelGenerationPayload,
    CreateGenerationPayload,
    CreateGenerationResponse,
    CreateImageEditPayload,
    CreateMotionGenerationPayload,
    GenerationModelPayload,
    GenerationUiCatalogResponse,
    GenerationJobEvent,
    GenerationResultPayload,
    GenerationUploadPayload,
    ImageEditFeedbackRequest,
    ImageEditFeedbackResponse,
    ImageEditInstructionPayload,
    ItemPayload,
    UserState,
)
from .supabase_client import get_client

router = APIRouter(prefix="/generations", tags=["generations"])

logger = logging.getLogger(__name__)
_MOTION_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()

QUALITY_FORWARD_MAP = {
    "1080p": "1k",
    "2K": "2k",
    "4K": "4k",
}

GENERATION_START_FAILURE_MESSAGE = "Unable to start generation right now. Please try again."
GENERATION_JOB_FAILURE_MESSAGE = "Generation failed. Please try again."
IMAGE_EDIT_START_FAILURE_MESSAGE = "Unable to start image edit right now. Please try again."
IMAGE_EDIT_JOB_FAILURE_MESSAGE = "Image edit failed. Please try again."
DEFAULT_GENERATION_STALE_TIMEOUT_SECONDS = 10 * 60
MOTION_START_FAILURE_MESSAGE = "Unable to start motion generation right now. Please try again."
SEGMIND_SEEDANCE_URL = "https://api.segmind.com/v1/seedance-2.0"
MOTION_REQUIRED_PLAN = "Pro"
MOTION_DEMO_VIDEO_PATH_ENV = "GEMZY_MOTION_DEMO_VIDEO_PATH"
MOTION_DEFAULT_VIDEO_CONTENT_TYPE = "video/mp4"
MOTION_MAX_VIDEO_BYTES = 200 * 1024 * 1024
DEFAULT_EDIT_MODE_TRIAL_EDITS = 2
BASE_TASK_TYPE_ON_MODEL = "on-model"
BASE_TASK_TYPE_PURE_JEWELRY = "pure-jewelry"
SERVER_MANAGED_PRESET_STYLE_KEYS = (
    "creative_direction",
    "creative_exclusions",
    "creative_variation_lanes",
    "creative_object_territory",
)
LEGACY_PRESET_SIGNATURES: dict[str, tuple[tuple[str, dict[str, str]], ...]] = {
    "on-model": (
        ("Autumn Golden Hour", {"background": "Warm Interior", "image_style": "Golden Hour"}),
        ("Christmas Tree Glow", {"background": "Evening Glow", "lighting": "Soft Wrap"}),
        ("Snowy Pine Glow", {"background": "Forest Shade", "lighting": "Scene Light"}),
        ("Midnight Glam", {"background": "Dark Studio", "image_style": "High Contrast"}),
    ),
    "pure-jewelry": (
        ("Gothic Velvet", {"style_type": "pure-studio", "surface": "Velvet"}),
        ("Pumpkin Harvest", {"style_type": "object-world", "object-territory": "Open", "relationship": "Resting On"}),
        ("Holiday Gift Box", {"style_type": "object-world", "object-territory": "Luxury Objects", "relationship": "Inside"}),
        ("Confetti Flatlay", {"style_type": "arranged", "arrangement-style": "Organic Scatter", "color-palette": "Rich & Dark"}),
    ),
}
FALLBACK_IMAGE_EDIT_HERO_PROMPT = (
    "Generate this exact same image. Change nothing except the specific modifications stated below. "
    "Every element of the original image - the background, the scene, the lighting, the model, the pose, "
    "the outfit, the skin, the framing, the sharpness - is preserved exactly as it appears. "
    "If anything other than the stated changes is different from the original, the image is not ready."
)

FALLBACK_IMAGE_EDIT_PURE_JEWELRY_ADDENDUM = (
    "The source was created as pure jewelry, so do not add or alter a model/person unless explicitly requested."
)

FALLBACK_IMAGE_EDIT_REQUESTED_EDITS_HEADING = "Requested edits:"

IMAGE_EDIT_OPTIONS: dict[str, dict[str, str]] = {
    "jewelry_smaller": {
        "label": "Make the jewelry a bit smaller",
        "category": "jewelry",
        "prompt": "Reduce the overall scale of the jewelry by approximately 10% - uniformly across all dimensions, preserving the exact proportions of the original piece. Width, height, and depth must all reduce by the same proportional amount. The jewelry's design, material, color, gemstones, metal tone, surface finish, and position on the body all remain identical to the original. Do not stretch, squash, narrow, or alter any individual dimension independently. The only difference between the new jewelry and the original is uniform scale. If the size reduction exceeds 15%, or if any property of the jewelry changes other than its scale, the image is not ready.",
    },
    "jewelry_bigger": {
        "label": "Make the jewelry a bit bigger",
        "category": "jewelry",
        "prompt": "Increase the overall scale of the jewelry by approximately 10% - uniformly across all dimensions, preserving the exact proportions of the original piece. Width, height, and depth must all increase by the same proportional amount. The jewelry's design, material, color, gemstones, metal tone, surface finish, and position on the body all remain identical to the original. Do not stretch, expand, widen, or alter any individual dimension independently. The only difference between the new jewelry and the original is uniform scale. If the size increase exceeds 15%, or if any property of the jewelry changes other than its scale, the image is not ready.",
    },
    "enhance_shine": {
        "label": "Enhance shine & reflections",
        "category": "jewelry",
        "prompt": "Enhance the metal and gemstone surfaces of the jewelry - increase specular highlights, deepen reflectivity, and add realistic polish and depth to the material surfaces. The enhancement must look photographically real - no artificial sparkle, no starburst effects, no graphic overlays. The jewelry should look like it was lit more precisely, not digitally altered.",
    },
    "material_aluminum": {
        "label": "Aluminum",
        "description": "Change the material of jewelry",
        "parentId": "jewelry_material",
        "parentLabel": "Jewelry material",
        "category": "jewelry",
        "exclusiveGroup": "jewelry_material",
        "prompt": (
            "Change the jewelry material to brushed aluminum while preserving the exact design, gemstones, scale, placement, and overall composition."
        ),
    },
    "material_gold": {
        "label": "Gold",
        "description": "Change the material of jewelry",
        "parentId": "jewelry_material",
        "parentLabel": "Jewelry material",
        "category": "jewelry",
        "exclusiveGroup": "jewelry_material",
        "prompt": (
            "Change the jewelry material to polished gold while preserving the exact design, gemstones, scale, placement, and overall composition."
        ),
    },
    "material_silver": {
        "label": "Silver",
        "description": "Change the material of jewelry",
        "parentId": "jewelry_material",
        "parentLabel": "Jewelry material",
        "category": "jewelry",
        "exclusiveGroup": "jewelry_material",
        "prompt": (
            "Change the jewelry material to polished silver while preserving the exact design, gemstones, scale, placement, and overall composition."
        ),
    },
    "material_bronze": {
        "label": "Bronze",
        "description": "Change the material of jewelry",
        "parentId": "jewelry_material",
        "parentLabel": "Jewelry material",
        "category": "jewelry",
        "exclusiveGroup": "jewelry_material",
        "prompt": (
            "Change the jewelry material to bronze while preserving the exact design, gemstones, scale, placement, and overall composition."
        ),
    },    "zoom_in": {
        "label": "Zoom in on the jewelry",
        "category": "framing",
        "prompt": "Crop the frame approximately 15% closer toward the jewelry, keeping the jewelry sharp, fully visible, and centered within the new frame. The jewelry must remain completely unobstructed.",
    },
    "zoom_out": {
        "label": "Zoom out for full context",
        "category": "framing",
        "prompt": "Pull the camera back so the jewelry and subject appear approximately 15% smaller within the frame — more of the existing scene, surface, and surroundings become visible around them. The jewelry remains sharp and fully visible. Do not invent new content beyond the original frame edges; only redistribute the existing scene composition so the subject occupies less of the frame than before.",
    },
    "camera_low_angle": {
        "label": "Low angle",
        "category": "framing",
        "prompt": "Reframe the image from a subtle low angle perspective - the camera shifts slightly downward, looking up toward the subject. The shift is gentle and editorial, not extreme. The jewelry remains fully visible and sharp.",
    },
    "camera_high_angle": {
        "label": "High angle",
        "category": "framing",
        "prompt": "Reframe the image from a subtle high angle perspective - the camera shifts slightly upward, looking down toward the subject. The shift is gentle and editorial, not extreme. The jewelry remains fully visible and sharp.",
    },
    "camera_rotate_left": {
        "label": "Rotate Slight Left",
        "category": "framing",
        "prompt": "Rotate the composition slightly to the left - a subtle, natural tilt of no more than 5 degrees. The jewelry remains sharp and fully visible.",
    },
    "lighting_soft_diffused": {
        "label": "Soft Diffused",
        "category": "lighting_photo",
        "prompt": "Apply soft, diffused lighting across the scene - light wraps from multiple directions, shadow edges become gradual and gentle, no harsh contrast. The jewelry is fully revealed under the soft light.",
    },
    "lighting_side_rim": {
        "label": "Side Rim",
        "category": "lighting_photo",
        "prompt": "Add a side rim light along one edge of the subject - a narrow, precise light source that creates a bright separation line along the jewelry, the jaw, or the shoulder depending on the composition. The rim light is subtle and editorial - it adds depth and separation without overpowering the existing lighting.",
    },
    "lighting_top_down": {
        "label": "Top Down",
        "category": "lighting_photo",
        "prompt": "Shift the primary light source to a top-down position - light falls from directly above, illuminating the top surfaces of the jewelry and the subject while allowing the sides to fall into natural shadow. The jewelry's top face and any gemstones catch the overhead light directly.",
    },
    "gradient_background": {
        "label": "Add subtle gradient to background",
        "category": "lighting_photo",
        "prompt": "If the background is a solid or near-solid color: introduce a subtle, natural gradient across that color - lighter at one edge, slightly deeper at the opposite edge, as if studio light is wrapping softly around the scene. The gradient must feel like natural light behavior, not a graphic effect. The color itself does not change - only its tonal depth. If the background is an environmental scene - a location, a textured surface, a real place - do not add a gradient. Instead, deepen the existing atmospheric depth of the scene by subtly darkening the corners and edges while keeping the center bright and sharp.",
    },
    "model_pose": {
        "label": "Change the model's pose",
        "category": "model",
        "prompt": "Change the model's pose to a clearly different position than the original - a different arm placement, a different head angle, a different body orientation, or a combination of these. The new pose must be visibly and immediately different from the original to a viewer comparing the two images. The pose remains natural and editorial - never stiff or performed. The jewelry must remain fully visible and in its original position on the body. The model's identity, outfit, and all other elements remain unchanged. If the pose appears unchanged or only barely different from the original, the image is not ready.",
    },
    "outfit_color": {
        "label": "Change the outfit color",
        "category": "model",
        "prompt": "Change the color of the outfit to a different complementary tone - keep the same fabric, the same silhouette, and the same garment entirely. Only the color changes.",
    },
    "upscale_image": {
        "label": "Upscale the image",
        "category": "upscale_sharpen",
        "prompt": "Upscale the image to higher resolution while preserving all natural detail - skin texture, fabric texture, jewelry surface, and background all retain their original quality without over-sharpening or introducing artificial detail. The image must look like a higher resolution version of the original, not a processed version of it.",
    },
    "sharpen_image": {
        "label": "Sharpen the image",
        "category": "upscale_sharpen",
        "prompt": "Sharpen the fine details of the image - the edges of the jewelry, the texture of the fabric, the clarity of the skin - while avoiding over-sharpening artifacts, halos, or unnatural crispness. The sharpening should feel like better focus, not digital processing.",
    },
}


def _edit_option_definitions_from_definition(definition: dict[str, Any]) -> dict[str, dict[str, str]]:
    definitions: dict[str, dict[str, str]] = {}
    raw_options = definition.get("editOptions") or []
    if not isinstance(raw_options, list):
        return definitions
    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            continue
        option_id = str(raw_option.get("id") or "").strip()
        label = str(raw_option.get("label") or "").strip()
        category = str(raw_option.get("category") or "").strip()
        prompt = str(raw_option.get("prompt") or "").strip()
        if not option_id or not label or not category:
            continue
        definitions[option_id] = {
            "label": label,
            "category": category,
            "prompt": prompt,
        }
    return definitions


def _resolve_image_edit_definition(
    payload: CreateImageEditPayload,
) -> dict[str, Any]:
    task_type = _image_edit_task_type(payload)
    edit_style = _style_with_task_type(payload.source.style, task_type)
    prompt_payload = {"request": {"style": edit_style}}
    try:
        matched_row = resolve_prompt_task_row(
            task_type,
            prompt_payload,
            client=get_client(),
            allow_defaults_fallback=True,
        )
    except Exception:
        return {}

    return matched_row.get("version", {}).get("definition") or {}


def _resolve_image_edit_option_definitions(
    payload: CreateImageEditPayload,
) -> dict[str, dict[str, str]]:
    definition = _resolve_image_edit_definition(payload)
    resolved = _edit_option_definitions_from_definition(definition)
    return resolved or IMAGE_EDIT_OPTIONS


def _resolve_image_edit_prompt_config(definition: dict[str, Any] | None) -> dict[str, str]:
    source = definition if isinstance(definition, dict) else {}
    return {
        "hero": str(source.get("hero") or FALLBACK_IMAGE_EDIT_HERO_PROMPT),
        "pure_jewelry_addendum": str(
            source.get("pure_jewelry_addendum") or FALLBACK_IMAGE_EDIT_PURE_JEWELRY_ADDENDUM
        ),
        "requested_edits_heading": str(
            source.get("requested_edits_heading") or FALLBACK_IMAGE_EDIT_REQUESTED_EDITS_HEADING
        ),
    }


def _style_with_task_type(
    style: dict[str, str] | None,
    task_type: str,
) -> dict[str, str]:
    next_style = dict(style or {})
    next_style["task_type"] = task_type
    return next_style


def _base_task_type_from_style(style: dict[str, str] | None) -> str | None:
    task_type = (style or {}).get("task_type", "").strip()
    if task_type.startswith(BASE_TASK_TYPE_PURE_JEWELRY):
        return BASE_TASK_TYPE_PURE_JEWELRY
    if task_type.startswith(BASE_TASK_TYPE_ON_MODEL):
        return BASE_TASK_TYPE_ON_MODEL
    return None


def _generation_task_type(payload: CreateGenerationPayload) -> str:
    from_style = _base_task_type_from_style(payload.style)
    if from_style:
        return from_style
    return (
        BASE_TASK_TYPE_PURE_JEWELRY
        if payload.model.slug == "pure-jewelry"
        else BASE_TASK_TYPE_ON_MODEL
    )


def _normalize_legacy_preset_value(value: object) -> str:
    """Treat UI labels and the slug IDs sent by older clients as equivalent."""

    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().casefold())


def _legacy_creation_preset_name(task_type: str, style: dict[str, str]) -> str | None:
    """Identify presets selected by clients that predate the presetId field."""

    matches: list[str] = []
    for name, signature in LEGACY_PRESET_SIGNATURES.get(task_type, ()):
        if all(
            _normalize_legacy_preset_value(style.get(key))
            == _normalize_legacy_preset_value(expected)
            for key, expected in signature.items()
        ):
            matches.append(name)
    return matches[0] if len(matches) == 1 else None


def _resolve_generation_style(payload: CreateGenerationPayload) -> dict[str, str]:
    """Apply server-owned preset prompt fields to the client-editable style."""

    task_type = _generation_task_type(payload)
    style = _style_with_task_type(payload.style, task_type)
    for key in SERVER_MANAGED_PRESET_STYLE_KEYS:
        style.pop(key, None)

    preset_id = (payload.presetId or "").strip()
    if not preset_id:
        legacy_name = _legacy_creation_preset_name(task_type, style)
        if not legacy_name:
            return style
        try:
            rows = (
                get_client()
                .table("creation_look_presets")
                .select("id,task_key,style")
                .eq("task_key", task_type)
                .eq("name", legacy_name)
                .eq("is_active", True)
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception:
            logger.warning(
                "Unable to resolve legacy creation preset",
                extra={"task_type": task_type, "preset_name": legacy_name},
                exc_info=True,
            )
            return style
        if not rows:
            return style
        preset_style = rows[0].get("style")
        if isinstance(preset_style, dict):
            for key in SERVER_MANAGED_PRESET_STYLE_KEYS:
                value = preset_style.get(key)
                if isinstance(value, str) and value.strip():
                    style[key] = value.strip()
        return style

    try:
        UUID(preset_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid creation preset identifier.",
        ) from exc

    rows = (
        get_client()
        .table("creation_look_presets")
        .select("id,task_key,style")
        .eq("id", preset_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This creation preset is no longer available.",
        )

    preset = rows[0]
    if preset.get("task_key") != task_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Creation preset does not match this generation type.",
        )

    preset_style = preset.get("style")
    if isinstance(preset_style, dict):
        for key in SERVER_MANAGED_PRESET_STYLE_KEYS:
            value = preset_style.get(key)
            if isinstance(value, str) and value.strip():
                style[key] = value.strip()

    return style


def _image_edit_source_base_task_type(payload: CreateImageEditPayload) -> str:
    from_style = _base_task_type_from_style(payload.source.style)
    if from_style:
        return from_style
    if (
        payload.source.modelSlug == "pure-jewelry"
        or payload.source.modelName == "Pure Jewelry"
    ):
        return BASE_TASK_TYPE_PURE_JEWELRY
    return BASE_TASK_TYPE_ON_MODEL


def _image_edit_task_type(payload: CreateImageEditPayload) -> str:
    return f"{_image_edit_source_base_task_type(payload)}/edited"


def _image_edit_model_name(payload: CreateImageEditPayload) -> str:
    if payload.source.modelName:
        return payload.source.modelName
    return (
        "Pure Jewelry"
        if _image_edit_source_base_task_type(payload) == BASE_TASK_TYPE_PURE_JEWELRY
        else "On Model"
    )


def _image_edit_model_id(payload: CreateImageEditPayload) -> str | None:
    if payload.source.modelId:
        return payload.source.modelId
    if _image_edit_source_base_task_type(payload) == BASE_TASK_TYPE_PURE_JEWELRY:
        return "pure-jewelry-model"
    return None


def _image_edit_model_image_uri(payload: CreateImageEditPayload) -> str | None:
    source_image_uri = payload.source.url or payload.source.previewUrl
    if _image_edit_source_base_task_type(payload) == BASE_TASK_TYPE_PURE_JEWELRY:
        return source_image_uri
    return payload.source.modelImageUri or source_image_uri


def _image_edit_model_image_base64(payload: CreateImageEditPayload) -> str | None:
    if _image_edit_source_base_task_type(payload) == BASE_TASK_TYPE_PURE_JEWELRY:
        return None
    return payload.source.modelImageBase64


def _dims_payload(dims: Any) -> dict[str, int] | None:
    if dims is None:
        return None
    if hasattr(dims, "model_dump"):
        data = dims.model_dump()
    elif isinstance(dims, dict):
        data = dims
    else:
        return None
    try:
        return {"w": int(data["w"]), "h": int(data["h"])}
    except (KeyError, TypeError, ValueError):
        return None


def _publish_generation_completed_notification(job: GenerationJob) -> None:
    params = {"jobId": job.id}
    if job.unsaved_collection_id:
        params["collectionId"] = job.unsaved_collection_id

    publish_app_notification(
        category="personal",
        kind="generation_completed",
        title="Generation completed",
        body="Tap to view your new looks",
        entity_key=f"generation:{job.id}",
        target_user_id=job.user_id,
        action={
            "pathname": "/generating",
            "params": params,
        },
    )


def _publish_generation_failed_notification(job: GenerationJob) -> None:
    publish_app_notification(
        category="personal",
        kind="generation_failed",
        title="Generation failed",
        body="Tap to review the failed generation",
        entity_key=f"generation-failed:{job.id}",
        target_user_id=job.user_id,
        action={
            "pathname": "/generating",
            "params": {"jobId": job.id},
        },
    )


def _image_edit_action_params(job: GenerationJob) -> dict[str, str]:
    params = {"editJobId": job.id}
    source_key = (
        job.edit_source.get("sourceKey")
        if isinstance(job.edit_source, dict)
        else None
    )
    if isinstance(source_key, str) and source_key:
        params["sourceKey"] = source_key
    return params


def _publish_image_edit_completed_notification(job: GenerationJob) -> None:
    publish_app_notification(
        category="personal",
        kind="image_edit_completed",
        title="Your edit is ready",
        body="Tap to review your edited image",
        entity_key=f"image-edit:{job.id}",
        target_user_id=job.user_id,
        action={
            "pathname": "/review-edit",
            "params": _image_edit_action_params(job),
        },
    )


def _publish_image_edit_failed_notification(job: GenerationJob) -> None:
    publish_app_notification(
        category="personal",
        kind="image_edit_failed",
        title="Edit failed",
        body="Tap to review the failed edit",
        entity_key=f"image-edit-failed:{job.id}",
        target_user_id=job.user_id,
        action={
            "pathname": "/review-edit",
            "params": _image_edit_action_params(job),
        },
    )


def _normalize_credit_value(value: object | None) -> int:
    """Return an integer credit balance."""

    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 0


def _normalize_edit_mode_trial_edits_remaining(value: object | None) -> int:
    try:
        remaining = int(value) if value is not None else DEFAULT_EDIT_MODE_TRIAL_EDITS
    except (TypeError, ValueError):
        remaining = DEFAULT_EDIT_MODE_TRIAL_EDITS
    return max(0, min(DEFAULT_EDIT_MODE_TRIAL_EDITS, remaining))


def _adjust_edit_mode_trial_edits(
    user_id: str,
    delta: int,
    *,
    max_attempts: int = 5,
) -> int | None:
    """Atomically consume or restore an Edit Mode trial use."""

    if delta == 0:
        resp = (
            get_client()
            .table("profiles")
            .select("edit_mode_trial_edits_remaining")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        return _normalize_edit_mode_trial_edits_remaining(
            rows[0].get("edit_mode_trial_edits_remaining")
        )

    sb = get_client()
    for _ in range(max_attempts):
        resp = (
            sb.table("profiles")
            .select("edit_mode_trial_edits_remaining")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load your Edit Mode trial balance right now.",
            )

        current = _normalize_edit_mode_trial_edits_remaining(
            rows[0].get("edit_mode_trial_edits_remaining")
        )
        if delta < 0 and current <= 0:
            return None
        next_remaining = max(
            0,
            min(DEFAULT_EDIT_MODE_TRIAL_EDITS, current + delta),
        )
        if next_remaining == current:
            return current

        update_resp = (
            sb.table("profiles")
            .update({"edit_mode_trial_edits_remaining": next_remaining}, count="exact")
            .eq("id", user_id)
            .eq("edit_mode_trial_edits_remaining", current)
            .execute()
        )
        if (update_resp.count or 0) == 1:
            return next_remaining

    logger.warning(
        "Failed to update Edit Mode trial balance for user %s after %s attempts",
        user_id,
        max_attempts,
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Your Edit Mode trial balance changed. Please try again.",
    )


def _adjust_profile_credits(user_id: str, delta: int, *, max_attempts: int = 5) -> int | None:
    """Atomically adjust trial, monthly, then purchased credits."""

    sb = get_client()
    if delta == 0:
        resp = sb.table("profiles").select("trial_credits,credits,purchased_credits").eq("id", user_id).limit(1).execute()
        rows = resp.data or []
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load your credit balance right now.",
            )
        return sum(
            _normalize_credit_value(rows[0].get(key))
            for key in ("trial_credits", "credits", "purchased_credits")
        )

    for _ in range(max_attempts):
        resp = sb.table("profiles").select("trial_credits,credits,purchased_credits").eq("id", user_id).limit(1).execute()
        rows = resp.data or []
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load your credit balance right now.",
            )

        current_trial = _normalize_credit_value(rows[0].get("trial_credits"))
        current_monthly = _normalize_credit_value(rows[0].get("credits"))
        current_purchased = _normalize_credit_value(rows[0].get("purchased_credits"))
        current_total = current_trial + current_monthly + current_purchased
        if delta < 0 and current_total < -delta:
            return None

        if delta < 0:
            spend = -delta
            spend_trial = min(current_trial, spend)
            spend_after_trial = spend - spend_trial
            spend_monthly = min(current_monthly, spend_after_trial)
            spend_purchased = spend_after_trial - spend_monthly
            new_trial = current_trial - spend_trial
            new_monthly = current_monthly - spend_monthly
            new_purchased = current_purchased - spend_purchased
        else:
            new_trial = current_trial
            new_monthly = current_monthly + delta
            new_purchased = current_purchased

        update_resp = (
            sb.table("profiles")
            .update(
                {
                    "trial_credits": new_trial,
                    "credits": new_monthly,
                    "purchased_credits": new_purchased,
                },
                count="exact",
            )
            .eq("id", user_id)
            .eq("trial_credits", current_trial)
            .eq("credits", current_monthly)
            .eq("purchased_credits", current_purchased)
            .execute()
        )
        if (update_resp.count or 0) == 1:
            return new_trial + new_monthly + new_purchased

    logger.warning("Failed to update credits for user %s after %s attempts", user_id, max_attempts)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Your credits changed while starting this generation. Please try again.",
    )


def _completed_credit_cost(job: GenerationJob) -> int:
    reserved = max(0, int(job.reserved_credit_cost or 0))
    if reserved <= 0:
        return 0

    completed = max(job.completed_looks, len(job.results))
    if completed <= 0:
        return 0

    completed = min(completed, job.total_looks)
    per_look = _credit_cost_per_look(job)
    if per_look <= 0:
        if job.total_looks <= 1:
            return reserved
        return min(reserved, (reserved * completed) // job.total_looks)
    return min(reserved, per_look * completed)


def _credit_cost_per_look(job: GenerationJob) -> int:
    per_look = max(0, int(job.credit_cost_per_look or 0))
    if per_look > 0:
        return per_look
    reserved = max(0, int(job.reserved_credit_cost or 0))
    if reserved <= 0:
        return 0
    return max(1, reserved // max(1, job.total_looks))


def _apply_generation_credit_refund(
    job: GenerationJob,
    target_refunded_credits: int,
) -> tuple[int, int]:
    """Atomically refund up to a cumulative target for a generation job."""

    response = get_client().rpc(
        "refund_generation_credits",
        {
            "p_job_id": job.id,
            "p_user_id": job.user_id,
            "p_target_refunded_credits": max(0, int(target_refunded_credits)),
        },
    ).execute()
    rows = response.data or []
    row = rows[0] if isinstance(rows, list) and rows else rows
    if not isinstance(row, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to refund generation credits right now.",
        )
    return (
        _normalize_credit_value(row.get("remaining_credits")),
        _normalize_credit_value(row.get("refunded_credits")),
    )


def _refund_unfinished_reserved_credits(job: GenerationJob) -> int | None:
    if _is_guest_user_id(job.user_id):
        return None

    with job.lifecycle_lock:
        reserved = max(0, int(job.reserved_credit_cost or 0))
        target_refunded = max(0, reserved - _completed_credit_cost(job))
        already_refunded = max(0, int(job.refunded_credit_cost or 0))
        if target_refunded <= already_refunded:
            return _adjust_profile_credits(job.user_id, 0)

        try:
            remaining, persisted_refunded = _apply_generation_credit_refund(
                job,
                target_refunded,
            )
        except Exception:
            logger.exception(
                "Failed to refund unfinished generation credits up to %s for job %s",
                target_refunded,
                job.id,
            )
            return None

        job.refunded_credit_cost = max(
            job.refunded_credit_cost,
            persisted_refunded,
        )
        return remaining


def _expire_stale_generation(job: GenerationJob) -> int | None:
    """Fail an active job after it stops receiving worker events."""

    if job.status not in {"queued", "in_progress"}:
        return None
    try:
        timeout_seconds = max(
            60.0,
            float(
                os.getenv(
                    "GENERATION_STALE_TIMEOUT_SECONDS",
                    str(DEFAULT_GENERATION_STALE_TIMEOUT_SECONDS),
                )
            ),
        )
    except ValueError:
        timeout_seconds = float(DEFAULT_GENERATION_STALE_TIMEOUT_SECONDS)
    if (datetime.utcnow() - job.updated_at).total_seconds() < timeout_seconds:
        return None

    with job.lifecycle_lock:
        if job.status not in {"queued", "in_progress"}:
            return None
        logger.warning(
            "Expiring stale generation job %s after %.0fs without an update",
            job.id,
            timeout_seconds,
        )
        mark_failed(job, "Generation timed out. Please try again.")
        remaining_credits = _refund_unfinished_reserved_credits(job)

    if not _is_guest_user_id(job.user_id):
        try:
            if job.job_type == "image_edit":
                _publish_image_edit_failed_notification(job)
            else:
                _publish_generation_failed_notification(job)
        except Exception:
            logger.exception("Failed to publish stale-job notification for %s", job.id)
    return remaining_credits


def _refund_cancelled_reserved_looks(job: GenerationJob, looks: int = 1) -> int | None:
    if _is_guest_user_id(job.user_id):
        return None

    with job.lifecycle_lock:
        requested_looks = max(1, int(looks or 1))
        completed = min(job.total_looks, max(job.completed_looks, len(job.results)))
        unfinished = max(0, job.total_looks - completed)
        cancellable = min(requested_looks, unfinished)
        if cancellable <= 0:
            return _adjust_profile_credits(job.user_id, 0)

        reserved = max(0, int(job.reserved_credit_cost or 0))
        already_refunded = max(0, int(job.refunded_credit_cost or 0))
        per_look = _credit_cost_per_look(job)
        completed_cost = _completed_credit_cost(job)
        available_reserved = max(0, reserved - already_refunded - completed_cost)
        refundable = min(available_reserved, cancellable * per_look)

        if refundable > 0:
            remaining, persisted_refunded = _apply_generation_credit_refund(
                job,
                already_refunded + refundable,
            )
            job.refunded_credit_cost = max(
                job.refunded_credit_cost,
                persisted_refunded,
            )
        else:
            remaining = _adjust_profile_credits(job.user_id, 0)

        job.total_looks = max(completed, job.total_looks - cancellable)
        job.completed_looks = min(job.total_looks, job.completed_looks)
        if job.total_looks <= 0:
            mark_failed(job, "Generation cancelled.")
        elif job.completed_looks >= job.total_looks and job.completed_looks > 0:
            mark_completed(job)
        else:
            job.progress = min(1.0, job.completed_looks / job.total_looks) if job.total_looks else 1.0
            job.touch()
        return remaining


def _resolve_generation_url(override: str | None) -> str:
    """Return the target generation endpoint."""

    configured_base = os.getenv("GENERATION_SERVER_URL", "").strip()
    candidate = override.strip() if override else configured_base
    if not candidate:
        candidate = (override or "").strip()

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation server is not configured",
        )

    path = os.getenv("GENERATION_SERVER_ENDPOINT", "/generate").strip()
    if not path:
        path = "/generate"

    normalized_base = candidate.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"

    if path == "/":
        return normalized_base
    return f"{normalized_base}{path}"


def _build_callback_url(job_id: str) -> str:
    base = os.getenv("GENERATION_CALLBACK_URL", "").strip()
    if not base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation callback URL is not configured",
        )

    return f"{base.rstrip('/')}/generations/{job_id}/events"


def _build_generation_payload(
    payload: CreateGenerationPayload,
    user: UserState,
    job_id: str,
    callback_url: str,
) -> dict[str, Any]:
    """Shape the payload forwarded to the downstream generation service."""

    request_payload = payload.model_dump(exclude={"generationServerUrl", "presetId"})
    request_payload["quality"] = QUALITY_FORWARD_MAP.get(payload.quality, payload.quality)
    return {
        "job": {
            "id": job_id,
            "userId": user.id,
            "callbackUrl": callback_url,
            "looks": payload.looks,
        },
        "user": user.model_dump(),
        "request": request_payload,
    }


def _decode_generation_image(result: GenerationResultPayload) -> bytes:
    """Return binary image data from a generation result payload."""

    candidate: str | None = None
    if result.base64:
        candidate = result.base64
    elif result.url and result.url.startswith("data:"):
        candidate = result.url

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generation result missing image data",
        )

    if "," in candidate:
        candidate = candidate.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(candidate, validate=True)
    except Exception as exc:  # pragma: no cover - malformed worker payload
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid generation image payload",
        ) from exc

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generation result is not a valid image",
        ) from exc

    return image_bytes


def _is_missing_model_columns(error: APIError) -> bool:
    message = (getattr(error, "message", None) or str(error)).lower()
    return "model" in message and "column" in message


def _build_result_metadata_payload(
    job: GenerationJob,
    *,
    image_size: int | None = None,
    content_type: str = "image/png",
    media_type: str = "image",
) -> dict[str, Any]:
    metadata_payload: dict[str, Any] = {
        "contentType": content_type,
        "mediaType": media_type,
        "source": job.job_type if job.job_type != "generation" else "generation",
        "jobId": job.id,
        "durationMs": int(
            (datetime.utcnow() - job.created_at).total_seconds() * 1000
        ),
    }
    if image_size is not None:
        metadata_payload["size"] = image_size
    if job.model_id:
        metadata_payload["modelId"] = job.model_id
    if job.model_name:
        metadata_payload["modelName"] = job.model_name
    if job.aspect:
        metadata_payload["aspect"] = job.aspect
    if job.dims:
        metadata_payload["dims"] = job.dims
    if job.quality:
        metadata_payload["quality"] = job.quality
    if job.style:
        metadata_payload["style"] = job.style
        task_type = job.style.get("task_type")
        if task_type:
            metadata_payload["taskType"] = task_type
    if job.job_type == "image_edit":
        metadata_payload["editSource"] = job.edit_source
        metadata_payload["editInstructions"] = job.edit_instructions
    return metadata_payload


MAX_IMAGE_DIMENSION = 2048
MAX_BASE64_SIZE_CHARS = 20 * 1024 * 1024  # ~15MB base64 encoded


def _process_upload(upload: GenerationUploadPayload) -> None:
    """Validate and intelligently resize over-sized generation uploads."""
    if not upload.base64:
        return

    # 1. Reject extremely large payloads outright
    if len(upload.base64) > MAX_BASE64_SIZE_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Image '{upload.name or 'upload'}' is too large. "
                "Please upload an image smaller than 15MB."
            ),
        )

    # 2. Extract base64 payload
    prefix = ""
    b64_data = upload.base64
    if "," in b64_data:
        prefix, b64_data = b64_data.split(",", 1)
        prefix += ","

    # 3. Decode & analyze image dimensions/size
    try:
        image_bytes = base64.b64decode(b64_data)
        img = Image.open(io.BytesIO(image_bytes))
    except (Exception, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image format for '{upload.name or 'upload'}'."
        ) from exc

    needs_resize = False
    if img.width > MAX_IMAGE_DIMENSION or img.height > MAX_IMAGE_DIMENSION:
        img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
        needs_resize = True
        
    if len(image_bytes) > 5 * 1024 * 1024:
        needs_resize = True

    # 4. Re-encode if we made changes
    if needs_resize:
        buffer = io.BytesIO()
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            
        img.save(buffer, format="JPEG", quality=85)
        new_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        upload.base64 = prefix + new_b64
        upload.width = img.width
        upload.height = img.height
        upload.fileSize = len(buffer.getvalue())
        upload.mimeType = "image/jpeg"


def _resolve_image_edit_storage_path(
    payload: CreateImageEditPayload,
) -> str | None:
    for candidate in (
        payload.source.storagePath,
        payload.source.url,
        payload.source.previewUrl,
    ):
        normalized = _normalize_storage_path(candidate)
        if normalized:
            return normalized
    return None


def _hydrate_image_edit_source_upload_from_storage(
    payload: CreateImageEditPayload,
    *,
    user: UserState,
) -> None:
    """Prefer a trusted storage-backed source image for collection edits.

    Collection-backed edit requests may arrive with stale signed URLs or a
    client-produced base64 payload that no longer represents the original
    image. When we can resolve a user-owned storage object, reload the source
    bytes directly from storage before running upload validation.
    """

    storage_path = _resolve_image_edit_storage_path(payload)
    if not storage_path:
        return

    prefix = f"{_user_storage_prefix(user.id)}/"
    if not storage_path.startswith(prefix):
        logger.warning(
            "Ignoring image edit storage path outside user prefix",
            extra={"user_id": user.id, "storage_path": storage_path},
        )
        return

    try:
        blob = _get_collections_bucket().blob(storage_path)
        image_bytes = blob.download_as_bytes()
    except Exception:
        logger.exception(
            "Failed to hydrate image edit source from storage",
            extra={"user_id": user.id, "storage_path": storage_path},
        )
        return

    payload.sourceImage.base64 = base64.b64encode(image_bytes).decode("utf-8")

    content_type = str(getattr(blob, "content_type", "") or "").strip()
    if content_type.lower().startswith("image/"):
        payload.sourceImage.mimeType = content_type

    blob_size = getattr(blob, "size", None)
    if isinstance(blob_size, int) and blob_size > 0:
        payload.sourceImage.fileSize = blob_size


def _persist_generation_result(
    job: GenerationJob, incoming: GenerationResultPayload
) -> GenerationResultPayload:
    """Upload a generation result to storage and persist it in the database."""

    image_bytes = _decode_generation_image(incoming)

    storage_path: str | None = None
    preview_url: str | None = None
    view_url: str | None = None
    upload_error: Exception | None = None

    try:
        bucket = _get_collections_bucket()

        result_source = "image_edit" if job.job_type == "image_edit" else "generation"
        storage_segment = "image-edits" if job.job_type == "image_edit" else "generations"
        storage_prefix = f"{_user_storage_prefix(job.user_id)}/{storage_segment}/{job.id}"
        storage_name = f"{storage_prefix}/{uuid4().hex}.png"
        blob = bucket.blob(storage_name)

        metadata = {
            "appUserId": job.user_id,
            "source": result_source,
            "jobId": job.id,
        }
        if COLLECTIONS_OWNER_METADATA_KEY and COLLECTIONS_OWNER_METADATA_KEY != "appUserId":
            metadata[COLLECTIONS_OWNER_METADATA_KEY] = job.user_id
        if job.model_id:
            metadata["modelId"] = job.model_id
        if job.model_name:
            metadata["modelName"] = job.model_name
        if job.aspect:
            metadata["aspect"] = job.aspect
        if job.quality:
            metadata["quality"] = job.quality
        if job.style:
            task_type = job.style.get("task_type")
            if task_type:
                metadata["taskType"] = task_type
            metadata["style"] = json.dumps(job.style)
        if job.job_type == "image_edit":
            metadata["editSource"] = json.dumps(job.edit_source or {})
            metadata["editInstructions"] = json.dumps(job.edit_instructions or [])

        blob.metadata = metadata
        if COLLECTIONS_CACHE_CONTROL:
            blob.cache_control = COLLECTIONS_CACHE_CONTROL
        blob.upload_from_string(image_bytes, content_type="image/png")

        storage_path = _normalize_storage_path(storage_name) or storage_name

        # FTUE stores preview URIs locally so signed originals are not durable
        # enough: they turn into blank cards after their signature expires.
        # Build the public variants before shaping the callback result so the
        # client receives a stable preview URL from the start.
        _generate_public_collection_variants(storage_path, "image/png")

        # Generate short-lived signed preview/full URLs for immediate viewing
        preview_url, view_url = _resolve_collection_image_variants(
            None,
            storage_path,
            include_signed=True,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime storage env
        upload_error = exc
        storage_path = None
        view_url = None
        logger.exception("Failed to upload generation result for job %s", job.id)

    collection_id: str | None = None
    item_id: str | None = None
    created_at: str | None = None

    if storage_path and _is_guest_user_id(job.user_id):
        collection_id = None
    elif storage_path:
        sb = get_client()
        try:
            collection_id = job.unsaved_collection_id or ensure_unsaved_collection(job.user_id)
        except HTTPException:  # pragma: no cover - Supabase failure
            logger.exception("Failed to prepare Draft collection for job %s", job.id)
            collection_id = None
        else:
            job.unsaved_collection_id = collection_id

        if collection_id:
            metadata_payload = _build_result_metadata_payload(
                job,
                image_size=len(image_bytes),
            )

            record_payload: dict[str, Any] = {
                "collection_id": collection_id,
                "user_id": job.user_id,
                "external_id": storage_path,    # canonical key (GCS path)
                "image_url": storage_path,      # store path; resolve to signed URL on read
                "metadata": metadata_payload,
                "model_id": job.model_id,
                "model_name": job.model_name,
                "is_new": True,
            }

            try:
                # Supabase Python: no .select() chaining after insert
                resp = sb.table("collection_items").insert(
                    record_payload, returning="representation"
                ).execute()
                inserted = resp.data or []
            except APIError as exc:  # pragma: no cover - optional migration guard
                if _is_missing_model_columns(exc):
                    logger.warning(
                        "collection_items missing model columns; inserting without model fields."
                    )
                    fallback_payload = dict(record_payload)
                    fallback_payload.pop("model_id", None)
                    fallback_payload.pop("model_name", None)
                    resp = sb.table("collection_items").insert(
                        fallback_payload, returning="representation"
                    ).execute()
                    inserted = resp.data or []
                else:
                    logger.exception(
                        "Failed to store generation result metadata for job %s", job.id
                    )
                    inserted = []
                    collection_id = None
            except Exception:  # pragma: no cover - Supabase transport failure
                logger.exception(
                    "Unexpected error storing generation result metadata for job %s", job.id
                )
                inserted = []
                collection_id = None
            else:
                if inserted:
                    record = inserted[0] if isinstance(inserted[0], dict) else {}
                    item_id = record.get("id")
                    created_at = record.get("created_at")
                    _refresh_collection_cover(collection_id, job.user_id)


    if not view_url:
        candidate: str | None = None
        if isinstance(incoming.url, str) and incoming.url.strip():
            trimmed = incoming.url.strip()
            lowered = trimmed.lower()
            if lowered.startswith(("http://", "https://", "data:")):
                candidate = trimmed
        view_url = candidate
        preview_url = preview_url or candidate

    created_iso = (
        created_at
        if isinstance(created_at, str)
        else datetime.utcnow().replace(microsecond=0).isoformat()
    )

    base64_payload = None if view_url else incoming.base64
    if upload_error and base64_payload is None and incoming.base64:
        base64_payload = incoming.base64

    return GenerationResultPayload(
        url=view_url,
        previewUrl=preview_url,
        base64=base64_payload,
        storagePath=storage_path,
        collectionId=collection_id,
        collectionItemId=item_id,
        modelId=job.model_id,
        modelName=job.model_name,
        createdAt=created_iso,
        metadata=_build_result_metadata_payload(job, image_size=len(image_bytes)),
    )


async def _persist_motion_result(
    job: GenerationJob, incoming: GenerationResultPayload
) -> GenerationResultPayload:
    """Upload a generated motion video to storage and persist its DB record."""

    video_bytes, content_type, provider_url = await _load_motion_video_bytes(incoming)
    if len(video_bytes) > MOTION_MAX_VIDEO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Motion video is too large to store",
        )

    normalized_content_type = content_type.split(";", 1)[0].strip() or MOTION_DEFAULT_VIDEO_CONTENT_TYPE
    if not normalized_content_type.startswith("video/"):
        normalized_content_type = MOTION_DEFAULT_VIDEO_CONTENT_TYPE

    bucket = _get_collections_bucket()
    storage_prefix = f"{_user_storage_prefix(job.user_id)}/motion/{job.id}"
    storage_name = f"{storage_prefix}/{uuid4().hex}{_motion_video_extension(normalized_content_type)}"
    blob = bucket.blob(storage_name)

    metadata = {
        "appUserId": job.user_id,
        "source": "motion",
        "mediaType": "video",
        "contentType": normalized_content_type,
        "jobId": job.id,
    }
    if COLLECTIONS_OWNER_METADATA_KEY and COLLECTIONS_OWNER_METADATA_KEY != "appUserId":
        metadata[COLLECTIONS_OWNER_METADATA_KEY] = job.user_id
    if job.model_id:
        metadata["modelId"] = job.model_id
    if job.model_name:
        metadata["modelName"] = job.model_name
    if job.aspect:
        metadata["aspect"] = job.aspect
    if job.quality:
        metadata["quality"] = job.quality
    if job.style:
        metadata["style"] = json.dumps(job.style)
        task_type = job.style.get("task_type")
        if task_type:
            metadata["taskType"] = task_type

    blob.metadata = metadata
    if COLLECTIONS_CACHE_CONTROL:
        blob.cache_control = COLLECTIONS_CACHE_CONTROL
    blob.upload_from_string(video_bytes, content_type=normalized_content_type)

    storage_path = _normalize_storage_path(storage_name) or storage_name
    preview_url, view_url = _resolve_collection_image_variants(
        None,
        storage_path,
        include_signed=True,
    )
    if not view_url or not view_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to generate signed URL for motion video",
        )

    collection_id = job.unsaved_collection_id or ensure_unsaved_collection(job.user_id)
    job.unsaved_collection_id = collection_id

    metadata_payload = _build_result_metadata_payload(
        job,
        image_size=len(video_bytes),
        content_type=normalized_content_type,
        media_type="video",
    )
    metadata_payload.update(incoming.metadata or {})
    metadata_payload.update(
        {
            "source": "motion",
            "mediaType": "video",
            "contentType": normalized_content_type,
            "storagePath": storage_path,
        }
    )
    if incoming.previewUrl:
        metadata_payload["previewUrl"] = incoming.previewUrl
        metadata_payload["previewUri"] = incoming.previewUrl
    if provider_url:
        metadata_payload["providerUrl"] = provider_url

    record_payload: dict[str, Any] = {
        "collection_id": collection_id,
        "user_id": job.user_id,
        "external_id": storage_path,
        "image_url": storage_path,
        "metadata": metadata_payload,
        "model_id": job.model_id,
        "model_name": job.model_name,
        "is_new": True,
    }

    try:
        resp = get_client().table("collection_items").insert(
            record_payload, returning="representation"
        ).execute()
        inserted = resp.data or []
    except APIError as exc:
        if not _is_missing_model_columns(exc):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to store motion video metadata",
            ) from exc
        fallback_payload = dict(record_payload)
        fallback_payload.pop("model_id", None)
        fallback_payload.pop("model_name", None)
        resp = get_client().table("collection_items").insert(
            fallback_payload, returning="representation"
        ).execute()
        inserted = resp.data or []
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to store motion video metadata",
        ) from exc

    record = inserted[0] if inserted and isinstance(inserted[0], dict) else {}
    created_at = record.get("created_at")
    created_iso = (
        created_at
        if isinstance(created_at, str)
        else datetime.utcnow().replace(microsecond=0).isoformat()
    )
    response_preview_url = (
        incoming.previewUrl
        or _coerce_str(metadata_payload.get("previewUrl"))
        or preview_url
        or view_url
    )

    return GenerationResultPayload(
        url=view_url,
        previewUrl=response_preview_url,
        mediaType="video",
        contentType=normalized_content_type,
        storagePath=storage_path,
        collectionId=collection_id,
        collectionItemId=record.get("id"),
        modelId=job.model_id,
        modelName=job.model_name,
        createdAt=created_iso,
        metadata=metadata_payload,
    )

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _forward_generation_request(
    url: str, payload: dict[str, Any]
) -> CreateGenerationResponse:
    # Requests contain one or more base64 images and may traverse a tunnel in
    # local/staging environments. Keep this aligned with the Moments caller so
    # a slow upload does not fail before the worker can enqueue the job.
    timeout = float(os.getenv("GENERATION_SERVER_TIMEOUT", "120"))
    headers: dict[str, str] = {}
    shared_secret = os.getenv("GENERATION_SHARED_SECRET", "").strip()
    if shared_secret:
        headers["X-Generation-Secret"] = shared_secret

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:  # pragma: no cover - network errors handled at runtime
        logger.warning(
            "Failed dispatching generation request: url=%s timeout=%ss "
            "error_type=%s error=%s",
            url,
            timeout,
            type(exc).__name__,
            str(exc)[:500],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to reach generation server",
        ) from exc

    if response.status_code >= 400:
        logger.warning(
            "Generation server returned %s for %s: %s",
            response.status_code,
            url,
            response.text[:1000] if response.text else "<empty>",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=GENERATION_START_FAILURE_MESSAGE,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid response from generation server",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid response from generation server",
        )

    try:
        return CreateGenerationResponse(**data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Generation server response validation failed",
        ) from exc



from .rate_limit import client_ip, limiter, LIMIT_generation_create

COST_PER_LOOK = {
    "1080p": 4,
    "2K": 5,
    "4K": 7,
}
MOTION_CREDITS_PER_VIDEO = {
    5: 25,
    8: 40,
}


def _motion_credit_cost(duration: int, video_count: int) -> int:
    return MOTION_CREDITS_PER_VIDEO[duration] * video_count


GUEST_USER_ID_PREFIX = "guest:"
GUEST_ALLOWED_TASK_TYPES = {BASE_TASK_TYPE_ON_MODEL, BASE_TASK_TYPE_PURE_JEWELRY}
GUEST_GENERATION_LOOKS = int(os.getenv("GUEST_GENERATION_LOOKS", "2"))
GUEST_GENERATION_QUALITY = os.getenv("GUEST_GENERATION_QUALITY", "1080p")
GUEST_GENERATION_MAX_UPLOADS = int(os.getenv("GUEST_GENERATION_MAX_UPLOADS", "1"))
GUEST_GENERATION_MAX_UPLOAD_BYTES = int(
    os.getenv("GUEST_GENERATION_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024))
)
GUEST_GENERATION_WINDOW_SECONDS = int(
    os.getenv("GUEST_GENERATION_WINDOW_SECONDS", str(24 * 60 * 60))
)
GUEST_GENERATION_MAX_PER_WINDOW = int(
    os.getenv("GUEST_GENERATION_MAX_PER_WINDOW", "8")
)
_GUEST_GENERATION_ATTEMPTS: dict[str, list[datetime]] = {}
GUEST_ALLOWED_1080P_DIMS = {
    "1:1": (1080, 1080),
    "2:3": (720, 1080),
    "3:2": (1620, 1080),
    "3:4": (810, 1080),
    "4:3": (1440, 1080),
    "4:5": (864, 1080),
    "9:16": (608, 1080),
    "16:9": (1920, 1080),
    "21:9": (2520, 1080),
}


def _is_guest_user_id(user_id: str | None) -> bool:
    return isinstance(user_id, str) and user_id.startswith(GUEST_USER_ID_PREFIX)


def _is_guest_generation_request(payload: CreateGenerationPayload) -> bool:
    return (payload.style or {}).get("onboarding_guest") == "true"


def _is_guest_generation_retry(payload: CreateGenerationPayload) -> bool:
    return (payload.style or {}).get("onboarding_guest_retry") == "true"


def _guest_request_key(request: Request) -> str:
    return client_ip(request) or "unknown"


def _check_guest_generation_quota(request: Request) -> None:
    if GUEST_GENERATION_MAX_PER_WINDOW <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest generation is disabled.",
        )

    key = _guest_request_key(request)
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=GUEST_GENERATION_WINDOW_SECONDS)
    attempts = [
        attempt
        for attempt in _GUEST_GENERATION_ATTEMPTS.get(key, [])
        if attempt >= window_start
    ]
    if len(attempts) >= GUEST_GENERATION_MAX_PER_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Guest generation limit reached. Please sign up to keep creating.",
        )

    attempts.append(now)
    _GUEST_GENERATION_ATTEMPTS[key] = attempts


def _validate_guest_generation_payload(
    request: Request,
    payload: CreateGenerationPayload,
) -> None:
    task_type = _generation_task_type(payload)
    if task_type not in GUEST_ALLOWED_TASK_TYPES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This guest generation mode is not available.",
        )
    if payload.collectionId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Collections require sign up.",
        )
    if payload.generationServerUrl:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Custom generation targets are not available for guest generation.",
        )
    if payload.promptOverrides:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Prompt overrides require sign up.",
        )
    is_retry = _is_guest_generation_retry(payload)
    has_valid_look_count = (
        1 <= payload.looks <= GUEST_GENERATION_LOOKS
        if is_retry
        else payload.looks == GUEST_GENERATION_LOOKS
    )
    if not has_valid_look_count:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign up to customize image count.",
        )
    if payload.quality != GUEST_GENERATION_QUALITY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign up to customize resolution.",
        )
    expected_dims = GUEST_ALLOWED_1080P_DIMS.get(payload.aspect)
    if expected_dims is None or (payload.dims.w, payload.dims.h) != expected_dims:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Guest generation dimensions do not match the selected aspect.",
        )
    if len(payload.uploads) < 1 or len(payload.uploads) > GUEST_GENERATION_MAX_UPLOADS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest generation supports one jewelry upload.",
        )
    if len(payload.items) < 1 or len(payload.items) > GUEST_GENERATION_MAX_UPLOADS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest generation supports one jewelry item.",
        )
    upload_ids = {upload.id for upload in payload.uploads}
    if any(item.uploadId not in upload_ids for item in payload.items):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generation item references an unknown upload.",
        )
    for upload in payload.uploads:
        declared_size = upload.fileSize or 0
        estimated_size = int(len(upload.base64) * 0.75)
        if max(declared_size, estimated_size) > GUEST_GENERATION_MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Guest upload is too large.",
            )

    _check_guest_generation_quota(request)


def _build_guest_user(job_id: str) -> UserState:
    return UserState(
        id=f"{GUEST_USER_ID_PREFIX}{job_id}",
        email=None,
        name="Guest",
        plan="Free",
        credits=GUEST_GENERATION_LOOKS
        * COST_PER_LOOK.get(GUEST_GENERATION_QUALITY, COST_PER_LOOK["1080p"]),
        monthlyCredits=0,
        purchasedCredits=0,
        onboardingCompleted=False,
    )


def _motion_frame_allowed_hosts() -> tuple[set[str], set[str]]:
    """Return (hosts allowed outright, GCS bucket names allowed on storage.googleapis.com)."""

    buckets = {
        name.strip().lower()
        for name in (
            os.getenv("GCS_COLLECTIONS_PUBLIC_BUCKET"),
            os.getenv("GCS_COLLECTIONS_APP_BUCKET"),
        )
        if name and name.strip()
    }
    hosts = {f"{bucket}.storage.googleapis.com" for bucket in buckets}
    public_host = (os.getenv("GCS_PUBLIC_HOST") or "").strip()
    if public_host:
        hosts.add((urlsplit(public_host).hostname or public_host).lower())
    extra = os.getenv("MOTION_FRAME_ALLOWED_HOSTS", "")
    hosts.update(host.strip().lower() for host in extra.split(",") if host.strip())
    return hosts, buckets


def _validate_motion_frame_url(value: str) -> str:
    """Only forward images from Gemzy storage to the video provider (no arbitrary URLs)."""

    frame_url = value.strip()
    if not frame_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Motion generation requires an HTTP image URL.",
        )
    parsed = urlsplit(frame_url)
    host = (parsed.hostname or "").lower()
    hosts, buckets = _motion_frame_allowed_hosts()
    if not hosts and not buckets:
        # Storage isn't configured (local development): nothing to compare against.
        return frame_url
    bucket = parsed.path.lstrip("/").split("/", 1)[0].lower()
    if host in hosts or (host == "storage.googleapis.com" and bucket in buckets):
        return frame_url
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Motion generation only accepts images stored in Gemzy.",
    )


def _extract_motion_json_url(data: Any) -> str | None:
    if isinstance(data, str):
        return data if data.startswith(("http://", "https://")) else None
    if isinstance(data, dict):
        for key in ("url", "video_url", "videoUrl", "output", "output_url"):
            url = _extract_motion_json_url(data.get(key))
            if url:
                return url
        for value in data.values():
            url = _extract_motion_json_url(value)
            if url:
                return url
    if isinstance(data, list):
        for value in data:
            url = _extract_motion_json_url(value)
            if url:
                return url
    return None


def _motion_result_metadata(
    payload: CreateMotionGenerationPayload,
    *,
    provider: str,
    source: str,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "source": source,
        "model": "seedance-2.0" if provider == "segmind" else "demo-motion",
        "duration": payload.duration,
        "resolution": payload.resolution,
        "aspectRatio": payload.aspectRatio,
        "contentType": MOTION_DEFAULT_VIDEO_CONTENT_TYPE,
        "mediaType": "video",
        "previewUrl": payload.firstFrameUrl,
        "previewUri": payload.firstFrameUrl,
    }


def _load_demo_motion_result(
    payload: CreateMotionGenerationPayload,
) -> GenerationResultPayload | None:
    demo_path = os.getenv(MOTION_DEMO_VIDEO_PATH_ENV, "").strip()
    if not demo_path:
        return None

    try:
        with open(demo_path, "rb") as video_file:
            video_bytes = video_file.read()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configured demo motion video is not readable",
        ) from exc

    encoded = base64.b64encode(video_bytes).decode("ascii")
    return GenerationResultPayload(
        url=f"data:{MOTION_DEFAULT_VIDEO_CONTENT_TYPE};base64,{encoded}",
        previewUrl=payload.firstFrameUrl,
        mediaType="video",
        contentType=MOTION_DEFAULT_VIDEO_CONTENT_TYPE,
        metadata=_motion_result_metadata(payload, provider="demo", source="local-demo"),
    )


def _decode_data_url_bytes(value: str) -> tuple[bytes, str]:
    if not value.startswith("data:") or "," not in value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid data URL payload",
        )

    header, encoded = value.split(",", 1)
    content_type = header[5:].split(";", 1)[0] or "application/octet-stream"
    try:
        return base64.b64decode(encoded), content_type
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid video payload",
        ) from exc


def _motion_content_type_from_result(
    result: GenerationResultPayload,
    fallback: str = MOTION_DEFAULT_VIDEO_CONTENT_TYPE,
) -> str:
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    for key in ("contentType", "mimeType"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().split(";", 1)[0]
    if isinstance(result.contentType, str) and result.contentType.strip():
        return result.contentType.strip().split(";", 1)[0]
    return fallback


def _motion_video_extension(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "application/octet-stream": ".mp4",
    }.get(normalized, ".mp4")


async def _load_motion_video_bytes(
    result: GenerationResultPayload,
) -> tuple[bytes, str, str | None]:
    if result.base64:
        video_bytes, content_type = _decode_data_url_bytes(
            result.base64
            if result.base64.startswith("data:")
            else f"data:{_motion_content_type_from_result(result)};base64,{result.base64}"
        )
        return video_bytes, content_type, None

    if result.url and result.url.startswith("data:"):
        video_bytes, content_type = _decode_data_url_bytes(result.url)
        return video_bytes, content_type, None

    if result.url and result.url.startswith(("http://", "https://")):
        timeout = float(os.getenv("SEGMIND_DOWNLOAD_TIMEOUT", "300"))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(result.url)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Motion video download failed: {detail}",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Motion video download failed",
            ) from exc

        content_type = response.headers.get(
            "content-type", _motion_content_type_from_result(result)
        ).split(";", 1)[0]
        return response.content, content_type, result.url

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Motion provider response did not include video data",
    )

async def _request_seedance_motion(
    payload: CreateMotionGenerationPayload,
    *,
    look_index: int,
) -> GenerationResultPayload:
    demo_result = _load_demo_motion_result(payload)
    if demo_result is not None:
        return demo_result

    api_key = os.getenv("SEGMIND_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Motion generation provider is not configured",
        )

    request_payload: dict[str, Any] = {
        "prompt": payload.prompt,
        "first_frame_url": _validate_motion_frame_url(payload.firstFrameUrl),
        "duration": payload.duration,
        "resolution": payload.resolution,
        "aspect_ratio": payload.aspectRatio,
        "generate_audio": payload.generateAudio,
        "return_last_frame": payload.returnLastFrame,
    }
    if payload.seed is not None:
        request_payload["seed"] = (
            min(2147483647, payload.seed + look_index)
            if payload.seed >= 0
            else payload.seed
        )

    timeout = float(os.getenv("SEGMIND_TIMEOUT", "900"))
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                SEGMIND_SEEDANCE_URL,
                headers=headers,
                json=request_payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Motion provider rejected the request: {detail}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Motion provider request failed",
        ) from exc

    content_type = response.headers.get("content-type", "application/octet-stream")
    if "application/json" in content_type.lower():
        data = response.json()
        url = _extract_motion_json_url(data)
        if not url:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Motion provider response did not include a video URL",
            )
        return GenerationResultPayload(
            url=url,
            previewUrl=payload.firstFrameUrl,
            mediaType="video",
            contentType=MOTION_DEFAULT_VIDEO_CONTENT_TYPE,
            metadata=_motion_result_metadata(
                payload, provider="segmind", source="remote-url"
            ),
        )

    encoded = base64.b64encode(response.content).decode("ascii")
    return GenerationResultPayload(
        url=f"data:{content_type};base64,{encoded}",
        previewUrl=payload.firstFrameUrl,
        mediaType="video",
        contentType=content_type.split(";", 1)[0],
        metadata=_motion_result_metadata(
            payload, provider="segmind", source="inline-video"
        ),
    )


async def _run_motion_generation_job(
    job: GenerationJob,
    *,
    payload: CreateMotionGenerationPayload,
    user_id: str,
    required_credits: int,
) -> None:
    mark_started(job)
    try:
        for index in range(payload.videoCount):
            provider_result = await _request_seedance_motion(payload, look_index=index)
            result = await _persist_motion_result(job, provider_result)
            add_result(job, result)
            update_progress(
                job,
                (index + 1) / payload.videoCount,
                index + 1,
            )
        mark_completed(job)
        try:
            _publish_generation_completed_notification(job)
        except Exception:
            logger.exception(
                "Failed to publish completion notification for motion job %s", job.id
            )
    except Exception:
        mark_failed(job, MOTION_START_FAILURE_MESSAGE)
        _refund_unfinished_reserved_credits(job)
        try:
            _publish_generation_failed_notification(job)
        except Exception:
            logger.exception(
                "Failed to publish failure notification for motion job %s", job.id
            )
        logger.exception("Motion generation job %s failed", job.id)
    finally:
        to_response(job)  # Persist the terminal analytics fact even with no client polling.


def _schedule_motion_generation_job(
    job: GenerationJob,
    *,
    payload: CreateMotionGenerationPayload,
    user_id: str,
    required_credits: int,
) -> None:
    task = asyncio.create_task(
        _run_motion_generation_job(
            job,
            payload=payload,
            user_id=user_id,
            required_credits=required_credits,
        )
    )
    _MOTION_BACKGROUND_TASKS.add(task)
    task.add_done_callback(_MOTION_BACKGROUND_TASKS.discard)


@router.get("/config")
def get_generation_config() -> dict[str, Any]:
    """Return the current configuration for generation costs."""
    return {
        "costPerLook": COST_PER_LOOK,
        "imageEditCost": {
            "base": COST_PER_LOOK["1080p"],
            "upscale": COST_PER_LOOK["4K"],
        },
        "motionCostByDuration": MOTION_CREDITS_PER_VIDEO,
    }


@router.get("/ui-config", response_model=GenerationUiCatalogResponse)
def get_generation_ui_config() -> GenerationUiCatalogResponse:
    """Return the server-driven UI catalog for generation surfaces."""

    client = get_client()
    try:
        ensure_default_prompt_registry(client=client)
    except Exception:
        logger.warning(
            "Prompt registry seeding failed during /generations/ui-config; falling back to available catalog data.",
            exc_info=True,
        )
    catalog = resolve_generation_ui_catalog(client=client)
    return GenerationUiCatalogResponse(**catalog)


def _resolve_image_edit_instructions(
    edit_ids: list[str],
    *,
    option_definitions: dict[str, dict[str, str]] | None = None,
) -> list[ImageEditInstructionPayload]:
    seen: set[str] = set()
    instructions: list[ImageEditInstructionPayload] = []
    unknown: list[str] = []
    option_definitions = option_definitions or IMAGE_EDIT_OPTIONS

    for edit_id in edit_ids:
        normalized = edit_id.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        option = option_definitions.get(normalized)
        if option is None:
            unknown.append(normalized)
            continue
        instructions.append(
            ImageEditInstructionPayload(
                id=normalized,
                label=option["label"],
                category=option["category"],
                prompt=option["prompt"],
            )
        )

    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported image edit option: {', '.join(unknown)}",
        )
    if not instructions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose at least one edit.",
        )
    return instructions


def _calculate_image_edit_cost(
    instructions: list[ImageEditInstructionPayload],
    quality: str | None,
) -> int:
    target_quality = (
        "4K"
        if any(instruction.id == "upscale_image" for instruction in instructions)
        else (quality or "1080p")
    )
    return COST_PER_LOOK.get(target_quality, COST_PER_LOOK["1080p"])


def _build_image_edit_prompt(
    payload: CreateImageEditPayload,
    instructions: list[ImageEditInstructionPayload],
    *,
    definition: dict[str, Any] | None = None,
) -> str:
    prompt_config = _resolve_image_edit_prompt_config(definition)
    lines = [prompt_config["hero"]]
    if payload.source.modelSlug == "pure-jewelry":
        lines.append(prompt_config["pure_jewelry_addendum"])

    lines.append(prompt_config["requested_edits_heading"])
    for index, instruction in enumerate(instructions, start=1):
        lines.append(
            f"{index}. {instruction.label}: {instruction.prompt or instruction.label}"
        )
    return "\n".join(lines)


def _build_image_edit_generation_payload(
    payload: CreateImageEditPayload,
    *,
    user: UserState,
    required_credits: int,
    instructions: list[ImageEditInstructionPayload],
    definition: dict[str, Any] | None = None,
) -> CreateGenerationPayload:
    source_base_task_type = _image_edit_source_base_task_type(payload)
    edit_style = _style_with_task_type(
        payload.source.style, _image_edit_task_type(payload)
    )
    edit_style["source_task_type"] = source_base_task_type
    edit_style["edit_ids"] = ",".join(instruction.id for instruction in instructions)
    edit_style["edit_labels"] = ",".join(
        instruction.label for instruction in instructions
    )
    edit_style["edit_categories"] = ",".join(
        instruction.category for instruction in instructions
    )
    if payload.source.modelSlug:
        edit_style["source_model_slug"] = payload.source.modelSlug

    return CreateGenerationPayload(
        generationServerUrl=payload.generationServerUrl,
        uploads=[payload.sourceImage],
        items=[
            ItemPayload(
                id="image-edit-source",
                type="Image",
                size="Original",
                uploadId=payload.sourceImage.id,
            )
        ],
        model=GenerationModelPayload(
            id=_image_edit_model_id(payload) or "image-edit",
            slug="image-edit",
            name=_image_edit_model_name(payload),
            planTier="Pro",
            tags=[],
            imageUri=_image_edit_model_image_uri(payload),
            imageBase64=_image_edit_model_image_base64(payload),
        ),
        style=edit_style,
        mode="ADVANCED",
        aspect=payload.aspect,
        dims=payload.dims,
        looks=1,
        quality=payload.quality,
        plan=user.plan or "Pro",
        creditsNeeded=required_credits,
        promptOverrides=[_build_image_edit_prompt(payload, instructions, definition=definition)],
    )


def _resolve_generation_target_collection_id(
    payload: CreateGenerationPayload,
    user: UserState,
) -> str | None:
    collection_id = (payload.collectionId or "").strip()
    if not collection_id:
        return None

    _ensure_collections_belong(user.id, [collection_id])
    return collection_id


def _resolve_image_edit_target_collection_id(
    payload: CreateImageEditPayload,
    user: UserState,
) -> str | None:
    collection_id = (payload.source.collectionId or "").strip()
    if not collection_id:
        return None

    _ensure_collections_belong(user.id, [collection_id])
    return collection_id


@router.post("/edits", response_model=CreateGenerationResponse)
@limiter.limit(LIMIT_generation_create)
async def create_image_edit(
    request: Request,
    payload: CreateImageEditPayload,
    user: UserState = Depends(get_current_user),
) -> CreateGenerationResponse:
    """Accept a follow-up edit request for a generated image."""

    from .plans import normalize_plan

    tier_levels = {"Free": 0, "Starter": 1, "Pro": 2, "Designer": 3}
    user_tier = normalize_plan(user.plan)
    edit_trial_remaining = _normalize_edit_mode_trial_edits_remaining(
        user.editModeTrialEditsRemaining
    )
    if tier_levels.get(user_tier, 0) < tier_levels["Pro"] and edit_trial_remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Image editing requires the Pro plan.",
        )

    definition = _resolve_image_edit_definition(payload)
    option_definitions = _edit_option_definitions_from_definition(definition) or IMAGE_EDIT_OPTIONS
    instructions = _resolve_image_edit_instructions(
        payload.edits,
        option_definitions=option_definitions,
    )
    required_credits = _calculate_image_edit_cost(instructions, payload.quality)
    target_collection_id = _resolve_image_edit_target_collection_id(payload, user)

    edit_trial_applied = False
    new_trial_remaining: int | None = None
    new_credits = user.credits

    if edit_trial_remaining > 0:
        consumed_trial_remaining = _adjust_edit_mode_trial_edits(user.id, -1)
        if consumed_trial_remaining is not None:
            edit_trial_applied = True
            new_trial_remaining = consumed_trial_remaining

    if not edit_trial_applied and required_credits > user.credits:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="You do not have enough credits to perform this action",
        )

    _hydrate_image_edit_source_upload_from_storage(payload, user=user)
    _process_upload(payload.sourceImage)

    job_id = uuid4().hex
    edit_payload = _build_image_edit_generation_payload(
        payload,
        user=user,
        required_credits=required_credits,
        instructions=instructions,
        definition=definition,
    )
    callback_url = _build_callback_url(job_id)
    target_url = _resolve_generation_url(payload.generationServerUrl)
    forwarded_payload = _build_generation_payload(edit_payload, user, job_id, callback_url)

    if not edit_trial_applied:
        adjusted_credits = _adjust_profile_credits(user.id, -required_credits)
        if adjusted_credits is None:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="You do not have enough credits to perform this action",
            )
        new_credits = adjusted_credits

    job = create_job(
        job_id,
        user.id,
        1,
        analytics_context=generation_context(request, user),
        model_id=_image_edit_model_id(payload),
        model_name=_image_edit_model_name(payload),
        style=edit_payload.style or None,
        aspect=edit_payload.aspect,
        dims=_dims_payload(edit_payload.dims),
        quality=edit_payload.quality,
        unsaved_collection_id=target_collection_id,
        job_type="image_edit",
        edit_source=payload.source.model_dump(exclude_none=True),
        edit_instructions=[instruction.model_dump() for instruction in instructions],
        edit_credit_cost=0 if edit_trial_applied else required_credits,
        edit_trial_applied=edit_trial_applied,
        edit_mode_trial_edits_remaining=new_trial_remaining,
        reserved_credit_cost=0 if edit_trial_applied else required_credits,
        credit_cost_per_look=0 if edit_trial_applied else required_credits,
    )

    try:
        response = await _forward_generation_request(target_url, forwarded_payload)
    except Exception:
        mark_failed(job, IMAGE_EDIT_START_FAILURE_MESSAGE)
        if edit_trial_applied:
            try:
                _adjust_edit_mode_trial_edits(user.id, 1)
            except Exception:
                logger.exception(
                    "Failed to restore Edit Mode trial for user %s after dispatch failure",
                    user.id,
                )
        else:
            _refund_unfinished_reserved_credits(job)
        to_response(job)
        raise

    if response.results:
        for result in response.results:
            generation_result = (
                GenerationResultPayload(**result)
                if isinstance(result, dict)
                else result
            )
            stored_result = _persist_generation_result(job, generation_result)
            add_result(job, stored_result)

    if response.status == "in_progress":
        mark_started(job)

    if response.progress is not None or response.completedLooks is not None:
        update_progress(job, response.progress or job.progress, response.completedLooks)

    has_completed_result = job.completed_looks >= job.total_looks and job.completed_looks > 0

    was_completed = job.status == "completed"

    if response.status == "completed" or (has_completed_result and response.status != "failed"):
        mark_completed(job)
        if not was_completed:
            try:
                _publish_image_edit_completed_notification(job)
            except Exception:
                logger.exception("Failed to publish completion notification for edit job %s", job.id)
    elif response.status == "failed":
        error_message = response.errors[0] if response.errors else IMAGE_EDIT_JOB_FAILURE_MESSAGE
        mark_failed(job, error_message)
        refunded_credits = _refund_unfinished_reserved_credits(job)
        if refunded_credits is not None:
            new_credits = refunded_credits
        try:
            _publish_image_edit_failed_notification(job)
        except Exception:
            logger.exception("Failed to publish failure notification for edit job %s", job.id)

    job_state = to_response(job)
    if response.status and response.status != job_state["status"]:
        job_state["status"] = response.status
    if response.progress is not None:
        job_state["progress"] = response.progress
    if response.completedLooks is not None:
        job_state["completedLooks"] = response.completedLooks
    if response.totalLooks is not None:
        job_state["totalLooks"] = response.totalLooks

    job_state["remainingCredits"] = new_credits
    job_state["editTrialApplied"] = edit_trial_applied
    job_state["editModeTrialEditsRemaining"] = new_trial_remaining
    return CreateGenerationResponse(**job_state)


@router.post("/edits/{edit_job_id}/feedback", response_model=ImageEditFeedbackResponse)
def submit_image_edit_feedback(
    edit_job_id: str,
    payload: ImageEditFeedbackRequest,
    user: UserState = Depends(get_current_user),
) -> ImageEditFeedbackResponse:
    """Persist beta feedback for a completed image edit."""

    job = get_job(edit_job_id)
    if job is not None and job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edit job not found")

    comment = payload.comment.strip() if isinstance(payload.comment, str) else None
    if comment == "":
        comment = None
    if comment and len(comment) > 2000:
        comment = comment[:2000]

    feedback_id = str(uuid4())
    created_at = datetime.utcnow().isoformat() + "Z"
    row = {
        "id": feedback_id,
        "user_id": user.id,
        "edit_job_id": edit_job_id,
        "source_key": payload.sourceKey,
        "rating": payload.rating,
        "comment": comment,
        "edit_option_ids": [
            item for item in payload.editOptionIds if isinstance(item, str) and item
        ],
        "edit_labels": [
            item for item in payload.editLabels if isinstance(item, str) and item
        ],
        "metadata": payload.metadata if isinstance(payload.metadata, dict) else {},
        "created_at": created_at,
        "updated_at": created_at,
    }

    get_client().table("image_edit_feedback").insert(row).execute()
    return ImageEditFeedbackResponse(id=feedback_id, createdAt=created_at)


@router.post("/motion", response_model=CreateGenerationResponse)
@limiter.limit(LIMIT_generation_create)
async def create_motion_generation(
    request: Request,
    payload: CreateMotionGenerationPayload,
    user: UserState = Depends(get_current_user),
) -> CreateGenerationResponse:
    """Generate a Seedance motion video from a selected image URL."""

    from .plans import normalize_plan

    tier_levels = {"Free": 0, "Starter": 1, "Pro": 2, "Designer": 3}
    user_tier = normalize_plan(user.plan)
    required_tier = normalize_plan(MOTION_REQUIRED_PLAN)
    if tier_levels.get(user_tier, 0) < tier_levels.get(required_tier, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This model requires the {required_tier} plan.",
        )

    # Reject foreign image URLs before any credits are reserved.
    _validate_motion_frame_url(payload.firstFrameUrl)

    credit_cost_per_video = MOTION_CREDITS_PER_VIDEO[payload.duration]
    required_credits = _motion_credit_cost(payload.duration, payload.videoCount)
    if required_credits > user.credits:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="You do not have enough credits to perform this action",
        )

    job_id = uuid4().hex
    new_credits = _adjust_profile_credits(user.id, -required_credits)
    if new_credits is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="You do not have enough credits to perform this action",
        )

    job = create_job(
        job_id,
        user.id,
        payload.videoCount,
        analytics_context=generation_context(request, user),
        model_id="motion-v1",
        model_name="Motion",
        style={"task_type": "motion", "prompt": payload.prompt},
        aspect=payload.aspectRatio,
        dims={"w": 608, "h": 1080},
        quality=payload.resolution,
        job_type="motion",
        reserved_credit_cost=required_credits,
        credit_cost_per_look=credit_cost_per_video,
    )

    _schedule_motion_generation_job(
        job,
        payload=payload,
        user_id=user.id,
        required_credits=required_credits,
    )

    job_state = to_response(job)
    job_state["remainingCredits"] = new_credits
    return CreateGenerationResponse(**job_state)


@router.post("/", response_model=CreateGenerationResponse)
@limiter.limit(LIMIT_generation_create)
async def create_generation(
    request: Request,
    payload: CreateGenerationPayload,
    user: UserState | None = Depends(get_optional_current_user),
) -> CreateGenerationResponse:
    """Accept a generation request from the client and relay it to the worker."""

    # model_debug = payload.model.model_dump()
    # if model_debug.get("imageBase64"):
    #     b64 = model_debug["imageBase64"]
    #     model_debug["imageBase64"] = f"{b64[:100]}... (len: {len(b64)})"
    # print("Model: ", json.dumps(model_debug, indent=2))

    job_id = uuid4().hex
    # Guest intent is explicit in the constrained FTUE payload. Treat it as a
    # guest job even if a stale/transitioning client session sends a bearer
    # token, so storage ownership and the post-signup migration contract do not
    # depend on an auth hydration race.
    is_guest_generation = _is_guest_generation_request(payload)
    if is_guest_generation:
        _validate_guest_generation_payload(request, payload)
        user = _build_guest_user(job_id)
    elif user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign up to start this generation.",
        )

    # Tier Enforcement
    tier_levels = {"Free": 0, "Starter": 1, "Pro": 2, "Designer": 3}
    from .plans import normalize_plan

    user_tier = normalize_plan(user.plan)
    required_tier = normalize_plan(payload.model.planTier)

    if (
        not is_guest_generation
        and tier_levels.get(user_tier, 0) < tier_levels.get(required_tier, 0)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This model requires the {required_tier} plan.",
        )

    # Calculate required credits server-side to prevent tampering
    required_credits = payload.looks * COST_PER_LOOK.get(payload.quality, 1)

    if not is_guest_generation and required_credits > user.credits:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="You do not have enough credits to perform this action",
        )

    # Validate and resize oversized uploads before sending off to worker
    for upload in payload.uploads:
        _process_upload(upload)

    generation_style = _resolve_generation_style(payload)
    payload = payload.model_copy(update={"style": generation_style})
    target_collection_id = (
        None
        if is_guest_generation
        else _resolve_generation_target_collection_id(payload, user)
    )

    callback_url = _build_callback_url(job_id)
    target_url = _resolve_generation_url(payload.generationServerUrl)
    forwarded_payload = _build_generation_payload(payload, user, job_id, callback_url)

    new_credits = 0
    if not is_guest_generation:
        adjusted_credits = _adjust_profile_credits(user.id, -required_credits)
        if adjusted_credits is None:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="You do not have enough credits to perform this action",
            )
        new_credits = adjusted_credits

    job = create_job(
        job_id,
        user.id,
        payload.looks,
        analytics_context={**generation_context(request, user), "jewelry_ids": [item.id for item in (payload.items or [])], "jewelry_id": payload.items[0].id if payload.items and len(payload.items) == 1 else None},
        model_id=payload.model.id,
        model_name=payload.model.name,
        style=payload.style or None,
        aspect=payload.aspect,
        dims=_dims_payload(payload.dims),
        quality=payload.quality,
        unsaved_collection_id=target_collection_id,
        reserved_credit_cost=0 if is_guest_generation else required_credits,
        credit_cost_per_look=0 if is_guest_generation else COST_PER_LOOK.get(payload.quality, 1),
    )

    try:
        response = await _forward_generation_request(target_url, forwarded_payload)
    except Exception:
        mark_failed(job, GENERATION_START_FAILURE_MESSAGE)
        if not is_guest_generation:
            _refund_unfinished_reserved_credits(job)
        to_response(job)
        raise

    # If the worker replies with immediate results, persist them now.
    if response.results:
        for result in response.results:
            if isinstance(result, dict):
                generation_result = GenerationResultPayload(**result)
            else:
                generation_result = result
            stored_result = _persist_generation_result(job, generation_result)
            add_result(job, stored_result)

    if response.status == "in_progress":
        mark_started(job)

    if response.progress is not None or response.completedLooks is not None:
        update_progress(job, response.progress or job.progress, response.completedLooks)

    if response.status == "completed":
        mark_completed(job)
        if not is_guest_generation:
            try:
                _publish_generation_completed_notification(job)
            except Exception:
                logger.exception("Failed to publish completion notification for generation job %s", job.id)
    elif response.status == "failed":
        error_message = response.errors[0] if response.errors else GENERATION_JOB_FAILURE_MESSAGE
        mark_failed(job, error_message)
        if not is_guest_generation:
            refunded_credits = _refund_unfinished_reserved_credits(job)
            if refunded_credits is not None:
                new_credits = refunded_credits
            try:
                _publish_generation_failed_notification(job)
            except Exception:
                logger.exception("Failed to publish failure notification for generation job %s", job.id)

    job_state = to_response(job)
    # Merge worker-provided status when available.
    if response.status and response.status != job_state["status"]:
        job_state["status"] = response.status
    if response.progress is not None:
        job_state["progress"] = response.progress
    if response.completedLooks is not None:
        job_state["completedLooks"] = response.completedLooks
    if response.totalLooks is not None:
        job_state["totalLooks"] = response.totalLooks
    
    # Include remaining credits in response for client state sync
    job_state["remainingCredits"] = new_credits

    return CreateGenerationResponse(**job_state)


def _require_secret(request: Request) -> None:
    expected = os.getenv("GENERATION_SHARED_SECRET", "").strip()
    if not expected:
        return
    provided = request.headers.get("X-Generation-Secret", "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid generation signature",
        )


@router.get("/{job_id}", response_model=CreateGenerationResponse)
async def retrieve_generation(
    job_id: str,
    user: UserState | None = Depends(get_optional_current_user),
) -> CreateGenerationResponse:
    """Return the latest status for a generation job."""

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")
    is_guest_job = _is_guest_user_id(job.user_id)
    if not is_guest_job and (user is None or job.user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")

    remaining_credits = _expire_stale_generation(job)
    job_state = to_response(job)
    if remaining_credits is not None:
        job_state["remainingCredits"] = remaining_credits
    return CreateGenerationResponse(**job_state)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_failed_generation(
    job_id: str,
    user: UserState = Depends(get_current_user),
) -> None:
    """Remove a failed generation job from server-side history."""

    job = get_job(job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")
    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only failed generations can be deleted",
        )
    delete_job(job_id)


@router.post("/{job_id}/cancel", response_model=CreateGenerationResponse)
async def cancel_generation(
    job_id: str,
    payload: CancelGenerationPayload | None = None,
    user: UserState = Depends(get_current_user),
) -> CreateGenerationResponse:
    """Cancel queued generation slots and refund only those credits."""

    job = get_job(job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")

    remaining_credits = _refund_cancelled_reserved_looks(job, payload.looks if payload else 1)

    job_state = to_response(job)
    if remaining_credits is not None:
        job_state["remainingCredits"] = remaining_credits
    return CreateGenerationResponse(**job_state)


@router.post("/{job_id}/events", response_model=CreateGenerationResponse)
async def receive_generation_event(
    job_id: str,
    event: GenerationJobEvent,
    request: Request,
) -> CreateGenerationResponse:
    """Receive streaming updates from the generation worker."""

    _require_secret(request)

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")

    remaining_credits: int | None = None

    if event.type == "started":
        mark_started(job)
    elif event.type == "result":
        if event.result is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Result event requires a payload",
            )
        with job.lifecycle_lock:
            if job.status in {"failed", "completed"} or len(job.results) >= job.total_looks:
                logger.info(
                    "Ignoring late result for terminal or full generation job %s",
                    job.id,
                )
            else:
                stored_result = _persist_generation_result(job, event.result)
                add_result(job, stored_result)
                if event.progress is not None or event.completedLooks is not None:
                    update_progress(job, event.progress or job.progress, event.completedLooks)
                if (
                    job.completed_looks >= job.total_looks
                    and job.completed_looks > 0
                    and job.status != "completed"
                ):
                    mark_completed(job)
                    if not _is_guest_user_id(job.user_id):
                        try:
                            if job.job_type == "image_edit":
                                _publish_image_edit_completed_notification(job)
                            else:
                                _publish_generation_completed_notification(job)
                        except Exception:
                            logger.exception("Failed to publish completion notification for job %s", job.id)
    elif event.type == "progress":
        if event.progress is None and event.completedLooks is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Progress event requires progress or completed count",
            )
        progress = event.progress if event.progress is not None else job.progress
        update_progress(job, progress, event.completedLooks)
    elif event.type == "completed":
        was_completed = job.status == "completed"
        mark_completed(job)
        if not was_completed:
            if not _is_guest_user_id(job.user_id):
                try:
                    if job.job_type == "image_edit":
                        _publish_image_edit_completed_notification(job)
                    else:
                        _publish_generation_completed_notification(job)
                except Exception:
                    logger.exception("Failed to publish completion notification for generation job %s", job.id)
    elif event.type == "failed":
        with job.lifecycle_lock:
            if event.error:
                logger.warning("Generation job %s failed: %s", job.id, event.error[:1000])
            else:
                logger.warning("Generation job %s failed without an error payload", job.id)
            failure_message = (
                IMAGE_EDIT_JOB_FAILURE_MESSAGE
                if job.job_type == "image_edit"
                else GENERATION_JOB_FAILURE_MESSAGE
            )
            mark_failed(job, failure_message)
            remaining_credits = _refund_unfinished_reserved_credits(job)
            if not _is_guest_user_id(job.user_id):
                try:
                    if job.job_type == "image_edit":
                        _publish_image_edit_failed_notification(job)
                    else:
                        _publish_generation_failed_notification(job)
                except Exception:
                    logger.exception("Failed to publish failure notification for generation job %s", job.id)
    elif event.type in {"cancelled", "canceled"}:
        with job.lifecycle_lock:
            logger.info("Generation job %s cancelled", job.id)
            mark_failed(job, "Generation cancelled.")
            remaining_credits = _refund_unfinished_reserved_credits(job)
    else:  # pragma: no cover - safeguard for future event types
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported event type",
        )

    job_state = to_response(job, strict_analytics=True)
    if remaining_credits is not None:
        job_state["remainingCredits"] = remaining_credits
    return CreateGenerationResponse(**job_state)
