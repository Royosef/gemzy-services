"""Utilities for working with Gemzy plan tiers."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from postgrest.exceptions import APIError

from .supabase_client import get_client

_PLAN_CREDITS_CACHE: dict[str, int] = {}
_PLAN_CREDITS_EXPIRES_AT: datetime | None = None
_PLAN_CREDITS_CACHE_TTL = int(os.getenv("PLAN_CREDITS_CACHE_TTL", "300"))
_DEFAULT_PLAN_FALLBACK = int(os.getenv("PLAN_DEFAULT_INITIAL_CREDITS", "0"))

_CANONICAL_PLAN_NAMES: dict[str, str] = {
    "free": "Free",
    "pro": "Pro",
    "designer": "Designer",
}


def normalize_plan(value: Any) -> str:
    """Normalise arbitrary plan identifiers to a canonical tier."""

    if value is None:
        return "Free"
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return "Free"
        return _CANONICAL_PLAN_NAMES.get(cleaned.lower(), cleaned)
    return "Free"


def _parse_initial_credits(value: Any) -> int | None:
    try:
        credits = int(value)
    except (TypeError, ValueError):
        return None
    if credits < 0:
        return None
    return credits


def _refresh_plan_cache() -> None:
    """Refresh the cached plan credit allocations from Supabase."""

    global _PLAN_CREDITS_CACHE, _PLAN_CREDITS_EXPIRES_AT

    sb = get_client()
    try:
        response = sb.table("plan_settings").select("plan,initial_credits").execute()
    except APIError:
        _PLAN_CREDITS_CACHE = {}
    else:
        data = response.data or []
        credits: dict[str, int] = {}
        for entry in data:
            plan_name = normalize_plan(entry.get("plan"))
            allocation = _parse_initial_credits(entry.get("initial_credits"))
            if allocation is None:
                continue
            credits[plan_name] = allocation
        if credits:
            _PLAN_CREDITS_CACHE = credits

    ttl = max(60, _PLAN_CREDITS_CACHE_TTL)
    _PLAN_CREDITS_EXPIRES_AT = datetime.now(timezone.utc) + timedelta(seconds=ttl)


def get_plan_initial_credits(plan: str | None) -> int:
    """Return the default monthly credit allocation for the provided plan."""

    normalized = normalize_plan(plan)
    now = datetime.now(timezone.utc)
    if (
        _PLAN_CREDITS_CACHE
        and _PLAN_CREDITS_EXPIRES_AT is not None
        and now < _PLAN_CREDITS_EXPIRES_AT
    ):
        cached = _PLAN_CREDITS_CACHE.get(normalized)
        if cached is not None:
            return cached

    _refresh_plan_cache()
    cached = _PLAN_CREDITS_CACHE.get(normalized)
    if cached is not None:
        return cached

    if _PLAN_CREDITS_CACHE:
        return _PLAN_CREDITS_CACHE.get("Free", next(iter(_PLAN_CREDITS_CACHE.values())))

    return _DEFAULT_PLAN_FALLBACK


# Plan tier ordering for upgrade/downgrade detection
_TIER_ORDER: dict[str, int] = {
    "Free": 0,
    "Pro": 1,
    "Designer": 2,
}


def is_upgrade(old_plan: str | None, new_plan: str | None) -> bool:
    """Check if this plan change is an upgrade (higher tier).
    
    Returns True if new_plan is a higher tier than old_plan.
    Examples:
        - Free → Pro: upgrade
        - Pro → Designer: upgrade
        - Designer → Pro: NOT upgrade (downgrade)
    """
    old_normalized = normalize_plan(old_plan)
    new_normalized = normalize_plan(new_plan)
    return _TIER_ORDER.get(new_normalized, 0) > _TIER_ORDER.get(old_normalized, 0)


__all__ = ["get_plan_initial_credits", "normalize_plan", "is_upgrade"]
