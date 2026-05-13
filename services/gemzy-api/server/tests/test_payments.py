import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server import payments
from server.schemas import UserState


class _Request:
    def __init__(self, payload: dict):
        self.payload = payload

    async def json(self) -> dict:
        return self.payload


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


def test_extract_credit_pack_amount_from_configured_product_ids():
    assert payments._extract_credit_pack_amount("credits_s") == 100
    assert payments._extract_credit_pack_amount("credits_S") == 100
    assert payments._extract_credit_pack_amount("credits_m") == 300
    assert payments._extract_credit_pack_amount("credits_M") == 300
    assert payments._extract_credit_pack_amount("cresits_l") == 700
    assert payments._extract_credit_pack_amount("credits_L") == 700
    assert payments._extract_credit_pack_amount("credits_xl") == 1500
    assert payments._extract_credit_pack_amount("credits_XL") == 1500


def test_extract_credit_pack_amount_ignores_subscription_like_product_id():
    assert payments._extract_credit_pack_amount("credits_l_pack") is None
    assert payments._extract_credit_pack_amount("designer_monthly") is None


def test_sum_virtual_currency_adjustments_handles_positive_and_negative_amounts():
    event = {
        "adjustments": [
            {"amount": 100},
            {"amount": "-20"},
            {"amount": 5.9},
            {"amount": "ignored"},
        ]
    }

    assert payments._sum_virtual_currency_adjustments(event) == 85


def test_subscription_ownership_allows_anonymous_original_app_user_id():
    assert not payments._has_subscription_account_mismatch(
        "user-2",
        "$RCAnonymousID:anonymous-user",
    )


def test_subscription_ownership_rejects_different_original_app_user_id():
    assert payments._has_subscription_account_mismatch("user-2", "user-1")


def test_sync_subscription_rejects_client_ownership_mismatch():
    payload = {
        "revenuecat_app_user_id": "user-2",
        "revenuecat_original_app_user_id": "user-1",
        "source": "restore",
    }
    current = UserState(id="user-2", credits=25, isAdmin=False)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(payments.sync_subscription(_Request(payload), current))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == payments.SUBSCRIPTION_ACCOUNT_MISMATCH_CODE


def test_sync_subscription_rejects_revenuecat_subscriber_ownership_mismatch(monkeypatch: pytest.MonkeyPatch):
    async def fetch_subscriber(_user_id: str):
        return {
            "original_app_user_id": "user-1",
            "entitlements": {
                "pro": {"expires_date": "2099-01-01T00:00:00Z"},
            },
        }

    monkeypatch.setattr(payments, "_fetch_rc_subscriber", fetch_subscriber)
    current = UserState(id="user-2", credits=25, isAdmin=False)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(payments.sync_subscription(_Request({}), current))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == payments.SUBSCRIPTION_ACCOUNT_MISMATCH_CODE


def test_sync_credit_pack_purchase_does_not_grant_credits_before_webhook(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(payments, "get_admin_user_metadata", lambda _user_id: {})
    monkeypatch.setattr(
        payments,
        "_fetch_current_profile",
        lambda _sb, _user_id: {"credits": 25, "purchased_credits": 10},
    )
    monkeypatch.setattr(payments, "get_client", lambda: object())

    payload = payments.CreditPackSyncRequest(
        productIdentifier="credits_s",
        purchaseDate="2026-04-19T12:00:00+00:00",
    )
    current = UserState(id="user-1", credits=25, isAdmin=False)

    result = asyncio.run(payments.sync_credit_pack_purchase(payload, current))

    assert result == {
        "status": "ok",
        "action": "awaiting_webhook",
        "creditsAdded": 0,
        "expectedCredits": 100,
        "currentCredits": 35,
    }


def test_sync_credit_pack_purchase_requires_existing_profile(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(payments, "get_admin_user_metadata", lambda _user_id: {})
    monkeypatch.setattr(payments, "_fetch_current_profile", lambda _sb, _user_id: None)
    monkeypatch.setattr(payments, "get_client", lambda: object())

    payload = payments.CreditPackSyncRequest(
        productIdentifier="credits_s",
        purchaseDate="2026-04-19T12:00:00+00:00",
    )
    current = UserState(id="user-1", credits=25, isAdmin=False)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(payments.sync_credit_pack_purchase(payload, current))

    assert exc_info.value.status_code == 404


def test_expiration_event_downgrades_even_when_stored_expiry_is_later(monkeypatch: pytest.MonkeyPatch):
    past_expiration_ms = int(datetime(2026, 4, 14, 17, 51, tzinfo=timezone.utc).timestamp() * 1000)
    fake_client = _FakeClient(
        {
            "profiles": [
                {
                    "plan": "Designer",
                    "credits": 500,
                    "purchased_credits": 0,
                    "rc_last_event_ms": None,
                    "subscription_expires_at": "2026-05-04T20:56:00+00:00",
                    "next_credit_reset_at": "2026-05-01T00:00:00+00:00",
                }
            ]
        }
    )

    monkeypatch.setattr(payments, "get_client", lambda: fake_client)
    monkeypatch.setattr(payments, "get_plan_initial_credits", lambda plan: 10 if plan == "Free" else 500)
    monkeypatch.setattr(payments, "schedule_next_credit_reset", lambda now=None: "2026-06-01T00:00:00+00:00")

    result = asyncio.run(
        payments.rc_webhook(
            _Request(
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
        )
    )

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
                    "next_credit_reset_at": "2026-06-01T00:00:00+00:00",
                },
            ),
            "filters": [("id", "user-1")],
        }
    ]
