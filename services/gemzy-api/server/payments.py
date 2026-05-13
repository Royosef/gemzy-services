"""RevenueCat payments integration."""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from .auth import get_current_user
from .credit_packs import match_credit_pack
from .credits import schedule_next_credit_reset
from .plans import get_plan_initial_credits, is_upgrade, normalize_plan
from .schemas import UserState
from .supabase_client import get_client
from .user_admin import get_admin_user_metadata, update_user_metadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

RC_WEBHOOK_AUTH = os.getenv("RC_WEBHOOK_AUTH")
RC_API_KEY = (
    os.getenv("RC_SECRET_KEY")
    or os.getenv("REVENUECAT_SECRET_KEY")
    or os.getenv("REVENUECAT_API_KEY")
)
RC_API_BASE = os.getenv("REVENUECAT_API_BASE", "https://api.revenuecat.com")
_CREDIT_PACK_SYNC_METADATA_KEY = "creditPackSyncMarkers"
_MAX_CREDIT_PACK_SYNC_MARKERS = 40
SUBSCRIPTION_ACCOUNT_MISMATCH_CODE = "subscription_account_mismatch"
SUBSCRIPTION_ACCOUNT_MISMATCH_MESSAGE = (
    "This subscription belongs to another account on this device."
)


class CreditPackSyncRequest(BaseModel):
    productIdentifier: str
    purchaseDate: str | None = None


class SubscriptionSyncRequest(BaseModel):
    revenuecat_app_user_id: str | None = None
    revenuecat_original_app_user_id: str | None = None
    source: str | None = None


def _product_to_tier(product_id: str) -> str:
    """Map RevenueCat product ID to plan tier."""
    product_lower = product_id.lower()
    if "designer" in product_lower:
        return "Designer"
    elif "pro" in product_lower:
        return "Pro"
    elif "starter" in product_lower:
        return "Starter"
    return "Free"


def _extract_credit_pack_amount(product_id: str | None) -> int | None:
    """Resolve the purchased credit amount from the shared server config."""
    pack = match_credit_pack(product_id)
    return pack["credits"] if pack else None


def _parse_purchase_date_to_ms(value: str | None) -> int | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    return int(parsed.timestamp() * 1000)


def _build_credit_pack_sync_marker(product_id: str | None, purchase_ms: int | None) -> str | None:
    if not product_id or not purchase_ms:
        return None

    return f"{product_id.strip().lower()}:{purchase_ms}"


def _normalize_app_user_id(value: object | None) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def _is_revenuecat_anonymous_app_user_id(value: str | None) -> bool:
    if not value:
        return False

    return value.startswith("$RCAnonymousID:") or value.startswith("RCAnonymousID:")


def _has_subscription_account_mismatch(app_user_id: object | None, original_app_user_id: object | None) -> bool:
    app_user = _normalize_app_user_id(app_user_id)
    original_user = _normalize_app_user_id(original_app_user_id)

    if not app_user or not original_user:
        return False
    if _is_revenuecat_anonymous_app_user_id(original_user):
        return False

    return original_user != app_user


def _subscription_account_mismatch_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": SUBSCRIPTION_ACCOUNT_MISMATCH_CODE,
            "message": SUBSCRIPTION_ACCOUNT_MISMATCH_MESSAGE,
        },
    )


def _ensure_subscription_sync_ownership(
    current_user_id: str,
    *,
    payload: SubscriptionSyncRequest | None = None,
    subscriber: dict | None = None,
) -> None:
    if payload:
        payload_app_user_id = _normalize_app_user_id(payload.revenuecat_app_user_id)
        if payload_app_user_id and payload_app_user_id != current_user_id:
            raise _subscription_account_mismatch_error()

        if _has_subscription_account_mismatch(
            current_user_id,
            payload.revenuecat_original_app_user_id,
        ):
            raise _subscription_account_mismatch_error()

    if subscriber and _has_subscription_account_mismatch(
        current_user_id,
        subscriber.get("original_app_user_id"),
    ):
        raise _subscription_account_mismatch_error()


