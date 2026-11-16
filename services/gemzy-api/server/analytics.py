"""PostHog delivery using the existing Supabase database and API worker.

Stable UUIDs deduplicate retries across workers and restarts. Never merge identities
server-side: the client identifies only after successful authentication.
"""
from __future__ import annotations

import logging
import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from .supabase_client import get_service_role_client

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return os.getenv("ANALYTICS_ENABLED", "false").lower() == "true"


def event_id(key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"gemzy:analytics:v2:{key}"))


def registration_event_id(user_id: str) -> str:
    # Matches the DB auth trigger without requiring the uuid-ossp extension.
    return str(UUID(hashlib.md5(f"gemzy:analytics:signup:{user_id}".encode()).hexdigest()))


def enqueue(event: str, distinct_id: str, key: str, properties: dict,
            occurred_at: str | None = None) -> None:
    if not enabled():
        return
    get_service_role_client().table("analytics_outbox").upsert({
        "id": event_id(key), "event": event, "distinct_id": distinct_id,
        "properties": {"analytics_schema_version": 2, "event_source": "server", "app_environment": os.getenv("APP_ENV", "unknown"), **properties},
        "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
    }, on_conflict="id", ignore_duplicates=True).execute()


def record_registration(user_id: str, method: str, created_at: str | None, context: dict) -> None:
    if not enabled():
        return
    properties = {k: context[k][:200] for k in (
        "anonymous_id", "demo_generation_id", "app_version", "platform", "app_environment", "first_utm_source", "first_utm_medium", "first_utm_campaign", "first_utm_content", "first_utm_term"
    ) if isinstance(context.get(k), str)}
    properties.update(user_id=user_id, auth_method=method, registration_date=created_at,
                      analytics_schema_version=2, event_source="server", application_context_received=True,
                      **{"$set_once": {"registration_date": created_at, "registration_app_version": context.get("app_version")}})
    try:
        get_service_role_client().rpc("record_analytics_registration", {
            "p_user_id": user_id, "p_event_id": registration_event_id(user_id),
            "p_properties": properties,
        }).execute()
    except Exception:
        # The DB auth trigger already recorded the first-success event atomically.
        # Application context enrichment must never break a successful login.
        logger.exception("Failed to enrich registration analytics for %s", user_id)


def record_revenue(event: dict) -> None:
    if not enabled() or not event.get("id"):
        return
    user_id = str(event.get("app_user_id", ""))
    try:
        UUID(user_id)
    except ValueError:
        return  # Never attach store-anonymous or unknown aliases to app accounts.
    kind = event.get("type")
    trial = str(event.get("period_type", "")).upper() == "TRIAL"
    name = {
        "INITIAL_PURCHASE": "Trial Started" if trial else "Subscription Purchase Completed",
        "RENEWAL": "Subscription Renewed",
        "CANCELLATION": "Subscription Canceled",
        "UNCANCELLATION": "Subscription Resumed",
        "EXPIRATION": "Subscription Expired",
        "NON_RENEWING_PURCHASE": "Credit Pack Purchase Completed",
        "REFUND": "Purchase Refunded",
        "REFUND_REVERSED": "Refund Reversed",
        "BILLING_ISSUE": "Subscription Billing Issue",
        "PRODUCT_CHANGE": "Subscription Product Changed",
    }.get(kind)
    if not name:
        return
    properties = {
        "user_id": user_id, "revenuecat_event_id": event["id"], "revenuecat_event_type": kind,
        "transaction_id": event.get("transaction_id"), "product_id": event.get("product_id"),
        "period_type": event.get("period_type"), "environment": event.get("environment"),
        "store": event.get("store"), "currency": event.get("currency"),
        "revenue": event.get("price_in_purchased_currency"), "revenue_usd": event.get("price"),
        "is_trial_conversion": event.get("is_trial_conversion", False),
        "cancellation_reason": event.get("cancel_reason"),
        "is_refund": isinstance(event.get("price"), (int, float)) and event["price"] < 0,
        "renewal_number": event.get("renewal_number"),
        "purchased_at_ms": event.get("purchased_at_ms"),
        "original_transaction_id": event.get("original_transaction_id"),
        "expiration_at_ms": event.get("expiration_at_ms"),
    }
    timestamp = event.get("event_timestamp_ms")
    occurred = datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat() if timestamp else None
    enqueue(name, user_id, f"revenuecat:{event['id']}", properties, occurred)


