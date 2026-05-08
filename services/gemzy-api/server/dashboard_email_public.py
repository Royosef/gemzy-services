from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from .dashboard_common import dashboard_table, utc_now_iso
from .dashboard_email_runtime import handle_unsubscribe_trigger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email", tags=["dashboard-email-public"])

TRANSPARENT_PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)

_SAFE_REDIRECT_RE = re.compile(r"^https?://", re.IGNORECASE)
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


def _lookup_recipient_by_token(token: str) -> dict | None:
    rows = (
        dashboard_table("email_campaign_recipients")
        .select("*")
        .eq("send_token", token)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _safe_redirect_target(url: str) -> bool:
    return bool(_SAFE_REDIRECT_RE.match(url.strip()))


def _transparent_pixel_response() -> Response:
    return Response(content=TRANSPARENT_PIXEL, media_type="image/gif", headers=_NO_CACHE_HEADERS)


def _simple_page(title: str, body: str | None = None) -> str:
    body_html = f"<p>{_escape_html(body)}</p>" if body else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width,initial-scale=1.0" />
<title>{_escape_html(title)}</title>
<style>
  body {{ margin:0; padding:48px 16px; background:#f5f5f5; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; color:#171717; }}
  .card {{ max-width:480px; margin:0 auto; background:#ffffff; border:1px solid #e5e5e5; border-radius:8px; padding:32px; }}
  h1 {{ margin:0 0 12px 0; font-size:22px; font-weight:600; }}
  p {{ margin:0; font-size:15px; line-height:1.5; color:#525252; }}
</style>
</head>
<body>
  <div class="card">
    <h1>{_escape_html(title)}</h1>
    {body_html}
  </div>
</body>
</html>"""


def _escape_html(value: str | None) -> str:
    text = value or ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@router.get("/click")
async def click_handler(
    request: Request,
    t: str = Query(default=""),
    u: str = Query(default=""),
    l: str | None = Query(default=None),
) -> Response:
    token = str(t or "")
    url = str(u or "")
    label = (l or "").strip()[:200] or None
    if not token or not url:
        return PlainTextResponse("Link expired or invalid.", status_code=404)

    recipient = None
    try:
        recipient = _lookup_recipient_by_token(token)
        dashboard_table("email_link_clicks").insert(
            {
                "campaign_id": recipient.get("campaign_id") if recipient else None,
                "send_token": token,
                "link_url": url,
                "link_label": label,
                "user_agent": request.headers.get("user-agent"),
            }
        ).execute()
        if recipient:
            update_payload = {
                "click_count": int(recipient.get("click_count") or 0) + 1,
                "first_click_at": recipient.get("first_click_at") or utc_now_iso(),
            }
            if recipient.get("first_click_at") in {None, ""}:
                update_payload["status"] = "clicked"
            else:
                update_payload["status"] = recipient.get("status")
            dashboard_table("email_campaign_recipients").update(update_payload).eq(
                "send_token", token
            ).execute()
    except Exception:
        logger.exception("Failed to record email click", extra={"token": token, "url": url})

    if not _safe_redirect_target(url):
        return PlainTextResponse("Link expired or invalid.", status_code=404)
    return RedirectResponse(url=url, status_code=302)


@router.get("/open")
async def open_handler(
    request: Request,
    t: str = Query(default=""),
) -> Response:
    token = str(t or "")
    if not token:
        return _transparent_pixel_response()

    try:
        recipient = _lookup_recipient_by_token(token)
        dashboard_table("email_opens").insert(
            {
                "campaign_id": recipient.get("campaign_id") if recipient else None,
                "send_token": token,
                "user_agent": request.headers.get("user-agent"),
            }
        ).execute()
        if recipient and recipient.get("opened_at") in {None, ""}:
            dashboard_table("email_campaign_recipients").update(
                {"opened_at": utc_now_iso(), "status": "opened"}
            ).eq("send_token", token).execute()
    except Exception:
        logger.exception("Failed to record email open", extra={"token": token})
    return _transparent_pixel_response()


@router.get("/vote")
async def vote_handler(
    t: str = Query(default=""),
    b: str = Query(default=""),
    o: str = Query(default=""),
) -> HTMLResponse:
    token = str(t or "")
    block_id = str(b or "")
    option_id = str(o or "")
    if not token or not block_id or not option_id:
        return HTMLResponse(_simple_page("Vote link expired or invalid."), status_code=404)

    try:
        recipient = _lookup_recipient_by_token(token)
        dashboard_table("email_votes").delete().eq("send_token", token).eq(
            "vote_block_id", block_id
        ).execute()
        dashboard_table("email_votes").insert(
            {
                "campaign_id": recipient.get("campaign_id") if recipient else None,
                "send_token": token,
                "vote_block_id": block_id,
                "option_id": option_id,
            }
        ).execute()
    except Exception:
        logger.exception(
            "Failed to record email vote",
            extra={"token": token, "block_id": block_id, "option_id": option_id},
        )

    return HTMLResponse(
        _simple_page(
            "Thanks for voting.",
            "We've recorded your response. You can close this tab.",
        )
    )


@router.get("/unsubscribe")
async def unsubscribe_handler(
    t: str = Query(default=""),
) -> HTMLResponse:
    token = str(t or "")
    if not token:
        return HTMLResponse(_simple_page("Unsubscribe link expired or invalid."), status_code=404)

    recipient = _lookup_recipient_by_token(token)
    if not recipient:
        return HTMLResponse(_simple_page("Unsubscribe link expired or invalid."), status_code=404)

    try:
        existing = (
            dashboard_table("email_unsubscribes")
            .select("*")
            .eq("contact_id", recipient["contact_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        if not existing:
            dashboard_table("email_unsubscribes").insert(
                {
                    "contact_id": recipient["contact_id"],
                    "source": "email_link",
                }
            ).execute()
        handle_unsubscribe_trigger(str(recipient["contact_id"]))
    except Exception:
        logger.exception("Failed to record unsubscribe", extra={"token": token})

    display_email = ""
    try:
        contact_rows = (
            dashboard_table("email_contacts")
            .select("*")
            .eq("id", recipient["contact_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        if contact_rows:
            display_email = str(contact_rows[0].get("email") or "")
    except Exception:
        logger.exception(
            "Failed to load email contact after unsubscribe",
            extra={"contact_id": recipient.get("contact_id")},
        )

    message = (
        f"{display_email} will no longer receive marketing email from Gemzy. You can close this tab."
        if display_email
        else "You will no longer receive marketing email from Gemzy. You can close this tab."
    )
    return HTMLResponse(_simple_page("Unsubscribed.", message))