def _get_credit_pack_sync_markers(metadata: dict | None) -> list[str]:
    raw_markers = (metadata or {}).get(_CREDIT_PACK_SYNC_METADATA_KEY)
    if not isinstance(raw_markers, list):
        return []

    return [value.strip() for value in raw_markers if isinstance(value, str) and value.strip()]


def _remember_credit_pack_sync_marker(user_id: str, metadata: dict | None, marker: str | None) -> None:
    if not marker:
        return

    next_metadata = dict(metadata or {})
    markers = [value for value in _get_credit_pack_sync_markers(next_metadata) if value != marker]
    markers.append(marker)
    next_metadata[_CREDIT_PACK_SYNC_METADATA_KEY] = markers[-_MAX_CREDIT_PACK_SYNC_MARKERS:]
    try:
        update_user_metadata(user_id, next_metadata)
    except Exception:
        logger.exception("[Credit Sync] Failed to persist sync marker for user=%s marker=%s", user_id, marker)


def _sum_virtual_currency_adjustments(event: dict) -> int:
    adjustments = event.get("adjustments") or []
    total = 0

    for adjustment in adjustments:
        if not isinstance(adjustment, dict):
            continue
        amount = adjustment.get("amount")
        if isinstance(amount, bool):
            continue
        if isinstance(amount, (int, float)):
            total += int(amount)
            continue
        if isinstance(amount, str):
            try:
                total += int(float(amount))
            except ValueError:
                continue

    return total


def _ms_to_iso(ms: int | None) -> str | None:
    """Convert milliseconds timestamp to ISO format string."""
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp into a UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_event_timestamp(event: dict) -> int | None:
    """Extract event timestamp in milliseconds for ordering."""
    # RevenueCat provides event_timestamp_ms in some events
    # Fall back to expiration_at_ms or current time
    return (
        event.get("event_timestamp_ms")
        or event.get("purchased_at_ms")
        or event.get("expiration_at_ms")
    )


