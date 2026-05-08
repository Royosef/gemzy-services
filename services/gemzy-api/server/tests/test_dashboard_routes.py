from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from server import dashboard_coach, dashboard_common, dashboard_meta, dashboard_social
from server.schemas import UserState


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _StubTable:
    def __init__(self, client: "_StubClient", name: str) -> None:
        self.client = client
        self.name = name
        self.filters: list[tuple[str, str, Any]] = []
        self.limit_value: int | None = None
        self.ordering: list[tuple[str, bool]] = []
        self.pending_insert: list[dict[str, Any]] | None = None
        self.pending_update: dict[str, Any] | None = None
        self.pending_upsert: list[dict[str, Any]] | None = None
        self.pending_delete = False
        self.upsert_conflict: str | None = None

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self.client.tables.setdefault(self.name, [])

    def select(self, *_args: Any, **_kwargs: Any) -> "_StubTable":
        return self

    def eq(self, column: str, value: Any) -> "_StubTable":
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> "_StubTable":
        self.filters.append(("in", column, list(values)))
        return self

    def gt(self, column: str, value: Any) -> "_StubTable":
        self.filters.append(("gt", column, value))
        return self

    def order(self, column: str, desc: bool = False) -> "_StubTable":
        self.ordering.append((column, desc))
        return self

    def limit(self, value: int) -> "_StubTable":
        self.limit_value = value
        return self

    def insert(self, payload: dict[str, Any] | list[dict[str, Any]]) -> "_StubTable":
        rows = payload if isinstance(payload, list) else [payload]
        self.pending_insert = [copy.deepcopy(row) for row in rows]
        return self

    def update(self, payload: dict[str, Any]) -> "_StubTable":
        self.pending_update = copy.deepcopy(payload)
        return self

    def upsert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> "_StubTable":
        rows = payload if isinstance(payload, list) else [payload]
        self.pending_upsert = [copy.deepcopy(row) for row in rows]
        self.upsert_conflict = on_conflict
        return self

    def delete(self) -> "_StubTable":
        self.pending_delete = True
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        for op, column, value in self.filters:
            current = row.get(column)
            if op == "eq" and current != value:
                return False
            if op == "in" and current not in set(value):
                return False
            if op == "gt" and not (current is not None and current > value):
                return False
        return True

    def _apply_insert_defaults(self, row: dict[str, Any]) -> dict[str, Any]:
        if "id" not in row:
            row["id"] = self.client.next_id(self.name)
        if self.name == "recommendations":
            row.setdefault("status", "active")
            row.setdefault("created_at", _now_iso())
        if self.name == "recommendation_actions":
            row.setdefault("created_at", _now_iso())
        if self.name == "social_recommendations":
            row.setdefault("status", "active")
            row.setdefault("generated_at", _now_iso())
        if self.name == "social_actions":
            row.setdefault("created_at", _now_iso())
        return row

    def execute(self) -> SimpleNamespace:
        if self.pending_insert is not None:
            created: list[dict[str, Any]] = []
            for row in self.pending_insert:
                prepared = self._apply_insert_defaults(row)
                created.append(copy.deepcopy(prepared))
                self.rows.append(copy.deepcopy(prepared))
            return SimpleNamespace(data=created)

        if self.pending_upsert is not None:
            saved: list[dict[str, Any]] = []
            conflict = self.upsert_conflict
            for row in self.pending_upsert:
                prepared = self._apply_insert_defaults(row)
                matched = None
                if conflict:
                    matched = next(
                        (
                            existing
                            for existing in self.rows
                            if existing.get(conflict) == prepared.get(conflict)
                        ),
                        None,
                    )
                if matched is None:
                    self.rows.append(copy.deepcopy(prepared))
                    saved.append(copy.deepcopy(prepared))
                else:
                    matched.update(copy.deepcopy(prepared))
                    saved.append(copy.deepcopy(matched))
            return SimpleNamespace(data=saved)

        filtered = [row for row in self.rows if self._matches(row)]

        if self.pending_update is not None:
            updated_rows: list[dict[str, Any]] = []
            for row in filtered:
                row.update(copy.deepcopy(self.pending_update))
                updated_rows.append(copy.deepcopy(row))
            return SimpleNamespace(data=updated_rows)

        if self.pending_delete:
            removed = [copy.deepcopy(row) for row in filtered]
            self.client.tables[self.name] = [row for row in self.rows if not self._matches(row)]
            return SimpleNamespace(data=removed)

        data = [copy.deepcopy(row) for row in filtered]
        for column, desc in reversed(self.ordering):
            data.sort(key=lambda row: row.get(column) or "", reverse=desc)
        if self.limit_value is not None:
            data = data[: self.limit_value]
        return SimpleNamespace(data=data)


