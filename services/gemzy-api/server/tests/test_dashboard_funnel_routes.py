from __future__ import annotations

import copy
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

from server import dashboard_common, dashboard_funnel
from server.schemas import UserState


class _StubTable:
    def __init__(self, client: "_StubClient", name: str) -> None:
        self.client = client
        self.name = name
        self.filters: list[tuple[str, str, Any]] = []
        self.limit_value: int | None = None
        self.ordering: list[tuple[str, bool]] = []
        self.pending_insert: list[dict[str, Any]] | None = None
        self.pending_update: dict[str, Any] | None = None
        self.pending_delete = False

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self.client.tables.setdefault(self.name, [])

    def select(self, *_args: Any, **_kwargs: Any) -> "_StubTable":
        return self

    def eq(self, column: str, value: Any) -> "_StubTable":
        self.filters.append(("eq", column, value))
        return self

    def limit(self, value: int) -> "_StubTable":
        self.limit_value = value
        return self

    def order(self, column: str, desc: bool = False) -> "_StubTable":
        self.ordering.append((column, desc))
        return self

    def insert(self, payload: dict[str, Any] | list[dict[str, Any]]) -> "_StubTable":
        rows = payload if isinstance(payload, list) else [payload]
        self.pending_insert = [copy.deepcopy(row) for row in rows]
        return self

    def update(self, payload: dict[str, Any]) -> "_StubTable":
        self.pending_update = copy.deepcopy(payload)
        return self

    def delete(self) -> "_StubTable":
        self.pending_delete = True
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        for op, column, value in self.filters:
            if op == "eq" and row.get(column) != value:
                return False
        return True

    def execute(self) -> SimpleNamespace:
        if self.pending_insert is not None:
            created: list[dict[str, Any]] = []
            for row in self.pending_insert:
                if "id" not in row:
                    row["id"] = self.client.next_id(self.name)
                created.append(copy.deepcopy(row))
                self.rows.append(copy.deepcopy(row))
            return SimpleNamespace(data=created)

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
            "funnels": [],
            "funnel_stages": [],
            "funnel_campaigns": [],
            "campaigns": [],
            "ads": [],
            "funnel_stage_sessions": [],
            "funnel_chat_messages": [],
            "chat_message_attachments": [],
            "funnel_view_snapshots": [],
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
    app.include_router(dashboard_funnel.router)
    app.include_router(dashboard_funnel.coach_stream_router)
    app.dependency_overrides[dashboard_funnel.get_current_user] = lambda: current_user
    stub = _StubClient()
    monkeypatch.setattr(dashboard_common, "get_client", lambda: stub)
    return TestClient(app), stub


def test_dashboard_funnel_routes_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_app(
        monkeypatch,
        UserState(id="user-1", credits=10, isAdmin=False),
    )

    response = client.get("/dashboard/funnel/funnels")

    assert response.status_code == 403


def test_dashboard_funnel_create_assign_and_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )
    stub.tables["campaigns"] = [
        {"id": "cmp-1", "name": "Launch", "status": "ACTIVE", "objective": "OUTCOME_APP_PROMOTION"}
    ]
    stub.tables["ads"] = [
        {
            "id": "ad-1",
            "campaign_id": "cmp-1",
            "spend": "12.00",
            "impressions": 1000,
            "reach": 800,
            "results": 15,
            "landing_page_views": 40,
            "engagements": 22,
            "conversions": 9,
        }
    ]

    create_response = client.post("/dashboard/funnel/funnels", json={"name": "App Launch"})
    assert create_response.status_code == 201
    funnel_id = create_response.json()["funnel"]["id"]
    stages = create_response.json()["stages"]
    awareness_id = next(row["id"] for row in stages if row["stage"] == "awareness")

    assign_response = client.post(
        "/dashboard/funnel/assign-campaign",
        json={"funnelId": funnel_id, "funnelStageId": awareness_id, "campaignId": "cmp-1"},
    )
    assert assign_response.status_code == 200

    detail_response = client.get(f"/dashboard/funnel/funnels/{funnel_id}/with-stages")
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["totalCampaigns"] == 1
    assert body["stages"][0]["campaigns"][0]["id"] == "cmp-1"


