"""Web purchases happen in the mobile app for now.

The web app shows "Complete your purchase in the app" (QR code on desktop, a button on phones)
instead of a checkout. This module records those purchase attempts, so an in-app purchase that
follows can be attributed to the website, and keeps the "tell me when I can buy on the website"
waitlist.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import analytics
from .auth import get_current_user
from .rate_limit import limiter
from .schemas import UserState
from .supabase_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web-purchase", tags=["web-purchase"])

# Smart link on the landing page: sends phones to the right store, shows both on desktop.
DEFAULT_APP_LINK = "https://www.gemzy.co/open"
ATTRIBUTION_WINDOW = timedelta(days=7)

# e.g. "credits:300", "plan:pro:monthly", "credits".
_PRODUCT = r"^[a-z0-9][a-z0-9:_-]{0,59}$"
_SOURCE = r"^[a-z][a-z0-9_]{0,39}$"


def app_link() -> str:
    link = os.getenv("APP_SMART_LINK", "").strip()
    return link if link.startswith("https://") else DEFAULT_APP_LINK


class PurchaseIntentPayload(BaseModel):
    product: str = Field(pattern=_PRODUCT)
    source: str = Field(pattern=_SOURCE)


class PurchaseIntentResponse(BaseModel):
    id: str
    waitlisted: bool


class WaitlistResponse(BaseModel):
    joined: bool
    joinedAt: str | None = None


def _waitlist_row(user_id: str) -> dict | None:
    rows = (
        get_client()
        .table("web_purchase_waitlist")
        .select("created_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None


@router.post("/intent", response_model=PurchaseIntentResponse)
@limiter.limit("30/minute")
def record_intent(
    request: Request,
    payload: PurchaseIntentPayload,
    user: UserState = Depends(get_current_user),
) -> PurchaseIntentResponse:
    """A signed-in user tried to buy on the website. The id goes into the QR code link."""

    rows = (
        get_client()
        .table("web_purchase_intents")
        .insert({"user_id": user.id, "product": payload.product, "source": payload.source})
        .execute()
    ).data or []
    if not rows:
        raise RuntimeError("web_purchase_intents insert returned no row")
    return PurchaseIntentResponse(id=str(rows[0]["id"]), waitlisted=_waitlist_row(user.id) is not None)


@router.get("/open", include_in_schema=False)
@limiter.limit("60/minute")
def open_app_link(
    request: Request, i: str | None = None, m: str | None = None
) -> RedirectResponse:
    """QR code / phone button target: notes the first open of an intent's link (`m`: "qr" or
    "button"), then goes to the app link.

    Public (the phone that scans is usually not signed in). Always redirects to the same fixed
    smart link, so it can't be used as an open redirect; an unknown id just redirects.
    """

    try:
        intent_id = str(UUID(i or ""))
    except ValueError:
        intent_id = None
    if intent_id:
        try:
            rows = (
                get_client()
                .table("web_purchase_intents")
                .update({"app_link_opened_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", intent_id)
                .is_("app_link_opened_at", "null")
                .execute()
            ).data or []
            if rows:
                row = rows[0]
                analytics.enqueue(
                    "Web App Link Clicked",
                    str(row["user_id"]),
                    f"web-app-link:{intent_id}",
                    {
                        "product": row.get("product"),
                        "source": row.get("source"),
                        "method": "button" if m == "button" else "qr",
                    },
                )
        except Exception:
            # Tracking must never stop the visitor from reaching the store.
            logger.exception("Failed to record app link open for intent %s", intent_id)
    return RedirectResponse(app_link(), status_code=302, headers={"Cache-Control": "no-store"})


@router.get("/waitlist", response_model=WaitlistResponse)
def get_waitlist(user: UserState = Depends(get_current_user)) -> WaitlistResponse:
    row = _waitlist_row(user.id)
    return WaitlistResponse(joined=row is not None, joinedAt=str(row["created_at"]) if row else None)


@router.post("/waitlist", response_model=WaitlistResponse)
@limiter.limit("10/minute")
def join_waitlist(
    request: Request,
    payload: PurchaseIntentPayload,
    user: UserState = Depends(get_current_user),
) -> WaitlistResponse:
    """Ask to be emailed when buying on the website opens. Idempotent: the first join is kept."""

    get_client().table("web_purchase_waitlist").upsert(
        {"user_id": user.id, "product": payload.product, "source": payload.source},
        on_conflict="user_id",
        ignore_duplicates=True,
    ).execute()
    row = _waitlist_row(user.id)
    return WaitlistResponse(joined=True, joinedAt=str(row["created_at"]) if row else None)


def recent_intent(user_id: str, purchased_at: datetime) -> dict | None:
    """The latest website purchase attempt in the 7 days before an in-app purchase, if any."""

    rows = (
        get_client()
        .table("web_purchase_intents")
        .select("product,source,created_at")
        .eq("user_id", user_id)
        .gte("created_at", (purchased_at - ATTRIBUTION_WINDOW).isoformat())
        .lte("created_at", purchased_at.isoformat())
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None