def _fetch_current_profile(sb, user_id: str) -> dict | None:
    """Fetch current user profile for comparison."""
    try:
        resp = (
            sb.table("profiles")
            .select("plan,credits,purchased_credits,rc_last_event_ms,subscription_expires_at,next_credit_reset_at")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        return data[0] if data else None
    except Exception as e:
        logger.warning(f"Failed to fetch profile for {user_id}: {e}")
        return None


def _parse_rc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_active_rc_entitlement(entitlement: dict, now: datetime) -> bool:
    expires = _parse_rc_datetime(entitlement.get("expires_date"))
    if expires is None:
        # Lifetime / non-expiring entitlement
        return True
    return expires > now


def _rc_subscriber_to_plan_and_expiry(subscriber: dict) -> tuple[str, str | None]:
    """Derive app plan from RevenueCat subscriber payload."""
    now = datetime.now(timezone.utc)
    entitlements = subscriber.get("entitlements") or {}

    active_names: list[str] = []
    active_expiries: list[datetime] = []

    for name, entitlement in entitlements.items():
        if not isinstance(entitlement, dict):
            continue
        if not _is_active_rc_entitlement(entitlement, now):
            continue
        active_names.append(str(name).lower())
        expires = _parse_rc_datetime(entitlement.get("expires_date"))
        if expires:
            active_expiries.append(expires)

    if "designer" in active_names:
        plan = "Designer"
    elif "pro" in active_names:
        plan = "Pro"
    elif "starter" in active_names:
        plan = "Starter"
    else:
        plan = "Free"

    expires_at = max(active_expiries).isoformat() if active_expiries else None
    return normalize_plan(plan), expires_at


async def _fetch_rc_subscriber(app_user_id: str) -> dict:
    if not RC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RevenueCat sync not configured",
        )

    url = f"{RC_API_BASE.rstrip('/')}/v1/subscribers/{app_user_id}"
    headers = {
        "Authorization": f"Bearer {RC_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 401:
                # Some RevenueCat setups/documentation examples use the raw secret key
                # in Authorization instead of a Bearer token.
                fallback_headers = {
                    "Authorization": RC_API_KEY,
                    "Content-Type": "application/json",
                }
                resp = await client.get(url, headers=fallback_headers)
    except httpx.RequestError as exc:
        logger.exception("[Sync] RevenueCat request failed for %s", app_user_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach RevenueCat",
        ) from exc

    if resp.status_code >= 400:
        logger.warning(
            "[Sync] RevenueCat error for %s: status=%s body=%s",
            app_user_id,
            resp.status_code,
            resp.text[:500],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="RevenueCat sync failed",
        )

    data = resp.json()
    subscriber = data.get("subscriber")
    if not isinstance(subscriber, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid RevenueCat response",
        )
    return subscriber


@router.post("/webhook")
async def rc_webhook(request: Request) -> dict:
    """Handle RevenueCat webhooks to update user credits and plan.
    
    Event handling rules:
    - INITIAL_PURCHASE: Set plan, overwrite credits, set expiration
    - RENEWAL: Keep plan, reset credits, update expiration
    - PRODUCT_CHANGE: Update plan immediately, do NOT overwrite credits (apply top-up if upgrade)
    - NON_RENEWING_PURCHASE: Source of truth for credit-pack top-ups
    - VIRTUAL_CURRENCY_TRANSACTION: Ignored for app credits to avoid double-grants
    - CANCELLATION: Ignore (auto-renew off, not immediate revoke)
    - EXPIRATION: Only downgrade if truly expired (expiration in past)
    """
    
    # Auth check
    auth_header = request.headers.get("Authorization")
    if RC_WEBHOOK_AUTH and auth_header != RC_WEBHOOK_AUTH:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth")

    payload = await request.json()
    event = payload.get("event", {})
    event_type = event.get("type")
    app_user_id = event.get("app_user_id")
    product_id = event.get("product_id", "")
    expiration_ms = event.get("expiration_at_ms")
    event_timestamp_ms = _get_event_timestamp(event)
    
    print(f"[RC Webhook] type={event_type}, user={app_user_id}, product={product_id}")
    logger.info(f"[RC Webhook] type={event_type}, user={app_user_id}, product={product_id}")
    
    if not app_user_id:
        return {"status": "ignored", "reason": "no_user_id"}

    original_app_user_id = event.get("original_app_user_id")
    if _has_subscription_account_mismatch(app_user_id, original_app_user_id):
        logger.warning(
            "[RC Webhook] Ignoring account ownership mismatch: app_user_id=%s original_app_user_id=%s type=%s",
            app_user_id,
            original_app_user_id,
            event_type,
        )
        return {"status": "ignored", "reason": SUBSCRIPTION_ACCOUNT_MISMATCH_CODE}

    sb = get_client()
    
    # Fetch current profile for comparison and guards
    current_profile = _fetch_current_profile(sb, app_user_id)
    if not current_profile:
        logger.warning(f"User {app_user_id} not found in profiles table")
        return {"status": "ignored", "reason": "user_not_found"}
    
    current_plan = current_profile.get("plan", "Free")
    current_credits = current_profile.get("credits", 0)
    current_purchased_credits = current_profile.get("purchased_credits", 0)
    last_event_ms = current_profile.get("rc_last_event_ms")
    current_expires_at = current_profile.get("subscription_expires_at")
    incoming_expires_iso = _ms_to_iso(expiration_ms)
    should_reset_credit_schedule = False
    credit_pack_sync_marker_to_remember: str | None = None
    credit_pack_sync_metadata: dict | None = None
    
    # Event ordering guard: reject events older than the last processed event
    if last_event_ms and event_timestamp_ms and event_timestamp_ms < last_event_ms:
        logger.info(f"[RC Webhook] Ignoring out-of-order event for {app_user_id}: event_ts={event_timestamp_ms} < last_ts={last_event_ms}")
        print(f"[RC Webhook] Ignoring out-of-order event for {app_user_id}")
        return {"status": "ignored", "reason": "out_of_order_event"}
    
    # Most lifecycle events should preserve the farthest-known active expiration.
    # Expiration/refund-style events are authoritative and may shorten access.
    new_expires_at = current_expires_at
    if incoming_expires_iso:
        if event_type in {"CANCELLATION", "EXPIRATION", "REFUND"}:
            new_expires_at = incoming_expires_iso
        elif not current_expires_at or incoming_expires_iso > current_expires_at:
            new_expires_at = incoming_expires_iso
    
    # Base update data (always update event timestamp and expiration)
    update_data: dict = {}
    if event_timestamp_ms:
        update_data["rc_last_event_ms"] = event_timestamp_ms
    if new_expires_at:
        update_data["subscription_expires_at"] = new_expires_at

    # ---------------------
    # INITIAL_PURCHASE
    # ---------------------
    if event_type == "INITIAL_PURCHASE":
        new_tier = normalize_plan(_product_to_tier(product_id))
        allocation = get_plan_initial_credits(new_tier)
        
        update_data["plan"] = new_tier
        update_data["credits"] = allocation  # Overwrite credits for new purchase
        should_reset_credit_schedule = True
        
        # Retention offer detection
        offer_code = event.get("offer_code", "")
        if "retention" in product_id.lower() or "retention" in offer_code.lower():
            update_data["retention_offer_used"] = True
            update_data["retention_offer_used_at"] = datetime.now(timezone.utc).isoformat()
        
        print(f"[RC Webhook] INITIAL_PURCHASE: {app_user_id} -> {new_tier}, credits={allocation}")
        logger.info(f"[RC Webhook] INITIAL_PURCHASE: {app_user_id} -> {new_tier}, credits={allocation}")
    
    # ---------------------
    # RENEWAL
    # ---------------------
    elif event_type == "RENEWAL":
        new_tier = normalize_plan(_product_to_tier(product_id))
        allocation = get_plan_initial_credits(new_tier)
        
        update_data["plan"] = new_tier
        update_data["credits"] = allocation  # Reset credits on renewal
        should_reset_credit_schedule = True
        
        print(f"[RC Webhook] RENEWAL: {app_user_id} -> {new_tier}, credits reset to {allocation}")
        logger.info(f"[RC Webhook] RENEWAL: {app_user_id} -> {new_tier}, credits reset to {allocation}")
    
    # ---------------------
    # PRODUCT_CHANGE
    # ---------------------
    elif event_type == "PRODUCT_CHANGE":
        new_tier = normalize_plan(_product_to_tier(product_id))
        
        update_data["plan"] = new_tier  # Update plan immediately
        # Do NOT overwrite credits (Rule B)
        
        # Rule C: Upgrade top-up (Pro â†’ Designer mid-cycle)
        if is_upgrade(current_plan, new_tier):
            new_tier_allocation = get_plan_initial_credits(new_tier)
            if current_credits < new_tier_allocation:
                update_data["credits"] = new_tier_allocation
                should_reset_credit_schedule = True
                print(f"[RC Webhook] PRODUCT_CHANGE (upgrade): {app_user_id} {current_plan} -> {new_tier}, topped up credits {current_credits} -> {new_tier_allocation}")
                logger.info(f"[RC Webhook] PRODUCT_CHANGE (upgrade): {app_user_id} {current_plan} -> {new_tier}, topped up credits")
            else:
                print(f"[RC Webhook] PRODUCT_CHANGE (upgrade): {app_user_id} {current_plan} -> {new_tier}, credits unchanged ({current_credits})")
                logger.info(f"[RC Webhook] PRODUCT_CHANGE (upgrade): {app_user_id} {current_plan} -> {new_tier}, credits unchanged")
        else:
            # Downgrade: keep current credits (Rule D)
            print(f"[RC Webhook] PRODUCT_CHANGE (downgrade): {app_user_id} {current_plan} -> {new_tier}, credits unchanged ({current_credits})")
            logger.info(f"[RC Webhook] PRODUCT_CHANGE (downgrade): {app_user_id} {current_plan} -> {new_tier}, credits unchanged")
    
    # ---------------------
    # NON_RENEWING_PURCHASE
    # ---------------------
    elif event_type == "NON_RENEWING_PURCHASE":
        credit_amount = _extract_credit_pack_amount(product_id)
        if credit_amount is None:
            logger.info(f"[RC Webhook] NON_RENEWING_PURCHASE ignored for non-credit product: {product_id}")
            return {"status": "ignored", "reason": "unknown_non_renewing_product"}

        webhook_metadata = get_admin_user_metadata(app_user_id)
        sync_marker = _build_credit_pack_sync_marker(
            product_id,
            event.get("purchased_at_ms") or event_timestamp_ms,
        )
        if sync_marker and sync_marker in _get_credit_pack_sync_markers(webhook_metadata):
            logger.info(f"[RC Webhook] NON_RENEWING_PURCHASE already synced for {app_user_id}: {sync_marker}")
            return {"status": "ok", "action": "already_synced"}

        update_data["purchased_credits"] = max(0, current_purchased_credits + credit_amount)
        print(f"[RC Webhook] NON_RENEWING_PURCHASE: {app_user_id} +{credit_amount} credits")
        logger.info(f"[RC Webhook] NON_RENEWING_PURCHASE: {app_user_id} +{credit_amount} credits")
        credit_pack_sync_marker_to_remember = sync_marker
        credit_pack_sync_metadata = webhook_metadata

    # ---------------------
    # CANCELLATION
    # ---------------------
    elif event_type == "CANCELLATION":
        now = datetime.now(timezone.utc)
        expires_dt = _parse_iso_datetime(incoming_expires_iso or new_expires_at)

        if expires_dt and expires_dt <= now:
            free_allocation = get_plan_initial_credits("Free")
            update_data["plan"] = "Free"
            update_data["credits"] = free_allocation
            should_reset_credit_schedule = True
            print(f"[RC Webhook] CANCELLATION: {app_user_id} - expired immediately, downgrading to Free")
            logger.info(f"[RC Webhook] CANCELLATION: {app_user_id} - expired immediately, downgraded to Free")
        else:
            print(f"[RC Webhook] CANCELLATION: {app_user_id} - access continues until expiration")
            logger.info(f"[RC Webhook] CANCELLATION: {app_user_id} - access continues until expiration")
    
    # ---------------------
    # EXPIRATION
    # ---------------------
    elif event_type in {"EXPIRATION", "REFUND"}:
        now = datetime.now(timezone.utc)
        effective_expiration = _parse_iso_datetime(incoming_expires_iso or new_expires_at)
        
        if effective_expiration and effective_expiration > now:
            print(f"[RC Webhook] {event_type}: {app_user_id} - ignoring, subscription still active")
            logger.info(f"[RC Webhook] {event_type}: {app_user_id} - ignoring, subscription still active")
            return {"status": "ignored", "reason": "subscription_still_active"}
        
        # Actually expired - downgrade to Free
        free_allocation = get_plan_initial_credits("Free")
        update_data["plan"] = "Free"
        update_data["credits"] = free_allocation
        should_reset_credit_schedule = True
        
        print(f"[RC Webhook] {event_type}: {app_user_id} - downgrading to Free")
        logger.info(f"[RC Webhook] {event_type}: {app_user_id} - downgrading to Free")
    
    # ---------------------
    # VIRTUAL_CURRENCY_TRANSACTION
    # ---------------------
    elif event_type == "VIRTUAL_CURRENCY_TRANSACTION":
        if _extract_credit_pack_amount(product_id) is None:
            logger.info(f"[RC Webhook] VIRTUAL_CURRENCY_TRANSACTION ignored for product: {product_id}")
            return {"status": "ignored", "reason": "non_credit_virtual_currency"}

        logger.info(f"[RC Webhook] VIRTUAL_CURRENCY_TRANSACTION ignored for app credits: {product_id}")
        print(f"[RC Webhook] VIRTUAL_CURRENCY_TRANSACTION: {app_user_id} ignored to avoid double-grant")
        return {"status": "ok", "action": "ignored_virtual_currency_transaction"}
    
    # ---------------------
    # Unknown event type
    # ---------------------
    else:
        logger.info(f"[RC Webhook] Unknown event type: {event_type} for {app_user_id}")
        return {"status": "ignored", "reason": "unknown_event_type"}
    
    if "credits" in update_data and should_reset_credit_schedule:
        update_data["next_credit_reset_at"] = schedule_next_credit_reset()

    # Apply updates
    if update_data:
        sb.table("profiles").update(update_data).eq("id", app_user_id).execute()
        _remember_credit_pack_sync_marker(
            app_user_id,
            credit_pack_sync_metadata,
            credit_pack_sync_marker_to_remember,
        )

    return {"status": "ok"}


@router.post("/sync-credits")
async def sync_credit_pack_purchase(
    payload: CreditPackSyncRequest,
    current: UserState = Depends(get_current_user),
) -> dict:
    product_id = payload.productIdentifier.strip()
    if not product_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="productIdentifier is required")

    purchase_ms = _parse_purchase_date_to_ms(payload.purchaseDate)
    if purchase_ms is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="purchaseDate is required")

    credit_amount = _extract_credit_pack_amount(product_id)
    if credit_amount is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown credit pack")

    sync_marker = _build_credit_pack_sync_marker(product_id, purchase_ms)
    logger.info("[Credit Sync] user=%s product=%s marker=%s", current.id, product_id, sync_marker)
    metadata = get_admin_user_metadata(current.id)
    if sync_marker and sync_marker in _get_credit_pack_sync_markers(metadata):
        logger.info("[Credit Sync] already synced user=%s marker=%s", current.id, sync_marker)
        current_profile = _fetch_current_profile(get_client(), current.id)
        return {
            "status": "ok",
            "action": "already_synced",
            "creditsAdded": 0,
            "currentCredits": ((current_profile.get("credits", 0) + current_profile.get("purchased_credits", 0)) if current_profile else current.credits),
        }

    current_profile = _fetch_current_profile(get_client(), current.id)
    if not current_profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    current_credits = current_profile.get("credits", 0)
    current_purchased_credits = current_profile.get("purchased_credits", 0)
    current_total_credits = current_credits + current_purchased_credits
    logger.info(
        "[Credit Sync] awaiting webhook purchased_credits grant user=%s product=%s marker=%s current_credits=%s",
        current.id,
        product_id,
        sync_marker,
        current_total_credits,
    )

    return {
        "status": "ok",
        "action": "awaiting_webhook",
        "creditsAdded": 0,
        "expectedCredits": credit_amount,
        "currentCredits": current_total_credits,
    }


