from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import notifications
from server.schemas import UserState


class _StubTable:
    def __init__(
        self,
        name: str,
        tables: dict[str, list[dict[str, Any]]],
        operations: dict[str, dict[str, list[dict[str, Any]]]],
    ) -> None:
        self.name = name
        self.tables = tables
        self.operations = operations
        self.filters: list[tuple[str, str, Any]] = []
        self.pending_update: dict[str, Any] | None = None

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self.tables.setdefault(self.name, [])

    def select(self, *_args: Any, **_kwargs: Any) -> "_StubTable":
        return self

    def eq(self, column: str, value: Any) -> "_StubTable":
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> "_StubTable":
        self.filters.append(("in", column, list(values)))
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> "_StubTable":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_StubTable":
        return self

    def insert(self, payload: dict[str, Any] | list[dict[str, Any]]) -> "_StubTable":
        rows = payload if isinstance(payload, list) else [payload]
        copies = [copy.deepcopy(row) for row in rows]
        self.operations.setdefault(self.name, {}).setdefault("inserted", []).extend(copies)
        self.rows.extend(copies)
        return self

    def upsert(self, payload: dict[str, Any], *, on_conflict: str) -> "_StubTable":
        row = copy.deepcopy(payload)
        self.operations.setdefault(self.name, {}).setdefault("upserted", []).append(row)
        keys = [part.strip() for part in on_conflict.split(",")]
        existing = next(
            (
                item
                for item in self.rows
                if all(item.get(key) == row.get(key) for key in keys)
            ),
            None,
        )
        if existing is None:
            self.rows.append(row)
        else:
            existing.update(row)
        return self

    def update(self, payload: dict[str, Any]) -> "_StubTable":
        self.pending_update = copy.deepcopy(payload)
        return self

    def execute(self) -> SimpleNamespace:
        data = list(self.rows)
        for op, column, value in self.filters:
            if op == "eq":
                data = [row for row in data if row.get(column) == value]
            elif op == "in":
                allowed = set(value)
                data = [row for row in data if row.get(column) in allowed]

        if self.pending_update is not None:
            self.operations.setdefault(self.name, {}).setdefault("updated", []).append(
                copy.deepcopy(self.pending_update)
            )
            for row in data:
                row.update(copy.deepcopy(self.pending_update))

        return SimpleNamespace(data=copy.deepcopy(data))


class _StubClient:
    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self.tables = {
            name: [copy.deepcopy(row) for row in rows]
            for name, rows in tables.items()
        }
        self.operations: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def table(self, name: str) -> _StubTable:
        return _StubTable(name, self.tables, self.operations)


def _build_app(
    monkeypatch: pytest.MonkeyPatch,
    current_user: UserState,
    *,
    app_notifications: list[dict[str, Any]] | None = None,
    push_tokens: list[dict[str, Any]] | None = None,
    profiles: list[dict[str, Any]] | None = None,
) -> tuple[FastAPI, _StubClient]:
    app = FastAPI()
    app.include_router(notifications.router)
    app.dependency_overrides[notifications.get_current_user] = lambda: current_user
    stub = _StubClient(
        {
            "app_notifications": app_notifications or [],
            "push_tokens": push_tokens or [],
            "push_notification_logs": [],
            "profiles": profiles or [],
        }
    )
    monkeypatch.setattr(notifications, "get_client", lambda: stub)
    return app, stub


def test_list_notifications_filters_expired_and_other_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = _build_app(
        monkeypatch,
        UserState(id="user-1", credits=10, isAdmin=False),
        app_notifications=[
            {
                "id": "general-1",
                "entity_key": "general:1",
                "category": "general",
                "kind": "new_feature",
                "title": "New feature!",
                "body": "Try it now",
                "created_at": "2026-04-12T08:00:00+00:00",
                "is_active": True,
            },
            {
                "id": "personal-1",
                "entity_key": "personal:1",
                "category": "personal",
                "target_user_id": "user-1",
                "kind": "subscription_payment_failed",
                "title": "Payment failed",
                "body": "Please retry",
                "created_at": "2026-04-12T09:00:00+00:00",
                "is_active": True,
            },
            {
                "id": "personal-2",
                "entity_key": "personal:2",
                "category": "personal",
                "target_user_id": "someone-else",
                "kind": "subscription_payment_failed",
                "title": "Payment failed",
                "body": "Should not be visible",
                "created_at": "2026-04-12T09:00:00+00:00",
                "is_active": True,
            },
            {
                "id": "expired-1",
                "entity_key": "expired:1",
                "category": "general",
                "kind": "maintenance",
                "title": "Expired",
                "body": "Old notice",
                "created_at": "2026-04-10T09:00:00+00:00",
                "expires_at": "2026-04-11T09:00:00+00:00",
                "is_active": True,
            },
        ],
    )

    client = TestClient(app)
    response = client.get("/notifications")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["general-1", "personal-1"]


