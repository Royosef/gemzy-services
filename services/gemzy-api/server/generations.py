from __future__ import annotations
"""Generation routing for dispatching create requests to the worker service."""

import json

import base64
import io
import os
from datetime import datetime
import logging
from typing import Any
from uuid import uuid4

from PIL import Image

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from postgrest.exceptions import APIError
from tenacity import retry, stop_after_attempt, wait_exponential

from prompting.registry import ensure_default_prompt_registry
from prompting.ui_catalog import resolve_generation_ui_catalog

from .auth import get_current_user
from .content import (
    COLLECTIONS_CACHE_CONTROL,
    COLLECTIONS_OWNER_METADATA_KEY,
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
    get_job,
    mark_completed,
    mark_failed,
    mark_started,
    to_response,
    update_progress,
)
from .notifications import publish_app_notification
from .schemas import (
    CreateGenerationPayload,
    CreateGenerationResponse,
    CreateImageEditPayload,
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

QUALITY_FORWARD_MAP = {
    "1080p": "1k",
    "2K": "2k",
    "4K": "4k",
}

GENERATION_START_FAILURE_MESSAGE = "Unable to start generation right now. Please try again."
GENERATION_JOB_FAILURE_MESSAGE = "Generation failed. Please try again."
IMAGE_EDIT_START_FAILURE_MESSAGE = "Unable to start image edit right now. Please try again."
IMAGE_EDIT_JOB_FAILURE_MESSAGE = "Image edit failed. Please try again."
DEFAULT_EDIT_MODE_TRIAL_EDITS = 2
IMAGE_EDIT_BASE_COST = 8
IMAGE_EDIT_UPSCALE_COST = 14
BASE_TASK_TYPE_ON_MODEL = "on-model"
BASE_TASK_TYPE_PURE_JEWELRY = "pure-jewelry"

IMAGE_EDIT_OPTIONS: dict[str, dict[str, str]] = {
    "jewelry_smaller": {
        "label": "Make the jewelry a bit smaller",
        "category": "jewelry",
        "prompt": "Make the jewelry slightly smaller while preserving its design and placement.",
    },
    "jewelry_bigger": {
        "label": "Make the jewelry a bit bigger",
        "category": "jewelry",
        "prompt": "Make the jewelry slightly larger while keeping it realistic and proportional.",
    },
    "enhance_shine": {
        "label": "Enhance shine & reflections",
        "category": "jewelry",
        "prompt": "Enhance gemstone and metal shine, reflections, depth, and polished highlights.",
    },
    "zoom_in": {
        "label": "Zoom in on the jewelry",
        "category": "framing",
        "prompt": "Crop closer toward the jewelry while keeping the image premium and balanced.",
    },
    "zoom_out": {
        "label": "Zoom out for full context",
        "category": "framing",
        "prompt": "Widen the framing to show more context around the jewelry and scene.",
    },
    "camera_low_angle": {
        "label": "Low angle",
        "category": "framing",
        "prompt": "Reframe from a subtle low angle perspective.",
    },
    "camera_high_angle": {
        "label": "High angle",
        "category": "framing",
        "prompt": "Reframe from a subtle high angle perspective.",
    },
    "camera_rotate_left": {
        "label": "Rotate Slight Left",
        "category": "framing",
        "prompt": "Rotate the composition slightly left while keeping the jewelry sharp.",
    },
    "lighting_soft_diffused": {
        "label": "Soft Diffused",
        "category": "lighting_photo",
        "prompt": "Apply soft diffused studio lighting with gentle, flattering shadows.",
    },
    "lighting_side_rim": {
        "label": "Side Rim",
        "category": "lighting_photo",
        "prompt": "Add a tasteful side rim light that outlines the jewelry and creates depth.",
    },
    "lighting_top_down": {
        "label": "Top Down",
        "category": "lighting_photo",
        "prompt": "Use elegant top-down lighting with clean highlights on the jewelry.",
    },
    "remove_background": {
        "label": "Remove the background",
        "category": "lighting_photo",
        "prompt": "Remove the background and create a clean transparent product-style cutout.",
    },
    "model_pose": {
        "label": "Change the model's pose",
        "category": "model",
        "prompt": "Adjust the model pose to feel more natural and editorial while preserving identity.",
    },
    "outfit_color": {
        "label": "Change the outfit color",
        "category": "model",
        "prompt": "Change the outfit color tastefully without changing jewelry or facial identity.",
    },
    "upscale_image": {
        "label": "Upscale the image",
        "category": "upscale_sharpen",
        "prompt": "Upscale the image for higher resolution while preserving natural detail.",
    },
    "sharpen_image": {
        "label": "Sharpen the image",
        "category": "upscale_sharpen",
        "prompt": "Sharpen fine details on the jewelry and image while avoiding artifacts.",
    },
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
    """Atomically adjust monthly credits first, then purchased credits."""

    sb = get_client()
    if delta == 0:
        resp = sb.table("profiles").select("credits,purchased_credits").eq("id", user_id).limit(1).execute()
        rows = resp.data or []
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load your credit balance right now.",
            )
        return _normalize_credit_value(rows[0].get("credits")) + _normalize_credit_value(rows[0].get("purchased_credits"))

    for _ in range(max_attempts):
        resp = sb.table("profiles").select("credits,purchased_credits").eq("id", user_id).limit(1).execute()
        rows = resp.data or []
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to load your credit balance right now.",
            )

        current_monthly = _normalize_credit_value(rows[0].get("credits"))
        current_purchased = _normalize_credit_value(rows[0].get("purchased_credits"))
        current_total = current_monthly + current_purchased
        if delta < 0 and current_total < -delta:
            return None

        if delta < 0:
            spend = -delta
            spend_monthly = min(current_monthly, spend)
            spend_purchased = spend - spend_monthly
            new_monthly = current_monthly - spend_monthly
            new_purchased = current_purchased - spend_purchased
        else:
            new_monthly = current_monthly + delta
            new_purchased = current_purchased

        update_resp = (
            sb.table("profiles")
            .update({"credits": new_monthly, "purchased_credits": new_purchased}, count="exact")
            .eq("id", user_id)
            .eq("credits", current_monthly)
            .eq("purchased_credits", current_purchased)
            .execute()
        )
        if (update_resp.count or 0) == 1:
            return new_monthly + new_purchased

    logger.warning("Failed to update credits for user %s after %s attempts", user_id, max_attempts)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Your credits changed while starting this generation. Please try again.",
    )


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

    request_payload = payload.model_dump(exclude={"generationServerUrl"})
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
        return base64.b64decode(candidate)
    except Exception as exc:  # pragma: no cover - malformed worker payload
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid generation image payload",
        ) from exc


