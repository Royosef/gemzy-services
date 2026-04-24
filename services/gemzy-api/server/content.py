"""Content and catalog endpoints."""

from __future__ import annotations

import mimetypes
import os
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse
from uuid import uuid4, UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .auth import get_current_user
from .schemas import (
    AddCollectionItemsPayload,
    Collection,
    CollectionImage,
    CollectionImageInput,
    CollectionItemsPage,
    CollectionUploadAuthorization,
    CollectionUploadRequest,
    CreateCollectionPayload,
    DeleteImagesPayload,
    DeleteImagesResponse,
    Model,
    ModelGalleryImage,
    MoveImagesPayload,
    MoveImagesResponse,
    SignedUrlResponse,
    UpdateCollectionPayload,
    UpdateModelPayload,
    UserState,
)
from .supabase_client import get_client
from .storage import (
    generate_signed_read_url_v4,
    get_bucket,
    maybe_get_bucket,
    user_storage_prefix,
)

_COLLECTIONS_BUCKET_CACHE = None

collections_router = APIRouter(prefix="/collections", tags=["collections"])
models_router = APIRouter(prefix="/models", tags=["models"])

mimetypes.add_type("image/webp", ".webp")

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------

COLLECTIONS_PUBLIC_BUCKET = os.getenv("GCS_COLLECTIONS_PUBLIC_BUCKET")
COLLECTIONS_APP_BUCKET = (
    os.getenv("GCS_COLLECTIONS_APP_BUCKET") or COLLECTIONS_PUBLIC_BUCKET
)
COLLECTIONS_PROJECT = os.getenv("GCS_PROJECT")

COLLECTIONS_UPLOAD_TTL = int(os.getenv("GCS_UPLOAD_URL_TTL", "900"))
COLLECTIONS_VIEW_TTL = int(os.getenv("GCS_VIEW_URL_TTL", "900"))
COLLECTIONS_CACHE_CONTROL = os.getenv(
    "GCS_COLLECTIONS_CACHE_CONTROL", "public, max-age=31536000, immutable"
)
COLLECTIONS_MAX_UPLOAD_BYTES = int(os.getenv("GCS_UPLOAD_MAX_BYTES", "26214400"))
COLLECTIONS_OWNER_METADATA_KEY = os.getenv("GCS_OWNER_METADATA_KEY", "appUserId")

DEFAULT_UNSAVED_COLLECTION_NAME = os.getenv(
    "DEFAULT_UNSAVED_COLLECTION_NAME", "Draft Images"
)
LEGACY_UNSAVED_COLLECTION_NAMES = tuple(
    name.strip()
    for name in os.getenv("LEGACY_UNSAVED_COLLECTION_NAMES", "Unsaved").split(",")
    if name.strip()
)

# ------------------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------------------


def _user_storage_prefix(user_id: str) -> str:
    return user_storage_prefix(user_id)


def _maybe_get_collections_bucket():
    """
    Return the collections bucket if configured, using a simple module-level cache.
    """
    global _COLLECTIONS_BUCKET_CACHE
    if _COLLECTIONS_BUCKET_CACHE is not None:
        return _COLLECTIONS_BUCKET_CACHE

    bucket = maybe_get_bucket(COLLECTIONS_APP_BUCKET, COLLECTIONS_PROJECT)
    _COLLECTIONS_BUCKET_CACHE = bucket
    return bucket


def _get_collections_bucket():
    """
    Return the collections bucket or raise if not configured, using the same cache.
    """
    global _COLLECTIONS_BUCKET_CACHE
    if _COLLECTIONS_BUCKET_CACHE is not None:
        return _COLLECTIONS_BUCKET_CACHE

    bucket = get_bucket(
        COLLECTIONS_APP_BUCKET,
        COLLECTIONS_PROJECT,
        missing_message="Storage bucket is not configured",
    )
    _COLLECTIONS_BUCKET_CACHE = bucket
    return bucket


def _normalize_storage_path(value: str | None) -> str | None:
    """Return a normalized storage object path (without bucket/scheme)."""

    if not value:
        return None

    trimmed = value.strip()
    if not trimmed:
        return None

    # Handle gs://bucket/path
    if trimmed.startswith("gs://"):
        without_scheme = trimmed[5:]
        parts = without_scheme.split("/", 1)
        trimmed = parts[1] if len(parts) == 2 else ""

    parsed = urlparse(trimmed)
    if parsed.scheme in {"http", "https"}:
        trimmed = parsed.path.lstrip("/")
    else:
        trimmed = trimmed.lstrip("/")

    return trimmed or None


def _has_public_scheme(uri: str) -> bool:
    """Return True when the URI uses an already public scheme."""

    normalized = uri.lower()
    return (
        normalized.startswith("http://")
        or normalized.startswith("https://")
        or normalized.startswith("data:")
    )


def _resolve_incoming_image_uri(uri: str, storage_path: str | None) -> str:
    """
    Return a URL or storage path that can be safely persisted.

    Priority:
    - storage_path (normalized GCS path)
    - public HTTP/data URL
    - normalized path derived from URI
    - original URI as a last resort
    """

    if storage_path:
        return storage_path

    if _has_public_scheme(uri):
        return uri

    normalized = _normalize_storage_path(uri)
    if normalized:
        return normalized

    return uri


