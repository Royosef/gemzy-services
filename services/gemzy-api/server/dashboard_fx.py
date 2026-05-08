from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends

from .auth import get_current_user
from .dashboard_common import ensure_dashboard_admin
from .schemas import DashboardFxRateResponse, UserState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard/fx", tags=["dashboard-fx"])

_PRIMARY_URL = "https://api.exchangerate.host/latest?base=USD&symbols=ILS"
_FALLBACK_URL = "https://open.er-api.com/v6/latest/USD"
_HARDCODED_FALLBACK = 3.7


def _fetched_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_rate(payload: object) -> float | None:
    if not isinstance(payload, dict):
        return None
    rates = payload.get("rates")
    if not isinstance(rates, dict):
        return None
    value = rates.get("ILS")
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return None


def _try_fetch_rate(url: str) -> float | None:
    try:
        response = httpx.get(url, timeout=5.0)
        if response.status_code != 200:
            return None
        return _extract_rate(response.json())
    except Exception:
        return None


def get_usd_to_ils_rate() -> DashboardFxRateResponse:
    fetched_at = _fetched_at()

    primary = _try_fetch_rate(_PRIMARY_URL)
    if primary is not None:
        return DashboardFxRateResponse(
            rate=primary,
            source="exchangerate.host",
            fetchedAt=fetched_at,
        )

    fallback = _try_fetch_rate(_FALLBACK_URL)
    if fallback is not None:
        return DashboardFxRateResponse(
            rate=fallback,
            source="open.er-api.com",
            fetchedAt=fetched_at,
        )

    logger.warning("[dashboard.fx] both providers failed, using hardcoded fallback")
    return DashboardFxRateResponse(
        rate=_HARDCODED_FALLBACK,
        source="fallback",
        fetchedAt=fetched_at,
    )


@router.get("/usd-ils", response_model=DashboardFxRateResponse)
def get_dashboard_fx_rate(
    current: UserState = Depends(get_current_user),
) -> DashboardFxRateResponse:
    ensure_dashboard_admin(current)
    return get_usd_to_ils_rate()
