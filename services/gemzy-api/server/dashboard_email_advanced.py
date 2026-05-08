from __future__ import annotations

import base64
import inspect
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .auth import get_current_user
from .dashboard_common import ensure_dashboard_admin, iso_or_none, utc_now_iso
from .dashboard_email_runtime import (
    EMAIL_EXTRACT_REGEX,
    ai_rewrite_text,
    blocks_from_json,
    convert_raw_html_to_blocks,
    create_signed_url,
    dispatch_trigger,
    ensure_contact,
    handle_cancellation_trigger,
    handle_purchase_trigger,
    handle_signup_trigger,
    is_smtp_configured,
    new_send_token,
    pick_default_signature_id,
    send_email,
    start_campaign_send,
    strip_html_for_fallback,
    upload_email_asset,
    verify_shared_secret,
    _delete_where,
    _find_all,
    _find_first,
    _insert_row,
    _load_rows,
    _normalize_email,
    _update_where,
)
from .schemas import UserState

router = APIRouter(prefix="/dashboard/email", tags=["dashboard-email-advanced"])
logger = logging.getLogger(__name__)


class ListTemplatesParams(BaseModel):
    sort: str = "recent"
    page: int = 1
    pageSize: int = 25


class CreateTemplatePayload(BaseModel):
    name: str
    subject: str = ""
    previewText: str | None = None
    blocks: Any = None
    signatureId: str | None = None


class UpdateTemplatePayload(BaseModel):
    name: str | None = None
    subject: str | None = None
    previewText: str | None = None
    blocks: Any = None
    signatureId: str | None = None


class CreateSignaturePayload(BaseModel):
    name: str
    blocks: Any = None
    isDefault: bool = False


class UpdateSignaturePayload(BaseModel):
    name: str | None = None
    blocks: Any = None


class SendTestPayload(BaseModel):
    to: str
    subject: str
    html: str
    signatureId: str | None = None
    templateId: str | None = None


class AiRewriteContextPayload(BaseModel):
    templateName: str | None = None
    subject: str | None = None
    surroundingText: str | None = None
    blockType: str | None = None
    intent: str = "rewrite"


class AiRewritePayload(BaseModel):
    text: str
    context: AiRewriteContextPayload = Field(default_factory=AiRewriteContextPayload)


class UploadAssetPayload(BaseModel):
    file: str
    fileName: str
    mimeType: str
    fileSize: int


class ConvertHtmlPayload(BaseModel):
    html: str


class CreateCampaignPayload(BaseModel):
    name: str
    templateId: str


class UpdateCampaignPayload(BaseModel):
    name: str | None = None
    templateId: str | None = None
    scheduledAt: str | None = None


class SetCampaignRecipientsPayload(BaseModel):
    campaignId: str
    groupIds: list[str] = Field(default_factory=list)
    contactIds: list[str] = Field(default_factory=list)
    excludeUnsubscribed: bool = True


class SendCampaignPayload(BaseModel):
    id: str
    scheduledAt: str | None = None


class MarkRecipientRepliedPayload(BaseModel):
    campaignId: str
    contactId: str


class CreateTriggerPayload(BaseModel):
    name: str
    description: str | None = None
    eventType: str
    templateId: str
    addToGroupId: str | None = None
    isActive: bool = True


class UpdateTriggerPayload(BaseModel):
    name: str | None = None
    description: str | None = None
    eventType: str | None = None
    templateId: str | None = None
    addToGroupId: str | None = None
    isActive: bool | None = None


class TestTriggerPayload(BaseModel):
    triggerId: str
    toEmail: str


def _sort_and_page(rows: list[dict[str, Any]], *, sort: str, page: int, page_size: int, recent_key: str = "updated_at") -> dict[str, Any]:
    if sort == "name_asc":
        rows = sorted(rows, key=lambda row: str(row.get("name") or "").lower())
    else:
        rows = sorted(rows, key=lambda row: str(row.get(recent_key) or ""), reverse=True)
    total = len(rows)
    start = (page - 1) * page_size
    return {"rows": rows[start : start + page_size], "total": total, "page": page, "pageSize": page_size}