def _coerce_str(value: Any) -> str | None:
    """Return a stripped string representation when possible."""

    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _extract_model_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Extract model identifiers from metadata objects."""

    if not isinstance(metadata, Mapping):
        return None, None

    model_id: str | None = None
    model_name: str | None = None

    model_entry = metadata.get("model")
    if isinstance(model_entry, Mapping):
        model_id = _coerce_str(
            model_entry.get("id")
            or model_entry.get("modelId")
            or model_entry.get("slug")
        )
        model_name = _coerce_str(
            model_entry.get("name")
            or model_entry.get("displayName")
            or model_entry.get("title")
        )
    elif isinstance(model_entry, str):
        model_name = _coerce_str(model_entry)

    for key in ("modelId", "model_id", "modelID", "leadModelId", "lead_model_id"):
        model_id = model_id or _coerce_str(metadata.get(key))

    for key in (
        "modelName",
        "model_name",
        "modelTitle",
        "leadModel",
        "lead_model",
        "modelDisplayName",
    ):
        model_name = model_name or _coerce_str(metadata.get(key))

    return model_id, model_name


def _extract_model_identifiers(
    image: CollectionImageInput,
    metadata: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Determine model identifiers from the incoming payload and metadata."""

    model_id = _coerce_str(getattr(image, "modelId", None))
    model_name = _coerce_str(getattr(image, "modelName", None))

    meta_model_id, meta_model_name = _extract_model_from_metadata(metadata)
    model_id = model_id or meta_model_id
    model_name = model_name or meta_model_name

    return model_id, model_name


def _generate_signed_image_url(
    normalized_path: str, *, ttl_seconds: int | None = None
) -> str | None:
    """Return a signed URL for the provided storage path when possible."""

    bucket = _maybe_get_collections_bucket()
    if bucket is None:
        return None

    try:
        blob = bucket.blob(normalized_path)
        return generate_signed_read_url_v4(
            blob,
            seconds=max(60, ttl_seconds or COLLECTIONS_VIEW_TTL),
        )
    except Exception:  # best effort
        return None


def _resolve_collection_image_variants(
    image_url: str | None,
    external_id: str | None,
    *,
    include_signed: bool = False,
) -> tuple[str | None, str | None]:
    """
    Return (preview, full) URLs for a stored collection image.

    When signing is enabled we generate distinct preview/full signatures so the
    client can progressively upgrade cached assets without reusing expired URLs.
    """

    candidates = [external_id, image_url]
    candidate: str | None = None

    for value in candidates:
        if isinstance(value, str) and value.strip():
            candidate = value.strip()
            break

    if not candidate:
        return None, None

    if _has_public_scheme(candidate):
        return candidate, candidate

    normalized = _normalize_storage_path(candidate)
    if not normalized:
        return candidate, candidate

    if include_signed:
        # Single signing operation; use the same URL for preview and full.
        signed = _generate_signed_image_url(
            normalized,
            ttl_seconds=max(60, COLLECTIONS_VIEW_TTL),
        )
        return signed or normalized, signed or normalized

    return normalized, normalized


def _guess_extension(content_type: str | None) -> str:
    """Return a file extension (with leading dot) for the provided MIME type."""

    if not content_type:
        return ".jpg"

    normalized = content_type.split(";")[0].strip().lower()
    if not normalized:
        return ".jpg"

    ext = mimetypes.guess_extension(normalized)
    if ext:
        return ext

    if normalized == "image/jpg":
        return ".jpg"

    return ".jpg"


def _isoformat(value: str | datetime | None) -> str:
    """Normalize timestamps to ISO8601 without microseconds."""

    if value is None:
        return datetime.utcnow().replace(microsecond=0).isoformat()
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return value


def _ensure_collections_belong(user_id: str, ids: Sequence[str]) -> None:
    """Ensure the given collection IDs belong to the user."""

    if not ids:
        return

    
    valid_ids = []
    for cid in ids:
        try:
            UUID(cid)
            valid_ids.append(cid)
        except (ValueError, TypeError):
            continue

    if not valid_ids:
        # If passed IDs are invalid, they won't be found, so we raise 404 naturally via the missing check logic?
        # Or if ids was not empty but valid_ids is empty, then "missing" will equal "ids".
        # missing = [cid for cid in ids if cid not in found] -> all ids.
        # So we can just proceed with empty valid_ids query, which returns empty rows.
        pass

    sb = get_client()
    rows = (
        sb.table("collections")
        .select("id")
        .eq("user_id", user_id)
        .in_("id", valid_ids)
        .execute()
    ).data or []

    found = {row["id"] for row in rows}
    missing = [cid for cid in ids if cid not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )


def _extract_lead_model(metadata: dict | None) -> str | None:
    """Best-effort extraction of the lead model from image metadata."""

    if not metadata:
        return None

    candidates: list[str | None] = []

    value = metadata.get("model") if isinstance(metadata, dict) else None
    if isinstance(value, dict):
        candidates.extend(
            [value.get("name"), value.get("displayName"), value.get("title")]
        )
    elif isinstance(value, str):
        candidates.append(value)

    if isinstance(metadata, dict):
        candidates.extend(
            [
                metadata.get("modelName"),
                metadata.get("model_name"),
                metadata.get("modelTitle"),
                metadata.get("leadModel"),
            ]
        )

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    return None


def _fetch_model_records(model_ids: set[str]) -> dict[str, dict[str | None]]:
    """Return name and avatar metadata for the provided model identifiers."""

    if not model_ids:
        return {}

    # Filter out invalid UUIDs to prevent database errors (like 22P02)
    valid_ids = []
    for mid in model_ids:
        try:
            UUID(mid)
            valid_ids.append(mid)
        except (ValueError, TypeError):
            continue

    if not valid_ids:
        return {}

    sb = get_client()
    rows = (
        sb.table("models")
        .select("id,name,image_url")
        .in_("id", valid_ids)
        .execute()
    ).data or []

    records: dict[str, dict[str | None]] = {}
    for row in rows:
        model_id = _coerce_str(row.get("id"))
        if not model_id:
            continue
        records[model_id] = {
            "name": _coerce_str(row.get("name")),
            "image_url": _coerce_str(row.get("image_url")),
        }

    return records


# ------------------------------------------------------------------------------
# Collections: internal mapping / fetch logic
# ------------------------------------------------------------------------------