def _is_missing_model_columns(error: APIError) -> bool:
    message = (getattr(error, "message", None) or str(error)).lower()
    return "model" in message and "column" in message


def _build_result_metadata_payload(
    job: GenerationJob,
    *,
    image_size: int | None = None,
    content_type: str = "image/png",
) -> dict[str, Any]:
    metadata_payload: dict[str, Any] = {
        "contentType": content_type,
        "source": "image_edit" if job.job_type == "image_edit" else "generation",
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

    if storage_path:
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


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _forward_generation_request(
    url: str, payload: dict[str, Any]
) -> CreateGenerationResponse:
    timeout = float(os.getenv("GENERATION_SERVER_TIMEOUT", "30"))
    headers: dict[str, str] = {}
    shared_secret = os.getenv("GENERATION_SHARED_SECRET", "").strip()
    if shared_secret:
        headers["X-Generation-Secret"] = shared_secret

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:  # pragma: no cover - network errors handled at runtime
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



from .rate_limit import limiter, LIMIT_generation_create

COST_PER_LOOK = {
    "1080p": 4,
    "2K": 5,
    "4K": 7,
}


@router.get("/config")
def get_generation_config() -> dict[str, Any]:
    """Return the current configuration for generation costs."""
    return {
        "costPerLook": COST_PER_LOOK,
        "imageEditCost": {
            "base": IMAGE_EDIT_BASE_COST,
            "upscale": IMAGE_EDIT_UPSCALE_COST,
        },
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


def _resolve_image_edit_instructions(edit_ids: list[str]) -> list[ImageEditInstructionPayload]:
    seen: set[str] = set()
    instructions: list[ImageEditInstructionPayload] = []
    unknown: list[str] = []

    for edit_id in edit_ids:
        normalized = edit_id.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        option = IMAGE_EDIT_OPTIONS.get(normalized)
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


def _calculate_image_edit_cost(instructions: list[ImageEditInstructionPayload]) -> int:
    return (
        IMAGE_EDIT_UPSCALE_COST
        if any(instruction.id == "upscale_image" for instruction in instructions)
        else IMAGE_EDIT_BASE_COST
    )


def _build_image_edit_prompt(
    payload: CreateImageEditPayload,
    instructions: list[ImageEditInstructionPayload],
) -> str:
    lines = [
        "Edit the uploaded source image. Preserve the original jewelry design, materials, identity, and premium campaign quality.",
        "Apply only the requested edits. Do not invent new jewelry, change logos, distort anatomy, or alter text/engravings unless directly required.",
    ]
    if payload.source.modelSlug == "pure-jewelry":
        lines.append(
            "The source was created as pure jewelry, so do not add or alter a model/person unless explicitly requested."
        )

    lines.append("Requested edits:")
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
            imageUri=payload.source.url or payload.source.previewUrl,
        ),
        style=edit_style,
        mode="ADVANCED",
        aspect=payload.aspect,
        dims=payload.dims,
        looks=1,
        quality=payload.quality,
        plan=user.plan or "Pro",
        creditsNeeded=required_credits,
        promptOverrides=[_build_image_edit_prompt(payload, instructions)],
    )


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
    if tier_levels.get(user_tier, 0) < tier_levels["Pro"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Image editing requires the Pro plan.",
        )

    instructions = _resolve_image_edit_instructions(payload.edits)
    required_credits = _calculate_image_edit_cost(instructions)
    target_collection_id = _resolve_image_edit_target_collection_id(payload, user)

    edit_trial_applied = False
    edit_trial_remaining = _normalize_edit_mode_trial_edits_remaining(
        user.editModeTrialEditsRemaining
    )
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

    _process_upload(payload.sourceImage)

    job_id = uuid4().hex
    edit_payload = _build_image_edit_generation_payload(
        payload,
        user=user,
        required_credits=required_credits,
        instructions=instructions,
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
    )

    try:
        response = await _forward_generation_request(target_url, forwarded_payload)
    except Exception:
        try:
            if edit_trial_applied:
                _adjust_edit_mode_trial_edits(user.id, 1)
            else:
                _adjust_profile_credits(user.id, required_credits)
        except Exception:
            logger.exception(
                "Failed to refund edit cost for user %s after edit dispatch failure",
                user.id,
            )
        mark_failed(job, IMAGE_EDIT_START_FAILURE_MESSAGE)
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


