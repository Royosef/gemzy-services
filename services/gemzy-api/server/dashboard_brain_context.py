from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from .auth import get_current_user
from .dashboard_common import ensure_dashboard_admin
from .dashboard_revenue import build_revenue_context, is_configured, summarize_revenue_context
from .schemas import DashboardAdminBrainContextResponse, UserState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/brain", tags=["dashboard-brain"])


@router.get("/context", response_model=DashboardAdminBrainContextResponse)
def admin_brain_context(
    current: UserState = Depends(get_current_user),
) -> DashboardAdminBrainContextResponse:
    ensure_dashboard_admin(current)
    started_at = time.time()
    revenue = build_revenue_context() if is_configured() else None
    revenue_summary = summarize_revenue_context(revenue) if revenue else None
    generated_in_ms = int((time.time() - started_at) * 1000)
    as_of = (
        str(revenue.get("asOf"))
        if isinstance(revenue, dict) and revenue.get("asOf")
        else datetime.now(timezone.utc).isoformat()
    )
    logger.info(
        "dashboard admin brain context served",
        extra={
            "generatedInMs": generated_in_ms,
            "revenueAvailable": revenue is not None,
        },
    )
    return DashboardAdminBrainContextResponse(
        asOf=as_of,
        generatedInMs=generated_in_ms,
        revenue=revenue,
        revenueSummary=revenue_summary,
        notes={
            "revenueAvailable": revenue is not None,
            "promptShipsTimeseries": False,
            "promptShipsSummary": revenue_summary is not None,
        },
    )