def _map_collections(
    rows: Sequence[dict],
    items: Sequence[dict],
    *,
    include_items: bool = False,
) -> list[Collection]:
    """Map raw DB rows + items into API Collection objects."""

    items_by_collection: dict[
        str, list[tuple[str | datetime | None, CollectionImage]]
    ] = {}
    model_ids: set[str] = set()

    for item in items:
        candidate = _coerce_str(item.get("model_id"))
        if candidate:
            model_ids.add(candidate)

    model_records = _fetch_model_records(model_ids)

    for item in items:
        collection_id = item.get("collection_id")
        if not collection_id:
            continue

        storage_path = _normalize_storage_path(item.get("external_id"))
        preview_uri, resolved_uri = _resolve_collection_image_variants(
            item.get("image_url"),
            storage_path,
            include_signed=include_items,
        )

        model_id = _coerce_str(item.get("model_id"))
        model_name = _coerce_str(item.get("model_name"))
        if model_id and not model_name:
            record = model_records.get(model_id)
            if record:
                model_name = record.get("name")

        collection_item = CollectionImage(
            id=item.get("external_id") or item.get("id"),
            uri=resolved_uri,
            previewUri=preview_uri,
            category=item.get("category"),
            isNew=bool(item.get("is_new")),
            isFavorite=bool(item.get("is_favorite")),
            metadata=item.get("metadata"),
            modelId=model_id,
            modelName=model_name,
            storagePath=storage_path,
        )

        items_by_collection.setdefault(collection_id, []).append(
            (item.get("created_at"), collection_item)
        )

    def _item_sort_key(value: tuple[str | datetime | None, CollectionImage]) -> float:
        created_at, _image = value
        if isinstance(created_at, datetime):
            return -created_at.timestamp()
        try:
            iso_value = str(created_at)
            if iso_value.endswith("Z"):
                iso_value = iso_value.replace("Z", "+00:00")
            return -datetime.fromisoformat(iso_value).timestamp()
        except Exception:
            return 0.0

    mapped: list[Collection] = []
    for row in rows:
        cid = row.get("id")
        sorted_items = sorted(items_by_collection.get(cid, []), key=_item_sort_key)

        cover_preview, cover_url = _resolve_collection_image_variants(
            row.get("cover_url"),
            None,
            include_signed=include_items,
        )

        lead_model_payload: dict[str, Any] | None = None
        if sorted_items:
            lead_counts: dict[str, dict[str, Any]] = {}
            for index, (_created_at, image) in enumerate(sorted_items):
                candidate_id = getattr(image, "modelId", None) or None
                candidate_name = getattr(image, "modelName", None) or None

                if candidate_id and not candidate_name:
                    record = model_records.get(candidate_id)
                    if record:
                        candidate_name = record.get("name")

                if not candidate_name and getattr(image, "metadata", None):
                    metadata = (
                        image.metadata if isinstance(image.metadata, Mapping) else None
                    )
                    if metadata:
                        candidate_name = _extract_lead_model(metadata)

                key = candidate_id or candidate_name
                if not key:
                    continue

                entry = lead_counts.get(key)
                if entry is None:
                    entry = {
                        "id": candidate_id,
                        "name": candidate_name,
                        "count": 0,
                        "first_seen": index,
                    }
                    lead_counts[key] = entry

                entry["count"] += 1
                if candidate_name and not entry.get("name"):
                    entry["name"] = candidate_name

            if lead_counts:
                ordered = sorted(
                    lead_counts.values(),
                    key=lambda entry: (-entry["count"], entry["first_seen"]),
                )
                chosen = next((entry for entry in ordered if entry.get("id")), None)
                if chosen is None:
                    chosen = ordered[0]

                if chosen:
                    record = (
                        model_records.get(chosen.get("id"))
                        if chosen.get("id")
                        else None
                    )
                    avatar_url = record.get("image_url") if record else None
                    name = chosen.get("name") or (
                        record.get("name") if record else None
                    )
                    lead_model_payload = {
                        "id": chosen.get("id"),
                        "name": name,
                        "avatarUrl": avatar_url,
                    }

        mapped.append(
            Collection(
                id=cid,
                name=row.get("name"),
                cover=cover_url,
                coverPreview=cover_preview,
                createdAt=_isoformat(row.get("created_at")),
                curatedBy=row.get("curated_by"),
                liked=bool(row.get("liked")),
                tags=row.get("tags") or [],
                description=row.get("description"),
                items=[entry[1] for entry in sorted_items] if include_items else None,
                leadModel=lead_model_payload,
            )
        )

    return mapped


def _fetch_collections(
    user_id: str,
    ids: Sequence[str] | None = None,
    *,
    include_items: bool = False,
) -> list[Collection]:
    """Fetch collections (and optionally their items) for a user."""

    sb = get_client()
    query = (
        sb.table("collections")
        .select("id,name,cover_url,curated_by,description,tags,created_at,liked")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
    )

    if ids:
        valid_ids = []
        for cid in ids:
            try:
                UUID(cid)
                valid_ids.append(cid)
            except (ValueError, TypeError):
                continue
        
        if not valid_ids:
            return []
            
        query = query.in_("id", valid_ids)

    rows = query.execute().data or []
    if not rows:
        return []

    collection_ids = [row["id"] for row in rows if row.get("id")]

    # Fetch the latest item created_at per collection so we can sort
    # collections by most-recently-added image instead of collection creation.
    latest_item_dates: dict[str, str] = {}
    try:
        latest_items = (
            sb.table("collection_items")
            .select("collection_id,created_at")
            .in_("collection_id", collection_ids)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        ).data or []
        for item in latest_items:
            cid = item.get("collection_id")
            if cid and cid not in latest_item_dates:
                latest_item_dates[cid] = item.get("created_at", "")
    except Exception:
        pass  # If this fails, we keep the original created_at order

    # Re-sort: collections with the newest item first
    if latest_item_dates:
        rows.sort(
            key=lambda row: latest_item_dates.get(row.get("id", ""), row.get("created_at", "")),
            reverse=True,
        )

    items: list[dict] = []

    if include_items and collection_ids:
        items = (
            sb.table("collection_items")
            .select(
                "collection_id,external_id,id,image_url,category,"
                "is_new,is_favorite,metadata,created_at,model_id,model_name"
            )
            .in_("collection_id", collection_ids)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        ).data or []

    return _map_collections(rows, items, include_items=include_items)


