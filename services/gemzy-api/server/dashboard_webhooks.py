from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from .dashboard_email_runtime import (
    ensure_contact,
    handle_cancellation_trigger,
    handle_purchase_trigger,
    handle_signup_trigger,
    verify_shared_secret,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["dashboard-webhooks"])


@router.post("/revenuecat")
async def revenuecat_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    secret = os.getenv("REVENUECAT_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook not configured.")
    if not verify_shared_secret(authorization or "", secret):
        raise HTTPException(status_code=401, detail="Invalid signature.")

    body = await request.json()
    event = body.get("event") if isinstance(body, dict) else None
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise HTTPException(status_code=400, detail="Missing event payload.")

    subscriber_attributes = event.get("subscriber_attributes") if isinstance(event.get("subscriber_attributes"), dict) else {}
    email_value = subscriber_attributes.get("$email") if isinstance(subscriber_attributes.get("$email"), dict) else {}
    email = str(email_value.get("value") or "").strip().lower()
    if not email:
        logger.info("RevenueCat event skipped without email", extra={"eventType": event.get("type")})
        return {"skipped": "no-email"}

    contact_id = ensure_contact(email, "revenuecat")
    event_type = str(event.get("type") or "")
    if event_type == "INITIAL_PURCHASE":
        return {"ok": True, "result": handle_purchase_trigger(contact_id)}
    if event_type in {"CANCELLATION", "EXPIRATION"}:
        return {"ok": True, "result": handle_cancellation_trigger(contact_id)}
    return {"ok": True}


@router.post("/auth-signup")
async def auth_signup_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    secret = os.getenv("AUTH_SIGNUP_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook not configured.")
    if not verify_shared_secret(authorization or "", secret):
        raise HTTPException(status_code=401, detail="Invalid signature.")

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="email is required.")
    email = str(body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required.")
    name = str(body.get("name") or "").strip() or None
    contact_id = ensure_contact(email, "signup", name)
    return {"ok": True, "result": handle_signup_trigger(contact_id)}

