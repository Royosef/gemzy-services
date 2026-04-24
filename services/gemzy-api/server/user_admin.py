"""Utilities for managing Supabase auth users and scheduled deletions."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Sequence

from postgrest.exceptions import APIError

from .credits import schedule_next_credit_reset
from .storage import maybe_get_bucket, user_storage_prefix

try:  # pragma: no cover - optional during testing without Supabase deps
    from .supabase_client import get_client, get_service_role_client
except Exception:  # pragma: no cover - fallback stub when supabase is unavailable
    def get_client():  # type: ignore[override]
        raise RuntimeError("Supabase client is not available")

    def get_service_role_client(*, fresh: bool = False):  # type: ignore[override]
        raise RuntimeError("Supabase client is not available")


def _isoformat(value: datetime) -> str:
    """Return a UTC ISO-8601 representation without microseconds."""

    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def get_admin_user_metadata(user_id: str, *, client=None) -> dict:
    """Fetch the persisted user metadata via the Supabase admin API."""

    sb = client or get_service_role_client()
    try:
        result = sb.auth.admin.get_user_by_id(user_id)
    except Exception:
        if client is None:
            return {}
        try:
            result = get_service_role_client(fresh=True).auth.admin.get_user_by_id(
                user_id
            )
        except Exception:  # pragma: no cover - network failure / admin disabled
            return {}
    user = getattr(result, "user", None)
    return getattr(user, "user_metadata", None) or {}


def update_user_metadata(
    user_id: str,
    metadata: dict,
    *,
    client=None,
) -> None:
    """Persist merged metadata on the Supabase auth user."""

    if not metadata:
        return

    sb = client or get_service_role_client()
    payload = {"user_metadata": metadata}
    try:
        sb.auth.admin.update_user_by_id(user_id, payload)
    except Exception:
        if client is None:
            raise
        admin_sb = get_service_role_client(fresh=True)
        admin_sb.auth.admin.update_user_by_id(user_id, payload)


def _resolve_grace_period_days(default: int = 30) -> int:
    raw = os.getenv("USER_DELETION_GRACE_DAYS", str(default))
    try:
        return max(0, int(raw))
    except ValueError:  # pragma: no cover - misconfiguration fallback
        return default


def _bucket_prefixes_for_user(
    user_id: str,
    overrides: Sequence[tuple[str | None, str]] | None = None,
) -> list[tuple[str, str]]:
    """Return bucket/prefix pairs that should be purged for a user."""

    prefix = user_storage_prefix(user_id)
    if overrides is not None:
        return [
            (bucket, template.format(prefix=prefix))
            for bucket, template in overrides
            if bucket
        ]

    collections_bucket = os.getenv("GCS_COLLECTIONS_PUBLIC_BUCKET")
    avatar_bucket = os.getenv("GCS_AVATARS_BUCKET") or collections_bucket

    mapping: list[tuple[str | None, str]] = []
    if collections_bucket:
        mapping.append((collections_bucket, f"{prefix}/"))
    if avatar_bucket:
        mapping.append((avatar_bucket, f"avatars/{prefix}/"))

    deduped: list[tuple[str, str]] = []
    seen = set()
    for bucket, bucket_prefix in mapping:
        if not bucket:
            continue
        key = (bucket, bucket_prefix)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _purge_user_storage(
    user_id: str,
    *,
    bucket_overrides: Sequence[tuple[str | None, str]] | None = None,
) -> None:
    project = os.getenv("GCS_PROJECT")
    if not project:
        return

    for bucket_name, prefix in _bucket_prefixes_for_user(
        user_id, overrides=bucket_overrides
    ):
        bucket = maybe_get_bucket(bucket_name, project)
        if bucket is None:
            continue
        try:
            blobs = bucket.list_blobs(prefix=prefix)
        except Exception:  # pragma: no cover - upstream failure
            continue
        for blob in blobs:
            try:
                blob.delete()
            except Exception:  # pragma: no cover - best effort cleanup
                continue


def schedule_user_deletion(
    user_id: str,
    *,
    grace_days: int | None = None,
    now: datetime | None = None,
    client=None,
) -> datetime:
    """Enqueue a user for future deletion and stamp metadata."""

    sb = client or get_service_role_client()
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    grace_period = grace_days if grace_days is not None else _resolve_grace_period_days()
    scheduled_for = now + timedelta(days=grace_period)

    record = {
        "user_id": user_id,
        "requested_at": _isoformat(now),
        "scheduled_for": _isoformat(scheduled_for),
        "grace_period_days": grace_period,
        "status": "scheduled",
        "updated_at": _isoformat(now),
    }

    try:
        sb.table(os.getenv("USER_DELETION_TABLE", "user_deletion_queue")).upsert(
            record, on_conflict="user_id"
        ).execute()
    except APIError as exc:
        raise RuntimeError("Failed to enqueue user deletion") from exc

    metadata = dict(get_admin_user_metadata(user_id, client=sb))
    metadata.update(
        {
            "deactivated": True,
            "deactivatedAt": metadata.get("deactivatedAt") or record["requested_at"],
            "deleteRequestedAt": record["requested_at"],
            "deleteScheduledFor": record["scheduled_for"],
            "deleteGracePeriodDays": grace_period,
        }
    )
    update_user_metadata(user_id, metadata, client=sb)

    try:
        (
            sb.table("profiles")
            .update({"deactivated_at": record["requested_at"]})
            .eq("id", user_id)
            .execute()
        )
    except APIError:
        pass

    return scheduled_for


def clear_user_deactivation(
    user_id: str,
    *,
    metadata: dict | None = None,
    profile: dict | None = None,
    now: datetime | None = None,
    client=None,
) -> tuple[dict, dict | None, str | None]:
    """Clear deactivation flags for a returning user.

    Returns the updated metadata, the sanitized profile (if provided), and the
    ISO timestamp when the reactivation occurred.
    """

    sb = client or get_service_role_client()
    metadata = dict(metadata or get_admin_user_metadata(user_id, client=sb))
    profile_copy = dict(profile) if profile is not None else None

    was_deactivated = bool(metadata.get("deactivated")) or bool(
        metadata.get("deactivatedAt")
    )
    if not was_deactivated and profile_copy is not None:
        was_deactivated = bool(profile_copy.get("deactivated_at"))

    if not was_deactivated:
        return metadata, profile_copy, None

    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    moment_iso = _isoformat(moment)

    metadata["deactivated"] = False
    metadata["deactivatedAt"] = None
    metadata["reactivatedAt"] = moment_iso
    metadata["deleteCancelledAt"] = moment_iso
    metadata["deleteRequestedAt"] = None
    metadata["deleteScheduledFor"] = None
    metadata["deleteGracePeriodDays"] = None

    try:
        update_user_metadata(user_id, metadata, client=sb)
    except Exception:
        # Continue with the best-effort cleanup even if metadata fails to persist.
        pass

    try:
        (
            sb.table("profiles")
            .update({"deactivated_at": None})
            .eq("id", user_id)
            .execute()
        )
    except APIError:
        pass
    else:
        if profile_copy is not None:
            profile_copy["deactivated_at"] = None

    table_name = os.getenv("USER_DELETION_TABLE", "user_deletion_queue")
    status_payload = {
        "status": "cancelled",
        "error": None,
        "deleted_at": None,
        "updated_at": moment_iso,
    }

    try:
        (
            sb.table(table_name)
            .update(status_payload)
            .eq("user_id", user_id)
            .execute()
        )
    except APIError:
        pass
    else:
        try:
            (
                sb.table(table_name)
                .update({"cancelled_at": moment_iso})
                .eq("user_id", user_id)
                .execute()
            )
        except Exception:
            pass

    return metadata, profile_copy, moment_iso


def perform_user_hard_delete(
    user_id: str,
    *,
    client=None,
    bucket_overrides: Sequence[tuple[str | None, str]] | None = None,
) -> None:
    """Remove the Supabase auth user, profile data, and storage assets."""

    sb = client or get_service_role_client()

    try:
        sb.table("profiles").delete().eq("id", user_id).execute()
    except APIError:
        pass

    _purge_user_storage(user_id, bucket_overrides=bucket_overrides)

    sb.auth.admin.delete_user(user_id)


def process_due_user_deletions(
    *,
    limit: int = 100,
    now: datetime | None = None,
    client=None,
    bucket_overrides: Sequence[tuple[str | None, str]] | None = None,
) -> int:
    """Process queued deletions that have reached the scheduled date."""

    sb = client or get_service_role_client()
    checkpoint = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    table_name = os.getenv("USER_DELETION_TABLE", "user_deletion_queue")

    try:
        response = (
            sb.table(table_name)
            .select("user_id")
            .lte("scheduled_for", _isoformat(checkpoint))
            .eq("status", "scheduled")
            .limit(limit)
            .execute()
        )
    except APIError:
        return 0

    rows = response.data or []
    processed = 0
    for row in rows:
        user_id = row.get("user_id")
        if not user_id:
            continue
        try:
            perform_user_hard_delete(
                user_id, client=sb, bucket_overrides=bucket_overrides
            )
            status_payload = {
                "status": "deleted",
                "deleted_at": _isoformat(checkpoint),
                "updated_at": _isoformat(checkpoint),
                "error": None,
            }
        except Exception as exc:  # pragma: no cover - best effort logging
            status_payload = {
                "status": "error",
                "error": str(exc),
                "updated_at": _isoformat(checkpoint),
            }
        try:
            (
                sb.table(table_name)
                .update(status_payload)
                .eq("user_id", user_id)
                .execute()
            )
        except APIError:
            pass
        processed += 1

    return processed


def process_due_credit_resets(
    *,
    limit: int = 100,
    now: datetime | None = None,
    client=None,
) -> int:
    """Identify and reset credits for users whose monthly cycle has ended."""
    from .plans import get_plan_initial_credits

    now = now or datetime.now(timezone.utc)
    sb = client or get_service_role_client()
    
    try:
        # Query profiles where next_credit_reset_at is actually due (<= now).
        resp = (
            sb.table("profiles")
            .select("id,plan,next_credit_reset_at")
            .lte("next_credit_reset_at", now.isoformat())
            .order("next_credit_reset_at")
            .limit(limit)
            .execute()
        )
    except APIError as e:
        # If the column doesn't exist yet, we can't proceed.
        if "column \"next_credit_reset_at\" does not exist" in str(e):
             return 0
        raise

    targets = resp.data or []
    count = 0
    
    for row in targets:
        user_id = row["id"]
        plan = row["plan"]
        
        allocation = get_plan_initial_credits(plan)
        next_reset = schedule_next_credit_reset(now=now)
        
        try:
            sb.table("profiles").update({
                "credits": allocation,
                "next_credit_reset_at": next_reset
            }).eq("id", user_id).execute()
            count += 1
        except Exception:
            continue
            
    return count


__all__ = [
    "clear_user_deactivation",
    "get_admin_user_metadata",
    "process_due_user_deletions",
    "process_due_credit_resets",
    "perform_user_hard_delete",
    "schedule_user_deletion",
    "update_user_metadata",
]