@pytest.mark.parametrize(
    "created_at",
    [
        "2026-05-01T08:00:00+00:00",
        "2026-05-01T08:00:00",
        datetime(2026, 5, 1, 8, 0, 0),
        datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc),
        None,
    ],
)
def test_dashboard_funnel_detail_normalizes_stage_created_at(
    monkeypatch: pytest.MonkeyPatch,
    created_at: object,
) -> None:
    client, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )
    stub.tables["funnels"] = [
        {"id": "funnel-1", "name": "App Launch", "status": "active", "created_at": "2026-05-01T08:00:00+00:00"}
    ]
    stub.tables["funnel_stages"] = [
        {
            "id": "stage-1",
            "funnel_id": "funnel-1",
            "stage": "awareness",
            "display_order": 1,
            "status": "in_progress",
            "threshold_metric": "reach",
            "threshold_target": 100,
            "created_at": created_at,
        }
    ]

    response = client.get("/dashboard/funnel/funnels/funnel-1/with-stages")

    assert response.status_code == 200
    body = response.json()
    assert body["stages"][0]["ageDays"] >= 0


def test_dashboard_funnel_session_and_coach_message(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )
    stub.tables["funnels"] = [
        {"id": "funnel-1", "name": "App Launch", "status": "active", "created_at": "2026-05-01T08:00:00+00:00"}
    ]
    stub.tables["funnel_stages"] = [
        {
            "id": "stage-1",
            "funnel_id": "funnel-1",
            "stage": "awareness",
            "display_order": 1,
            "status": "in_progress",
            "threshold_metric": "reach",
            "threshold_target": 100,
            "created_at": "2026-05-01T08:00:00+00:00",
        }
    ]

    async def _fake_generate(_funnel_id: str, _stage: str, _message: str) -> dict[str, Any]:
        return {
            "reply": "We should tighten the audience.",
            "suggestedPanelUpdate": {"step": 1, "data": {"gender": "female"}},
            "stepReady": False,
            "tokenUsage": {"input": 100, "output": 50, "cacheRead": 0, "cacheCreation": 0},
            "costUsd": 0.01,
        }

    monkeypatch.setattr(dashboard_funnel, "_generate_coach_response", _fake_generate)

    session_response = client.get("/dashboard/funnel/stage-session", params={"funnelId": "funnel-1", "stage": "awareness"})
    assert session_response.status_code == 200
    session_id = session_response.json()["session"]["id"]

    message_response = client.post(
        "/dashboard/funnel/coach-message",
        json={"sessionId": session_id, "message": "What should we change?"},
    )
    assert message_response.status_code == 200
    assert message_response.json()["assistantMessage"]["content"] == "We should tighten the audience."

    accept_response = client.post(
        "/dashboard/funnel/panel-update/accept",
        json={
            "sessionId": session_id,
            "step": 1,
            "data": {"gender": "female"},
            "summary": "Accepted targeting update",
        },
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["step_states"]["1"]["gender"] == "female"


def test_dashboard_coach_stream_returns_sse_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
    )
    stub.tables["funnels"] = [{"id": "funnel-1", "name": "App Launch", "status": "active"}]
    stub.tables["funnel_stages"] = [
        {
            "id": "stage-1",
            "funnel_id": "funnel-1",
            "stage": "awareness",
            "display_order": 1,
            "status": "in_progress",
            "threshold_metric": "reach",
            "threshold_target": 100,
            "created_at": "2026-05-01T08:00:00+00:00",
        }
    ]
    stub.tables["funnel_stage_sessions"] = [
        {"id": "session-1", "funnel_id": "funnel-1", "stage": "awareness", "current_step": 1}
    ]

    async def _fake_generate(_funnel_id: str, _stage: str, _message: str) -> dict[str, Any]:
        return {
            "reply": "Streamed reply.",
            "suggestedPanelUpdate": None,
            "stepReady": False,
            "tokenUsage": {"input": 10, "output": 5, "cacheRead": 0, "cacheCreation": 0},
            "costUsd": 0.0,
        }

    monkeypatch.setattr(dashboard_funnel, "_generate_coach_response", _fake_generate)

    response = client.post("/api/coach/stream", json={"sessionId": "session-1", "message": "Hi"})

    assert response.status_code == 200
    assert "data:" in response.text
    assert "Streamed reply." in response.text
