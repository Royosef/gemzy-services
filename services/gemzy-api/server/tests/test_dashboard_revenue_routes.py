from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from server import dashboard_brain_context, dashboard_fx, dashboard_revenue
from server.schemas import (
    DashboardRevenueCohortRetentionResponse,
    DashboardFxRateResponse,
    DashboardRevenueChartPointResponse,
    DashboardRevenueChartResponse,
    DashboardRevenueMonthlyToYearlyResponse,
    DashboardRevenuePackBreakdownItemResponse,
    DashboardRevenuePackBreakdownResponse,
    DashboardRevenuePlanBreakdownItemResponse,
    DashboardRevenuePlanBreakdownResponse,
    DashboardRevenueSubscriberDetailResponse,
    DashboardRevenueSubscriberListResponse,
    DashboardRevenueSubscriberRowResponse,
    UserState,
)


def _build_app(
    current_user: UserState,
) -> TestClient:
    app = FastAPI()
    app.include_router(dashboard_fx.router)
    app.include_router(dashboard_revenue.router)
    app.include_router(dashboard_brain_context.router)
    app.dependency_overrides[dashboard_fx.get_current_user] = lambda: current_user
    app.dependency_overrides[dashboard_revenue.get_current_user] = lambda: current_user
    app.dependency_overrides[dashboard_brain_context.get_current_user] = lambda: current_user
    return TestClient(app)


def test_dashboard_revenue_routes_require_admin() -> None:
    client = _build_app(UserState(id="user-1", credits=0, isAdmin=False))

    response = client.get("/dashboard/fx/usd-ils")

    assert response.status_code == 403


def test_dashboard_revenue_project_id_prefers_server_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVENUECAT_PROJECT_ID", "server-project")
    monkeypatch.setenv("VITE_REVENUECAT_PROJECT_ID", "vite-project")

    assert dashboard_revenue.get_project_id() == "server-project"


def test_dashboard_revenue_project_id_falls_back_to_compat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVENUECAT_PROJECT_ID", raising=False)
    monkeypatch.setenv("VITE_REVENUECAT_PROJECT_ID", "vite-project")

    assert dashboard_revenue.get_project_id() == "vite-project"


def test_dashboard_revenue_project_path_raises_clear_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVENUECAT_PROJECT_ID", raising=False)
    monkeypatch.delenv("VITE_REVENUECAT_PROJECT_ID", raising=False)

    with pytest.raises(dashboard_revenue.RevenueCatApiError) as exc:
        dashboard_revenue._project_path("/charts/mrr")

    assert "REVENUECAT_PROJECT_ID" in str(exc.value)


