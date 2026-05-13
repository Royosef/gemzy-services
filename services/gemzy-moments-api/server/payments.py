"""RevenueCat payments integration."""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from .auth import get_current_user
from .plans import get_plan_initial_credits, is_upgrade, normalize_plan
from .schemas import UserState
from .supabase_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

RC_WEBHOOK_AUTH = os.getenv("RC_WEBHOOK_AUTH")


def _product_to_tier(product_id: str) -> str:
    """Map RevenueCat product ID to plan tier."""
    product_lower = product_id.lower()
    if "designer" in product_lower:
        return "Designer"
    elif "pro" in product_lower:
        return "Pro"
    return "Free"


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
            .select("plan,credits,rc_last_event_ms,subscription_expires_at")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        return data[0] if data else None
    except Exception as e:
        logger.warning(f"Failed to fetch profile for {user_id}: {e}")
        return None


@router.post("/webhook")
async def rc_webhook(request: Request) -> dict:
    """Handle RevenueCat webhooks to update user credits and plan.
    
    Event handling rules:
    - INITIAL_PURCHASE: Set plan, overwrite credits, set expiration
    - RENEWAL: Keep plan, reset credits, update expiration
    - PRODUCT_CHANGE: Update plan immediately, do NOT overwrite credits (apply top-up if upgrade)
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

    sb = get_client()
    
    # Fetch current profile for comparison and guards
    current_profile = _fetch_current_profile(sb, app_user_id)
    if not current_profile:
        logger.warning(f"User {app_user_id} not found in profiles table")
        return {"status": "ignored", "reason": "user_not_found"}
    
    current_plan = current_profile.get("plan", "Free")
    current_credits = current_profile.get("credits", 0)
    last_event_ms = current_profile.get("rc_last_event_ms")
    current_expires_at = current_profile.get("subscription_expires_at")
    incoming_expires_iso = _ms_to_iso(expiration_ms)
    
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
        
        print(f"[RC Webhook] RENEWAL: {app_user_id} -> {new_tier}, credits reset to {allocation}")
        logger.info(f"[RC Webhook] RENEWAL: {app_user_id} -> {new_tier}, credits reset to {allocation}")
    
    # ---------------------
    # PRODUCT_CHANGE
    # ---------------------
    elif event_type == "PRODUCT_CHANGE":
        new_tier = normalize_plan(_product_to_tier(product_id))
        
        update_data["plan"] = new_tier  # Update plan immediately
        # Do NOT overwrite credits (Rule B)
        
        # Rule C: Upgrade top-up (Pro → Designer mid-cycle)
        if is_upgrade(current_plan, new_tier):
            new_tier_allocation = get_plan_initial_credits(new_tier)
            if current_credits < new_tier_allocation:
                update_data["credits"] = new_tier_allocation
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
    # CANCELLATION
    # ---------------------
    elif event_type == "CANCELLATION":
        now = datetime.now(timezone.utc)
        expires_dt = _parse_iso_datetime(incoming_expires_iso or new_expires_at)

        if expires_dt and expires_dt <= now:
            free_allocation = get_plan_initial_credits("Free")
            update_data["plan"] = "Free"
            update_data["credits"] = free_allocation
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
        
        print(f"[RC Webhook] {event_type}: {app_user_id} - downgrading to Free")
        logger.info(f"[RC Webhook] {event_type}: {app_user_id} - downgrading to Free")
    
    # ---------------------
    # Unknown event type
    # ---------------------
    else:
        logger.info(f"[RC Webhook] Unknown event type: {event_type} for {app_user_id}")
        return {"status": "ignored", "reason": "unknown_event_type"}
    
    # Apply updates
    if update_data:
        sb.table("profiles").update(update_data).eq("id", app_user_id).execute()

    return {"status": "ok"}


@router.post("/sync")
async def sync_subscription(
    request: Request,
    current: UserState = Depends(get_current_user),
) -> dict:
    """Sync user's plan from client after purchase/restore.
    
    This provides immediate UI feedback. Credits and retention logic
    are handled by the webhook (source of truth).
    """
    payload = await request.json()
    product_id = payload.get("product_id", "")
    
    new_tier = normalize_plan(_product_to_tier(product_id))
    
    logger.info(f"[Sync] User {current.id} syncing plan to {new_tier} (product: {product_id})")
    
    sb = get_client()
    sb.table("profiles").update({"plan": new_tier}).eq("id", current.id).execute()
    
    return {"status": "ok", "plan": new_tier}

