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

from server import dashboard_common, dashboard_email_public


class _StubTable:
    def __init__(self, client: "_StubClient", name: str) -> None:
        self.client = client
        self.name = name
        self.filters: list[tuple[str, str, Any]] = []
        self.limit_value: int | None = None
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
        if self.limit_value is not None:
            data = data[: self.limit_value]
        return SimpleNamespace(data=data)


class _StubClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "email_campaign_recipients": [],
            "email_contacts": [],
            "email_link_clicks": [],
            "email_opens": [],
            "email_unsubscribes": [],
            "email_votes": [],
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


def _build_app(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _StubClient]:
    app = FastAPI()
    app.include_router(dashboard_email_public.router)
    stub = _StubClient()
    monkeypatch.setattr(dashboard_common, "get_client", lambda: stub)
    monkeypatch.setattr(dashboard_email_public, "dashboard_table", stub.table)
    return TestClient(app), stub


def test_click_route_records_click_and_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch)
    stub.tables["email_campaign_recipients"] = [
        {
            "id": "recipient-1",
            "campaign_id": "campaign-1",
            "contact_id": "contact-1",
            "send_token": "token-1",
            "click_count": 0,
            "first_click_at": None,
            "status": "sent",
        }
    ]

    response = client.get(
        "/api/email/click",
        params={"t": "token-1", "u": "https://example.com/shop", "l": "Shop now"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/shop"
    assert stub.tables["email_link_clicks"][0]["send_token"] == "token-1"
    assert stub.tables["email_campaign_recipients"][0]["click_count"] == 1
    assert stub.tables["email_campaign_recipients"][0]["status"] == "clicked"


def test_click_route_blocks_unsafe_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch)
    stub.tables["email_campaign_recipients"] = [
        {"id": "recipient-1", "campaign_id": "campaign-1", "contact_id": "contact-1", "send_token": "token-1"}
    ]

    response = client.get(
        "/api/email/click",
        params={"t": "token-1", "u": "javascript:alert(1)"},
        follow_redirects=False,
    )

    assert response.status_code == 404


def test_open_route_records_open_and_returns_pixel(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch)
    stub.tables["email_campaign_recipients"] = [
        {
            "id": "recipient-1",
            "campaign_id": "campaign-1",
            "contact_id": "contact-1",
            "send_token": "token-1",
            "opened_at": None,
            "status": "sent",
        }
    ]

    response = client.get("/api/email/open", params={"t": "token-1"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/gif")
    assert stub.tables["email_opens"][0]["send_token"] == "token-1"
    assert stub.tables["email_campaign_recipients"][0]["status"] == "opened"
    assert stub.tables["email_campaign_recipients"][0]["opened_at"]


def test_vote_route_replaces_existing_vote(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch)
    stub.tables["email_campaign_recipients"] = [
        {"id": "recipient-1", "campaign_id": "campaign-1", "contact_id": "contact-1", "send_token": "token-1"}
    ]
    stub.tables["email_votes"] = [
        {
            "id": "vote-1",
            "campaign_id": "campaign-1",
            "send_token": "token-1",
            "vote_block_id": "block-1",
            "option_id": "old-option",
        }
    ]

    response = client.get("/api/email/vote", params={"t": "token-1", "b": "block-1", "o": "new-option"})

    assert response.status_code == 200
    assert "Thanks for voting." in response.text
    assert len(stub.tables["email_votes"]) == 1
    assert stub.tables["email_votes"][0]["option_id"] == "new-option"


def test_unsubscribe_route_records_opt_out_and_renders_email(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch)
    stub.tables["email_campaign_recipients"] = [
        {"id": "recipient-1", "campaign_id": "campaign-1", "contact_id": "contact-1", "send_token": "token-1"}
    ]
    stub.tables["email_contacts"] = [{"id": "contact-1", "email": "hello@example.com"}]

    response = client.get("/api/email/unsubscribe", params={"t": "token-1"})

    assert response.status_code == 200
    assert "hello@example.com will no longer receive marketing email from Gemzy." in response.text
    assert stub.tables["email_unsubscribes"][0]["contact_id"] == "contact-1"
