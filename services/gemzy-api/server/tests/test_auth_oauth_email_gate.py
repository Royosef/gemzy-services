"""OAuth email allowlist tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import sys

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import auth


class _FakeUser:
    def __init__(self, email: str | None = None) -> None:
        self.id = "user-123"
        self.email = email
        self.user_metadata = {"email": email} if email else {}


class _FakeSession:
    def __init__(self) -> None:
        self.access_token = "access"
        self.refresh_token = "refresh"


class _FakeAuth:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def sign_in_with_id_token(self, payload: dict[str, Any]) -> SimpleNamespace:
        self.calls.append(payload)
        return SimpleNamespace(user=_FakeUser(payload.get("email")), session=_FakeSession())


class _FakeClient:
    def __init__(self) -> None:
        self.auth = _FakeAuth()

    class _Table:
        def update(self, *_args: Any, **_kwargs: Any) -> "_FakeClient._Table":
            return self

        def eq(self, *_args: Any, **_kwargs: Any) -> "_FakeClient._Table":
            return self

        def insert(self, *_args: Any, **_kwargs: Any) -> "_FakeClient._Table":
            return self

        def execute(self) -> SimpleNamespace:
            return SimpleNamespace(data=[])

    def table(self, *_args: Any, **_kwargs: Any):  # pragma: no cover - unused
        return self._Table()


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router)

    fake_client = _FakeClient()
    monkeypatch.setattr(auth, "get_client", lambda: fake_client)
    monkeypatch.setattr(auth, "_user_profile", lambda *_args, **_kwargs: {"plan": "Pro", "credits": 10})
    monkeypatch.setattr(auth, "clear_user_deactivation", lambda *a, **k: ({}, {"plan": "Pro"}, None))
    monkeypatch.setattr(auth, "get_plan_initial_credits", lambda *_: 0)

    return TestClient(app)


def _jwt_with_email(email: str) -> str:
    # header and signature not validated; payload is what matters for tests
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


def test_oauth_login_allows_whitelisted_email(monkeypatch: pytest.MonkeyPatch, app: TestClient) -> None:
    token = _jwt_with_email("allowed@example.com")

    # Whitelist check passes
    monkeypatch.setattr(auth, "_is_email_allowed", lambda email, client=None: email == "allowed@example.com")
    async def _exchange(code: str, redirect_uri: str | None = None) -> dict[str, str]:
        return {"id_token": token, "access_token": "atk"}

    monkeypatch.setattr(auth, "exchange_google_code", _exchange)

    response = app.post(
        "/auth/oauth",
        json={"provider": "google", "token": "auth-code"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == "user-123"


def test_oauth_login_blocks_non_whitelisted_email(monkeypatch: pytest.MonkeyPatch, app: TestClient) -> None:
    token = _jwt_with_email("blocked@example.com")

    monkeypatch.setattr(auth, "_is_email_allowed", lambda email, client=None: False)
    async def _exchange(code: str, redirect_uri: str | None = None) -> dict[str, str]:
        return {"id_token": token, "access_token": "atk"}

    monkeypatch.setattr(auth, "exchange_google_code", _exchange)

    response = app.post(
        "/auth/oauth",
        json={"provider": "google", "token": "auth-code"},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_oauth_login_blocks_when_email_missing(monkeypatch: pytest.MonkeyPatch, app: TestClient) -> None:
    # token without email field
    token = "header.{}.sig"
    monkeypatch.setattr(auth, "_is_email_allowed", lambda email, client=None: True)
    async def _exchange(code: str, redirect_uri: str | None = None) -> dict[str, str]:
        return {"id_token": token, "access_token": "atk"}

    monkeypatch.setattr(auth, "exchange_google_code", _exchange)

    response = app.post(
        "/auth/oauth",
        json={"provider": "google", "token": "auth-code"},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