@collections_router.get("/recent-items", response_model=list[CollectionImage])
def get_recent_collection_items(
    limit: int = Query(20, ge=1, le=100),
    user: UserState = Depends(get_current_user),
) -> list[CollectionImage]:
    """Fetch the most recent collection items across all collections."""
    sb = get_client()
    
    # minimal join or just fetch items. We need model info too maybe?
    # actually existing fetch_collections logic fetches items then fetches models separately if needed.
    # Let's simplify and just fetch items.
    
    items = (
        sb.table("collection_items")
        .select(
            "collection_id,external_id,id,image_url,category,"
            "is_new,is_favorite,metadata,created_at,model_id,model_name"
        )
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []
    
    # Prefetch models if needed
    model_ids: set[str] = set()
    for item in items:
        candidate = _coerce_str(item.get("model_id"))
        if candidate:
            model_ids.add(candidate)
            
    model_records = _fetch_model_records(model_ids)
    
    mapped: list[CollectionImage] = []
    
    for item in items:
        storage_path = _normalize_storage_path(item.get("external_id"))
        
        # Include signed URLs for immediate display
        preview_uri, resolved_uri = _resolve_collection_image_variants(
            item.get("image_url"),
            storage_path,
            include_signed=True, 
        )
        
        model_id = _coerce_str(item.get("model_id"))
        model_name = _coerce_str(item.get("model_name"))
        if model_id and not model_name:
            record = model_records.get(model_id)
            if record:
                model_name = record.get("name")
                
        mapped.append(
            CollectionImage(
                id=item.get("external_id") or item.get("id"),
                uri=resolved_uri,
                previewUri=preview_uri,
                category=item.get("category"),
                isNew=bool(item.get("is_new")),
                isFavorite=bool(item.get("is_favorite")),
                metadata=item.get("metadata"),
                modelId=model_id,
                modelName=model_name,
                storagePath=storage_path,
            )
        )
        
    return mapped


# ------------------------------------------------------------------------------
# Collections: storage & uploads
# ------------------------------------------------------------------------------


def _generate_upload_authorization(
    user_id: str, request: CollectionUploadRequest
) -> CollectionUploadAuthorization:
    """Return a signed upload URL for a new collection image."""

    content_type = (request.contentType or "image/jpeg").split(";")[0].strip()
    if not content_type:
        content_type = "image/jpeg"

    if not content_type.lower().startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image uploads are supported",
        )

    if request.size and request.size > COLLECTIONS_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image exceeds maximum allowed size",
        )

    prefix = _user_storage_prefix(user_id)
    extension = _guess_extension(content_type)
    object_id = uuid4().hex
    object_path = f"{prefix}/{object_id}{extension}"

    bucket = _get_collections_bucket()
    blob = bucket.blob(object_path)

    expiration = timedelta(seconds=max(60, COLLECTIONS_UPLOAD_TTL))
    try:
        upload_url = blob.generate_signed_url(
            version="v4",
            expiration=expiration,
            method="PUT",
            content_type=content_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to generate upload URL",
        ) from exc

    expires_at = (datetime.utcnow() + expiration).replace(
        microsecond=0
    ).isoformat() + "Z"

    headers = {"Content-Type": content_type}
    if request.size:
        headers.setdefault("Content-Length", str(request.size))

    view_url: str | None = None
    ttl_seconds = int(expiration.total_seconds())
    try:
        view_url = generate_signed_read_url_v4(blob, seconds=ttl_seconds)
    except Exception:
        view_url = None

    return CollectionUploadAuthorization(
        uploadUrl=upload_url,
        storagePath=object_path,
        publicUrl=view_url or object_path,
        headers=headers,
        expiresAt=expires_at,
    )


