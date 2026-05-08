from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .auth import get_current_user
from .dashboard_common import dashboard_table, ensure_dashboard_admin, iso_or_none, utc_now_iso
from .schemas import UserState

router = APIRouter(prefix="/dashboard/email", tags=["dashboard-email"])
logger = logging.getLogger(__name__)

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_ROWS_PER_IMPORT = 25_000
REJECTED_SAMPLE_LIMIT = 50
EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
EMAIL_EXTRACT_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

UNSUBSCRIBED_KEY = "unsubscribed"
AUTO_MANAGED_KEYS = {"unsubscribed", "new_users", "new_payers", "all_subscribers"}
SYSTEM_AUTO_MANAGED_KEYS = {"unsubscribed"}


class EmailImportPayload(BaseModel):
    csv: str = Field(min_length=1, max_length=MAX_CSV_BYTES)
    source: str = Field(default="csv_import", min_length=1, max_length=64)
    groupIds: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CreateContactPayload(BaseModel):
    email: str
    name: str | None = None
    groupIds: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class UpdateContactPayload(BaseModel):
    name: str | None = None
    tags: list[str] | None = None


class BulkDeleteContactsPayload(BaseModel):
    ids: list[str]


class BulkDeleteAllMatchingPayload(BaseModel):
    q: str = ""


class BulkGroupMembershipPayload(BaseModel):
    contactIds: list[str]


class BulkAddAllMatchingPayload(BaseModel):
    q: str = ""


class CreateGroupPayload(BaseModel):
    name: str
    description: str | None = None
    isAutoManaged: bool = False
    autoManagedKey: str | None = None


class UpdateGroupPayload(BaseModel):
    name: str | None = None
    description: str | None = None
    isAutoManaged: bool | None = None
    autoManagedKey: str | None = None


def _load_rows(table_name: str) -> list[dict[str, Any]]:
    return dashboard_table(table_name).select("*").execute().data or []


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _unique_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags:
        tag = raw.strip()
        if not tag:
            continue
        lowered = tag.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(tag)
    return out


def _is_wired_auto_managed_key(key: str | None) -> bool:
    return key == UNSUBSCRIBED_KEY


def _sort_contacts(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "name_asc":
        return sorted(
            rows,
            key=lambda row: (
                (row.get("name") or "").strip().lower() == "",
                (row.get("name") or "").strip().lower(),
                str(row.get("email") or "").lower(),
            ),
        )
    if sort == "recently_added":
        return sorted(rows, key=lambda row: iso_or_none(row.get("created_at")) or "", reverse=True)
    return sorted(rows, key=lambda row: str(row.get("email") or "").lower())


def _matches_contact_search(row: dict[str, Any], search: str) -> bool:
    if not search:
        return True
    haystacks = [str(row.get("email") or "").lower(), str(row.get("name") or "").lower()]
    lowered = search.lower()
    return any(lowered in haystack for haystack in haystacks)


def _paginate(rows: list[dict[str, Any]], page: int, page_size: int) -> list[dict[str, Any]]:
    offset = (page - 1) * page_size
    return rows[offset : offset + page_size]


def _serialize_contact(
    row: dict[str, Any],
    *,
    groups: list[dict[str, str]] | None = None,
    is_unsubscribed: bool = False,
) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row.get("email") or "",
        "name": row.get("name"),
        "source": row.get("source"),
        "tags": list(row.get("tags") or []),
        "createdAt": iso_or_none(row.get("created_at")),
        "updatedAt": iso_or_none(row.get("updated_at")),
        "groups": groups or [],
        "isUnsubscribed": is_unsubscribed,
    }


def _serialize_group(group: dict[str, Any], member_count: int) -> dict[str, Any]:
    return {
        "id": group["id"],
        "name": group.get("name") or "",
        "description": group.get("description"),
        "isAutoManaged": bool(group.get("is_auto_managed")),
        "autoManagedKey": group.get("auto_managed_key"),
        "memberCount": member_count,
        "createdAt": iso_or_none(group.get("created_at")),
        "updatedAt": iso_or_none(group.get("updated_at")),
    }