def drain_outbox() -> int:
    key = os.getenv("POSTHOG_API_KEY")
    if not enabled() or not key:
        return 0
    sb = get_service_role_client()
    # Give successful auth responses time to attach campaign/version context to
    # the auth trigger's event before delivery. Original occurrence time is kept.
    ready_at = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    rows = sb.table("analytics_outbox").select("*").is_("delivered_at", "null").lt("occurred_at", ready_at).order("occurred_at").limit(100).execute().data or []
    if not rows:
        return 0
    host = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com").rstrip("/")
    response = httpx.post(f"{host}/batch/", json={"api_key": key, "batch": [{
        "uuid": row["id"], "event": row["event"], "timestamp": row["occurred_at"],
        "properties": {"app_environment": os.getenv("APP_ENV", "unknown"), **row["properties"], "distinct_id": row["distinct_id"]},
    } for row in rows]}, timeout=15)
    response.raise_for_status()
    sb.table("analytics_outbox").update({"delivered_at": datetime.now(timezone.utc).isoformat()}).in_("id", [row["id"] for row in rows]).execute()
    return len(rows)


def generation_context(request, user=None) -> dict:
    import json
    raw = request.headers.get("X-Gemzy-Analytics", "{}")
    if len(raw) > 4096:
        return {}
    try:
        context = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(context, dict):
        return {}
    properties = {k: context.get(k)[:200] for k in ("anonymous_id", "app_version", "platform", "app_environment", "first_utm_source", "first_utm_medium", "first_utm_campaign", "first_utm_content", "first_utm_term")
                  if isinstance(context.get(k), str)}
    if user and not user.id.startswith("guest:"):
        properties.update(registration_date=user.createdAt, subscription_plan=user.plan,
                          trial_expires_at=user.trialExpiresAt, purchased_credits_balance=user.purchasedCredits)
    return properties


def record_generation(job, terminal: bool = False) -> None:
    if not enabled():
        return
    guest = job.user_id.startswith("guest:")
    identity = job.analytics_context.get("anonymous_id") if guest else job.user_id
    if not identity:
        return  # Old guest clients have no linkable analytics identity.
    generation_type = (job.style or {}).get("task_type", job.job_type)
    properties = {
        **job.analytics_context, "generation_id": job.id, "job_id": job.id,
        "user_id": None if guest else job.user_id, "is_anonymous_demo": guest,
        "generation_type": generation_type, "output_count": len(job.results) if terminal else 0,
        "$process_person_profile": not guest,
        "outputs_requested": job.total_looks, "resolution": job.quality,
        "width": (job.dims or {}).get("w"), "height": (job.dims or {}).get("h"),
        "generation_status": job.status if terminal else "queued", "success": job.status == "completed" and bool(job.results) if terminal else None,
        "credits_consumed": max(0, job.reserved_credit_cost - job.refunded_credit_cost) if terminal else None,
        "duration_ms": max(0, int((job.updated_at - job.created_at).total_seconds() * 1000)) if terminal else None,
        "jewelry_ids": job.analytics_context.get("jewelry_ids", []),
        "jewelry_id": job.analytics_context.get("jewelry_id"),
        "event_unit": "generation_request",
    }
    name = ("Generation Completed" if job.status == "completed" else "Generation Failed") if terminal else "Generation Started"
    occurred = (job.updated_at if terminal else job.created_at).replace(tzinfo=timezone.utc).isoformat()
    enqueue(name, identity, f"generation:{job.id}:{'terminal' if terminal else 'started'}", properties, occurred)
    if guest:
        enqueue(name.replace("Generation", "Demo Generation"), identity,
                f"demo:{job.id}:{'terminal' if terminal else 'started'}", properties, occurred)