def test_publish_notification_requires_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = _build_app(monkeypatch, UserState(id="user-1", credits=10, isAdmin=False))

    client = TestClient(app)
    response = client.post(
        "/notifications",
        json={
            "category": "general",
            "kind": "new_feature",
            "title": "New feature!",
            "body": "Try it now",
        },
    )

    assert response.status_code == 403


def test_register_push_token_upserts_backend_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, stub = _build_app(
        monkeypatch,
        UserState(id="user-1", credits=10, isAdmin=False),
        push_tokens=[
            {
                "token": "ExpoPushToken[existing]",
                "user_id": "someone-else",
                "platform": "android",
                "is_active": True,
            }
        ],
    )

    client = TestClient(app)
    response = client.post(
        "/notifications/push-tokens",
        json={
            "token": "ExpoPushToken[existing]",
            "platform": "ios",
            "appVersion": "0.0.9",
        },
    )

    assert response.status_code == 204
    assert stub.tables["push_tokens"][0]["user_id"] == "user-1"
    assert stub.tables["push_tokens"][0]["platform"] == "ios"
    assert stub.tables["push_tokens"][0]["app_version"] == "0.0.9"


def test_publish_notification_inserts_backend_row_and_sends_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
        push_tokens=[
            {
                "token": "ExpoPushToken[user-1]",
                "user_id": "user-1",
                "platform": "ios",
                "is_active": True,
            },
            {
                "token": "ExpoPushToken[user-2]",
                "user_id": "user-2",
                "platform": "android",
                "is_active": True,
            },
        ],
        profiles=[
            {
                "id": "user-1",
                "notification_preferences": {
                    "gemzyUpdates": True,
                    "personalUpdates": True,
                    "email": True,
                },
            },
            {
                "id": "user-2",
                "notification_preferences": {
                    "gemzyUpdates": False,
                    "personalUpdates": True,
                    "email": True,
                },
            },
        ],
    )
    sent_messages: list[dict[str, Any]] = []
    monkeypatch.setattr(
        notifications,
        "_send_expo_push_messages",
        lambda dispatches, *, notification_id: sent_messages.extend(
            [dispatch["message"] for dispatch in dispatches]
        ),
    )

    client = TestClient(app)
    response = client.post(
        "/notifications",
        json={
            "entityKey": "announcement:new-presets:on-model",
            "category": "general",
            "kind": "new_presets",
            "title": "New presets!",
            "body": "New presets are available in On Model",
            "action": {
                "pathname": "/on-model",
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["entityKey"] == "announcement:new-presets:on-model"
    assert payload["kind"] == "new_presets"
    assert stub.operations["app_notifications"]["inserted"][0]["published_by"] == "admin-1"
    assert stub.operations["app_notifications"]["inserted"][0]["action_pathname"] == "/on-model"
    assert [message["to"] for message in sent_messages] == ["ExpoPushToken[user-1]"]
    assert sent_messages[0]["channelId"] == "gemzy-general-v2"
    assert sent_messages[0]["data"]["pathname"] == "/on-model"


def test_publish_app_notification_deduplicates_same_generation_entity_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
        push_tokens=[
            {
                "token": "ExpoPushToken[user-1]",
                "user_id": "user-1",
                "platform": "ios",
                "is_active": True,
            }
        ],
        profiles=[
            {
                "id": "user-1",
                "notification_preferences": {
                    "gemzyUpdates": True,
                    "personalUpdates": True,
                    "email": True,
                },
            }
        ],
    )
    sent_dispatch_batches: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(
        notifications,
        "_send_expo_push_messages",
        lambda dispatches, *, notification_id: sent_dispatch_batches.append(
            [copy.deepcopy(dispatch) for dispatch in dispatches]
        ),
    )

    first = notifications.publish_app_notification(
        category="personal",
        kind="generation_completed",
        title="Generation completed",
        body="Tap to view your new looks",
        entity_key="generation:job-123",
        target_user_id="user-1",
        action={
            "pathname": "/generating",
            "params": {"jobId": "job-123"},
        },
    )
    stub.tables["push_notification_logs"].append(
        {
            "notification_id": first.id,
            "status": "accepted",
            "push_token": "ExpoPushToken[user-1]",
            "user_id": "user-1",
        }
    )
    second = notifications.publish_app_notification(
        category="personal",
        kind="generation_completed",
        title="Generation completed",
        body="Tap to view your new looks",
        entity_key="generation:job-123",
        target_user_id="user-1",
        action={
            "pathname": "/generating",
            "params": {"jobId": "job-123"},
        },
    )

    assert first.id == second.id
    assert len(stub.operations["app_notifications"]["inserted"]) == 1
    assert len(sent_dispatch_batches) == 1
    assert sent_dispatch_batches[0][0]["message"]["data"]["entityKey"] == "generation:job-123"


def test_publish_app_notification_retries_existing_entity_key_without_accepted_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
        push_tokens=[
            {
                "token": "ExpoPushToken[user-1]",
                "user_id": "user-1",
                "platform": "ios",
                "is_active": True,
            }
        ],
        profiles=[
            {
                "id": "user-1",
                "notification_preferences": {
                    "gemzyUpdates": True,
                    "personalUpdates": True,
                    "email": True,
                },
            }
        ],
    )
    sent_dispatch_batches: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(
        notifications,
        "_send_expo_push_messages",
        lambda dispatches, *, notification_id: sent_dispatch_batches.append(
            [copy.deepcopy(dispatch) for dispatch in dispatches]
        ),
    )

    first = notifications.publish_app_notification(
        category="personal",
        kind="generation_completed",
        title="Generation completed",
        body="Tap to view your new looks",
        entity_key="generation:job-123",
        target_user_id="user-1",
        action={
            "pathname": "/generating",
            "params": {"jobId": "job-123"},
        },
    )
    second = notifications.publish_app_notification(
        category="personal",
        kind="generation_completed",
        title="Generation completed",
        body="Tap to view your new looks",
        entity_key="generation:job-123",
        target_user_id="user-1",
        action={
            "pathname": "/generating",
            "params": {"jobId": "job-123"},
        },
    )

    assert first.id == second.id
    assert len(stub.operations["app_notifications"]["inserted"]) == 1
    assert len(sent_dispatch_batches) == 2
    assert sent_dispatch_batches[1][0]["message"]["data"]["entityKey"] == "generation:job-123"


def test_publish_notification_deactivates_invalid_stored_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
        push_tokens=[
            {
                "token": "not-a-valid-token",
                "user_id": "user-1",
                "platform": "ios",
                "is_active": True,
            }
        ],
        profiles=[
            {
                "id": "user-1",
                "notification_preferences": {
                    "gemzyUpdates": True,
                    "personalUpdates": True,
                    "email": True,
                },
            }
        ],
    )
    monkeypatch.setattr(
        notifications,
        "_send_expo_push_messages",
        lambda dispatches, *, notification_id: pytest.fail("send should not be called"),
    )

    client = TestClient(app)
    response = client.post(
        "/notifications",
        json={
            "category": "general",
            "kind": "new_feature",
            "title": "New feature!",
            "body": "Try it now",
        },
    )

    assert response.status_code == 201
    assert stub.tables["push_tokens"][0]["is_active"] is False


