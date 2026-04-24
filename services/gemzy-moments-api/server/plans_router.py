"""Plans configuration router for exposing plan settings."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .plans import normalize_plan
from .supabase_client import get_client

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/config")
def get_plans_config() -> dict[str, Any]:
    """Return plan configurations including monthly credits."""
    sb = get_client()
    response = sb.table("plan_settings").select("plan,initial_credits").execute()
    data = response.data or []

    credits: dict[str, int] = {}
    for entry in data:
        plan_name = normalize_plan(entry.get("plan"))
        allocation = entry.get("initial_credits")
        if allocation is not None:
            try:
                credits[plan_name] = int(allocation)
            except (TypeError, ValueError):
                continue

    return {"credits": credits}
