"""Admin-published notification endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from .auth import get_current_user
from .schemas import (
    AppNotification,
    AppNotificationAction,
    PublishAppNotificationRequest,
    PushTokenRegistrationRequest,
    UserState,
)
from .supabase_client import get_client

router = APIRouter(prefix="/notifications", tags=["notifications"])
logger = logging.getLogger(__name__)

_ALLOWED_CATEGORIES = {"general", "personal"}
_ALLOWED_KINDS = {
    "app_update",
    "new_feature",
    "new_presets",
    "limited_time",
    "maintenance",
    "generation_completed",
    "generation_failed",
    "subscription_payment_failed",
    "subscription_renews_soon",
}
_EXPO_PUSH_TOKEN_PREFIXES = ("ExponentPushToken[", "ExpoPushToken[")
_EXPO_PUSH_API_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_PUSH_BATCH_SIZE = 100
_PERSONAL_NOTIFICATION_LIFETIME_DAYS = 7
_DEFAULT_ANDROID_CHANNEL_ID = "gemzy-general-v2"
T = TypeVar("T")
PushTarget = dict[str, str]
PushDispatch = dict[str, Any]


def _redact_push_token(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= 18:
        return value
    return f"{value[:12]}...{value[-6:]}"


def _count_targets_by_platform(targets: list[PushTarget]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for target in targets:
        platform = target.get("platform") or "unknown"
        counts[platform] = counts.get(platform, 0) + 1
    return counts


def _target_log_context(target: PushTarget) -> dict[str, str | None]:
    return {
        "user_id": target.get("user_id"),
        "platform": target.get("platform"),
        "token": _redact_push_token(target.get("token")),
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _normalize_action(row: dict[str, Any]) -> AppNotificationAction | None:
    pathname = row.get("action_pathname")
    params = row.get("action_params")
    url = row.get("action_url")
    if not pathname and not url:
        return None
    return AppNotificationAction(
        pathname=pathname if isinstance(pathname, str) and pathname else None,
        params=params if isinstance(params, dict) else None,
        url=url if isinstance(url, str) and url else None,
    )


def _coerce_notification_action(
    action: AppNotificationAction | dict[str, Any] | None,
) -> AppNotificationAction | None:
    if action is None:
        return None
    if isinstance(action, AppNotificationAction):
        return action
    if isinstance(action, dict):
        pathname = action.get("pathname")
        params = action.get("params")
        url = action.get("url")
        return AppNotificationAction(
            pathname=pathname if isinstance(pathname, str) and pathname else None,
            params=params if isinstance(params, dict) else None,
            url=url if isinstance(url, str) and url else None,
        )
    return None


def _is_expo_push_token(value: str) -> bool:
    return any(value.startswith(prefix) and value.endswith("]") for prefix in _EXPO_PUSH_TOKEN_PREFIXES)


def _notification_pref_enabled(
    preferences: object | None,
    key: str,
    *,
    default: bool = True,
) -> bool:
    if not isinstance(preferences, dict):
        return default
    value = preferences.get(key)
    return value if isinstance(value, bool) else default


def _chunked(items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _deactivate_push_tokens(targets: list[PushTarget]) -> None:
    if not targets:
        return

    now = _format_datetime(_utc_now())
    sb = get_client()
    seen_pairs: set[tuple[str, str]] = set()
    for target in targets:
        token = target.get("token")
        user_id = target.get("user_id")
        if not token or not user_id:
            continue

        pair = (token, user_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        (
            sb.table("push_tokens")
            .update({"is_active": False, "updated_at": now})
            .eq("token", token)
            .eq("user_id", user_id)
            .execute()
        )
        logger.info("Deactivated push token: %s", _target_log_context(target))


def _insert_push_logs(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    get_client().table("push_notification_logs").insert(rows).execute()


def _build_push_log_row(
    *,
    status: str,
    notification_id: str | None,
    target: PushTarget,
    message: dict[str, Any],
    ticket: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    now = _format_datetime(_utc_now())
    return {
        "id": str(uuid4()),
        "notification_id": notification_id,
        "user_id": target.get("user_id"),
        "push_token": target.get("token"),
        "provider": "expo",
        "status": status,
        "ticket_id": ticket.get("id") if isinstance(ticket, dict) and isinstance(ticket.get("id"), str) else None,
        "error_code": error_code,
        "error_message": error_message,
        "payload": message,
        "ticket": ticket,
        "created_at": now,
        "updated_at": now,
    }


def _select_push_targets_for_notification(
    category: str,
    *,
    target_user_id: str | None,
) -> list[PushTarget]:
    sb = get_client()
    query = sb.table("push_tokens").select("token,user_id,platform").eq("is_active", True)
    if category == "personal" and target_user_id:
        query = query.eq("user_id", target_user_id)

    token_response = query.execute()
    token_rows = [
        row
        for row in token_response.data or []
        if isinstance(row, dict)
        and isinstance(row.get("token"), str)
        and isinstance(row.get("user_id"), str)
    ]
    if not token_rows:
        logger.info(
            "Push target selection found no active tokens for category=%s target_user_id=%s",
            category,
            target_user_id,
        )
        return []

    user_ids = sorted({str(row["user_id"]) for row in token_rows})
    profiles_response = (
        sb.table("profiles")
        .select("id,notification_preferences")
        .in_("id", user_ids)
        .execute()
    )
    preferences_by_user = {
        str(row["id"]): row.get("notification_preferences")
        for row in profiles_response.data or []
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }

    preference_key = "personalUpdates" if category == "personal" else "gemzyUpdates"
    valid_targets: list[PushTarget] = []
    invalid_targets: list[PushTarget] = []
    preference_filtered_count = 0
    seen_pairs: set[tuple[str, str]] = set()
    for row in token_rows:
        token = str(row["token"])
        user_id = str(row["user_id"])
        platform = row.get("platform") if isinstance(row.get("platform"), str) else "unknown"
        pair = (token, user_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        if not _is_expo_push_token(token):
            invalid_targets.append({"token": token, "user_id": user_id, "platform": platform})
            continue

        if not _notification_pref_enabled(preferences_by_user.get(user_id), preference_key):
            preference_filtered_count += 1
            continue

        valid_targets.append({"token": token, "user_id": user_id, "platform": platform})

    _deactivate_push_tokens(invalid_targets)
    logger.info(
        "Push target selection complete: category=%s target_user_id=%s active_rows=%s valid=%s invalid=%s preference_filtered=%s valid_platforms=%s",
        category,
        target_user_id,
        len(token_rows),
        len(valid_targets),
        len(invalid_targets),
        preference_filtered_count,
        _count_targets_by_platform(valid_targets),
    )
    return valid_targets


def _find_notification_by_entity_key(entity_key: str) -> dict[str, Any] | None:
    response = (
        get_client()
        .table("app_notifications")
        .select("*")
        .eq("entity_key", entity_key)
        .limit(1)
        .execute()
    )
    for row in response.data or []:
        if isinstance(row, dict):
            return row
    return None


def _build_push_dispatches(
    targets: list[PushTarget],
    notification: dict[str, Any],
) -> list[PushDispatch]:
    payload_data = {
        "notificationId": notification.get("id"),
        "category": notification.get("category"),
        "kind": notification.get("kind"),
        "pathname": notification.get("action_pathname"),
        "params": notification.get("action_params"),
        "url": notification.get("action_url"),
        "entityKey": notification.get("entity_key"),
        "createdAt": notification.get("created_at"),
        "expiresAt": notification.get("expires_at"),
    }
    payload_data = {
        key: value
        for key, value in payload_data.items()
        if value is not None and value != ""
    }

    return [
        {
            "target": target,
            "message": {
                "to": target["token"],
                "title": notification["title"],
                "body": notification["body"],
                "sound": "default",
                "priority": "high",
                "channelId": _DEFAULT_ANDROID_CHANNEL_ID,
                "data": payload_data,
            },
        }
        for target in targets
    ]


def _send_expo_push_messages(
    dispatches: list[PushDispatch],
    *,
    notification_id: str | None,
) -> None:
    if not dispatches:
        return

    headers = {
        "accept": "application/json",
        "accept-encoding": "gzip, deflate",
        "content-type": "application/json",
    }

    with httpx.Client(timeout=10) as client:
        for batch in _chunked(dispatches, _EXPO_PUSH_BATCH_SIZE):
            batch_messages = [dispatch["message"] for dispatch in batch]
            logger.info(
                "Sending Expo push batch: notification_id=%s batch_size=%s platforms=%s channel_id=%s",
                notification_id,
                len(batch),
                _count_targets_by_platform([dispatch["target"] for dispatch in batch]),
                batch_messages[0].get("channelId") if batch_messages else None,
            )
            try:
                response = client.post(_EXPO_PUSH_API_URL, json=batch_messages, headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning(
                    "Expo push send failed: notification_id=%s batch_size=%s error=%s",
                    notification_id,
                    len(batch),
                    exc,
                )
                _insert_push_logs(
                    [
                        _build_push_log_row(
                            status="failed",
                            notification_id=notification_id,
                            target=dispatch["target"],
                            message=dispatch["message"],
                            error_code="request_error",
                            error_message=str(exc),
                        )
                        for dispatch in batch
                    ]
                )
                continue

            try:
                payload = response.json()
            except ValueError:
                logger.warning("Expo push send returned non-JSON payload")
                _insert_push_logs(
                    [
                        _build_push_log_row(
                            status="failed",
                            notification_id=notification_id,
                            target=dispatch["target"],
                            message=dispatch["message"],
                            error_code="invalid_response",
                            error_message="Expo push send returned non-JSON payload",
                        )
                        for dispatch in batch
                    ]
                )
                continue

            tickets = payload.get("data", []) if isinstance(payload, dict) else []
            rows_to_log: list[dict[str, Any]] = []
            tokens_to_deactivate: list[PushTarget] = []
            accepted_count = 0
            failed_count = 0
            for index, dispatch in enumerate(batch):
                ticket = tickets[index] if index < len(tickets) and isinstance(tickets[index], dict) else None
                if not ticket:
                    failed_count += 1
                    rows_to_log.append(
                        _build_push_log_row(
                            status="failed",
                            notification_id=notification_id,
                            target=dispatch["target"],
                            message=dispatch["message"],
                            error_code="missing_ticket",
                            error_message="Expo push send did not return a ticket for this message",
                        )
                    )
                    continue

                if ticket.get("status") == "ok":
                    accepted_count += 1
                    rows_to_log.append(
                        _build_push_log_row(
                            status="accepted",
                            notification_id=notification_id,
                            target=dispatch["target"],
                            message=dispatch["message"],
                            ticket=ticket,
                        )
                    )
                    continue

                failed_count += 1
                details = ticket.get("details")
                detail_error = details.get("error") if isinstance(details, dict) else None
                error_message = (
                    ticket.get("message")
                    if isinstance(ticket.get("message"), str) and ticket.get("message")
                    else str(details) if details is not None else "Expo push ticket error"
                )
                rows_to_log.append(
                    _build_push_log_row(
                        status="failed",
                        notification_id=notification_id,
                        target=dispatch["target"],
                        message=dispatch["message"],
                        ticket=ticket,
                        error_code=detail_error if isinstance(detail_error, str) else "ticket_error",
                        error_message=error_message,
                    )
                )
                logger.warning(
                    "Expo push ticket error: notification_id=%s error=%s target=%s message=%s",
                    notification_id,
                    detail_error if isinstance(detail_error, str) else "ticket_error",
                    _target_log_context(dispatch["target"]),
                    error_message,
                )
                if detail_error == "DeviceNotRegistered":
                    tokens_to_deactivate.append(dispatch["target"])
                    logger.warning(
                        "Expo push token is no longer registered: %s",
                        _target_log_context(dispatch["target"]),
                    )

            logger.info(
                "Expo push batch finished: notification_id=%s batch_size=%s accepted=%s failed=%s",
                notification_id,
                len(batch),
                accepted_count,
                failed_count,
            )
            _insert_push_logs(rows_to_log)
            _deactivate_push_tokens(tokens_to_deactivate)


def publish_app_notification(
    *,
    category: str,
    kind: str,
    title: str,
    body: str,
    entity_key: str | None = None,
    target_user_id: str | None = None,
    action: AppNotificationAction | dict[str, Any] | None = None,
    expires_at: datetime | None = None,
    published_by: str | None = None,
) -> AppNotification:
    """Persist and dispatch an app notification from server-side workflows."""

    normalized_category = category if category in _ALLOWED_CATEGORIES else "general"
    normalized_kind = kind.strip()
    normalized_title = title.strip()
    normalized_body = body.strip()
    normalized_action = _coerce_notification_action(action)

    if normalized_kind not in _ALLOWED_KINDS:
        raise ValueError(f"Unsupported notification kind: {normalized_kind}")
    if not normalized_title or not normalized_body:
        raise ValueError("Notification title and body are required")
    if normalized_category == "personal" and not target_user_id:
        raise ValueError("Personal notifications require a target user")

    now = _utc_now()
    notification_id = str(uuid4())
    resolved_entity_key = (entity_key or "").strip() or f"system:{normalized_kind}:{notification_id}"
    existing = _find_notification_by_entity_key(resolved_entity_key)
    if existing is not None:
        logger.info(
            "Skipping publish for existing notification entity_key=%s existing_id=%s",
            resolved_entity_key,
            existing.get("id"),
        )
        return _normalize_notification(existing)

    resolved_expires_at = expires_at
    if resolved_expires_at is None and normalized_category == "personal":
        resolved_expires_at = now + timedelta(days=_PERSONAL_NOTIFICATION_LIFETIME_DAYS)

    payload = {
        "id": notification_id,
        "entity_key": resolved_entity_key,
        "category": normalized_category,
        "kind": normalized_kind,
        "title": normalized_title,
        "body": normalized_body,
        "created_at": _format_datetime(now),
        "updated_at": _format_datetime(now),
        "expires_at": _format_datetime(resolved_expires_at),
        "action_pathname": normalized_action.pathname if normalized_action else None,
        "action_params": normalized_action.params if normalized_action and normalized_action.params else None,
        "action_url": normalized_action.url if normalized_action else None,
        "target_user_id": target_user_id if normalized_category == "personal" else None,
        "published_by": published_by,
        "is_active": True,
    }

    logger.info(
        "Publishing app notification id=%s category=%s kind=%s target_user_id=%s entity_key=%s",
        notification_id,
        normalized_category,
        normalized_kind,
        target_user_id,
        resolved_entity_key,
    )
    get_client().table("app_notifications").insert(payload).execute()
    targets = _select_push_targets_for_notification(
        normalized_category,
        target_user_id=target_user_id if normalized_category == "personal" else None,
    )
    logger.info(
        "Notification id=%s selected %s push targets",
        notification_id,
        len(targets),
    )
    if targets:
        _send_expo_push_messages(
            _build_push_dispatches(targets, payload),
            notification_id=notification_id,
        )

    return _normalize_notification(payload)


def _normalize_notification(row: dict[str, Any]) -> AppNotification:
    created_at = _parse_datetime(row.get("created_at")) or _utc_now()
    expires_at = _parse_datetime(row.get("expires_at"))
    return AppNotification(
        id=str(row.get("id") or ""),
        entityKey=row.get("entity_key") if isinstance(row.get("entity_key"), str) else None,
        category=row.get("category") if row.get("category") in _ALLOWED_CATEGORIES else "general",
        kind=str(row.get("kind") or ""),
        title=str(row.get("title") or ""),
        body=str(row.get("body") or ""),
        createdAt=_format_datetime(created_at) or _format_datetime(_utc_now()) or "",
        expiresAt=_format_datetime(expires_at),
        action=_normalize_action(row),
    )


def _ensure_admin(current: UserState) -> None:
    if current.isAdmin:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required",
    )


@router.post("/push-tokens", status_code=status.HTTP_204_NO_CONTENT)
def register_push_token(
    data: PushTokenRegistrationRequest,
    current: UserState = Depends(get_current_user),
) -> None:
    """Register or refresh the authenticated user's Expo push token."""

    token = data.token.strip()
    if not _is_expo_push_token(token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Expo push token",
        )

    now = _utc_now()
    payload = {
        "token": token,
        "user_id": current.id,
        "platform": data.platform,
        "app_version": (
            data.appVersion.strip()
            if isinstance(data.appVersion, str) and data.appVersion.strip()
            else None
        ),
        "is_active": True,
        "last_registered_at": _format_datetime(now),
        "updated_at": _format_datetime(now),
    }
    get_client().table("push_tokens").upsert(payload, on_conflict="token").execute()
    logger.info(
        "Registered Expo push token for user_id=%s platform=%s app_version=%s token=%s",
        current.id,
        data.platform,
        payload["app_version"],
        _redact_push_token(token),
    )


