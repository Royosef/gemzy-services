from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from server import payments


class _Request:
    def __init__(self, payload: dict, headers: dict | None = None):
        self._payload = payload
        self.headers = headers or {}

    async def json(self) -> dict:
        return self._payload


class _FakeTable:
    def __init__(self, client, name: str):
        self._client = client
        self._name = name
        self._operation = None
        self._filters: list[tuple[str, object]] = []

    def select(self, *_args, **_kwargs):
        return self

    def update(self, data):
        self._operation = ("update", data)
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self._operation is None:
            data = self._client.table_data.get(self._name, [])
            return SimpleNamespace(data=data)

        self._client.calls.append(
            {
                "table": self._name,
                "operation": self._operation,
                "filters": list(self._filters),
            }
        )
        return SimpleNamespace(data=[])


class _FakeClient:
    def __init__(self, table_data: dict[str, object]):
        self.table_data = table_data
        self.calls: list[dict] = []

    def table(self, name: str):
        return _FakeTable(self, name)


def test_expiration_event_downgrades_even_when_stored_expiry_is_later(monkeypatch):
    past_expiration_ms = int(datetime(2026, 4, 14, 17, 51, tzinfo=timezone.utc).timestamp() * 1000)
    fake_client = _FakeClient(
        {
            "profiles": [
                {
                    "plan": "Designer",
                    "credits": 500,
                    "rc_last_event_ms": None,
                    "subscription_expires_at": "2026-05-04T20:56:00+00:00",
                }
            ]
        }
    )

    monkeypatch.setattr(payments, "get_client", lambda: fake_client)
    monkeypatch.setattr(payments, "get_plan_initial_credits", lambda plan: 10 if plan == "Free" else 500)

    request = _Request(
        {
            "event": {
                "type": "EXPIRATION",
                "app_user_id": "user-1",
                "product_id": "gemzy_designer_monthly",
                "expiration_at_ms": past_expiration_ms,
                "event_timestamp_ms": past_expiration_ms,
            }
        }
    )

    result = asyncio.run(payments.rc_webhook(request))

    assert result == {"status": "ok"}
    assert fake_client.calls == [
        {
            "table": "profiles",
            "operation": (
                "update",
                {
                    "rc_last_event_ms": past_expiration_ms,
                    "subscription_expires_at": "2026-04-14T17:51:00+00:00",
                    "plan": "Free",
                    "credits": 10,
                },
            ),
            "filters": [("id", "user-1")],
        }
    ]
