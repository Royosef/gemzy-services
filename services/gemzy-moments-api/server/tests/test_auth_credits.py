from __future__ import annotations

from types import SimpleNamespace

from server import auth


class _FakeTable:
    def __init__(self, client, name: str):
        self._client = client
        self._name = name
        self._operation = None
        self._filters: list[tuple[str, object]] = []

    def update(self, data):
        self._operation = ("update", data)
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def execute(self):
        self._client.calls.append(
            {
                "table": self._name,
                "operation": self._operation,
                "filters": list(self._filters),
            }
        )
        return SimpleNamespace(data=[])


class _FakeClient:
    def __init__(self):
        self.calls: list[dict] = []

    def table(self, name: str):
        return _FakeTable(self, name)


def test_ensure_monthly_credits_downgrades_expired_paid_plan(monkeypatch):
    fake_client = _FakeClient()
    metadata_updates: list[dict] = []

    monkeypatch.setattr(auth, "get_client", lambda: fake_client)
    monkeypatch.setattr(auth, "get_plan_initial_credits", lambda plan: 5 if plan == "Free" else 500)
    monkeypatch.setattr(
        auth,
        "update_user_metadata",
        lambda _user_id, metadata, client=None: metadata_updates.append(dict(metadata)),
    )

    profile, metadata = auth._ensure_monthly_credits(
        "user-1",
        "Designer",
        {
            "plan": "Designer",
            "credits": 500,
            "subscription_expires_at": "2026-04-14T17:51:00+00:00",
        },
        {
            "plan": "Designer",
            "credits": 500,
            "creditsRenewedAt": "2026-04-01T00:00:00+00:00",
        },
    )

    assert profile["plan"] == "Free"
    assert profile["credits"] == 5
    assert metadata["plan"] == "Free"
    assert metadata["plan_tier"] == "Free"
    assert metadata["credits"] == 5
    assert fake_client.calls == [
        {
            "table": "profiles",
            "operation": ("update", {"plan": "Free", "credits": 5}),
            "filters": [("id", "user-1")],
        }
    ]
    assert metadata_updates
    assert metadata_updates[0]["plan"] == "Free"
    assert metadata_updates[0]["credits"] == 5