def test_dashboard_fx_revenue_and_brain_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_app(UserState(id="admin-1", credits=0, isAdmin=True))

    monkeypatch.setattr(
        dashboard_fx,
        "get_usd_to_ils_rate",
        lambda: DashboardFxRateResponse(
            rate=3.82,
            source="exchangerate.host",
            fetchedAt="2026-05-03T10:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        dashboard_revenue,
        "_safe_overview_metrics",
        lambda: [
            {"id": "mrr", "value": 449},
            {"id": "revenue", "value": 470},
            {"id": "active_subscriptions", "value": 11},
            {"id": "active_trials", "value": 3},
            {"id": "new_customers", "value": 9},
            {"id": "active_users", "value": 55},
        ],
    )
    monkeypatch.setattr(
        dashboard_revenue,
        "_safe_chart",
        lambda chart_name, range_days, filters=None: DashboardRevenueChartResponse(
            chartName=chart_name,
            resolution="day",
            values=[
                DashboardRevenueChartPointResponse(
                    cohort=1,
                    date="2026-05-01",
                    value=12.5,
                    incomplete=False,
                    measure=0,
                )
            ],
            yaxisCurrency="USD",
        ),
    )
    monkeypatch.setattr(
        dashboard_revenue,
        "derive_plan_breakdown",
        lambda: DashboardRevenuePlanBreakdownResponse(
            plans=[
                DashboardRevenuePlanBreakdownItemResponse(
                    plan="Pro",
                    cadence="Monthly",
                    count=8,
                )
            ],
            totalActiveSubscribers=8,
        ),
    )
    monkeypatch.setattr(
        dashboard_revenue,
        "derive_credits_by_package",
        lambda range_days: DashboardRevenuePackBreakdownResponse(
            packs=[
                DashboardRevenuePackBreakdownItemResponse(
                    size="XL",
                    revenue=120.0,
                    units=4,
                )
            ]
        ),
    )
    monkeypatch.setattr(
        dashboard_brain_context,
        "is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        dashboard_brain_context,
        "build_revenue_context",
        lambda: {
            "asOf": "2026-05-03T10:00:00+00:00",
            "mrrUsd": 449,
            "activeSubscribersCount": 11,
        },
    )
    monkeypatch.setattr(
        dashboard_brain_context,
        "summarize_revenue_context",
        lambda context: {
            "asOf": context["asOf"],
            "snapshot": {"mrrUsd": context["mrrUsd"]},
        },
    )

    fx_response = client.get("/dashboard/fx/usd-ils")
    overview_response = client.get("/dashboard/revenuecat/overview")
    mrr_response = client.get("/dashboard/revenuecat/charts/mrr?rangeDays=90")
    plans_response = client.get("/dashboard/revenuecat/plan-breakdown")
    packs_response = client.get("/dashboard/revenuecat/credits-by-package?rangeDays=30")
    brain_response = client.get("/api/admin/brain/context")

    assert fx_response.status_code == 200
    assert fx_response.json()["rate"] == 3.82

    assert overview_response.status_code == 200
    assert overview_response.json()["mrr"] == 449
    assert overview_response.json()["activeSubscriptions"] == 11

    assert mrr_response.status_code == 200
    assert mrr_response.json()["chartName"] == "mrr"
    assert mrr_response.json()["values"][0]["date"] == "2026-05-01"

    assert plans_response.status_code == 200
    assert plans_response.json()["plans"][0]["plan"] == "Pro"

    assert packs_response.status_code == 200
    assert packs_response.json()["packs"][0]["size"] == "XL"

    assert brain_response.status_code == 200
    assert brain_response.json()["notes"]["revenueAvailable"] is True
    assert brain_response.json()["revenueSummary"]["snapshot"]["mrrUsd"] == 449


def test_dashboard_revenue_subscriber_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_app(UserState(id="admin-1", credits=0, isAdmin=True))
    monkeypatch.setattr(
        dashboard_revenue,
        "load_walk",
        lambda: {
            "walk": {
                "customers": [{"id": "cust-1234", "firstSeenAt": 1000, "lastSeenAt": 2000, "lastSeenCountry": "US", "lastSeenPlatform": "ios"}],
                "subscriptions": [
                    {
                        "customerId": "cust-1234",
                        "productId": "gemzy_pro_monthly",
                        "status": "active",
                        "givesAccess": True,
                        "startsAt": 1_700_000_000_000,
                        "endsAt": None,
                        "entitlementLookupKeys": ["pro"],
                    }
                ],
                "purchases": [
                    {
                        "customerId": "cust-1234",
                        "productId": "credits_xl",
                        "purchasedAt": 1_700_100_000_000,
                        "revenueUsd": 49.0,
                        "quantity": 1,
                        "environment": "production",
                    }
                ],
            },
            "products": [
                {"id": "gemzy_pro_monthly", "storeIdentifier": "gemzy_pro_monthly", "duration": "P1M"},
                {"id": "credits_xl", "storeIdentifier": "credits_xl", "duration": None},
            ],
        },
    )

    list_response = client.get("/dashboard/revenuecat/subscribers?page=1&pageSize=25")
    detail_response = client.get("/dashboard/revenuecat/subscribers/cust-1234")
    cohort_response = client.get("/dashboard/revenuecat/cohort-retention")
    conversions_response = client.get("/dashboard/revenuecat/monthly-to-yearly?rangeDays=365")

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["customerId"] == "cust-1234"
    assert list_response.json()["items"][0]["plan"] == "Pro"

    assert detail_response.status_code == 200
    assert detail_response.json()["customerId"] == "cust-1234"
    assert detail_response.json()["purchases"][0]["pack"] == "XL"

    assert cohort_response.status_code == 200
    assert isinstance(cohort_response.json()["cohorts"], list)

    assert conversions_response.status_code == 200
    assert conversions_response.json()["conversions"] == 0