@router.get("", response_model=list[AppNotification])
def list_notifications(current: UserState = Depends(get_current_user)) -> list[AppNotification]:
    """Return active notifications relevant to the authenticated user."""

    response = (
        get_client()
        .table("app_notifications")
        .select("*")
        .eq("is_active", True)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )

    now = _utc_now()
    notifications: list[AppNotification] = []
    for row in response.data or []:
        if not isinstance(row, dict):
            continue
        expires_at = _parse_datetime(row.get("expires_at"))
        if expires_at is not None and expires_at <= now:
            continue

        category = row.get("category")
        target_user_id = row.get("target_user_id")
        if category == "personal":
            if not isinstance(target_user_id, str) or target_user_id != current.id:
                continue

        notifications.append(_normalize_notification(row))

    return notifications


@router.post(
    "",
    response_model=AppNotification,
    status_code=status.HTTP_201_CREATED,
)
def publish_notification(
    data: PublishAppNotificationRequest,
    current: UserState = Depends(get_current_user),
) -> AppNotification:
    """Create a notification from the admin dashboard."""

    _ensure_admin(current)

    category = data.category if data.category in _ALLOWED_CATEGORIES else "general"
    kind = data.kind.strip()
    title = data.title.strip()
    body = data.body.strip()

    if kind not in _ALLOWED_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported notification kind",
        )
    if not title or not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title and body are required",
        )
    if category == "personal" and not data.targetUserId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Personal notifications require a target user",
        )

    return publish_app_notification(
        category=category,
        kind=kind,
        title=title,
        body=body,
        entity_key=(data.entityKey or "").strip() or None,
        target_user_id=data.targetUserId if category == "personal" else None,
        action=data.action,
        expires_at=_parse_datetime(data.expiresAt),
        published_by=current.id,
    )