def _group_membership_map(contact_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    if not contact_ids:
        return {}
    groups = {row["id"]: row for row in _load_rows("email_groups")}
    memberships = _load_rows("email_group_members")
    out: dict[str, list[dict[str, str]]] = {}
    for membership in memberships:
        contact_id = membership.get("contact_id")
        group_id = membership.get("group_id")
        if contact_id not in contact_ids or group_id not in groups:
            continue
        out.setdefault(contact_id, []).append({"id": group_id, "name": groups[group_id].get("name") or ""})
    for contact_group_rows in out.values():
        contact_group_rows.sort(key=lambda row: row["name"].lower())
    return out


def _unsubscribed_contact_ids() -> set[str]:
    return {str(row.get("contact_id")) for row in _load_rows("email_unsubscribes") if row.get("contact_id")}


def _count_group_members(group: dict[str, Any]) -> int:
    if bool(group.get("is_auto_managed")) and group.get("auto_managed_key") == UNSUBSCRIBED_KEY:
        return len(_unsubscribed_contact_ids())
    return sum(1 for row in _load_rows("email_group_members") if row.get("group_id") == group["id"])


def _get_group_or_404(group_id: str) -> dict[str, Any]:
    groups = _load_rows("email_groups")
    group = next((row for row in groups if row.get("id") == group_id), None)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")
    return group


def _ensure_not_auto_managed(group_id: str) -> dict[str, Any]:
    group = _get_group_or_404(group_id)
    if bool(group.get("is_auto_managed")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group is auto-managed. Membership is computed from unsubscribe events.",
        )
    return group


def _load_matching_contact_ids(search: str) -> list[str]:
    rows = [row for row in _load_rows("email_contacts") if _matches_contact_search(row, search.strip())]
    return [str(row["id"]) for row in rows]


type_ParsedRow = dict[str, str | None]


def _parse_csv(text: str) -> tuple[list[type_ParsedRow], str | None]:
    stripped = text.lstrip("\ufeff")
    lines = _split_csv_lines(stripped)
    if not lines:
        return [], "File is empty."

    sample = next((line for line in lines if line.strip()), "")
    delimiter = _detect_delimiter(sample)
    header_warning = None
    if delimiter != ",":
        header_warning = "Detected semicolon-separated values." if delimiter == ";" else "Detected tab-separated values."

    rows: list[type_ParsedRow] = []
    for line in lines:
        if not line.strip():
            continue
        cells = [cell.strip() for cell in _parse_csv_line(line, delimiter)]
        email = None
        email_cell_idx = -1
        for index, cell in enumerate(cells):
            match = EMAIL_EXTRACT_REGEX.search(cell)
            if match:
                email = match.group(0)
                email_cell_idx = index
                break
        if not email:
            continue

        name = None
        for index, cell in enumerate(cells):
            if index == email_cell_idx or not cell or EMAIL_EXTRACT_REGEX.search(cell):
                continue
            name = cell
            break
        rows.append({"email": email, "name": name})

    if not rows and header_warning is None:
        header_warning = "No email-shaped values were found in this file."
    return rows, header_warning


def _detect_delimiter(sample: str) -> str:
    commas = 0
    semis = 0
    tabs = 0
    in_quotes = False
    index = 0
    while index < len(sample):
        ch = sample[index]
        if ch == '"':
            if in_quotes and index + 1 < len(sample) and sample[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
            index += 1
            continue
        if not in_quotes:
            if ch == ",":
                commas += 1
            elif ch == ";":
                semis += 1
            elif ch == "\t":
                tabs += 1
        index += 1
    if semis > commas and semis >= tabs:
        return ";"
    if tabs > commas and tabs > semis:
        return "\t"
    return ","


def _split_csv_lines(text: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    in_quotes = False
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == '"':
            if in_quotes and index + 1 < len(text) and text[index + 1] == '"':
                buf.extend(['"', '"'])
                index += 2
                continue
            in_quotes = not in_quotes
            buf.append(ch)
            index += 1
            continue
        if ch in {"\n", "\r"} and not in_quotes:
            if ch == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                index += 1
            out.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(ch)
        index += 1
    if buf:
        out.append("".join(buf))
    return out


def _parse_csv_line(line: str, delimiter: str = ",") -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    in_quotes = False
    index = 0
    while index < len(line):
        ch = line[index]
        if ch == '"':
            if in_quotes and index + 1 < len(line) and line[index + 1] == '"':
                buf.append('"')
                index += 2
                continue
            in_quotes = not in_quotes
            index += 1
            continue
        if ch == delimiter and not in_quotes:
            out.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(ch)
        index += 1
    out.append("".join(buf))
    return out


@router.get("/stats")
async def get_stats(current: UserState = Depends(get_current_user)) -> dict[str, int]:
    ensure_dashboard_admin(current)
    return {
        "totalContacts": len(_load_rows("email_contacts")),
        "totalGroups": len(_load_rows("email_groups")),
        "unsubscribedCount": len(_load_rows("email_unsubscribes")),
    }


@router.post("/import")
async def import_csv(payload: EmailImportPayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    rows, header_warning = _parse_csv(payload.csv)
    total_rows_in_file = len(rows)
    truncated = total_rows_in_file > MAX_ROWS_PER_IMPORT
    working = rows[:MAX_ROWS_PER_IMPORT] if truncated else rows

    seen: dict[str, type_ParsedRow] = {}
    invalid: list[str] = []
    duplicates_in_file: list[str] = []
    for row in working:
        normalized = _normalize_email(str(row["email"] or ""))
        if not EMAIL_REGEX.match(normalized):
            invalid.append(str(row["email"] or ""))
            continue
        if normalized in seen:
            duplicates_in_file.append(str(row["email"] or ""))
            continue
        seen[normalized] = {"email": normalized, "name": _normalize_text(row.get("name"))}

    tags = _unique_tags(payload.tags)
    existing_contacts = _load_rows("email_contacts")
    existing_by_email = {_normalize_email(str(row.get("email") or "")): row for row in existing_contacts}
    inserted_rows: list[dict[str, Any]] = []
    existing_in_db: list[str] = []
    now = utc_now_iso()
    for candidate in seen.values():
        email = str(candidate["email"] or "")
        if email in existing_by_email:
            existing_in_db.append(email)
            continue
        row = {
            "id": str(uuid4()),
            "email": email,
            "name": candidate.get("name"),
            "source": payload.source.strip() or "csv_import",
            "tags": tags,
            "created_at": now,
            "updated_at": now,
        }
        dashboard_table("email_contacts").insert(row).execute()
        existing_by_email[email] = row
        inserted_rows.append(row)

    if payload.groupIds:
        memberships = _load_rows("email_group_members")
        existing_memberships = {(str(row.get("group_id")), str(row.get("contact_id"))) for row in memberships}
        for email in seen.keys():
            contact = existing_by_email.get(email)
            if not contact:
                continue
            for group_id in payload.groupIds:
                key = (group_id, str(contact["id"]))
                if key in existing_memberships:
                    continue
                dashboard_table("email_group_members").insert(
                    {"group_id": group_id, "contact_id": contact["id"]}
                ).execute()
                existing_memberships.add(key)

    return {
        "totalRowsInFile": total_rows_in_file,
        "added": len(inserted_rows),
        "skippedExistingInDb": len(existing_in_db),
        "skippedDuplicateInFile": len(duplicates_in_file),
        "invalid": len(invalid),
        "rejectedSamples": {
            "invalid": invalid[:REJECTED_SAMPLE_LIMIT],
            "duplicateInFile": duplicates_in_file[:REJECTED_SAMPLE_LIMIT],
            "existingInDb": existing_in_db[:REJECTED_SAMPLE_LIMIT],
        },
        "truncated": truncated,
        "headerWarning": header_warning,
    }


@router.get("/contacts")
async def list_contacts(
    q: str = Query(default=""),
    sort: str = Query(default="email_asc"),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=100),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    search = q.strip()
    rows = [row for row in _load_rows("email_contacts") if _matches_contact_search(row, search)]
    rows = _sort_contacts(rows, sort)
    total = len(rows)
    page_rows = _paginate(rows, page, pageSize)
    groups_map = _group_membership_map([str(row["id"]) for row in page_rows])
    unsubscribed = _unsubscribed_contact_ids()
    return {
        "rows": [
            _serialize_contact(
                row,
                groups=groups_map.get(str(row["id"]), []),
                is_unsubscribed=str(row["id"]) in unsubscribed,
            )
            for row in page_rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/contacts/{contact_id}")
async def get_contact(contact_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any] | None:
    ensure_dashboard_admin(current)
    row = next((row for row in _load_rows("email_contacts") if row.get("id") == contact_id), None)
    if not row:
        return None
    groups_map = _group_membership_map([contact_id])
    unsubscribed = _unsubscribed_contact_ids()
    return _serialize_contact(row, groups=groups_map.get(contact_id, []), is_unsubscribed=contact_id in unsubscribed)


@router.post("/contacts", status_code=status.HTTP_201_CREATED)
async def create_contact(payload: CreateContactPayload, current: UserState = Depends(get_current_user)) -> dict[str, str]:
    ensure_dashboard_admin(current)
    normalized_email = _normalize_email(payload.email)
    if not EMAIL_REGEX.match(normalized_email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A valid email is required.")
    existing = next(
        (row for row in _load_rows("email_contacts") if _normalize_email(str(row.get("email") or "")) == normalized_email),
        None,
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A contact with that email already exists.",
        )

    contact_id = str(uuid4())
    now = utc_now_iso()
    dashboard_table("email_contacts").insert(
        {
            "id": contact_id,
            "email": normalized_email,
            "name": _normalize_text(payload.name),
            "tags": _unique_tags(payload.tags),
            "source": "manual",
            "created_at": now,
            "updated_at": now,
        }
    ).execute()

    if payload.groupIds:
        memberships = _load_rows("email_group_members")
        existing_memberships = {(str(row.get("group_id")), str(row.get("contact_id"))) for row in memberships}
        for group_id in payload.groupIds:
            key = (group_id, contact_id)
            if key in existing_memberships:
                continue
            dashboard_table("email_group_members").insert({"group_id": group_id, "contact_id": contact_id}).execute()
            existing_memberships.add(key)

    return {"id": contact_id}


@router.patch("/contacts/{contact_id}")
async def update_contact(
    contact_id: str,
    payload: UpdateContactPayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    contacts = _load_rows("email_contacts")
    row = next((item for item in contacts if item.get("id") == contact_id), None)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")
    patch: dict[str, Any] = {"updated_at": utc_now_iso()}
    if payload.name is not None:
        patch["name"] = _normalize_text(payload.name)
    if payload.tags is not None:
        patch["tags"] = _unique_tags(payload.tags)
    dashboard_table("email_contacts").update(patch).eq("id", contact_id).execute()
    return {"ok": True}


def _delete_contact_everywhere(contact_id: str) -> None:
    dashboard_table("email_group_members").delete().eq("contact_id", contact_id).execute()
    dashboard_table("email_unsubscribes").delete().eq("contact_id", contact_id).execute()
    dashboard_table("email_contacts").delete().eq("id", contact_id).execute()


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str, current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    _delete_contact_everywhere(contact_id)
    return {"ok": True}


@router.post("/contacts/bulk-delete")
async def bulk_delete_contacts(
    payload: BulkDeleteContactsPayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, int]:
    ensure_dashboard_admin(current)
    deleted = 0
    for contact_id in payload.ids:
        exists = any(row.get("id") == contact_id for row in _load_rows("email_contacts"))
        if not exists:
            continue
        _delete_contact_everywhere(contact_id)
        deleted += 1
    return {"deleted": deleted}


@router.post("/contacts/bulk-delete-matching")
async def bulk_delete_all_matching_contacts(
    payload: BulkDeleteAllMatchingPayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, int]:
    ensure_dashboard_admin(current)
    ids = _load_matching_contact_ids(payload.q.strip())
    deleted = 0
    for contact_id in ids:
        _delete_contact_everywhere(contact_id)
        deleted += 1
    return {"deleted": deleted}


@router.post("/groups/{group_id}/members")
async def bulk_add_contacts_to_group(
    group_id: str,
    payload: BulkGroupMembershipPayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    _ensure_not_auto_managed(group_id)
    memberships = _load_rows("email_group_members")
    existing = {(str(row.get("group_id")), str(row.get("contact_id"))) for row in memberships}
    for contact_id in payload.contactIds:
        key = (group_id, contact_id)
        if key in existing:
            continue
        dashboard_table("email_group_members").insert({"group_id": group_id, "contact_id": contact_id}).execute()
        existing.add(key)
    return {"ok": True}


@router.post("/groups/{group_id}/members/all-matching")
async def bulk_add_all_matching_to_group(
    group_id: str,
    payload: BulkAddAllMatchingPayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, int]:
    ensure_dashboard_admin(current)
    _ensure_not_auto_managed(group_id)
    ids = _load_matching_contact_ids(payload.q.strip())
    memberships = _load_rows("email_group_members")
    existing = {(str(row.get("group_id")), str(row.get("contact_id"))) for row in memberships}
    added = 0
    for contact_id in ids:
        key = (group_id, contact_id)
        if key in existing:
            continue
        dashboard_table("email_group_members").insert({"group_id": group_id, "contact_id": contact_id}).execute()
        existing.add(key)
        added += 1
    return {"added": added, "scanned": len(ids)}


@router.delete("/groups/{group_id}/members")
async def bulk_remove_contacts_from_group(
    group_id: str,
    payload: BulkGroupMembershipPayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    _ensure_not_auto_managed(group_id)
    for contact_id in payload.contactIds:
        dashboard_table("email_group_members").delete().eq("group_id", group_id).eq("contact_id", contact_id).execute()
    return {"ok": True}


@router.get("/groups")
async def list_groups(current: UserState = Depends(get_current_user)) -> list[dict[str, Any]]:
    ensure_dashboard_admin(current)
    rows = _load_rows("email_groups")
    rows.sort(key=lambda row: (bool(row.get("is_auto_managed")), str(row.get("name") or "").lower()))
    rows.sort(key=lambda row: bool(row.get("is_auto_managed")))
    return [_serialize_group(row, _count_group_members(row)) for row in rows]


@router.get("/groups/{group_id}")
async def get_group(group_id: str, current: UserState = Depends(get_current_user)) -> dict[str, Any] | None:
    ensure_dashboard_admin(current)
    group = next((row for row in _load_rows("email_groups") if row.get("id") == group_id), None)
    if not group:
        return None
    return _serialize_group(group, _count_group_members(group))


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(payload: CreateGroupPayload, current: UserState = Depends(get_current_user)) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required.")
    if payload.isAutoManaged and not payload.autoManagedKey:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Auto-managed groups require a source.")
    if payload.autoManagedKey and payload.autoManagedKey not in AUTO_MANAGED_KEYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown auto-managed source.")
    if any(str(row.get("name") or "").strip().lower() == name.lower() for row in _load_rows("email_groups")):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A group with that name already exists.")
    if payload.autoManagedKey == UNSUBSCRIBED_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The Unsubscribed source is reserved for the system group.",
        )

    group_id = str(uuid4())
    now = utc_now_iso()
    row = {
        "id": group_id,
        "name": name,
        "description": _normalize_text(payload.description),
        "is_auto_managed": payload.isAutoManaged,
        "auto_managed_key": payload.autoManagedKey if payload.isAutoManaged else None,
        "created_at": now,
        "updated_at": now,
    }
    dashboard_table("email_groups").insert(row).execute()
    return _serialize_group(row, 0)


@router.patch("/groups/{group_id}")
async def update_group(
    group_id: str,
    payload: UpdateGroupPayload,
    current: UserState = Depends(get_current_user),
) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    existing = _get_group_or_404(group_id)
    is_system = existing.get("auto_managed_key") in SYSTEM_AUTO_MANAGED_KEYS
    if is_system and (
        payload.isAutoManaged is False
        or (payload.autoManagedKey is not None and payload.autoManagedKey != existing.get("auto_managed_key"))
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group is system-managed. Its source cannot be changed.",
        )

    patch: dict[str, Any] = {"updated_at": utc_now_iso()}
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required.")
        patch["name"] = name
    if payload.description is not None:
        patch["description"] = _normalize_text(payload.description)
    if payload.isAutoManaged is not None:
        patch["is_auto_managed"] = payload.isAutoManaged
        if payload.isAutoManaged is False:
            patch["auto_managed_key"] = None
    if payload.autoManagedKey is not None and not is_system:
        if payload.autoManagedKey not in AUTO_MANAGED_KEYS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown auto-managed source.")
        patch["auto_managed_key"] = payload.autoManagedKey
        patch["is_auto_managed"] = True

    if patch.get("is_auto_managed") is True and not (patch.get("auto_managed_key") or existing.get("auto_managed_key")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Auto-managed groups require a source.")

    dashboard_table("email_groups").update(patch).eq("id", group_id).execute()
    return {"ok": True}


@router.delete("/groups/{group_id}")
async def delete_group(group_id: str, current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    row = _get_group_or_404(group_id)
    if row.get("auto_managed_key") in SYSTEM_AUTO_MANAGED_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group is system-managed and cannot be deleted. Membership is computed from unsubscribe events.",
        )
    dashboard_table("email_group_members").delete().eq("group_id", group_id).execute()
    dashboard_table("email_groups").delete().eq("id", group_id).execute()
    return {"ok": True}


@router.get("/groups/{group_id}/contacts")
async def list_group_contacts(
    group_id: str,
    q: str = Query(default=""),
    sort: str = Query(default="email_asc"),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=100),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    group = next((row for row in _load_rows("email_groups") if row.get("id") == group_id), None)
    if not group:
        return {"group": None, "rows": [], "total": 0, "page": page, "pageSize": pageSize}

    if bool(group.get("is_auto_managed")) and not _is_wired_auto_managed_key(group.get("auto_managed_key")):
        return {
            "group": {
                "id": group["id"],
                "name": group.get("name") or "",
                "description": group.get("description"),
                "isAutoManaged": True,
                "autoManagedKey": group.get("auto_managed_key"),
                "pendingSync": True,
            },
            "rows": [],
            "total": 0,
            "page": page,
            "pageSize": pageSize,
        }

    contacts = {str(row["id"]): row for row in _load_rows("email_contacts")}
    if bool(group.get("is_auto_managed")) and group.get("auto_managed_key") == UNSUBSCRIBED_KEY:
        member_ids = _unsubscribed_contact_ids()
    else:
        member_ids = {
            str(row.get("contact_id"))
            for row in _load_rows("email_group_members")
            if row.get("group_id") == group_id and row.get("contact_id")
        }
    rows = [contacts[contact_id] for contact_id in member_ids if contact_id in contacts]
    rows = [row for row in rows if _matches_contact_search(row, q.strip())]
    rows = _sort_contacts(rows, sort)
    total = len(rows)
    page_rows = _paginate(rows, page, pageSize)
    return {
        "group": {
            "id": group["id"],
            "name": group.get("name") or "",
            "description": group.get("description"),
            "isAutoManaged": bool(group.get("is_auto_managed")),
            "autoManagedKey": group.get("auto_managed_key"),
            "pendingSync": False,
        },
        "rows": [_serialize_contact(row) for row in page_rows],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/groups/{group_id}/addable-contacts")
async def list_addable_contacts(
    group_id: str,
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=100),
    current: UserState = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_dashboard_admin(current)
    group = next((row for row in _load_rows("email_groups") if row.get("id") == group_id), None)
    if not group or bool(group.get("is_auto_managed")):
        return {"rows": [], "total": 0, "page": page, "pageSize": pageSize}

    already_member_ids = {
        str(row.get("contact_id"))
        for row in _load_rows("email_group_members")
        if row.get("group_id") == group_id and row.get("contact_id")
    }
    rows = [
        row
        for row in _load_rows("email_contacts")
        if str(row["id"]) not in already_member_ids and _matches_contact_search(row, q.strip())
    ]
    rows = sorted(rows, key=lambda row: str(row.get("email") or "").lower())
    total = len(rows)
    page_rows = _paginate(rows, page, pageSize)
    return {
        "rows": [{"id": row["id"], "email": row.get("email") or "", "name": row.get("name")} for row in page_rows],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }
