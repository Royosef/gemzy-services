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

from server import dashboard_common, dashboard_email_advanced, dashboard_email_public, dashboard_webhooks
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
            "email_templates": [],
            "email_signatures": [],
            "email_send_log": [],
            "email_campaigns": [],
            "email_campaign_recipients": [],
            "email_link_clicks": [],
            "email_opens": [],
            "email_votes": [],
            "email_triggers": [],
            "email_trigger_sends": [],
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
    app.include_router(dashboard_email_advanced.router)
    app.include_router(dashboard_email_public.router)
    app.include_router(dashboard_webhooks.router)
    app.dependency_overrides[dashboard_email_advanced.get_current_user] = lambda: current_user
    stub = _StubClient()
    def _delete_where_stub(table_name: str, **filters: Any) -> None:
        rows = stub.tables.setdefault(table_name, [])
        stub.tables[table_name] = [
            row
            for row in rows
            if not all(row.get(key) == value for key, value in filters.items())
        ]

    monkeypatch.setattr(dashboard_common, "get_client", lambda: stub)
    monkeypatch.setattr(dashboard_email_advanced, "_load_rows", lambda table_name: stub.tables.setdefault(table_name, []))
    monkeypatch.setattr(dashboard_email_advanced, "_find_first", lambda table_name, **filters: next((row for row in stub.tables.setdefault(table_name, []) if all(row.get(k) == v for k, v in filters.items())), None))
    monkeypatch.setattr(dashboard_email_advanced, "_find_all", lambda table_name, **filters: [row for row in stub.tables.setdefault(table_name, []) if all(row.get(k) == v for k, v in filters.items())])
    monkeypatch.setattr(dashboard_email_advanced, "_insert_row", lambda table_name, payload: stub.tables.setdefault(table_name, []).append(copy.deepcopy(payload)) or payload)
    monkeypatch.setattr(dashboard_email_advanced, "_update_where", lambda table_name, patch, **filters: [row.update(copy.deepcopy(patch)) or row for row in stub.tables.setdefault(table_name, []) if all(row.get(k) == v for k, v in filters.items())])
    monkeypatch.setattr(dashboard_email_advanced, "_delete_where", _delete_where_stub)
    monkeypatch.setattr(dashboard_email_public, "dashboard_table", stub.table)
    monkeypatch.setattr(dashboard_webhooks, "ensure_contact", lambda email, source, name=None: _ensure_contact_stub(stub, email, source, name))
    return TestClient(app), stub


def _ensure_contact_stub(stub: _StubClient, email: str, source: str, name: str | None = None) -> str:
    normalized = email.strip().lower()
    existing = next((row for row in stub.tables["email_contacts"] if row.get("email") == normalized), None)
    if existing:
        return str(existing["id"])
    row = {
        "id": f"contact-{len(stub.tables['email_contacts']) + 1}",
        "email": normalized,
        "name": name,
        "source": source,
        "tags": [],
        "created_at": "2026-05-02T10:00:00+00:00",
        "updated_at": "2026-05-02T10:00:00+00:00",
    }
    stub.tables["email_contacts"].append(row)
    return str(row["id"])


def test_advanced_email_routes_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_app(monkeypatch, UserState(id="user-1", credits=0, isAdmin=False))
    response = client.get("/dashboard/email/templates")
    assert response.status_code == 403


