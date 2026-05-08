from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from server import dashboard_common, dashboard_social_sources
from server.schemas import DashboardInstagramInsightResponse, UserState


class _StubTable:
    def __init__(self, client: "_StubClient", name: str) -> None:
        self.client = client
        self.name = name
        self.filters: list[tuple[str, str, Any]] = []
        self.limit_value: int | None = None
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
        return True

    def execute(self) -> SimpleNamespace:
        if self.pending_insert is not None:
            created: list[dict[str, Any]] = []
            for row in self.pending_insert:
                created.append(copy.deepcopy(row))
                self.rows.append(copy.deepcopy(row))
            return SimpleNamespace(data=created)

        if self.pending_upsert is not None:
            saved: list[dict[str, Any]] = []
            for row in self.pending_upsert:
                prepared = copy.deepcopy(row)
                matched = None
                if self.upsert_conflict:
                    matched = next(
                        (
                            existing
                            for existing in self.rows
                            if existing.get(self.upsert_conflict) == prepared.get(self.upsert_conflict)
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
        if self.limit_value is not None:
            data = data[: self.limit_value]
        return SimpleNamespace(data=data)


class _StubClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "social_accounts": [],
            "social_posts": [],
            "search_queries": [],
        }

    def schema(self, _name: str) -> "_StubClient":
        return self

    def table(self, name: str) -> _StubTable:
        return _StubTable(self, name)


def _build_app(
    monkeypatch: pytest.MonkeyPatch,
    current_user: UserState,
) -> tuple[TestClient, _StubClient]:
    app = FastAPI()
    app.include_router(dashboard_social_sources.router)
    app.dependency_overrides[dashboard_social_sources.get_current_user] = lambda: current_user
    stub = _StubClient()
    monkeypatch.setattr(dashboard_common, "get_client", lambda: stub)
    return TestClient(app), stub


def test_social_sources_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_app(monkeypatch, UserState(id="user-1", credits=10, isAdmin=False))

    response = client.post("/dashboard/social/discovery/run", json={})

    assert response.status_code == 403


def test_discovery_route_upserts_social_accounts_and_logs_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, stub = _build_app(monkeypatch, UserState(id="admin-1", credits=10, isAdmin=True))
    stub.tables["social_accounts"] = [
        {
            "id": "shinybrand",
            "username": "shinybrand",
            "source": "tavily_search",
            "discovery_source": "tavily_search",
            "discovered_via_query": "old query",
            "source_url": "https://old.example.com",
            "first_seen_at": "2026-04-01T00:00:00+00:00",
            "synced_at": "2026-04-01T00:00:00+00:00",
        }
    ]

    async def _fake_search(_query: str, max_results: int = 20) -> tuple[list[dict[str, Any]], int]:
        assert max_results == 20
        return (
            [
                {
                    "url": "https://editorial.example.com/story",
                    "title": "Top small brands including @shinybrand and @newatelier",
                    "content": "Based in New York. Handmade fine jewelry. 12K followers.",
                }
            ],
            125,
        )

    monkeypatch.setattr(dashboard_social_sources, "search_tavily", _fake_search)

    response = client.post(
        "/dashboard/social/discovery/run",
        json={"queries": ["best jewelry brands"], "maxResults": 20},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["queriesRun"] == 1
    assert body["newAccountsAdded"] == 1
    assert body["totalUniqueHandles"] == 2
    assert len(stub.tables["search_queries"]) == 1

    shiny = next(row for row in stub.tables["social_accounts"] if row["id"] == "shinybrand")
    fresh = next(row for row in stub.tables["social_accounts"] if row["id"] == "newatelier")
    assert shiny["source_url"] == "https://old.example.com"
    assert shiny["discovered_via_query"] == "old query"
    assert fresh["source_url"] == "https://editorial.example.com/story"
    assert fresh["discovery_source"] == "tavily_search"
    assert fresh["fit_score"] > 0


@pytest.mark.asyncio
async def test_sync_recent_engagers_preserves_existing_discovery_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubClient()
    stub.tables["social_accounts"] = [
        {
            "id": "brandone",
            "username": "brandone",
            "source": "tavily_search",
            "discovery_source": "tavily_search",
            "source_url": "https://editorial.example.com/roundup",
            "discovered_via_query": "seed query",
            "first_seen_at": "2026-04-01T00:00:00+00:00",
            "last_engaged_with_us_at": None,
            "synced_at": "2026-04-01T00:00:00+00:00",
        }
    ]
    monkeypatch.setattr(dashboard_common, "get_client", lambda: stub)

    async def _fake_business_account_id() -> str:
        return "ig-1"

    async def _fake_recent_media(_ig_id: str, _days: int) -> list[dict[str, Any]]:
        return [{"id": "post-1", "timestamp": "2026-05-01T10:00:00+00:00"}]

    async def _fake_fetch_pages(_url: str, max_pages: int = 20) -> list[dict[str, Any]]:
        assert max_pages == 5
        return [{"username": "brandone", "timestamp": "2026-05-01T12:00:00+00:00"}]

    monkeypatch.setattr(dashboard_social_sources, "get_business_account_id", _fake_business_account_id)
    monkeypatch.setattr(dashboard_social_sources, "_get_recent_media", _fake_recent_media)
    monkeypatch.setattr(dashboard_social_sources, "_fetch_all_meta_pages", _fake_fetch_pages)

    result = await dashboard_social_sources.sync_recent_engagers(days=30)

    assert result["postsScanned"] == 1
    assert result["uniqueAccounts"] == 1
    row = stub.tables["social_accounts"][0]
    assert row["source"] == "tavily_search"
    assert row["discovery_source"] == "tavily_search"
    assert row["source_url"] == "https://editorial.example.com/roundup"
    assert row["last_engaged_with_us_at"] == "2026-05-01T12:00:00+00:00"


def test_instagram_routes_return_sync_and_insight_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _build_app(monkeypatch, UserState(id="admin-1", credits=10, isAdmin=True))

    async def _fake_sync_all(days: int = 30):
        assert days == 14
        return dashboard_social_sources.DashboardInstagramSyncResponse(
            engagers={"postsScanned": 3, "commentsSeen": 9, "uniqueAccounts": 2, "postsSkipped": 0},
            mentioners={"mediaFound": 1, "uniqueAccounts": 1, "postsUpserted": 1},
            dmSenders={"conversations": 4, "uniqueAccounts": 2},
            durationMs=250,
        )

    async def _fake_insights(metrics: list[str], days: int = 7):
        assert metrics == ["reach", "profile_views"]
        assert days == 7
        return [
            DashboardInstagramInsightResponse(name="reach", total=1200),
            DashboardInstagramInsightResponse(name="profile_views", total=87),
        ]

    monkeypatch.setattr(dashboard_social_sources, "sync_all_instagram", _fake_sync_all)
    monkeypatch.setattr(dashboard_social_sources, "get_account_insights", _fake_insights)

    sync_response = client.post("/dashboard/social/instagram/sync", json={"days": 14})
    insights_response = client.get("/dashboard/social/instagram/insights?metrics=reach,profile_views&days=7")

    assert sync_response.status_code == 200
    assert sync_response.json()["engagers"]["commentsSeen"] == 9
    assert insights_response.status_code == 200
    assert insights_response.json()[0]["name"] == "reach"