def _serialize_template(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "subject": row.get("subject") or "",
        "previewText": row.get("preview_text"),
        "blocks": row.get("blocks") or [],
        "signatureId": row.get("signature_id"),
        "createdAt": iso_or_none(row.get("created_at")),
        "updatedAt": iso_or_none(row.get("updated_at")),
    }


def _serialize_signature(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "blocks": row.get("blocks") or [],
        "isDefault": bool(row.get("is_default")),
        "createdAt": iso_or_none(row.get("created_at")),
        "updatedAt": iso_or_none(row.get("updated_at")),
    }


def _campaign_metrics(campaign_id: str) -> tuple[int, int]:
    unique_opens = len({str(row.get("send_token")) for row in _find_all("email_opens", campaign_id=campaign_id) if row.get("send_token")})
    unique_clicks = len({str(row.get("send_token")) for row in _find_all("email_link_clicks", campaign_id=campaign_id) if row.get("send_token")})
    return unique_opens, unique_clicks


def _serialize_campaign_row(row: dict[str, Any]) -> dict[str, Any]:
    template = _find_first("email_templates", id=row.get("template_id")) if row.get("template_id") else None
    unique_opens, unique_clicks = _campaign_metrics(str(row["id"]))
    sent_count = int(row.get("sent_count") or 0)
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "status": row.get("status") or "draft",
        "subject": template.get("subject") if template else None,
        "recipientCount": int(row.get("recipient_count") or 0),
        "sentCount": sent_count,
        "failedCount": int(row.get("failed_count") or 0),
        "replyCount": int(row.get("reply_count") or 0),
        "scheduledAt": iso_or_none(row.get("scheduled_at")),
        "sentAt": iso_or_none(row.get("sent_at")),
        "createdAt": iso_or_none(row.get("created_at")),
        "uniqueOpens": unique_opens,
        "uniqueClicks": unique_clicks,
        "openRate": unique_opens / sent_count if sent_count > 0 else 0,
        "clickRate": unique_clicks / sent_count if sent_count > 0 else 0,
    }


@router.get("/templates")
async def list_templates(
    sort: str = Query(default="recent"),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=100),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    data = _sort_and_page(_load_rows("email_templates"), sort=sort, page=page, page_size=pageSize)
    data["rows"] = [_serialize_template(row) for row in data["rows"]]
    return data