def _finalize_collection_objects(
    entries: Iterable[tuple[str, str | None, str | None]],
) -> None:
    """Apply metadata / cache headers for newly uploaded objects."""

    bucket = _maybe_get_collections_bucket()
    if bucket is None:
        return

    seen: set[str] = set()
    for storage_path, content_type, user_id in entries:
        normalized = (storage_path or "").strip().lstrip("/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)

        try:
            blob = bucket.blob(normalized)
            updates = False
            metadata = dict(blob.metadata or {})

            if user_id:
                metadata.setdefault("appUserId", user_id)
                if COLLECTIONS_OWNER_METADATA_KEY:
                    metadata[COLLECTIONS_OWNER_METADATA_KEY] = user_id

            if metadata:
                blob.metadata = metadata
                updates = True

            if content_type:
                blob.content_type = content_type
                updates = True

            if COLLECTIONS_CACHE_CONTROL:
                blob.cache_control = COLLECTIONS_CACHE_CONTROL
                updates = True

            if updates:
                blob.patch()
        except Exception:
            continue


def _prepare_collection_images(
    images: Sequence[CollectionImageInput], user_id: str
) -> list[dict[str, object]]:
    """Normalize and validate incoming collection image payloads."""

    prepared: list[dict[str, object]] = []
    touched: list[tuple[str, str | None, str | None]] = []
    prefix = f"{_user_storage_prefix(user_id)}/"

    for image in images:
        raw_uri = (image.uri or "").strip()
        if not raw_uri:
            continue

        storage_path = _normalize_storage_path(getattr(image, "storagePath", None))
        if storage_path:
            if storage_path.startswith(prefix):
                # Valid user-owned GCS path — finalize metadata on the object.
                touched.append((storage_path, image.contentType, user_id))
            else:
                # The provided path is not under this user's prefix (e.g. a
                # UUID-hex external_id or a full https:// URL whose path
                # includes the bucket name).  Treat it as absent so we fall
                # back to using the URI as the canonical image reference.
                storage_path = None
        else:
            derived_path = None
            if not _has_public_scheme(raw_uri):
                derived_path = _normalize_storage_path(raw_uri)
            if derived_path and derived_path.startswith(prefix):
                storage_path = derived_path
                touched.append((storage_path, image.contentType, user_id))

        external_id = storage_path or uuid4().hex

        metadata: dict[str, object] = {}
        if image.contentType:
            metadata["contentType"] = image.contentType
        if image.size is not None:
            metadata["size"] = image.size
        if image.width is not None:
            metadata["width"] = image.width
        if image.height is not None:
            metadata["height"] = image.height
        if image.hash:
            metadata["hash"] = image.hash
        if image.name:
            metadata["name"] = image.name

        metadata.setdefault("appUserId", user_id)
        if (
            COLLECTIONS_OWNER_METADATA_KEY
            and COLLECTIONS_OWNER_METADATA_KEY != "appUserId"
        ):
            metadata.setdefault(COLLECTIONS_OWNER_METADATA_KEY, user_id)

        model_id, model_name = _extract_model_identifiers(image, metadata)
        if model_id and "modelId" not in metadata:
            metadata["modelId"] = model_id
        if model_name and "modelName" not in metadata:
            metadata["modelName"] = model_name

        resolved_uri = _resolve_incoming_image_uri(raw_uri, storage_path)

        prepared.append(
            {
                "external_id": external_id,
                "image_url": resolved_uri,
                "category": image.category,
                "metadata": metadata or None,
                "model_id": model_id,
                "model_name": model_name,
                "storage_path": storage_path,
            }
        )

    if touched:
        _finalize_collection_objects(touched)

    return prepared


def _refresh_collection_cover(collection_id: str, user_id: str | None = None) -> None:
    """Refresh the collection cover based on latest item."""

    sb = get_client()
    query = (
        sb.table("collection_items")
        .select("image_url,external_id")
        .eq("collection_id", collection_id)
        .order("created_at", desc=True)
        .limit(1)
    )
    if user_id:
        query = query.eq("user_id", user_id)

    resp = query.execute()
    image_url = None
    data = resp.data or []
    if data:
        first = data[0]
        image_url = first.get("image_url") or first.get("external_id")

    if image_url:
        sb.table("collections").update({"cover_url": image_url}).eq(
            "id", collection_id
        ).execute()


def ensure_unsaved_collection(user_id: str) -> str:
    """Ensure the user has a Draft/Unsaved collection and return its ID."""

    sb = get_client()

    # Try existing
    existing = (
        sb.table("collections")
        .select("id")
        .eq("user_id", user_id)
        .eq("name", DEFAULT_UNSAVED_COLLECTION_NAME)
        .limit(1)
        .execute()
    ).data or []
    if existing:
        cid = _coerce_str(existing[0].get("id"))
        if cid:
            return cid

    # Try legacy names and rename them
    if LEGACY_UNSAVED_COLLECTION_NAMES:
        legacy = (
            sb.table("collections")
            .select("id,name")
            .eq("user_id", user_id)
            .in_("name", list(LEGACY_UNSAVED_COLLECTION_NAMES))
            .limit(1)
            .execute()
        ).data or []
        if legacy:
            cid = _coerce_str(legacy[0].get("id"))
            if cid:
                legacy_name = _coerce_str(legacy[0].get("name"))
                if legacy_name and legacy_name != DEFAULT_UNSAVED_COLLECTION_NAME:
                    try:
                        (
                            sb.table("collections")
                            .update({"name": DEFAULT_UNSAVED_COLLECTION_NAME})
                            .eq("id", cid)
                            .eq("user_id", user_id)
                            .execute()
                        )
                    except Exception:
                        pass
                return cid

    # Create
    created_resp = (
        sb.table("collections")
        .insert(
            {
                "user_id": user_id,
                "name": DEFAULT_UNSAVED_COLLECTION_NAME,
                "liked": False,
            },
            returning="representation",
        )
        .execute()
    )
    created = created_resp.data or []
    if created:
        cid = _coerce_str(created[0].get("id"))
        if cid:
            return cid

    # Fallback re-fetch (handles concurrent creation)
    fallback = (
        sb.table("collections")
        .select("id")
        .eq("user_id", user_id)
        .eq("name", DEFAULT_UNSAVED_COLLECTION_NAME)
        .limit(1)
        .execute()
    ).data or []
    if fallback:
        cid = _coerce_str(fallback[0].get("id"))
        if cid:
            return cid

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unable to prepare Draft collection",
    )


def _remove_from_unsaved_collection(
    user_id: str,
    storage_paths: Sequence[str],
    *,
    skip_collection_id: str | None = None,
) -> None:
    """Remove generated assets from the Draft collection once filed elsewhere."""

    normalized: list[str] = []
    seen: set[str] = set()
    for value in storage_paths:
        candidate = _normalize_storage_path(value)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)

    if not normalized:
        return

    try:
        unsaved_id = ensure_unsaved_collection(user_id)
    except HTTPException:
        return

    if skip_collection_id and unsaved_id == skip_collection_id:
        return

    sb = get_client()
    try:
        (
            sb.table("collection_items")
            .delete()
            .eq("user_id", user_id)
            .eq("collection_id", unsaved_id)
            .in_("external_id", normalized)
            .execute()
        )
    except Exception:
        return

    _refresh_collection_cover(unsaved_id, user_id)


# ------------------------------------------------------------------------------
# Collections: API routes
# ------------------------------------------------------------------------------


