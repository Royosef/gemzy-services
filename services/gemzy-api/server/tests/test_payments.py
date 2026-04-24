import asyncio

import pytest
from fastapi import HTTPException

from server import payments
from server.schemas import UserState


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


def test_sync_credit_pack_purchase_does_not_grant_credits_before_webhook(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(payments, "get_admin_user_metadata", lambda _user_id: {})
    monkeypatch.setattr(
        payments,
        "_fetch_current_profile",
        lambda _sb, _user_id: {"credits": 25},
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
        "currentCredits": 25,
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