@router.get("/templates/{template_id}")
async def get_template(template_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any] | None:
    ensure_dashboard_admin(current)
    row = _find_first("email_templates", id=template_id)
    return _serialize_template(row) if row else None


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(payload: CreateTemplatePayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    now = utc_now_iso()
    row = {
        "id": str(uuid4()),
        "name": payload.name.strip(),
        "subject": payload.subject,
        "preview_text": payload.previewText.strip() if isinstance(payload.previewText, str) and payload.previewText.strip() else None,
        "blocks": payload.blocks if payload.blocks is not None else [{"type": "raw_html", "content": "", "id": str(uuid4())}],
        "signature_id": payload.signatureId or pick_default_signature_id(),
        "created_at": now,
        "updated_at": now,
    }
    _insert_row("email_templates", row)
    return _serialize_template(row)


@router.patch("/templates/{template_id}")
async def update_template(
    template_id: str,
    payload: UpdateTemplatePayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    row = _find_first("email_templates", id=template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found.")
    patch = {"updated_at": utc_now_iso()}
    if payload.name is not None:
        patch["name"] = payload.name.strip()
    if payload.subject is not None:
        patch["subject"] = payload.subject
    if payload.previewText is not None:
        patch["preview_text"] = payload.previewText.strip() if payload.previewText.strip() else None
    if payload.blocks is not None:
        patch["blocks"] = payload.blocks
    if payload.signatureId is not None:
        patch["signature_id"] = payload.signatureId or None
    _update_where("email_templates", patch, id=template_id)
    return {"ok": True}


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    _delete_where("email_templates", id=template_id)
    return {"ok": True}


@router.post("/templates/{template_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_template(template_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    original = _find_first("email_templates", id=template_id)
    if not original:
        raise HTTPException(status_code=404, detail="Template not found.")
    now = utc_now_iso()
    copy = {
        "id": str(uuid4()),
        "name": f'{original.get("name") or "Template"} (copy)',
        "subject": original.get("subject") or "",
        "preview_text": original.get("preview_text"),
        "blocks": original.get("blocks") or [],
        "signature_id": original.get("signature_id"),
        "created_at": now,
        "updated_at": now,
    }
    _insert_row("email_templates", copy)
    return _serialize_template(copy)


@router.get("/signatures")
async def list_signatures(current: UserState = Depends(get_current_user)) -> list[dict[str, Any]]:
    ensure_dashboard_admin(current)
    rows = sorted(
        _load_rows("email_signatures"),
        key=lambda row: (not bool(row.get("is_default")), str(row.get("name") or "").lower()),
    )
    return [_serialize_signature(row) for row in rows]


@router.get("/signatures/{signature_id}")
async def get_signature(signature_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any] | None:
    ensure_dashboard_admin(current)
    row = _find_first("email_signatures", id=signature_id)
    return _serialize_signature(row) if row else None


@router.post("/signatures", status_code=status.HTTP_201_CREATED)
async def create_signature(payload: CreateSignaturePayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    if payload.isDefault:
        for row in _load_rows("email_signatures"):
            if row.get("is_default"):
                _update_where("email_signatures", {"is_default": False}, id=row["id"])
    now = utc_now_iso()
    row = {
        "id": str(uuid4()),
        "name": payload.name.strip(),
        "blocks": payload.blocks if payload.blocks is not None else [{"type": "raw_html", "content": "", "id": str(uuid4())}],
        "is_default": payload.isDefault,
        "created_at": now,
        "updated_at": now,
    }
    _insert_row("email_signatures", row)
    return _serialize_signature(row)


@router.patch("/signatures/{signature_id}")
async def update_signature(
    signature_id: str,
    payload: UpdateSignaturePayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    row = _find_first("email_signatures", id=signature_id)
    if not row:
        raise HTTPException(status_code=404, detail="Signature not found.")
    patch = {"updated_at": utc_now_iso()}
    if payload.name is not None:
        patch["name"] = payload.name.strip()
    if payload.blocks is not None:
        patch["blocks"] = payload.blocks
    _update_where("email_signatures", patch, id=signature_id)
    return {"ok": True}


@router.post("/signatures/{signature_id}/set-default")
async def set_default_signature(signature_id: str, current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    target = _find_first("email_signatures", id=signature_id)
    if not target:
        raise HTTPException(status_code=404, detail="Signature not found.")
    for row in _load_rows("email_signatures"):
        if row.get("is_default"):
            _update_where("email_signatures", {"is_default": False}, id=row["id"])
    _update_where("email_signatures", {"is_default": True, "updated_at": utc_now_iso()}, id=signature_id)
    return {"ok": True}


@router.delete("/signatures/{signature_id}")
async def delete_signature(signature_id: str, current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    row = _find_first("email_signatures", id=signature_id)
    if not row:
        raise HTTPException(status_code=404, detail="Signature not found.")
    if bool(row.get("is_default")):
        raise HTTPException(status_code=400, detail="Set a different signature as default before deleting this one.")
    _delete_where("email_signatures", id=signature_id)
    return {"ok": True}


@router.post("/send-test")
async def send_test(payload: SendTestPayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    if not is_smtp_configured():
        return {
            "success": False,
            "error": "SMTP is not configured. Set GMAIL_SMTP_USER and GMAIL_SMTP_PASSWORD in the server environment.",
            "smtpResponse": None,
            "durationMs": 0,
        }
    result = send_email(
        to=payload.to,
        subject=payload.subject,
        html=payload.html,
        text=strip_html_for_fallback(payload.html),
    )
    _insert_row(
        "email_send_log",
        {
            "id": str(uuid4()),
            "template_id": payload.templateId,
            "recipient_email": payload.to,
            "recipient_contact_id": None,
            "campaign_id": None,
            "status": "sent" if result.get("success") else "failed",
            "error_message": result.get("error"),
            "sent_at": utc_now_iso() if result.get("success") else None,
            "smtp_response": result.get("smtpResponse"),
            "attempt": 1,
            "attempted_at": utc_now_iso(),
        },
    )
    return {
        "success": bool(result.get("success")),
        "error": result.get("error"),
        "smtpResponse": result.get("smtpResponse"),
        "durationMs": 0,
    }


@router.get("/send-log")
async def recent_send_log(
    limit: int = Query(default=20, ge=1, le=100),
    current: UserState = Depends(get_current_user),
) -> list[dict[str, Any]]:
    ensure_dashboard_admin(current)
    rows = sorted(_load_rows("email_send_log"), key=lambda row: str(row.get("attempted_at") or ""), reverse=True)[:limit]
    return rows


@router.post("/ai-rewrite")
async def ai_rewrite(payload: AiRewritePayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    result = ai_rewrite_text(text=payload.text, context=payload.context.model_dump())
    if inspect.isawaitable(result):
        result = await result
    return result


@router.post("/upload-asset")
async def upload_asset(payload: UploadAssetPayload, current: UserState = Depends(get_current_user)) -> dict[str, str]:
    ensure_dashboard_admin(current)
    try:
        buffer = base64.b64decode(payload.file, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="File payload is not valid base64.") from exc
    if len(buffer) > payload.fileSize:
        payload.fileSize = len(buffer)
    return upload_email_asset(buffer=buffer, file_name=payload.fileName, mime_type=payload.mimeType)


@router.post("/convert-raw-html")
async def convert_raw_html(payload: ConvertHtmlPayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    return {"blocks": convert_raw_html_to_blocks(payload.html)}


@router.get("/campaigns")
async def list_campaigns(
    sort: str = Query(default="recent"),
    statusFilter: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=100),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    rows = _load_rows("email_campaigns")
    if statusFilter != "all":
        rows = [row for row in rows if row.get("status") == statusFilter]
    recent_key = "sent_at" if sort == "sent" else "created_at"
    data = _sort_and_page(rows, sort="recent", page=page, page_size=pageSize, recent_key=recent_key)
    data["rows"] = [_serialize_campaign_row(row) for row in data["rows"]]
    return data


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any] | None:
    ensure_dashboard_admin(current)
    row = _find_first("email_campaigns", id=campaign_id)
    if not row:
        return None
    template = _find_first("email_templates", id=row.get("template_id")) if row.get("template_id") else None
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "status": row.get("status") or "draft",
        "templateId": row.get("template_id"),
        "templateName": template.get("name") if template else None,
        "templateSubject": template.get("subject") if template else None,
        "recipientCount": int(row.get("recipient_count") or 0),
        "sentCount": int(row.get("sent_count") or 0),
        "failedCount": int(row.get("failed_count") or 0),
        "replyCount": int(row.get("reply_count") or 0),
        "scheduledAt": iso_or_none(row.get("scheduled_at")),
        "sentAt": iso_or_none(row.get("sent_at")),
        "createdAt": iso_or_none(row.get("created_at")),
        "updatedAt": iso_or_none(row.get("updated_at")),
        "templateSnapshot": row.get("template_snapshot"),
    }


@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
async def create_campaign(payload: CreateCampaignPayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    now = utc_now_iso()
    row = {
        "id": str(uuid4()),
        "name": payload.name.strip(),
        "template_id": payload.templateId,
        "status": "draft",
        "recipient_count": 0,
        "sent_count": 0,
        "failed_count": 0,
        "reply_count": 0,
        "scheduled_at": None,
        "sent_at": None,
        "template_snapshot": None,
        "created_at": now,
        "updated_at": now,
    }
    _insert_row("email_campaigns", row)
    return row


@router.patch("/campaigns/{campaign_id}")
async def update_campaign(
    campaign_id: str,
    payload: UpdateCampaignPayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    row = _find_first("email_campaigns", id=campaign_id)
    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if row.get("status") not in {"draft", "scheduled"}:
        raise HTTPException(status_code=400, detail="Only draft or scheduled campaigns can be edited.")
    patch = {"updated_at": utc_now_iso()}
    if payload.name is not None:
        patch["name"] = payload.name.strip()
    if payload.templateId is not None:
        patch["template_id"] = payload.templateId
    if payload.scheduledAt is not None:
        patch["scheduled_at"] = payload.scheduledAt or None
    _update_where("email_campaigns", patch, id=campaign_id)
    return {"ok": True}


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    row = _find_first("email_campaigns", id=campaign_id)
    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if row.get("status") != "draft":
        raise HTTPException(status_code=400, detail="Only draft campaigns can be deleted. Sent campaigns stay in history.")
    _delete_where("email_campaigns", id=campaign_id)
    _delete_where("email_campaign_recipients", campaign_id=campaign_id)
    return {"ok": True}


@router.post("/campaigns/recipients")
async def set_campaign_recipients(payload: SetCampaignRecipientsPayload, current: UserState = Depends(get_current_user)) -> dict[str, int]:
    ensure_dashboard_admin(current)
    campaign = _find_first("email_campaigns", id=payload.campaignId)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if campaign.get("status") not in {"draft", "scheduled"}:
        raise HTTPException(status_code=400, detail="Recipients can only be set on draft or scheduled campaigns.")

    contact_ids = {contact_id for contact_id in payload.contactIds}
    memberships = _load_rows("email_group_members")
    for membership in memberships:
        if membership.get("group_id") in payload.groupIds and membership.get("contact_id"):
            contact_ids.add(str(membership["contact_id"]))
    if payload.excludeUnsubscribed:
        unsubscribed = {str(row.get("contact_id")) for row in _load_rows("email_unsubscribes") if row.get("contact_id")}
        contact_ids = {contact_id for contact_id in contact_ids if contact_id not in unsubscribed}

    _delete_where("email_campaign_recipients", campaign_id=payload.campaignId)
    for contact_id in contact_ids:
        _insert_row(
            "email_campaign_recipients",
            {
                "id": str(uuid4()),
                "campaign_id": payload.campaignId,
                "contact_id": contact_id,
                "send_token": new_send_token(),
                "status": "pending",
                "sent_at": None,
                "opened_at": None,
                "first_click_at": None,
                "click_count": 0,
                "reply_at": None,
                "error_message": None,
            },
        )
    _update_where(
        "email_campaigns",
        {
            "recipient_count": len(contact_ids),
            "sent_count": 0,
            "failed_count": 0,
            "updated_at": utc_now_iso(),
        },
        id=payload.campaignId,
    )
    return {"recipientCount": len(contact_ids)}


@router.post("/campaigns/send")
async def send_campaign(payload: SendCampaignPayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    campaign = _find_first("email_campaigns", id=payload.id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if campaign.get("status") in {"sending", "sent"}:
        raise HTTPException(status_code=400, detail=f'Campaign is already {campaign.get("status")}.')
    if int(campaign.get("recipient_count") or 0) == 0:
        raise HTTPException(status_code=400, detail="Add recipients before sending.")
    if payload.scheduledAt:
        _update_where(
            "email_campaigns",
            {"status": "scheduled", "scheduled_at": payload.scheduledAt, "updated_at": utc_now_iso()},
            id=payload.id,
        )
        return {"scheduled": True, "scheduledAt": payload.scheduledAt}
    start_campaign_send(payload.id)
    return {"scheduled": False}


@router.post("/campaigns/mark-replied")
async def mark_recipient_replied(payload: MarkRecipientRepliedPayload, current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    recipient = _find_first("email_campaign_recipients", campaign_id=payload.campaignId, contact_id=payload.contactId)
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found.")
    already = recipient.get("reply_at") not in {None, ""}
    if not already:
        _update_where(
            "email_campaign_recipients",
            {"reply_at": utc_now_iso()},
            campaign_id=payload.campaignId,
            contact_id=payload.contactId,
        )
        campaign = _find_first("email_campaigns", id=payload.campaignId)
        _update_where(
            "email_campaigns",
            {
                "reply_count": int(campaign.get("reply_count") or 0) + 1 if campaign else 1,
                "updated_at": utc_now_iso(),
            },
            id=payload.campaignId,
        )
    return {"reset": already}


@router.get("/campaigns/{campaign_id}/analytics")
async def campaign_analytics(campaign_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any] | None:
    ensure_dashboard_admin(current)
    campaign = _find_first("email_campaigns", id=campaign_id)
    if not campaign:
        return None
    opens = _find_all("email_opens", campaign_id=campaign_id)
    clicks = _find_all("email_link_clicks", campaign_id=campaign_id)
    unique_opens = len({str(row.get("send_token")) for row in opens if row.get("send_token")})
    unique_clicks = len({str(row.get("send_token")) for row in clicks if row.get("send_token")})

    link_perf_map: dict[tuple[str, str | None], dict[str, Any]] = {}
    for click in clicks:
        key = (str(click.get("link_url") or ""), click.get("link_label"))
        bucket = link_perf_map.setdefault(key, {"linkUrl": key[0], "linkLabel": key[1], "tokens": set(), "totalClicks": 0})
        bucket["totalClicks"] += 1
        bucket["tokens"].add(str(click.get("send_token") or ""))
    link_performance = [
        {
            "linkUrl": value["linkUrl"],
            "linkLabel": value["linkLabel"],
            "totalClicks": value["totalClicks"],
            "uniqueClicks": len(value["tokens"]),
        }
        for value in sorted(link_perf_map.values(), key=lambda item: item["totalClicks"], reverse=True)
    ]

    votes_by_block = {str(block.get("id")): block for block in blocks_from_json((campaign.get("template_snapshot") or {}).get("blocks")) if str(block.get("type")) == "vote"}
    vote_counts: dict[tuple[str, str], int] = {}
    for vote in _find_all("email_votes", campaign_id=campaign_id):
        key = (str(vote.get("vote_block_id") or ""), str(vote.get("option_id") or ""))
        vote_counts[key] = vote_counts.get(key, 0) + 1
    votes = []
    for (block_id, option_id), count in vote_counts.items():
        block = votes_by_block.get(block_id) or {}
        option = next((item for item in block.get("options", []) if isinstance(item, dict) and str(item.get("id")) == option_id), None)
        votes.append(
            {
                "voteBlockId": block_id,
                "optionId": option_id,
                "votes": count,
                "question": block.get("question"),
                "optionLabel": option.get("label") if option else None,
            }
        )
    sent_count = int(campaign.get("sent_count") or 0)
    return {
        "campaign": {
            "id": campaign["id"],
            "name": campaign.get("name") or "",
            "status": campaign.get("status") or "draft",
            "sentCount": sent_count,
        },
        "engagement": {
            "totalOpens": len(opens),
            "uniqueOpens": unique_opens,
            "totalClicks": len(clicks),
            "uniqueClicks": unique_clicks,
            "openRate": unique_opens / sent_count if sent_count else 0,
            "clickRate": unique_clicks / sent_count if sent_count else 0,
            "clickToOpen": unique_clicks / unique_opens if unique_opens else 0,
        },
        "linkPerformance": link_performance,
        "votes": votes,
    }


@router.get("/campaigns/{campaign_id}/recipients")
async def campaign_recipients(
    campaign_id: str,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=100),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    contacts_by_id = {str(row["id"]): row for row in _load_rows("email_contacts")}
    recipients = [row for row in _load_rows("email_campaign_recipients") if row.get("campaign_id") == campaign_id]
    recipients = sorted(recipients, key=lambda row: str(contacts_by_id.get(str(row.get("contact_id")), {}).get("email") or "").lower())
    total = len(recipients)
    start = (page - 1) * pageSize
    page_rows = recipients[start : start + pageSize]
    return {
        "rows": [
            {
                "contactId": row.get("contact_id"),
                "email": contacts_by_id.get(str(row.get("contact_id")), {}).get("email") or "",
                "name": contacts_by_id.get(str(row.get("contact_id")), {}).get("name"),
                "status": row.get("status") or "pending",
                "sentAt": iso_or_none(row.get("sent_at")),
                "openedAt": iso_or_none(row.get("opened_at")),
                "firstClickAt": iso_or_none(row.get("first_click_at")),
                "clickCount": int(row.get("click_count") or 0),
                "replyAt": iso_or_none(row.get("reply_at")),
            }
            for row in page_rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/triggers")
async def list_triggers(current: UserState = Depends(get_current_user)) -> list[dict[str, Any]]:
    ensure_dashboard_admin(current)
    templates = {str(row["id"]): row for row in _load_rows("email_templates")}
    groups = {str(row["id"]): row for row in _load_rows("email_groups")}
    rows = sorted(_load_rows("email_triggers"), key=lambda row: str(row.get("name") or "").lower())
    result = []
    for row in rows:
        sends = [send for send in _load_rows("email_trigger_sends") if send.get("trigger_id") == row["id"]]
        result.append(
            {
                "id": row["id"],
                "name": row.get("name") or "",
                "description": row.get("description"),
                "eventType": row.get("event_type"),
                "templateId": row.get("template_id"),
                "templateName": templates.get(str(row.get("template_id")), {}).get("name"),
                "isActive": bool(row.get("is_active")),
                "addToGroupId": row.get("add_to_group_id"),
                "groupName": groups.get(str(row.get("add_to_group_id")), {}).get("name"),
                "sendsTotal": len(sends),
                "sendsLast30d": len(sends),
                "createdAt": iso_or_none(row.get("created_at")),
                "updatedAt": iso_or_none(row.get("updated_at")),
            }
        )
    return result


@router.get("/triggers/{trigger_id}")
async def get_trigger(trigger_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any] | None:
    ensure_dashboard_admin(current)
    row = _find_first("email_triggers", id=trigger_id)
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "description": row.get("description"),
        "eventType": row.get("event_type"),
        "templateId": row.get("template_id"),
        "addToGroupId": row.get("add_to_group_id"),
        "isActive": bool(row.get("is_active")),
        "createdAt": iso_or_none(row.get("created_at")),
        "updatedAt": iso_or_none(row.get("updated_at")),
    }


@router.post("/triggers", status_code=status.HTTP_201_CREATED)
async def create_trigger(payload: CreateTriggerPayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    now = utc_now_iso()
    row = {
        "id": str(uuid4()),
        "name": payload.name.strip(),
        "description": payload.description.strip() if isinstance(payload.description, str) and payload.description.strip() else None,
        "event_type": payload.eventType,
        "template_id": payload.templateId,
        "add_to_group_id": payload.addToGroupId or None,
        "is_active": payload.isActive,
        "created_at": now,
        "updated_at": now,
    }
    _insert_row("email_triggers", row)
    return row


@router.patch("/triggers/{trigger_id}")
async def update_trigger(
    trigger_id: str,
    payload: UpdateTriggerPayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    row = _find_first("email_triggers", id=trigger_id)
    if not row:
        raise HTTPException(status_code=404, detail="Trigger not found.")
    patch = {"updated_at": utc_now_iso()}
    if payload.name is not None:
        patch["name"] = payload.name.strip()
    if payload.description is not None:
        patch["description"] = payload.description.strip() if payload.description.strip() else None
    if payload.eventType is not None:
        patch["event_type"] = payload.eventType
    if payload.templateId is not None:
        patch["template_id"] = payload.templateId
    if payload.addToGroupId is not None:
        patch["add_to_group_id"] = payload.addToGroupId or None
    if payload.isActive is not None:
        patch["is_active"] = payload.isActive
    _update_where("email_triggers", patch, id=trigger_id)
    return {"ok": True}


@router.delete("/triggers/{trigger_id}")
async def delete_trigger(trigger_id: str, current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    _delete_where("email_triggers", id=trigger_id)
    return {"ok": True}


@router.get("/triggers/{trigger_id}/sends")
async def trigger_sends(
    trigger_id: str,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=100),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    contacts = {str(row["id"]): row for row in _load_rows("email_contacts")}
    sends = [row for row in _load_rows("email_trigger_sends") if row.get("trigger_id") == trigger_id]
    sends = sorted(sends, key=lambda row: str(row.get("sent_at") or ""), reverse=True)
    total = len(sends)
    start = (page - 1) * pageSize
    page_rows = sends[start : start + pageSize]
    return {
        "rows": [
            {
                "contactId": row.get("contact_id"),
                "email": contacts.get(str(row.get("contact_id")), {}).get("email") or "",
                "sentAt": iso_or_none(row.get("sent_at")),
                "status": row.get("status") or "failed",
                "errorMessage": row.get("error_message"),
            }
            for row in page_rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.post("/triggers/test")
async def test_trigger(payload: TestTriggerPayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    trigger = _find_first("email_triggers", id=payload.triggerId)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found.")
    contact_id = ensure_contact(payload.toEmail, "trigger_test")
    return dispatch_trigger(str(trigger.get("event_type") or ""), contact_id)