class _StubClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "ads": [],
            "ad_sets": [],
            "campaigns": [],
            "recommendations": [],
            "recommendation_actions": [],
            "social_accounts": [],
            "social_actions": [],
            "social_recommendations": [],
        }
        self.counters: dict[str, int] = {}

    def schema(self, _name: str) -> "_StubClient":
        return self

    def next_id(self, table: str) -> str:
        value = self.counters.get(table, 0) + 1
        self.counters[table] = value
        return f"{table}-{value}"

    def table(self, name: str) -> _StubTable:
        return _StubTable(self, name)


def _build_app(
    monkeypatch: pytest.MonkeyPatch,
    current_user: UserState,
) -> tuple[TestClient, _StubClient]:
    app = FastAPI()
    app.include_router(dashboard_meta.router)
    app.include_router(dashboard_coach.router)
    app.include_router(dashboard_social.router)
    app.dependency_overrides[dashboard_meta.get_current_user] = lambda: current_user
    app.dependency_overrides[dashboard_coach.get_current_user] = lambda: current_user
    app.dependency_overrides[dashboard_social.get_current_user] = lambda: current_user
    stub = _StubClient()
    monkeypatch.setattr(dashboard_common, "get_client", lambda: stub)
    return TestClient(app), stub


def test_dashboard_routes_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_app(
        monkeypatch,
        UserState(id="user-1", credits=10, isAdmin=False),
    )

    response = client.get("/dashboard/meta/overview")

    assert response.status_code == 403


def test_dashboard_meta_routes_expose_sync_metrics_and_top_ads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )
    stub.tables["campaigns"] = [{"id": "cmp-1", "name": "Spring Launch"}]
    stub.tables["ads"] = [
        {
            "id": "ad-1",
            "name": "Hero Creative",
            "campaign_id": "cmp-1",
            "spend": "12.50",
            "results": 8,
            "impressions": 1500,
            "cost_per_result": "1.56",
            "synced_at": "2026-05-01T08:00:00+00:00",
        },
        {
            "id": "ad-2",
            "name": "UGC Cut",
            "campaign_id": "cmp-1",
            "spend": "5.00",
            "results": 3,
            "impressions": 500,
            "cost_per_result": "1.67",
            "synced_at": "2026-05-01T08:10:00+00:00",
        },
    ]
    async def _fake_sync_campaigns() -> int:
        return 4

    async def _fake_sync_ad_sets() -> tuple[int, int, int]:
        return 6, 2, 4

    async def _fake_sync_ads() -> int:
        return 9

    monkeypatch.setattr(dashboard_meta, "_sync_campaigns", _fake_sync_campaigns)
    monkeypatch.setattr(dashboard_meta, "_sync_ad_sets", _fake_sync_ad_sets)
    monkeypatch.setattr(dashboard_meta, "_sync_ads", _fake_sync_ads)

    sync_response = client.post("/dashboard/meta/sync")
    overview_response = client.get("/dashboard/meta/overview")
    top_ads_response = client.get("/dashboard/meta/top-ads")

    assert sync_response.status_code == 200
    assert sync_response.json()["adSets"] == 6
    assert overview_response.status_code == 200
    assert overview_response.json()["totalSpend"] == "17.50"
    assert overview_response.json()["totalResults"] == 11
    assert top_ads_response.status_code == 200
    assert top_ads_response.json()[0]["adName"] == "Hero Creative"