@router.post("/sync")
async def sync_subscription(
    request: Request,
    current: UserState = Depends(get_current_user),
) -> dict:
    """Sync user's plan from client after purchase/restore.
    
    This provides immediate UI feedback. Credits and retention logic
    are handled by the webhook (source of truth).
    """
    # Client payload is used only as an ownership guard. Plan selection is still
    # reconciled directly from RevenueCat to avoid trusting client product IDs.
    payload: SubscriptionSyncRequest | None = None
    try:
        raw_payload = await request.json()
        if isinstance(raw_payload, dict):
            payload = SubscriptionSyncRequest(**raw_payload)
    except Exception:
        pass

    _ensure_subscription_sync_ownership(current.id, payload=payload)

    subscriber = await _fetch_rc_subscriber(current.id)
    _ensure_subscription_sync_ownership(current.id, subscriber=subscriber)
    new_tier, expires_at = _rc_subscriber_to_plan_and_expiry(subscriber)

    logger.info("[Sync] User %s reconciled to %s from RevenueCat", current.id, new_tier)

    sb = get_client()

    # Avoid race-condition: fetch current db profile to see if this reflects an undetected upgrade.
    # If the webhook hasn't fired yet, we should eagerly provision credits here so we don't cheat the user.
    current_profile = _fetch_current_profile(sb, current.id)
    current_plan = current_profile.get("plan", "Free") if current_profile else "Free"
    current_credits = current_profile.get("credits", 0) if current_profile else 0

    update_data: dict = {"plan": new_tier}
    if expires_at is not None:
        update_data["subscription_expires_at"] = expires_at
    elif new_tier == "Free":
        update_data["subscription_expires_at"] = None

    if is_upgrade(current_plan, new_tier) or (current_plan != new_tier and new_tier == "Free"):
        new_allocation = get_plan_initial_credits(new_tier)
        if current_credits < new_allocation:
            update_data["credits"] = new_allocation
            update_data["next_credit_reset_at"] = schedule_next_credit_reset()

    sb.table("profiles").update(update_data).eq("id", current.id).execute()

    return {"status": "ok", "plan": new_tier}