@collections_router.get(
    "/{collection_id}/items",
    response_model=CollectionItemsPage,
)
def list_collection_items(
    collection_id: str,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    includeSigned: bool = True,  # whether to return signed URLs
    current: UserState = Depends(get_current_user),
) -> CollectionItemsPage:
    """Return paginated items for a single collection."""

    sb = get_client()

    # Base ordered query: already scoped by user + collection,
    # so we don't need a separate _ensure_collections_belong call up front.
    query = (
        sb.table("collection_items")
        .select(
            "collection_id,external_id,id,image_url,category,"
            "is_new,is_favorite,metadata,created_at,model_id,model_name"
        )
        .eq("user_id", current.id)
        .eq("collection_id", collection_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
    )

    # Keyset pagination using created_at (id kept only for cursor stability)
    if cursor:
        # cursor format: "<created_at_iso>|<id>"
        try:
            created_at_str, _cursor_id = cursor.split("|", 1)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid cursor",
            )

        # For now we paginate only by created_at DESC.
        # If strict tie-breaking is needed, this is where you'd add an extra condition on id.
        query = query.lt("created_at", created_at_str)

    # Fetch one extra row to know if there's a next page
    rows = (query.limit(limit + 1).execute().data) or []

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items: list[CollectionImage] = []
    next_cursor: str | None = None

    for row in page_rows:
        raw_external_id = row.get("external_id")
        # Normalized storage path for client usage and signing
        storage_path = _normalize_storage_path(raw_external_id)

        preview_uri, resolved_uri = _resolve_collection_image_variants(
            row.get("image_url"),
            storage_path,
            include_signed=includeSigned,
        )

        model_id = _coerce_str(row.get("model_id"))
        model_name = _coerce_str(row.get("model_name"))

        items.append(
            CollectionImage(
                id=raw_external_id or row.get("id"),
                uri=resolved_uri or "",
                previewUri=preview_uri,
                category=row.get("category"),
                isNew=bool(row.get("is_new")),
                isFavorite=bool(row.get("is_favorite")),
                metadata=row.get("metadata"),
                modelId=model_id,
                modelName=model_name,
                storagePath=storage_path,
            )
        )

    if has_more and page_rows:
        last = page_rows[-1]
        created_at = last.get("created_at")
        if isinstance(created_at, datetime):
            created_str = created_at.replace(microsecond=0).isoformat() + "Z"
        else:
            created_str = str(created_at)
        last_id = _coerce_str(last.get("id") or last.get("external_id")) or ""
        next_cursor = f"{created_str}|{last_id}"

    return CollectionItemsPage(items=items, nextCursor=next_cursor)


@collections_router.get(
    "/items/{external_id:path}/signed-url",
    response_model=SignedUrlResponse,
)
def generate_item_signed_url(
    external_id: str,
    variant: str | None = None,
    includePreview: bool = False,  # noqa: N803 - API casing
    current: UserState = Depends(get_current_user),
) -> SignedUrlResponse:
    """Return a short-lived signed URL for a stored collection item."""

    if variant == "preview":
        includePreview = True

    normalized = _normalize_storage_path(external_id)
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    # Security check: ensure the object is under the current user's prefix
    prefix = f"{_user_storage_prefix(current.id)}/"
    if not normalized.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    bucket = _maybe_get_collections_bucket()
    if bucket is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage bucket is not configured",
        )

    blob = bucket.blob(normalized)
    expiration = timedelta(seconds=max(60, COLLECTIONS_VIEW_TTL))

    try:
        # Single signing call; reuse for preview if requested
        url = generate_signed_read_url_v4(
            blob,
            seconds=int(expiration.total_seconds()),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to generate signed URL",
        ) from exc

    if not url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to generate signed URL",
        )

    preview_url = url if includePreview else None
    expires_at = (datetime.utcnow() + expiration).replace(
        microsecond=0
    ).isoformat() + "Z"

    return SignedUrlResponse(url=url, previewUrl=preview_url, expiresAt=expires_at)


@collections_router.get("/", response_model=list[Collection])
def list_collections(
    includeItems: bool = False,  # noqa: N803 - API casing
    current: UserState = Depends(get_current_user),
) -> list[Collection]:
    """Return all collections that belong to the authenticated user."""

    return _fetch_collections(current.id, include_items=includeItems)


@collections_router.post(
    "/uploads",
    response_model=CollectionUploadAuthorization,
    status_code=status.HTTP_201_CREATED,
)
def authorize_collection_upload(
    payload: CollectionUploadRequest,
    current: UserState = Depends(get_current_user),
) -> CollectionUploadAuthorization:
    """Return a signed URL that allows the client to upload an image to storage."""

    if payload.size is not None and payload.size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image size must be positive",
        )

    return _generate_upload_authorization(current.id, payload)


@collections_router.post(
    "/", response_model=Collection, status_code=status.HTTP_201_CREATED
)
def create_collection_endpoint(
    payload: CreateCollectionPayload,
    current: UserState = Depends(get_current_user),
) -> Collection:
    """Create a new collection and upload its initial items."""

    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collection name is required",
        )

    prepared = _prepare_collection_images(payload.images, current.id)
    if not prepared:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one image is required",
        )

    collection_id = uuid4().hex
    timestamp = datetime.utcnow().isoformat()

    sb = get_client()
    sb.table("collections").insert(
        {
            "id": collection_id,
            "user_id": current.id,
            "name": name,
            "cover_url": prepared[0]["image_url"] if prepared else None,
            "curated_by": current.name,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    ).execute()

    if prepared:
        items = []
        for item in prepared:
            item_id = uuid4().hex
            payload_item: dict[str, Any] = {
                "id": item_id,
                "collection_id": collection_id,
                "user_id": current.id,
                "external_id": item["external_id"],
                "image_url": item["image_url"],
                "category": item.get("category"),
                "is_new": True,
            }
            metadata = item.get("metadata")
            if metadata:
                payload_item["metadata"] = metadata
            model_id = item.get("model_id")
            if model_id:
                payload_item["model_id"] = model_id
            model_name = item.get("model_name")
            if model_name:
                payload_item["model_name"] = model_name
            items.append(payload_item)

        sb.table("collection_items").insert(items).execute()
        _refresh_collection_cover(collection_id, current.id)

    moved_paths = [
        item.get("storage_path")
        for item in prepared
        if isinstance(item.get("storage_path"), str)
    ]
    if moved_paths:
        _remove_from_unsaved_collection(
            current.id,
            moved_paths,
            skip_collection_id=collection_id,
        )

    collections = _fetch_collections(current.id, [collection_id], include_items=False)
    if not collections:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create collection",
        )

    return collections[0]