@router.post("/", response_model=CreateGenerationResponse)
@limiter.limit(LIMIT_generation_create)
async def create_generation(
    request: Request,
    payload: CreateGenerationPayload,
    user: UserState = Depends(get_current_user),
) -> CreateGenerationResponse:
    """Accept a generation request from the client and relay it to the worker."""

    # model_debug = payload.model.model_dump()
    # if model_debug.get("imageBase64"):
    #     b64 = model_debug["imageBase64"]
    #     model_debug["imageBase64"] = f"{b64[:100]}... (len: {len(b64)})"
    # print("Model: ", json.dumps(model_debug, indent=2))

    job_id = uuid4().hex

    # Tier Enforcement
    tier_levels = {"Free": 0, "Starter": 1, "Pro": 2, "Designer": 3}
    from .plans import normalize_plan

    user_tier = normalize_plan(user.plan)
    required_tier = normalize_plan(payload.model.planTier)

    if tier_levels.get(user_tier, 0) < tier_levels.get(required_tier, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This model requires the {required_tier} plan.",
        )

    # Calculate required credits server-side to prevent tampering
    required_credits = payload.looks * COST_PER_LOOK.get(payload.quality, 1)

    if required_credits > user.credits:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="You do not have enough credits to perform this action",
        )

    # Validate and resize oversized uploads before sending off to worker
    for upload in payload.uploads:
        _process_upload(upload)

    generation_style = _style_with_task_type(
        payload.style, _generation_task_type(payload)
    )
    payload = payload.model_copy(update={"style": generation_style})

    callback_url = _build_callback_url(job_id)
    target_url = _resolve_generation_url(payload.generationServerUrl)
    forwarded_payload = _build_generation_payload(payload, user, job_id, callback_url)

    new_credits = _adjust_profile_credits(user.id, -required_credits)
    if new_credits is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="You do not have enough credits to perform this action",
        )

    job = create_job(
        job_id,
        user.id,
        payload.looks,
        model_id=payload.model.id,
        model_name=payload.model.name,
        style=payload.style or None,
        aspect=payload.aspect,
        dims=_dims_payload(payload.dims),
        quality=payload.quality,
    )

    try:
        response = await _forward_generation_request(target_url, forwarded_payload)
    except Exception:
        try:
            _adjust_profile_credits(user.id, required_credits)
        except Exception:
            logger.exception("Failed to refund credits for user %s after dispatch failure", user.id)
        mark_failed(job, GENERATION_START_FAILURE_MESSAGE)
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
        try:
            _publish_generation_completed_notification(job)
        except Exception:
            logger.exception("Failed to publish completion notification for generation job %s", job.id)
    elif response.status == "failed":
        error_message = response.errors[0] if response.errors else GENERATION_JOB_FAILURE_MESSAGE
        mark_failed(job, error_message)
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
    user: UserState = Depends(get_current_user),
) -> CreateGenerationResponse:
    """Return the latest status for a generation job."""

    job = get_job(job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")

    return CreateGenerationResponse(**to_response(job))


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

    if event.type == "started":
        mark_started(job)
    elif event.type == "result":
        if event.result is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Result event requires a payload",
            )
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
            try:
                if job.job_type == "image_edit":
                    _publish_image_edit_completed_notification(job)
                else:
                    _publish_generation_completed_notification(job)
            except Exception:
                logger.exception("Failed to publish completion notification for generation job %s", job.id)
    elif event.type == "failed":
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
        try:
            if job.job_type == "image_edit":
                _publish_image_edit_failed_notification(job)
            else:
                _publish_generation_failed_notification(job)
        except Exception:
            logger.exception("Failed to publish failure notification for generation job %s", job.id)
    else:  # pragma: no cover - safeguard for future event types
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported event type",
        )

    return CreateGenerationResponse(**to_response(job))
