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


def test_ensure_monthly_credits_initializes_missing_schedule_without_reset(
    monkeypatch,
):
    client = _FakeClient()

    monkeypatch.setattr(auth, "get_client", lambda: client)
    monkeypatch.setattr(auth, "get_plan_initial_credits", lambda *_: 40)

    profile = auth._ensure_monthly_credits(
        "user-1",
        "Free",
        {"credits": 7, "next_credit_reset_at": None},
    )

    assert profile["credits"] == 7

    update_call = client.calls[0]
    assert update_call["table"] == "profiles"
    assert update_call["operation"][1].keys() == {"next_credit_reset_at"}


def test_ensure_monthly_credits_resets_due_balance(
    monkeypatch,
):
    client = _FakeClient()

    monkeypatch.setattr(auth, "get_client", lambda: client)
    monkeypatch.setattr(auth, "get_plan_initial_credits", lambda *_: 40)

    profile = auth._ensure_monthly_credits(
        "user-1",
        "Free",
        {"credits": 7, "next_credit_reset_at": "2024-01-01T00:00:00Z"},
    )

    assert profile["credits"] == 40
    assert "next_credit_reset_at" in profile

    update_call = client.calls[0]
    assert update_call["table"] == "profiles"
    assert update_call["operation"][1]["credits"] == 40
    assert "next_credit_reset_at" in update_call["operation"][1]


def test_build_user_state_uses_profile_as_source_of_truth():
    state = auth._build_user_state(
        "user-1",
        {
            "name": "Profile Name",
            "plan": "Designer",
            "credits": 12,
            "avatar_url": "https://example.com/profile.png",
            "notification_preferences": {
                "gemzyUpdates": False,
                "personalUpdates": True,
                "email": False,
            },
            "is_admin": True,
        },
        {
            "name": "Metadata Name",
            "plan": "Free",
            "credits": 999,
            "avatar_url": "https://example.com/meta.png",
            "notification_preferences": {
                "gemzyUpdates": True,
                "personalUpdates": False,
                "email": True,
            },
            "is_admin": False,
            "reactivatedAt": "2024-01-01T00:00:00Z",
        },
    )

    assert state.name == "Profile Name"
    assert state.plan == "Designer"
    assert state.credits == 12
    assert state.avatarUrl == "https://example.com/profile.png"
    assert state.notificationPreferences is not None
    assert state.notificationPreferences.gemzyUpdates is False
    assert state.notificationPreferences.personalUpdates is True
    assert state.notificationPreferences.email is False
    assert state.isAdmin is True
    assert state.reactivatedAt == "2024-01-01T00:00:00Z"


def test_build_new_profile_payload_supports_legacy_metadata_keys(monkeypatch):
    monkeypatch.setattr(auth, "get_plan_initial_credits", lambda *_: 40)
    monkeypatch.setattr(
        auth,
        "schedule_next_credit_reset",
        lambda now=None: "2024-02-01T00:00:00Z",
    )

    payload = auth._build_new_profile_payload(
        "user-1",
        {
            "full_name": "Legacy Name",
            "avatarUrl": "https://example.com/avatar.png",
            "notificationPreferences": {
                "gemzyUpdates": False,
                "personalUpdates": True,
                "email": False,
            },
        },
    )

    assert payload == {
        "id": "user-1",
        "plan": "Free",
        "credits": 40,
        "next_credit_reset_at": "2024-02-01T00:00:00Z",
        "name": "Legacy Name",
        "avatar_url": "https://example.com/avatar.png",
        "notification_preferences": {
            "gemzyUpdates": False,
            "personalUpdates": True,
            "email": False,
        },
    }


def test_build_user_state_exposes_style_trials_defaults():
    state = auth._build_user_state("user-1", {})

    assert state.styleTrials == {
        "onModel": {"pendingSelectionKeys": [], "remainingUses": 3},
        "pureJewelry": {"pendingSelectionKeys": [], "remainingUses": 3},
    }


def test_normalize_style_trial_state_sanitizes_payload():
    normalized = auth._normalize_style_trial_state(
        {
            "pendingSelectionKeys": ["background::Studio", 123, None],
            "remainingUses": 99,
        }
    )

    assert normalized == {
        "pendingSelectionKeys": ["background::Studio"],
        "remainingUses": 3,
    }