def test_dashboard_meta_spend_timeseries_and_campaign_performance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )
    stub.tables["campaigns"] = [
        {"id": "cmp-1", "name": "Spring Launch", "status": "ACTIVE"},
        {"id": "cmp-2", "name": "Retargeting", "status": "PAUSED"},
    ]
    stub.tables["ads"] = [
        {
            "id": "ad-1",
            "name": "Hero Creative",
            "campaign_id": "cmp-1",
            "spend": "40.00",
            "synced_at": "2026-05-01T08:00:00+00:00",
        },
        {
            "id": "ad-2",
            "name": "UGC Cut",
            "campaign_id": "cmp-2",
            "spend": "20.00",
            "synced_at": "2026-05-02T08:00:00+00:00",
        },
    ]

    async def _fake_fetch_all_pages(_url: str) -> list[dict[str, Any]]:
        return [
            {
                "campaign_id": "cmp-1",
                "campaign_name": "Spring Launch",
                "spend": "80.00",
                "actions": [{"action_type": "purchase", "value": "4"}],
                "action_values": [{"action_type": "purchase", "value": "160.00"}],
            },
            {
                "campaign_id": "cmp-2",
                "campaign_name": "Retargeting",
                "spend": "25.00",
                "actions": [],
                "action_values": [],
            },
        ]

    monkeypatch.setattr(
        dashboard_meta,
        "get_usd_to_ils_rate",
        lambda: SimpleNamespace(rate=4.0),
    )
    monkeypatch.setattr(dashboard_meta, "_fetch_all_pages", _fake_fetch_all_pages)
    monkeypatch.setattr(dashboard_meta, "_meta_config", lambda: ("token", "act_123"))
    dashboard_meta._campaign_performance_cache.clear()

    spend_response = client.get("/dashboard/meta/spend-timeseries?rangeDays=3650")
    performance_response = client.get("/dashboard/meta/campaign-performance?rangeDays=30")

    assert spend_response.status_code == 200
    spend_body = spend_response.json()
    assert spend_body["currency"] == "USD"
    assert spend_body["points"][0]["date"] == "2026-05-01"
    assert spend_body["points"][0]["spend"] == 15.0

    assert performance_response.status_code == 200
    performance_body = performance_response.json()
    assert performance_body["hasAnyAttribution"] is True
    assert performance_body["rows"][0]["campaignId"] == "cmp-1"
    assert performance_body["rows"][0]["spendUsd"] == 20.0
    assert performance_body["rows"][0]["revenueUsd"] == 40.0
    assert performance_body["rows"][0]["roas"] == 2.0
    assert performance_body["rows"][0]["cacUsd"] == 5.0


def test_dashboard_meta_config_strips_quoted_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "'quoted-token'")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", '"123456"')

    token, account_id = dashboard_meta._meta_config()

    assert token == "quoted-token"
    assert account_id == "act_123456"


