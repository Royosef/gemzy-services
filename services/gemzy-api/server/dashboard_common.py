from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from .schemas import UserState
from .supabase_client import get_client


def ensure_dashboard_admin(current: UserState) -> None:
    if current.isAdmin:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Dashboard admin access required"
    )


def dashboard_db():
    schema = (os.getenv("SUPABASE_DASHBOARD_SCHEMA") or "dashboard").strip()
    client = get_client()
    if schema:
        return client.schema(schema)
    return client


def dashboard_table(name: str):
    return dashboard_db().table(name)


def iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
