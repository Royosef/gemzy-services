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
    GenerationUiCatalogResponse,
    GenerationJobEvent,
    GenerationResultPayload,
    GenerationUploadPayload,
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
            detail=f"Image '{upload.name or 'upload'}' is too large. Please upload an image smaller than 15MB."
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

        storage_prefix = f"{_user_storage_prefix(job.user_id)}/generations/{job.id}"
        storage_name = f"{storage_prefix}/{uuid4().hex}.png"
        blob = bucket.blob(storage_name)

        metadata = {
            "appUserId": job.user_id,
            "source": "generation",
            "jobId": job.id,
        }
        if COLLECTIONS_OWNER_METADATA_KEY and COLLECTIONS_OWNER_METADATA_KEY != "appUserId":
            metadata[COLLECTIONS_OWNER_METADATA_KEY] = job.user_id
        if job.model_id:
            metadata["modelId"] = job.model_id
        if job.model_name:
            metadata["modelName"] = job.model_name

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
            metadata_payload: dict[str, Any] = {
                "contentType": "image/png",
                "size": len(image_bytes),
                "source": "generation",
                "jobId": job.id,
                "durationMs": int((datetime.utcnow() - job.created_at).total_seconds() * 1000),
            }
            if job.model_id:
                metadata_payload["modelId"] = job.model_id
            if job.model_name:
                metadata_payload["modelName"] = job.model_name
            if job.style:
                metadata_payload["style"] = job.style

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
        "costPerLook": COST_PER_LOOK
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
    
    callback_url = _build_callback_url(job_id)
    target_url = _resolve_generation_url(
        payload.generationServerUrl
    )
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
    elif event.type == "progress":
        if event.progress is None and event.completedLooks is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Progress event requires progress or completed count",
            )
        progress = event.progress if event.progress is not None else job.progress
        update_progress(job, progress, event.completedLooks)
    elif event.type == "completed":
        mark_completed(job)
        try:
            _publish_generation_completed_notification(job)
        except Exception:
            logger.exception("Failed to publish completion notification for generation job %s", job.id)
    elif event.type == "failed":
        if event.error:
            logger.warning("Generation job %s failed: %s", job.id, event.error[:1000])
        else:
            logger.warning("Generation job %s failed without an error payload", job.id)
        mark_failed(job, GENERATION_JOB_FAILURE_MESSAGE)
        try:
            _publish_generation_failed_notification(job)
        except Exception:
            logger.exception("Failed to publish failure notification for generation job %s", job.id)
    else:  # pragma: no cover - safeguard for future event types
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported event type",
        )

    return CreateGenerationResponse(**to_response(job))