def test_dashboard_coach_flow_generate_record_and_undo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )
    stub.tables["campaigns"] = [
        {"id": "cmp-1", "name": "Launch", "synced_at": "2026-05-01T08:00:00+00:00"}
    ]
    stub.tables["ad_sets"] = [
        {
            "id": "set-1",
            "name": "Prospecting",
            "budget_mode": "ABO",
            "daily_budget": "25.00",
            "optimization_goal": "PURCHASE",
            "learning_stage": "learning",
        }
    ]
    stub.tables["ads"] = [
        {
            "id": "ad-1",
            "name": "Best Seller",
            "status": "ACTIVE",
            "campaign_id": "cmp-1",
            "ad_set_id": "set-1",
            "spend": "100.00",
            "impressions": 5000,
            "reach": 3000,
            "results": 12,
            "cost_per_result": "8.33",
            "cpm": "20.00",
            "synced_at": "2026-05-01T08:10:00+00:00",
        }
    ]

    async def _fake_claude(_system: str, _message: str, max_tokens: int = 4096) -> dict[str, str]:
        return {
            "text": json.dumps(
                [
                    {
                        "action": "Increase spend on Best Seller",
                        "reasoning": "It is producing the strongest results.",
                        "executionNotes": "Raise budget by 20% in Ads Manager.",
                        "priority": "high",
                    }
                ]
            )
        }

    monkeypatch.setattr(dashboard_coach, "call_claude", _fake_claude)

    generate_response = client.post("/dashboard/coach/generate-overview")
    assert generate_response.status_code == 200
    recommendation_id = generate_response.json()[0]["id"]

    list_response = client.get("/dashboard/coach/recommendations")
    assert list_response.status_code == 200
    assert list_response.json()[0]["action"] == "Increase spend on Best Seller"

    action_response = client.post(
        "/dashboard/coach/actions",
        json={"recommendationId": recommendation_id, "action": "done"},
    )
    assert action_response.status_code == 200
    action_id = action_response.json()["id"]
    recommendation = stub.tables["recommendations"][0]
    assert recommendation["status"] == "done"

    undo_response = client.post(
        "/dashboard/coach/actions/undo",
        json={"recommendationActionId": action_id},
    )
    assert undo_response.status_code == 200
    assert stub.tables["recommendations"][0]["status"] == "active"


def test_dashboard_social_flow_generate_record_stats_and_undo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )
    stub.tables["social_accounts"] = [
        {
            "id": "acct-1",
            "username": "foundbrand",
            "follower_count": 12000,
            "niche": "Jewelry",
            "location": "NYC",
            "fit_score": 9.4,
            "discovered_via_query": "best jewelry brands",
            "source_url": "https://example.com/foundbrand",
            "bad_fit_flag": False,
            "discovery_source": "tavily_search",
        }
    ]

    async def _fake_claude(_system: str, _message: str, max_tokens: int = 3500) -> dict[str, str]:
        return {
            "text": json.dumps(
                [
                    {
                        "accountId": "acct-1",
                        "actionType": "Comment",
                        "reasoning": "Strong fit and recent activity.",
                        "priority": "high",
                        "postTypes": [
                            {"label": "product_closeup", "template": "Love this detail."},
                            {"label": "styled_lifestyle", "template": "Beautiful styling."},
                            {"label": "process_bts", "template": "Amazing craft."},
                            {"label": "universal", "template": "So good."},
                        ],
                    }
                ]
            )
        }

    monkeypatch.setattr(dashboard_social, "call_claude", _fake_claude)

    generate_response = client.post("/dashboard/social/generate-daily-actions")
    assert generate_response.status_code == 200
    recommendation_id = generate_response.json()["recommendations"][0]["id"]
    assert generate_response.json()["stats"]["generatedCount"] == 1

    actions_response = client.get("/dashboard/social/actions")
    assert actions_response.status_code == 200
    assert actions_response.json()[0]["account"]["username"] == "foundbrand"

    record_response = client.post(
        "/dashboard/social/actions",
        json={
            "recommendationId": recommendation_id,
            "actionType": "Dismissed",
            "dismissReason": "not_a_real_brand",
        },
    )
    assert record_response.status_code == 200
    assert stub.tables["social_accounts"][0]["bad_fit_flag"] is True

    stats_response = client.get("/dashboard/social/stats")
    assert stats_response.status_code == 200
    assert stats_response.json()["completedToday"] == 1
    assert stats_response.json()["actionsByType"]["Dismissed"] == 1

    undo_response = client.post(
        "/dashboard/social/actions/undo",
        json={"recommendationId": recommendation_id},
    )
    assert undo_response.status_code == 200
    assert stub.tables["social_accounts"][0]["bad_fit_flag"] is False
    assert stub.tables["social_recommendations"][0]["status"] == "active"
