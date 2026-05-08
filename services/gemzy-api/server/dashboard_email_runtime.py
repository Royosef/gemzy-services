from __future__ import annotations

import base64
import logging
import os
import re
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from threading import Thread
from time import sleep
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException, status

from .dashboard_ai import GEMZY_CONTEXT, call_claude
from .dashboard_common import dashboard_table, iso_or_none, utc_now_iso
from .supabase_client import get_service_role_client

logger = logging.getLogger(__name__)

ASSETS_BUCKET = "dashboard-assets"
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
SIGNED_URL_TTL_SECONDS = 3600
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
EMAIL_SEND_RATE_PER_SECOND = 2
TRACKING_PATH_RE = re.compile(r"/api/email/(click|open|vote|unsubscribe)", re.IGNORECASE)
EMAIL_EXTRACT_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _dashboard_storage_bucket():
    return get_service_role_client().storage.from_(ASSETS_BUCKET)


def _sanitize_file_name(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    raw_stem = stem if dot else name
    raw_ext = ext if dot else ""
    clean_stem = (
        "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in raw_stem.lower()).strip("-")[:60] or "file"
    )
    clean_ext = "".join(ch for ch in raw_ext.lower() if ch.isalnum())[:8]
    return f"{clean_stem}.{clean_ext}" if clean_ext else clean_stem


def create_signed_url(storage_path: str, expires_in: int = SIGNED_URL_TTL_SECONDS) -> str:
    payload = _dashboard_storage_bucket().create_signed_url(storage_path, expires_in)
    signed_url = payload.get("signedURL") or payload.get("signedUrl")
    if not signed_url:
        raise RuntimeError(f"Could not create signed URL for {storage_path}.")
    return signed_url


def upload_email_asset(*, buffer: bytes, file_name: str, mime_type: str) -> dict[str, str]:
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type.")
    if not buffer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty.")
    if len(buffer) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds 5MB limit.")
    safe_name = _sanitize_file_name(file_name)
    storage_path = f"email/{uuid4()}-{safe_name}"
    _dashboard_storage_bucket().upload(
        storage_path,
        buffer,
        {"content-type": mime_type, "upsert": "false"},
    )
    return {"storagePath": storage_path, "signedUrl": create_signed_url(storage_path, 60 * 60 * 24)}


def _read_env(name: str) -> str | None:
    raw = os.getenv(name)
    if not raw:
        return None
    stripped = raw.strip().strip("'").strip('"')
    return stripped or None


def is_smtp_configured() -> bool:
    return bool(_read_env("GMAIL_SMTP_USER") and _read_env("GMAIL_SMTP_PASSWORD"))


def get_dashboard_base_url() -> str:
    return os.getenv("PUBLIC_DASHBOARD_URL") or os.getenv("DASHBOARD_PUBLIC_URL") or "https://app.gemzy.co"


def _smtp_default_from_address() -> str | None:
    return _read_env("GMAIL_SMTP_FROM_ADDRESS") or _read_env("GMAIL_SMTP_USER")


def _smtp_default_from_name() -> str:
    return _read_env("GMAIL_SMTP_FROM_NAME") or "Gemzy"


def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    to_name: str | None = None,
    from_address: str | None = None,
    from_name: str | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    user = _read_env("GMAIL_SMTP_USER")
    password = _read_env("GMAIL_SMTP_PASSWORD")
    if not user or not password:
        message = "SMTP is not configured. Set GMAIL_SMTP_USER and GMAIL_SMTP_PASSWORD."
        return {
            "success": False,
            "error": message,
            "smtpResponse": None,
            "isRateLimitError": False,
            "isPermanentError": False,
        }

    sender = from_address or _smtp_default_from_address()
    if not sender:
        return {
            "success": False,
            "error": "No GMAIL_SMTP_FROM_ADDRESS or GMAIL_SMTP_USER set.",
            "smtpResponse": None,
            "isRateLimitError": False,
            "isPermanentError": False,
        }

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((from_name or _smtp_default_from_name(), sender))
    message["To"] = formataddr((to_name or "", to)) if to_name else to
    if reply_to:
        message["Reply-To"] = reply_to
    for key, value in (headers or {}).items():
        message[key] = value
    if text:
        message.set_content(text)
        message.add_alternative(html, subtype="html")
    else:
        message.set_content(strip_html_for_fallback(html))
        message.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
            server.login(user, password)
            response = server.send_message(message)
        return {
            "success": True,
            "error": None,
            "smtpResponse": str(response or "ok"),
            "isRateLimitError": False,
            "isPermanentError": False,
        }
    except smtplib.SMTPResponseException as exc:
        code = int(getattr(exc, "smtp_code", 0) or 0)
        is_rate = 400 <= code < 500
        is_permanent = 500 <= code < 600
        return {
            "success": False,
            "error": str(exc),
            "smtpResponse": str(code) if code else None,
            "isRateLimitError": is_rate,
            "isPermanentError": is_permanent,
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "smtpResponse": None,
            "isRateLimitError": False,
            "isPermanentError": False,
        }


def _load_rows(table_name: str) -> list[dict[str, Any]]:
    return dashboard_table(table_name).select("*").execute().data or []


def _find_first(table_name: str, **filters: Any) -> dict[str, Any] | None:
    rows = _load_rows(table_name)
    for row in rows:
        if all(row.get(key) == value for key, value in filters.items()):
            return row
    return None


def _find_all(table_name: str, **filters: Any) -> list[dict[str, Any]]:
    rows = _load_rows(table_name)
    return [row for row in rows if all(row.get(key) == value for key, value in filters.items())]


def _insert_row(table_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    dashboard_table(table_name).insert(payload).execute()
    return payload


def _update_where(table_name: str, patch: dict[str, Any], **filters: Any) -> list[dict[str, Any]]:
    query = dashboard_table(table_name).update(patch)
    for key, value in filters.items():
        query = query.eq(key, value)
    return query.execute().data or []


def _delete_where(table_name: str, **filters: Any) -> list[dict[str, Any]]:
    query = dashboard_table(table_name).delete()
    for key, value in filters.items():
        query = query.eq(key, value)
    return query.execute().data or []


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def ensure_contact(email: str, source: str, name: str | None = None) -> str:
    normalized = _normalize_email(email)
    existing = _find_first("email_contacts", email=normalized)
    if existing:
        return str(existing["id"])
    now = utc_now_iso()
    row = {
        "id": str(uuid4()),
        "email": normalized,
        "name": name.strip() if isinstance(name, str) and name.strip() else None,
        "source": source,
        "tags": [],
        "created_at": now,
        "updated_at": now,
    }
    _insert_row("email_contacts", row)
    return str(row["id"])


def pick_default_signature_id() -> str | None:
    row = _find_first("email_signatures", is_default=True)
    return str(row["id"]) if row else None


def blocks_from_json(raw: Any) -> list[dict[str, Any]]:
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _substitute_tokens(text: str, ctx: dict[str, Any]) -> str:
    return (
        str(text or "")
        .replace("{{name}}", str(ctx.get("recipientName") or ""))
        .replace("{{email}}", str(ctx.get("recipientEmail") or ""))
    )


def _unsubscribe_url(ctx: dict[str, Any]) -> str:
    base = str(ctx.get("baseUrl") or get_dashboard_base_url()).rstrip("/")
    token = str(ctx.get("unsubscribeToken") or "preview")
    return f"{base}/api/email/unsubscribe?t={quote(token)}"


def _vote_url(block_id: str, option_id: str, ctx: dict[str, Any]) -> str:
    base = str(ctx.get("baseUrl") or get_dashboard_base_url()).rstrip("/")
    token = str(ctx.get("unsubscribeToken") or "preview")
    campaign_id = str(ctx.get("campaignId") or "preview")
    return (
        f"{base}/api/email/vote?t={quote(token)}"
        f"&c={quote(campaign_id)}&b={quote(block_id)}&o={quote(option_id)}"
    )


def _paragraphs_from_text(text: str) -> str:
    paragraphs = [escape(line.strip()) for line in str(text).split("\n") if line.strip()]
    if not paragraphs:
        return ""
    return "".join(f'<p style="margin:0 0 12px 0;">{paragraph}</p>' for paragraph in paragraphs)


def _render_block(block: dict[str, Any], ctx: dict[str, Any]) -> str:
    block_type = str(block.get("type") or "")
    align = str(block.get("align") or "left")
    align_style = "text-align:center;" if align == "center" else "text-align:right;" if align == "right" else "text-align:left;"
    width_pct = int(block.get("widthPct") or 100)
    width_attr = f' style="width:{width_pct}%;margin:0 auto;"' if width_pct < 100 else ""

    def wrap(inner: str, padding_y: int = 14) -> str:
        return f'<tr><td style="padding:{padding_y}px 24px;"><div{width_attr}>{inner}</div></td></tr>'

    if block_type == "text":
        return wrap(f'<div style="{align_style}line-height:1.55;font-size:15px;">{_paragraphs_from_text(_substitute_tokens(str(block.get("content") or ""), ctx))}</div>')
    if block_type == "heading":
        level = int(block.get("level") or 2)
        font_size = 28 if level == 1 else 22 if level == 2 else 18
        tag = f"h{level if level in {1, 2, 3} else 2}"
        content = escape(_substitute_tokens(str(block.get("content") or ""), ctx))
        return wrap(f'<{tag} style="margin:0;{align_style}font-size:{font_size}px;line-height:1.3;font-weight:600;color:#0a0a0a;">{content}</{tag}>')
    if block_type == "image":
        src = str(block.get("src") or "").strip()
        alt_text = escape(str(block.get("alt") or ""))
        if not src:
            return wrap(f'<div style="{align_style}padding:20px;border:1px dashed #d4d4d4;color:#a3a3a3;font-size:12px;">Image not set.</div>')
        href = str(block.get("href") or "").strip()
        img = f'<img src="{escape(src, quote=True)}" alt="{alt_text}" style="display:block;max-width:100%;height:auto;border:0;outline:none;text-decoration:none;" />'
        if href:
            img = f'<a href="{escape(href, quote=True)}" target="_blank" rel="noopener" style="display:inline-block;">{img}</a>'
        return wrap(f'<div style="{align_style}">{img}</div>', padding_y=8)
    if block_type == "button":
        label = escape(_substitute_tokens(str(block.get("label") or ""), ctx))
        href = escape(str(block.get("href") or ""), quote=True)
        bg = escape(str(block.get("bgColor") or "#0a0a0a"), quote=True)
        fg = escape(str(block.get("textColor") or "#ffffff"), quote=True)
        return wrap(
            f'<div style="{align_style}"><a href="{href}" target="_blank" rel="noopener" style="display:inline-block;background:{bg};color:{fg};text-decoration:none;font-weight:600;font-size:15px;padding:12px 24px;border-radius:6px;">{label}</a></div>'
        )
    if block_type == "url_link":
        label = escape(_substitute_tokens(str(block.get("label") or ""), ctx))
        href = escape(str(block.get("href") or ""), quote=True)
        return wrap(f'<div style="{align_style}font-size:15px;line-height:1.55;"><a href="{href}" target="_blank" rel="noopener" style="color:#0a0a0a;text-decoration:underline;">{label}</a></div>')
    if block_type == "social_links":
        items = []
        for link in block.get("links") or []:
            if not isinstance(link, dict):
                continue
            href = escape(str(link.get("href") or ""), quote=True)
            platform = escape(str(link.get("platform") or "link"))
            items.append(f'<a href="{href}" target="_blank" rel="noopener" style="display:inline-block;margin:0 6px;color:#0a0a0a;text-decoration:none;">{platform.title()}</a>')
        return wrap(f'<div style="{align_style}">{"".join(items)}</div>')
    if block_type == "divider":
        thickness = max(1, min(10, int(block.get("thickness") or 1)))
        color = escape(str(block.get("color") or "#e5e5e5"), quote=True)
        return wrap(f'<div style="border-top:{thickness}px solid {color};margin:0;font-size:0;line-height:0;">&nbsp;</div>', padding_y=8)
    if block_type == "spacer":
        height = max(4, min(200, int(block.get("height") or 24)))
        return f'<tr><td style="padding:0;height:{height}px;line-height:{height}px;font-size:0;">&nbsp;</td></tr>'
    if block_type == "signature":
        explicit_id = block.get("signatureId")
        signatures_by_id = ctx.get("signaturesById") or {}
        target = signatures_by_id.get(str(explicit_id)) if explicit_id else ctx.get("signature")
        if not target:
            return ""
        child_ctx = dict(ctx)
        child_ctx["signature"] = None
        return "".join(_render_block(child, child_ctx) for child in target.get("blocks", []))
    if block_type == "unsubscribe":
        label = escape(str(block.get("label") or "Unsubscribe"))
        href = escape(_unsubscribe_url(ctx), quote=True)
        return wrap(f'<div style="{align_style}font-size:12px;color:#737373;"><a href="{href}" target="_blank" rel="noopener" style="color:#737373;text-decoration:underline;">{label}</a></div>')
    if block_type == "vote":
        question = escape(_substitute_tokens(str(block.get("question") or ""), ctx))
        options_html = []
        for option in block.get("options") or []:
            if not isinstance(option, dict):
                continue
            href = escape(_vote_url(str(block.get("id") or ""), str(option.get("id") or ""), ctx), quote=True)
            label = escape(_substitute_tokens(str(option.get("label") or ""), ctx))
            options_html.append(
                f'<a href="{href}" target="_blank" rel="noopener" style="display:inline-block;margin:6px;background:#fafafa;border:1px solid #e5e5e5;color:#0a0a0a;text-decoration:none;font-weight:500;font-size:14px;padding:10px 18px;border-radius:6px;">{label}</a>'
            )
        return wrap(f'<div style="{align_style}"><div style="font-size:15px;font-weight:600;margin-bottom:8px;color:#0a0a0a;">{question}</div><div>{"".join(options_html)}</div></div>')
    if block_type == "raw_html":
        return wrap(_substitute_tokens(str(block.get("content") or ""), ctx))
    return wrap(f'<div style="{align_style}line-height:1.55;font-size:15px;">{_paragraphs_from_text(_substitute_tokens(str(block.get("content") or ""), ctx))}</div>')


def render_blocks_to_html(blocks: list[dict[str, Any]], ctx: dict[str, Any] | None = None) -> str:
    render_ctx = dict(ctx or {})
    has_signature_block = any(str(block.get("type") or "") == "signature" for block in blocks)
    rows = [_render_block(block, render_ctx) for block in blocks]
    if not has_signature_block and render_ctx.get("signature") and render_ctx["signature"].get("blocks"):
        child_ctx = dict(render_ctx)
        child_ctx["signature"] = None
        rows.extend(_render_block(block, child_ctx) for block in render_ctx["signature"]["blocks"])
    inner = "\n".join(row for row in rows if row)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width,initial-scale=1.0" />
<title>Gemzy email</title>
</head>
<body style="margin:0;padding:0;background:#f5f5f5;-webkit-text-size-adjust:100%;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f5f5;">
  <tr>
    <td align="center" style="padding:24px 12px;">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#171717;">
        {inner}
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def render_blocks_to_text(blocks: list[dict[str, Any]], ctx: dict[str, Any] | None = None) -> str:
    render_ctx = dict(ctx or {})
    out: list[str] = []
    for block in blocks:
        block_type = str(block.get("type") or "")
        if block_type in {"text", "heading"}:
            out.append(_substitute_tokens(str(block.get("content") or ""), render_ctx))
        elif block_type in {"button", "url_link"}:
            out.append(f'{_substitute_tokens(str(block.get("label") or ""), render_ctx)}: {str(block.get("href") or "")}')
        elif block_type == "image":
            out.append(f'[image: {str(block.get("alt") or "").strip() or "image"}]')
        elif block_type == "social_links":
            items = []
            for link in block.get("links") or []:
                if isinstance(link, dict):
                    items.append(f'{str(link.get("platform") or "link")}: {str(link.get("href") or "")}')
            out.append("\n".join(items))
        elif block_type == "divider":
            out.append("----")
        elif block_type == "signature":
            signatures_by_id = render_ctx.get("signaturesById") or {}
            explicit_id = block.get("signatureId")
            target = signatures_by_id.get(str(explicit_id)) if explicit_id else render_ctx.get("signature")
            if target:
                child_ctx = dict(render_ctx)
                child_ctx["signature"] = None
                out.append(render_blocks_to_text(target.get("blocks", []), child_ctx))
        elif block_type == "unsubscribe":
            out.append(f'{str(block.get("label") or "Unsubscribe")}: {_unsubscribe_url(render_ctx)}')
        elif block_type == "vote":
            lines = [_substitute_tokens(str(block.get("question") or ""), render_ctx)]
            for option in block.get("options") or []:
                if isinstance(option, dict):
                    lines.append(
                        f'- {str(option.get("label") or "")}: {_vote_url(str(block.get("id") or ""), str(option.get("id") or ""), render_ctx)}'
                    )
            out.append("\n".join(lines))
        elif block_type == "raw_html":
            out.append(strip_html_for_fallback(str(block.get("content") or "")))
    if not any(str(block.get("type") or "") == "signature" for block in blocks) and render_ctx.get("signature"):
        out.append(render_blocks_to_text(render_ctx["signature"].get("blocks", []), {**render_ctx, "signature": None}))
    return "\n\n".join(part for part in out if part).strip()


def strip_html_for_fallback(html: str) -> str:
    return (
        str(html)
        .replace("<br>", "\n")
        .replace("<br/>", "\n")
        .replace("<br />", "\n")
    )


def inject_tracking(html: str, send_token: str, campaign_id: str, base_url: str) -> str:
    pixel = f'<img src="{base_url.rstrip("/")}/api/email/open?t={quote(send_token)}" alt="" width="1" height="1" style="display:block;border:0;outline:none;text-decoration:none;height:1px;width:1px;" />'

    def replace_anchor(match: re.Match[str]) -> str:
        pre = match.group(1) or ""
        href_double = match.group(3)
        href_single = match.group(4)
        post = match.group(5) or ""
        label = match.group(6) or ""
        original = (href_double or href_single or "").strip()
        if not original:
            return match.group(0)
        if TRACKING_PATH_RE.search(original):
            return match.group(0)
        if original.startswith("mailto:") or original.startswith("tel:") or original.startswith("#"):
            return match.group(0)
        cleaned_label = re.sub(r"<[^>]+>", " ", label)
        cleaned_label = re.sub(r"\s+", " ", cleaned_label).strip()[:120]
        tracked = (
            f'{base_url.rstrip("/")}/api/email/click?t={quote(send_token)}'
            f'&u={quote(original, safe="")}'
        )
        if cleaned_label:
            tracked += f'&l={quote(cleaned_label, safe="")}'
        return f'<a{pre}href="{tracked}"{post}>{label}</a>'

    tracked_html = re.sub(
        r'<a\b([^>]*?)href=("([^"]*)"|\'([^\']*)\')([^>]*)>([\s\S]*?)</a>',
        replace_anchor,
        html,
        flags=re.IGNORECASE,
    )
    if re.search(r"</body>", tracked_html, flags=re.IGNORECASE):
        return re.sub(r"</body>", f"{pixel}</body>", tracked_html, flags=re.IGNORECASE)
    return f"{tracked_html}\n{pixel}"


def convert_raw_html_to_blocks(html: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"<!--[\s\S]*?-->", "", html)
    cleaned = re.sub(r"<style[\s\S]*?</style>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<script[\s\S]*?</script>", "", cleaned, flags=re.IGNORECASE)
    body_match = re.search(r"<body\b[^>]*>([\s\S]*?)</body>", cleaned, flags=re.IGNORECASE)
    content = (body_match.group(1) if body_match else cleaned).strip()
    if not content:
        return [{"id": str(uuid4()), "type": "raw_html", "content": html, "widthPct": 100}]
    blocks: list[dict[str, Any]] = []
    for heading in re.finditer(r"<h([1-3])\b[^>]*>([\s\S]*?)</h\1>", content, flags=re.IGNORECASE):
        blocks.append(
            {
                "id": str(uuid4()),
                "type": "heading",
                "level": int(heading.group(1)),
                "content": strip_html_for_fallback(heading.group(2)),
                "widthPct": 100,
            }
        )
    for paragraph in re.finditer(r"<p\b[^>]*>([\s\S]*?)</p>", content, flags=re.IGNORECASE):
        blocks.append(
            {
                "id": str(uuid4()),
                "type": "text",
                "content": strip_html_for_fallback(paragraph.group(1)),
                "widthPct": 100,
            }
        )
    for image in re.finditer(r"<img\b([^>]*)/?>", content, flags=re.IGNORECASE):
        attrs = dict(re.findall(r'(\w+)\s*=\s*["\']?([^"\'>\s]+)', image.group(1)))
        blocks.append(
            {
                "id": str(uuid4()),
                "type": "image",
                "src": attrs.get("src", ""),
                "alt": attrs.get("alt", ""),
                "fillMode": "fit",
                "widthPct": 100,
                "align": "center",
            }
        )
    if not blocks:
        return [{"id": str(uuid4()), "type": "raw_html", "content": html, "widthPct": 100}]
    return blocks


async def ai_rewrite_text(*, text: str, context: dict[str, Any]) -> dict[str, Any]:
    intent = context.get("intent") or "rewrite"
    if intent == "shorten":
        intent_line = "Shorten the selected text without losing meaning. Keep the voice."
    elif intent == "expand":
        intent_line = "Expand the selected text by one sentence. Keep the voice."
    else:
        intent_line = "Rewrite the selected text with the same intent and structure but improved wording. Keep it close to the original length."
    subject_block = f'\nSubject line of this email: {context.get("subject")}' if context.get("subject") else ""
    template_block = f'\nTemplate name: {context.get("templateName")}' if context.get("templateName") else ""
    block_type_line = f'\nBlock type: {context.get("blockType")}' if context.get("blockType") else ""
    surrounding_block = (
        f'\n\nSURROUNDING TEXT (read-only, for tone matching):\n{context.get("surroundingText")}'
        if context.get("surroundingText")
        else ""
    )
    user_message = f"""CONTEXT: email_ai_rewrite
{template_block}{subject_block}{block_type_line}

INTENT: {intent}
{intent_line}

CONSTRAINTS
- Apply the Gemzy voice rules from the system prompt.
- Never use em dashes.
- Period-ended sentences. No "Please". No "We couldn't".
- Match the surrounding tone if present.
- Return ONLY the rewritten text. No preamble. No quotes around it. No explanation.

SELECTED TEXT:
{text}{surrounding_block}"""
    result = await call_claude(GEMZY_CONTEXT, user_message, max_tokens=1000)
    cleaned = (
        str(result["text"])
        .strip()
        .removeprefix("```")
        .removesuffix("```")
        .strip()
        .strip('"')
        .strip()
    )
    return {
        "rewritten": cleaned,
        "tokenUsage": {
            "input": int(result.get("inputTokens") or 0),
            "output": int(result.get("outputTokens") or 0),
            "cacheRead": int(result.get("cacheReadTokens") or 0),
            "cacheCreation": int(result.get("cacheCreationTokens") or 0),
        },
    }


def _subject_with_tokens(subject: str, contact: dict[str, Any]) -> str:
    return subject.replace("{{name}}", str(contact.get("name") or "")).replace("{{email}}", str(contact.get("email") or ""))


def _render_template_context(template: dict[str, Any], contact: dict[str, Any], signatures_by_id: dict[str, Any], *, unsubscribe_token: str, campaign_id: str) -> tuple[str, str]:
    signature = signatures_by_id.get(str(template.get("signature_id"))) if template.get("signature_id") else None
    ctx = {
        "recipientName": contact.get("name") or "",
        "recipientEmail": contact.get("email") or "",
        "signature": signature,
        "signaturesById": signatures_by_id,
        "unsubscribeToken": unsubscribe_token,
        "campaignId": campaign_id,
        "baseUrl": get_dashboard_base_url(),
    }
    blocks = blocks_from_json(template.get("blocks"))
    return render_blocks_to_html(blocks, ctx), render_blocks_to_text(blocks, ctx)


def _log_send_attempt(
    *,
    template_id: str | None,
    recipient_email: str,
    recipient_contact_id: str | None,
    campaign_id: str | None,
    attempt: int,
    result: dict[str, Any],
) -> None:
    _insert_row(
        "email_send_log",
        {
            "id": str(uuid4()),
            "template_id": template_id,
            "recipient_email": recipient_email,
            "recipient_contact_id": recipient_contact_id,
            "campaign_id": campaign_id,
            "status": "sent" if result.get("success") else "failed",
            "error_message": result.get("error"),
            "smtp_response": result.get("smtpResponse"),
            "attempt": attempt,
            "sent_at": utc_now_iso() if result.get("success") else None,
            "attempted_at": utc_now_iso(),
        },
    )


def dispatch_trigger(event_type: str, contact_id: str) -> dict[str, Any]:
    result = {"triggersFired": 0, "emailsSent": 0, "duplicatesSkipped": 0, "failures": []}
    contact = _find_first("email_contacts", id=contact_id)
    if not contact:
        return result

    triggers = [
        row
        for row in _load_rows("email_triggers")
        if row.get("event_type") == event_type and bool(row.get("is_active"))
    ]
    signatures = {str(row["id"]): {"blocks": blocks_from_json(row.get("blocks"))} for row in _load_rows("email_signatures")}

    for trigger in triggers:
        existing = _find_first("email_trigger_sends", trigger_id=trigger["id"], contact_id=contact_id)
        if existing:
            result["duplicatesSkipped"] += 1
            continue
        template_id = trigger.get("template_id")
        template = _find_first("email_templates", id=template_id) if template_id else None
        if not template:
            result["failures"].append({"triggerId": trigger["id"], "reason": "template not found"})
            continue
        html, text = _render_template_context(template, contact, signatures, unsubscribe_token="preview", campaign_id="preview")
        send_result = send_email(
            to=str(contact.get("email") or ""),
            to_name=str(contact.get("name") or "") or None,
            subject=_subject_with_tokens(str(template.get("subject") or ""), contact),
            html=html,
            text=text,
            headers={
                "X-Gemzy-Trigger-Id": str(trigger["id"]),
                "X-Gemzy-Trigger-Event": event_type,
            },
        )
        result["triggersFired"] += 1
        _insert_row(
            "email_trigger_sends",
            {
                "id": str(uuid4()),
                "trigger_id": trigger["id"],
                "contact_id": contact_id,
                "status": "sent" if send_result.get("success") else "failed",
                "error_message": send_result.get("error"),
                "sent_at": utc_now_iso(),
            },
        )
        _log_send_attempt(
            template_id=str(template["id"]),
            recipient_email=str(contact.get("email") or ""),
            recipient_contact_id=contact_id,
            campaign_id=None,
            attempt=1,
            result=send_result,
        )
        if send_result.get("success"):
            result["emailsSent"] += 1
            add_to_group_id = trigger.get("add_to_group_id")
            if add_to_group_id and not _find_first("email_group_members", group_id=add_to_group_id, contact_id=contact_id):
                _insert_row("email_group_members", {"group_id": add_to_group_id, "contact_id": contact_id})
        else:
            result["failures"].append({"triggerId": trigger["id"], "reason": send_result.get("error") or "send failed"})
    return result


def handle_signup_trigger(contact_id: str) -> dict[str, Any]:
    return dispatch_trigger("user_signup", contact_id)


def handle_unsubscribe_trigger(contact_id: str) -> dict[str, Any]:
    return dispatch_trigger("user_unsubscribed", contact_id)


def handle_purchase_trigger(contact_id: str) -> dict[str, Any]:
    return dispatch_trigger("user_purchase", contact_id)


def handle_cancellation_trigger(contact_id: str) -> dict[str, Any]:
    return dispatch_trigger("user_cancellation", contact_id)


def new_send_token() -> str:
    return secrets.token_hex(16)


def finalize_campaign_status(campaign_id: str) -> None:
    campaign = _find_first("email_campaigns", id=campaign_id)
    if not campaign:
        return
    recipient_count = int(campaign.get("recipient_count") or 0)
    sent_count = int(campaign.get("sent_count") or 0)
    failed_count = int(campaign.get("failed_count") or 0)
    status_value = "sent" if failed_count == 0 and sent_count == recipient_count else "failed" if sent_count == 0 else "partial"
    _update_where(
        "email_campaigns",
        {
            "status": status_value,
            "sent_at": utc_now_iso() if status_value in {"sent", "partial"} else None,
            "updated_at": utc_now_iso(),
        },
        id=campaign_id,
    )


def send_campaign_now(campaign_id: str) -> None:
    campaign = _find_first("email_campaigns", id=campaign_id)
    if not campaign:
        return
    template_id = campaign.get("template_id")
    template = _find_first("email_templates", id=template_id) if template_id else None
    if not template:
        _update_where("email_campaigns", {"status": "failed", "updated_at": utc_now_iso()}, id=campaign_id)
        return

    signatures = {str(row["id"]): {"blocks": blocks_from_json(row.get("blocks"))} for row in _load_rows("email_signatures")}
    snapshot = {
        "subject": template.get("subject") or "",
        "previewText": template.get("preview_text"),
        "blocks": blocks_from_json(template.get("blocks")),
        "signatureId": template.get("signature_id"),
        "signature": signatures.get(str(template.get("signature_id"))) if template.get("signature_id") else None,
    }
    _update_where(
        "email_campaigns",
        {"status": "sending", "template_snapshot": snapshot, "updated_at": utc_now_iso()},
        id=campaign_id,
    )

    recipients = [row for row in _load_rows("email_campaign_recipients") if row.get("campaign_id") == campaign_id and row.get("status") == "pending"]
    contacts_by_id = {str(row["id"]): row for row in _load_rows("email_contacts")}

    for recipient in recipients:
        contact = contacts_by_id.get(str(recipient.get("contact_id")))
        if not contact:
            continue
        html, text = _render_template_context(
            template,
            contact,
            signatures,
            unsubscribe_token=str(recipient.get("send_token") or ""),
            campaign_id=campaign_id,
        )
        html = inject_tracking(html, str(recipient.get("send_token") or ""), campaign_id, get_dashboard_base_url())
        send_result = send_email(
            to=str(contact.get("email") or ""),
            to_name=str(contact.get("name") or "") or None,
            subject=_subject_with_tokens(str(template.get("subject") or ""), contact),
            html=html,
            text=text,
            headers={
                "X-Gemzy-Send-Token": str(recipient.get("send_token") or ""),
                "X-Gemzy-Campaign-Id": campaign_id,
            },
        )
        _log_send_attempt(
            template_id=str(template["id"]),
            recipient_email=str(contact.get("email") or ""),
            recipient_contact_id=str(contact["id"]),
            campaign_id=campaign_id,
            attempt=1,
            result=send_result,
        )
        if send_result.get("success"):
            _update_where(
                "email_campaign_recipients",
                {"status": "sent", "sent_at": utc_now_iso()},
                campaign_id=campaign_id,
                contact_id=contact["id"],
            )
            current = _find_first("email_campaigns", id=campaign_id)
            _update_where(
                "email_campaigns",
                {
                    "sent_count": int(current.get("sent_count") or 0) + 1 if current else 1,
                    "updated_at": utc_now_iso(),
                },
                id=campaign_id,
            )
        else:
            _update_where(
                "email_campaign_recipients",
                {"status": "failed", "error_message": "send failed; see email_send_log for details"},
                campaign_id=campaign_id,
                contact_id=contact["id"],
            )
            current = _find_first("email_campaigns", id=campaign_id)
            _update_where(
                "email_campaigns",
                {
                    "failed_count": int(current.get("failed_count") or 0) + 1 if current else 1,
                    "updated_at": utc_now_iso(),
                },
                id=campaign_id,
            )
        sleep(1 / EMAIL_SEND_RATE_PER_SECOND)

    finalize_campaign_status(campaign_id)


def start_campaign_send(campaign_id: str) -> None:
    def runner() -> None:
        try:
            send_campaign_now(campaign_id)
        except Exception:
            logger.exception("send_campaign_now failed", extra={"campaignId": campaign_id})

    Thread(target=runner, daemon=True, name=f"campaign-send-{campaign_id}").start()


def verify_shared_secret(auth_header: str, secret: str) -> bool:
    match = re.match(r"^Bearer\s+(.+)$", auth_header or "", flags=re.IGNORECASE)
    if not match:
        return False
    provided = match.group(1).strip()
    return secrets.compare_digest(provided, secret)