@collections_router.post("/{collection_id}/items", response_model=Collection)
def add_collection_items(
    collection_id: str,
    payload: AddCollectionItemsPayload,
    current: UserState = Depends(get_current_user),
) -> Collection:
    """Append new items to an existing collection."""

    _ensure_collections_belong(current.id, [collection_id])

    prepared = _prepare_collection_images(payload.images, current.id)
    if prepared:
        sb = get_client()
        items = []
        for item in prepared:
            item_id = uuid4().hex
            payload_item: dict[str, Any] = {
                "id": item_id,
                "collection_id": collection_id,
                "user_id": current.id,
                "external_id": item["external_id"],
                "image_url": item["image_url"],
                "category": item.get("category"),
                "is_new": True,
            }
            metadata = item.get("metadata")
            if metadata:
                payload_item["metadata"] = metadata
            model_id = item.get("model_id")
            if model_id:
                payload_item["model_id"] = model_id
            model_name = item.get("model_name")
            if model_name:
                payload_item["model_name"] = model_name
            items.append(payload_item)

        sb.table("collection_items").insert(items).execute()
        _refresh_collection_cover(collection_id, current.id)

    moved_paths = [
        item.get("storage_path")
        for item in prepared
        if isinstance(item.get("storage_path"), str)
    ]
    if moved_paths:
        _remove_from_unsaved_collection(
            current.id,
            moved_paths,
            skip_collection_id=collection_id,
        )

    collections = _fetch_collections(current.id, [collection_id], include_items=True)
    if not collections:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )

    return collections[0]


@collections_router.get("/{collection_id}", response_model=Collection)
def retrieve_collection(
    collection_id: str,
    current: UserState = Depends(get_current_user),
) -> Collection:
    """Return a single collection owned by the authenticated user."""

    _ensure_collections_belong(current.id, [collection_id])
    collections = _fetch_collections(
        current.id,
        [collection_id],
        include_items=False,
    )
    if not collections:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found"
        )
    return collections[0]


@collections_router.patch("/{collection_id}", response_model=Collection)
def update_collection(
    collection_id: str,
    payload: UpdateCollectionPayload,
    current: UserState = Depends(get_current_user),
) -> Collection:
    """Update mutable fields for a collection."""

    updates: dict[str, object] = {"updated_at": datetime.utcnow().isoformat()}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.cover is not None:
        updates["cover_url"] = payload.cover
    if payload.liked is not None:
        updates["liked"] = payload.liked

    if len(updates) == 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No changes provided",
        )

    _ensure_collections_belong(current.id, [collection_id])
    sb = get_client()
    sb.table("collections").update(updates).eq("id", collection_id).execute()

    if payload.cover is None:
        _refresh_collection_cover(collection_id, current.id)

    collections = _fetch_collections(current.id, [collection_id], include_items=True)
    if not collections:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )

    return collections[0]


@collections_router.delete("/{collection_id}")
def delete_collection(
    collection_id: str,
    current: UserState = Depends(get_current_user),
) -> dict:
    """Delete a collection and its assets."""

    _ensure_collections_belong(current.id, [collection_id])

    sb = get_client()
    (
        sb.table("collection_items")
        .delete()
        .eq("collection_id", collection_id)
        .eq("user_id", current.id)
        .execute()
    )
    sb.table("collections").delete().eq("id", collection_id).execute()

    return {"deleted": True}


@collections_router.post("/move-images", response_model=MoveImagesResponse)
def move_images(
    payload: MoveImagesPayload,
    current: UserState = Depends(get_current_user),
) -> MoveImagesResponse:
    """Move images between two collections."""

    if payload.sourceId == payload.targetId:
        return MoveImagesResponse(moved=0)

    image_ids = [image_id for image_id in payload.imageIds if image_id]
    if not image_ids:
        return MoveImagesResponse(moved=0)

    _ensure_collections_belong(current.id, [payload.sourceId, payload.targetId])

    sb = get_client()
    response = (
        sb.table("collection_items")
        .update(
            {
                "collection_id": payload.targetId,
                "user_id": current.id,
                "is_new": True,
            }
        )
        .eq("collection_id", payload.sourceId)
        .eq("user_id", current.id)
        .in_("external_id", image_ids)
        .execute()
    )
    moved = len(response.data or [])

    if moved:
        _refresh_collection_cover(payload.sourceId, current.id)
        _refresh_collection_cover(payload.targetId, current.id)

    return MoveImagesResponse(moved=moved)


@collections_router.post("/delete-images", response_model=DeleteImagesResponse)
def delete_images(
    payload: DeleteImagesPayload,
    current: UserState = Depends(get_current_user),
) -> DeleteImagesResponse:
    """Remove images from a collection."""

    image_ids = [image_id for image_id in payload.imageIds if image_id]
    if not image_ids:
        return DeleteImagesResponse(deleted=0)

    _ensure_collections_belong(current.id, [payload.collectionId])

    sb = get_client()
    response = (
        sb.table("collection_items")
        .delete()
        .eq("collection_id", payload.collectionId)
        .eq("user_id", current.id)
        .in_("external_id", image_ids)
        .execute()
    )
    deleted = len(response.data or [])

    if deleted:
        _refresh_collection_cover(payload.collectionId, current.id)

    return DeleteImagesResponse(deleted=deleted)


# ------------------------------------------------------------------------------
# Models: mapping / fetch logic
# ------------------------------------------------------------------------------