def test_templates_signatures_and_send_test_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch, UserState(id="admin-1", credits=0, isAdmin=True))
    monkeypatch.setattr(dashboard_email_advanced, "is_smtp_configured", lambda: True)
    monkeypatch.setattr(
        dashboard_email_advanced,
        "send_email",
        lambda **_kwargs: {
            "success": True,
            "error": None,
            "smtpResponse": "ok",
            "isRateLimitError": False,
            "isPermanentError": False,
        },
    )
    monkeypatch.setattr(
        dashboard_email_advanced,
        "ai_rewrite_text",
        lambda **_kwargs: {"rewritten": "Sharper copy.", "tokenUsage": {"input": 1, "output": 1, "cacheRead": 0, "cacheCreation": 0}},
    )
    monkeypatch.setattr(
        dashboard_email_advanced,
        "upload_email_asset",
        lambda **_kwargs: {"storagePath": "email/test.png", "signedUrl": "https://signed.example/email/test.png"},
    )

    signature_response = client.post(
        "/dashboard/email/signatures",
        json={"name": "Team signature", "blocks": [{"id": "b1", "type": "text", "content": "Thanks"}], "isDefault": True},
    )
    assert signature_response.status_code == 201
    signature_id = signature_response.json()["id"]

    template_response = client.post(
        "/dashboard/email/templates",
        json={"name": "Welcome", "subject": "Hello {{name}}", "blocks": [{"id": "b1", "type": "text", "content": "Hi {{name}}"}], "signatureId": signature_id},
    )
    assert template_response.status_code == 201
    template_id = template_response.json()["id"]

    list_response = client.get("/dashboard/email/templates")
    assert list_response.status_code == 200
    assert list_response.json()["rows"][0]["name"] == "Welcome"

    duplicate_response = client.post(f"/dashboard/email/templates/{template_id}/duplicate")
    assert duplicate_response.status_code == 201

    rewrite_response = client.post(
        "/dashboard/email/ai-rewrite",
        json={"text": "Rewrite this", "context": {"intent": "rewrite"}},
    )
    assert rewrite_response.status_code == 200
    assert rewrite_response.json()["rewritten"] == "Sharper copy."

    upload_response = client.post(
        "/dashboard/email/upload-asset",
        json={"file": "aGVsbG8=", "fileName": "hero.png", "mimeType": "image/png", "fileSize": 5},
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["storagePath"] == "email/test.png"

    send_test_response = client.post(
        "/dashboard/email/send-test",
        json={"to": "test@example.com", "subject": "Preview", "html": "<p>hello</p>", "templateId": template_id},
    )
    assert send_test_response.status_code == 200
    assert send_test_response.json()["success"] is True
    assert len(stub.tables["email_send_log"]) == 1


def test_campaigns_and_triggers_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch, UserState(id="admin-1", credits=0, isAdmin=True))
    monkeypatch.setattr(dashboard_email_advanced, "start_campaign_send", lambda _campaign_id: None)
    monkeypatch.setattr(dashboard_email_advanced, "dispatch_trigger", lambda _event_type, _contact_id: {"triggersFired": 1, "emailsSent": 1, "duplicatesSkipped": 0, "failures": []})

    stub.tables["email_templates"] = [
        {
            "id": "tpl-1",
            "name": "Launch",
            "subject": "Launch",
            "preview_text": None,
            "blocks": [{"id": "b1", "type": "text", "content": "Body"}],
            "signature_id": None,
            "created_at": "2026-05-02T10:00:00+00:00",
            "updated_at": "2026-05-02T10:00:00+00:00",
        }
    ]
    stub.tables["email_groups"] = [{"id": "group-1", "name": "VIP"}]
    stub.tables["email_contacts"] = [
        {"id": "contact-1", "email": "ada@example.com", "name": "Ada", "source": "manual", "tags": [], "created_at": "2026-05-02T10:00:00+00:00", "updated_at": "2026-05-02T10:00:00+00:00"}
    ]
    stub.tables["email_group_members"] = [{"group_id": "group-1", "contact_id": "contact-1"}]

    campaign_response = client.post("/dashboard/email/campaigns", json={"name": "May launch", "templateId": "tpl-1"})
    assert campaign_response.status_code == 201
    campaign_id = campaign_response.json()["id"]

    recipients_response = client.post(
        "/dashboard/email/campaigns/recipients",
        json={"campaignId": campaign_id, "groupIds": ["group-1"], "contactIds": [], "excludeUnsubscribed": True},
    )
    assert recipients_response.status_code == 200
    assert recipients_response.json()["recipientCount"] == 1

    send_response = client.post("/dashboard/email/campaigns/send", json={"id": campaign_id, "scheduledAt": None})
    assert send_response.status_code == 200
    assert send_response.json()["scheduled"] is False

    mark_replied_response = client.post(
        "/dashboard/email/campaigns/mark-replied",
        json={"campaignId": campaign_id, "contactId": "contact-1"},
    )
    assert mark_replied_response.status_code == 200

    analytics_response = client.get(f"/dashboard/email/campaigns/{campaign_id}/analytics")
    assert analytics_response.status_code == 200
    assert analytics_response.json()["engagement"]["totalOpens"] == 0

    trigger_response = client.post(
        "/dashboard/email/triggers",
        json={"name": "Signup welcome", "description": "Send on signup", "eventType": "user_signup", "templateId": "tpl-1", "isActive": True},
    )
    assert trigger_response.status_code == 201
    trigger_id = trigger_response.json()["id"]

    trigger_list_response = client.get("/dashboard/email/triggers")
    assert trigger_list_response.status_code == 200
    assert trigger_list_response.json()[0]["name"] == "Signup welcome"

    test_trigger_response = client.post(
        "/dashboard/email/triggers/test",
        json={"triggerId": trigger_id, "toEmail": "new@example.com"},
    )
    assert test_trigger_response.status_code == 200
    assert test_trigger_response.json()["emailsSent"] == 1


def test_webhooks_require_secret_and_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _build_app(monkeypatch, UserState(id="admin-1", credits=0, isAdmin=True))
    monkeypatch.setenv("REVENUECAT_WEBHOOK_SECRET", "rc-secret")
    monkeypatch.setenv("AUTH_SIGNUP_WEBHOOK_SECRET", "signup-secret")
    monkeypatch.setattr(dashboard_webhooks, "handle_purchase_trigger", lambda contact_id: {"contactId": contact_id, "type": "purchase"})
    monkeypatch.setattr(dashboard_webhooks, "handle_cancellation_trigger", lambda contact_id: {"contactId": contact_id, "type": "cancel"})
    monkeypatch.setattr(dashboard_webhooks, "handle_signup_trigger", lambda contact_id: {"contactId": contact_id, "type": "signup"})

    unauthorized = client.post("/api/webhooks/auth-signup", json={"email": "user@example.com"})
    assert unauthorized.status_code == 401

    signup = client.post(
        "/api/webhooks/auth-signup",
        headers={"Authorization": "Bearer signup-secret"},
        json={"email": "user@example.com", "name": "User"},
    )
    assert signup.status_code == 200
    assert signup.json()["ok"] is True

    revenuecat = client.post(
        "/api/webhooks/revenuecat",
        headers={"Authorization": "Bearer rc-secret"},
        json={"event": {"type": "INITIAL_PURCHASE", "subscriber_attributes": {"$email": {"value": "buyer@example.com"}}}},
    )
    assert revenuecat.status_code == 200
    assert revenuecat.json()["ok"] is True
    assert len(stub.tables["email_contacts"]) >= 2
