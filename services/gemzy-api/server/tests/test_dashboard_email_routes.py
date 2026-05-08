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

from server import dashboard_common, dashboard_email
from server.schemas import UserState


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
            "email_contacts": [],
            "email_groups": [],
            "email_group_members": [],
            "email_unsubscribes": [],
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
    app.include_router(dashboard_email.router)
    app.dependency_overrides[dashboard_email.get_current_user] = lambda: current_user
    stub = _StubClient()
    monkeypatch.setattr(dashboard_common, "get_client", lambda: stub)
    monkeypatch.setattr(dashboard_email, "dashboard_table", stub.table)
    return TestClient(app), stub


def test_dashboard_email_routes_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_app(monkeypatch, UserState(id="user-1", credits=0, isAdmin=False))

    response = client.get("/dashboard/email/stats")

    assert response.status_code == 403


def test_dashboard_email_stats_and_contacts_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch, UserState(id="admin-1", credits=0, isAdmin=True))
    stub.tables["email_groups"] = [
        {
            "id": "group-1",
            "name": "VIP",
            "description": "Top customers",
            "is_auto_managed": False,
            "auto_managed_key": None,
            "created_at": "2026-05-01T08:00:00+00:00",
            "updated_at": "2026-05-01T08:00:00+00:00",
        }
    ]
    stub.tables["email_contacts"] = [
        {
            "id": "contact-1",
            "email": "ada@example.com",
            "name": "Ada",
            "tags": ["vip"],
            "source": "manual",
            "created_at": "2026-05-01T08:00:00+00:00",
            "updated_at": "2026-05-01T08:00:00+00:00",
        }
    ]
    stub.tables["email_group_members"] = [{"group_id": "group-1", "contact_id": "contact-1"}]

    stats_response = client.get("/dashboard/email/stats")
    list_response = client.get("/dashboard/email/contacts")
    detail_response = client.get("/dashboard/email/contacts/contact-1")

    assert stats_response.status_code == 200
    assert stats_response.json()["totalContacts"] == 1
    assert list_response.status_code == 200
    assert list_response.json()["rows"][0]["groups"][0]["name"] == "VIP"
    assert detail_response.status_code == 200
    assert detail_response.json()["email"] == "ada@example.com"


def test_dashboard_email_create_update_and_delete_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch, UserState(id="admin-1", credits=0, isAdmin=True))
    stub.tables["email_groups"] = [
        {
            "id": "group-1",
            "name": "VIP",
            "description": None,
            "is_auto_managed": False,
            "auto_managed_key": None,
            "created_at": "2026-05-01T08:00:00+00:00",
            "updated_at": "2026-05-01T08:00:00+00:00",
        }
    ]

    create_response = client.post(
        "/dashboard/email/contacts",
        json={
            "email": "new@example.com",
            "name": "New Person",
            "groupIds": ["group-1"],
            "tags": ["vip", "vip", "beta"],
        },
    )
    assert create_response.status_code == 201
    contact_id = create_response.json()["id"]

    update_response = client.patch(
        f"/dashboard/email/contacts/{contact_id}",
        json={"name": "Updated Person", "tags": ["gold"]},
    )
    assert update_response.status_code == 200

    contact = next(row for row in stub.tables["email_contacts"] if row["id"] == contact_id)
    assert contact["name"] == "Updated Person"
    assert contact["tags"] == ["gold"]
    assert stub.tables["email_group_members"][0]["group_id"] == "group-1"

    delete_response = client.delete(f"/dashboard/email/contacts/{contact_id}")
    assert delete_response.status_code == 200
    assert stub.tables["email_contacts"] == []
    assert stub.tables["email_group_members"] == []


def test_dashboard_email_groups_and_memberships(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch, UserState(id="admin-1", credits=0, isAdmin=True))
    stub.tables["email_contacts"] = [
        {
            "id": "contact-1",
            "email": "a@example.com",
            "name": "A",
            "tags": [],
            "source": "manual",
            "created_at": "2026-05-01T08:00:00+00:00",
            "updated_at": "2026-05-01T08:00:00+00:00",
        },
        {
            "id": "contact-2",
            "email": "b@example.com",
            "name": "B",
            "tags": [],
            "source": "manual",
            "created_at": "2026-05-02T08:00:00+00:00",
            "updated_at": "2026-05-02T08:00:00+00:00",
        },
    ]
    stub.tables["email_groups"] = [
        {
            "id": "group-1",
            "name": "Newsletter",
            "description": None,
            "is_auto_managed": False,
            "auto_managed_key": None,
            "created_at": "2026-05-01T08:00:00+00:00",
            "updated_at": "2026-05-01T08:00:00+00:00",
        },
        {
            "id": "group-2",
            "name": "Unsubscribed",
            "description": None,
            "is_auto_managed": True,
            "auto_managed_key": "unsubscribed",
            "created_at": "2026-05-01T08:00:00+00:00",
            "updated_at": "2026-05-01T08:00:00+00:00",
        },
    ]
    stub.tables["email_unsubscribes"] = [{"contact_id": "contact-2"}]

    add_response = client.post(
        "/dashboard/email/groups/group-1/members",
        json={"contactIds": ["contact-1"]},
    )
    assert add_response.status_code == 200

    groups_response = client.get("/dashboard/email/groups")
    detail_response = client.get("/dashboard/email/groups/group-1/contacts")
    unsubscribed_response = client.get("/dashboard/email/groups/group-2/contacts")
    addable_response = client.get("/dashboard/email/groups/group-1/addable-contacts")

    assert groups_response.status_code == 200
    assert groups_response.json()[0]["memberCount"] == 1
    assert detail_response.json()["rows"][0]["email"] == "a@example.com"
    assert unsubscribed_response.json()["rows"][0]["email"] == "b@example.com"
    assert addable_response.json()["rows"][0]["id"] == "contact-2"

    remove_response = client.request(
        "DELETE",
        "/dashboard/email/groups/group-1/members",
        json={"contactIds": ["contact-1"]},
    )
    assert remove_response.status_code == 200
    assert stub.tables["email_group_members"] == []


def test_dashboard_email_import_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch, UserState(id="admin-1", credits=0, isAdmin=True))
    stub.tables["email_groups"] = [
        {
            "id": "group-1",
            "name": "Imported",
            "description": None,
            "is_auto_managed": False,
            "auto_managed_key": None,
            "created_at": "2026-05-01T08:00:00+00:00",
            "updated_at": "2026-05-01T08:00:00+00:00",
        }
    ]
    stub.tables["email_contacts"] = [
        {
            "id": "existing-1",
            "email": "existing@example.com",
            "name": "Existing",
            "tags": [],
            "source": "manual",
            "created_at": "2026-05-01T08:00:00+00:00",
            "updated_at": "2026-05-01T08:00:00+00:00",
        }
    ]

    response = client.post(
        "/dashboard/email/import",
        json={
            "csv": "Email,Name\nnew@example.com,New\nexisting@example.com,Existing\nbad-email,Bad\nnew@example.com,Duplicate\n",
            "source": "csv_import",
            "groupIds": ["group-1"],
            "tags": ["vip"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["added"] == 1
    assert body["skippedExistingInDb"] == 1
    assert body["skippedDuplicateInFile"] == 1
    assert body["invalid"] == 0
    imported = next(row for row in stub.tables["email_contacts"] if row["email"] == "new@example.com")
    assert imported["tags"] == ["vip"]
    assert any(row["contact_id"] == imported["id"] for row in stub.tables["email_group_members"])