def _map_models(
    rows: Sequence[dict],
    gallery_rows: Sequence[dict],
    liked_ids: set[str] | None = None,
) -> list[Model]:
    """Map raw DB rows into API Model objects."""

    gallery_map: dict[str, list[dict]] = {}
    for row in gallery_rows:
        model_id = row.get("model_id")
        if not model_id:
            continue
        gallery_map.setdefault(model_id, []).append(row)

    liked_ids = liked_ids or set()
    mapped: list[Model] = []

    for row in rows:
        model_id = row.get("id")
        gallery: list[ModelGalleryImage] = []

        for order, image in enumerate(gallery_map.get(model_id, [])):
            preview_uri, full_uri = _resolve_collection_image_variants(
                image.get("image_url"),
                None,
                include_signed=True,
            )
            if not full_uri:
                continue

            gallery.append(
                ModelGalleryImage(
                    id=image.get("id") or f"{model_id}-{order}",
                    uri=full_uri,
                    thumbnail=preview_uri or full_uri,
                    order=order,
                )
            )

        mapped.append(
            Model(
                id=model_id,
                slug=row.get("slug"),
                name=row.get("name"),
                PlanTier=row.get("plan"),
                highlight=row.get("highlight"),
                description=row.get("description"),
                img=row.get("image_url"),
                gallery=gallery,
                liked=model_id in liked_ids,
                tags=row.get("tags") or [],
                spotlightTag=row.get("spotlight_tag"),
                stage=row.get("stage"),
            )
        )

    return mapped


def _fetch_models(
    ids: Sequence[str] | None = None,
    slugs: Sequence[str] | None = None,
    user_id: str | None = None,
    include_gallery: bool = True,
) -> list[Model]:
    """Fetch models and optional gallery images."""

    sb = get_client()
    query = (
        sb.table("models")
        .select("id,slug,name,plan,highlight,description,image_url,tags,spotlight_tag,stage")
        .order("display_order")
    )

    # Filter by stage and environment
    app_env = os.getenv("APP_ENV", "development")
    query = query.neq("stage", "inactive")
    if app_env == "production":
        query = query.eq("stage", "prod")
    else:
        # For development/staging, show both prod and dev
        query = query.in_("stage", ["prod", "dev"])

    if ids:
        # Filter out invalid UUIDs to prevent database errors
        valid_ids = []
        for mid in ids:
            try:
                UUID(mid)
                valid_ids.append(mid)
            except (ValueError, TypeError):
                continue
        
        if not valid_ids:
            # If ids were provided but none are valid UUIDs, return empty result instantly
            # unless we fall through (but here we are in 'if ids' block)
            # Actually, if ids are provided but invalid, we should search for nothing or return empty.
            return []
            
        query = query.in_("id", valid_ids)
    elif slugs:
        query = query.in_("slug", list(slugs))

    rows = query.execute().data or []
    if not rows:
        return []

    model_ids = [row.get("id") for row in rows if row.get("id")]
    gallery_rows: list[dict] = []

    if model_ids and include_gallery:
        gallery_rows = (
            sb.table("model_gallery")
            .select("id,model_id,image_url,created_at")
            .in_("model_id", model_ids)
            .order("created_at", desc=True)
            .execute()
        ).data or []

    liked_ids: set[str] = set()
    if user_id:
        liked_rows = (
            sb.table("model_likes").select("model_id").eq("user_id", user_id).execute()
        ).data or []
        liked_ids = {
            entry.get("model_id") for entry in liked_rows if entry.get("model_id")
        }

    return _map_models(rows, gallery_rows, liked_ids)


# ------------------------------------------------------------------------------
# Models: API routes
# ------------------------------------------------------------------------------


@models_router.get("/", response_model=list[Model])
def list_models(
    includeGallery: bool = True,  # noqa: N803 - API casing
    current: UserState = Depends(get_current_user),
) -> list[Model]:
    """Return the available Gemzy models."""

    return _fetch_models(user_id=current.id, include_gallery=includeGallery)


@models_router.get("/{model_id}", response_model=Model)
def retrieve_model(
    model_id: str,
    current: UserState = Depends(get_current_user),
) -> Model:
    """Return a single Gemzy model by its id or slug."""

    models = _fetch_models(ids=[model_id], user_id=current.id)
    if not models:
        models = _fetch_models(slugs=[model_id], user_id=current.id)

    if not models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    return models[0]


@models_router.get("/{model_id}/gallery", response_model=list[ModelGalleryImage])
def list_model_gallery(
    model_id: str,
    current: UserState = Depends(get_current_user),
) -> list[ModelGalleryImage]:
    """Return signed gallery images for a model."""

    models = _fetch_models(ids=[model_id], user_id=current.id, include_gallery=False)
    if not models:
        models = _fetch_models(
            slugs=[model_id], user_id=current.id, include_gallery=False
        )
    if not models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    sb = get_client()
    gallery_rows = (
        sb.table("model_gallery")
        .select("id,image_url,created_at")
        .eq("model_id", models[0].id)
        .order("created_at", desc=True)
        .execute()
    ).data or []

    mapped: list[ModelGalleryImage] = []
    for order, row in enumerate(gallery_rows):
        preview_uri, full_uri = _resolve_collection_image_variants(
            row.get("image_url"),
            None,
            include_signed=True,
        )
        uri = full_uri or ""
        mapped.append(
            ModelGalleryImage(
                id=row.get("id"),
                uri=uri,
                thumbnail=preview_uri or uri,
                order=order,
            )
        )

    return mapped


@models_router.patch("/{model_id}", response_model=Model)
def update_model(
    model_id: str,
    payload: UpdateModelPayload,
    current: UserState = Depends(get_current_user),
) -> Model:
    """Update mutable fields for a model."""

    sb = get_client()

    if payload.liked is not None:
        if payload.liked:
            sb.table("model_likes").upsert(
                {"user_id": current.id, "model_id": model_id},
                on_conflict="user_id,model_id",
            ).execute()
        else:
            sb.table("model_likes").delete().eq("user_id", current.id).eq(
                "model_id", model_id
            ).execute()

    models = _fetch_models(ids=[model_id], user_id=current.id)
    if not models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    return models[0]