def test_send_expo_push_messages_logs_ticket_errors_and_deactivates_exact_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, stub = _build_app(
        monkeypatch,
        UserState(id="admin-1", credits=10, isAdmin=True),
        push_tokens=[
            {
                "token": "ExpoPushToken[stale-token]",
                "user_id": "user-1",
                "platform": "ios",
                "is_active": True,
            },
            {
                "token": "ExpoPushToken[fresh-token]",
                "user_id": "user-1",
                "platform": "ios",
                "is_active": True,
            },
        ],
    )

    class _FakeHttpxClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_FakeHttpxClient":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def post(self, *_args: Any, **_kwargs: Any) -> Any:
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "data": [
                        {
                            "status": "error",
                            "message": "The recipient device is not registered",
                            "details": {"error": "DeviceNotRegistered"},
                        },
                        {
                            "status": "ok",
                            "id": "ticket-2",
                        },
                    ]
                },
            )

    monkeypatch.setattr(notifications.httpx, "Client", _FakeHttpxClient)

    notifications._send_expo_push_messages(
        [
            {
                "target": {"token": "ExpoPushToken[stale-token]", "user_id": "user-1"},
                "message": {"to": "ExpoPushToken[stale-token]", "title": "One", "body": "Body"},
            },
            {
                "target": {"token": "ExpoPushToken[fresh-token]", "user_id": "user-1"},
                "message": {"to": "ExpoPushToken[fresh-token]", "title": "Two", "body": "Body"},
            },
        ],
        notification_id="notification-1",
    )

    assert stub.tables["push_tokens"][0]["is_active"] is False
    assert stub.tables["push_tokens"][1]["is_active"] is True
    assert [row["status"] for row in stub.tables["push_notification_logs"]] == ["failed", "accepted"]
    assert stub.tables["push_notification_logs"][0]["error_code"] == "DeviceNotRegistered"
    assert stub.tables["push_notification_logs"][1]["ticket_id"] == "ticket-2"
