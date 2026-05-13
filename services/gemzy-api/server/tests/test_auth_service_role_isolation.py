from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import auth


class _FailingServiceAuth:
    def get_user(self, _token: str):
        raise AssertionError("service-role client should not be used for auth.get_user")

    def refresh_session(self, _refresh: str):
        raise AssertionError("service-role client should not be used for auth.refresh_session")

    def sign_in_with_id_token(self, _payload: dict):
        raise AssertionError("service-role client should not be used for auth.sign_in_with_id_token")


class _FailingServiceClient:
    def __init__(self) -> None:
        self.auth = _FailingServiceAuth()


class _FakeUser:
    def __init__(self, email: str = "user@example.com") -> None:
        self.id = "user-123"
        self.email = email
        self.user_metadata = {"email": email}
        self.created_at = None


class _FakeSession:
    def __init__(self) -> None:
        self.access_token = "access-token"
        self.refresh_token = "refresh-token"


class _UserAuthClient:
    def __init__(self) -> None:
        self.get_user_calls: list[str] = []
        self.refresh_calls: list[str] = []
        self.oauth_calls: list[dict] = []

    def get_user(self, token: str) -> SimpleNamespace:
        self.get_user_calls.append(token)
        return SimpleNamespace(user=_FakeUser())

    def refresh_session(self, refresh_token: str) -> SimpleNamespace:
        self.refresh_calls.append(refresh_token)
        return SimpleNamespace(session=_FakeSession())

    def sign_in_with_id_token(self, payload: dict) -> SimpleNamespace:
        self.oauth_calls.append(payload)
        return SimpleNamespace(user=_FakeUser("oauth@example.com"), session=_FakeSession())


class _UserClient:
    def __init__(self) -> None:
        self.auth = _UserAuthClient()


def test_get_current_user_uses_user_client(monkeypatch) -> None:
    service_client = _FailingServiceClient()
    user_client = _UserClient()

    monkeypatch.setattr(auth, "get_client", lambda: service_client)
    monkeypatch.setattr(auth, "create_user_client", lambda: user_client)
    monkeypatch.setattr(
        auth,
        "_ensure_profile_exists",
        lambda user_id, metadata, client=None, provided_name=None: ({"plan": "Free", "credits": 5}, False),
    )
    monkeypatch.setattr(
        auth,
        "clear_user_deactivation",
        lambda *args, **kwargs: ({}, {"plan": "Free", "credits": 5}, None),
    )
    monkeypatch.setattr(auth, "_ensure_monthly_credits", lambda user_id, plan, profile: profile)
    monkeypatch.setattr(
        auth,
        "_build_user_state",
        lambda user_id, profile, metadata, created_at=None, auth_user=None: {
            "id": user_id,
            "plan": profile.get("plan"),
            "credits": profile.get("credits", 0),
        },
    )
    monkeypatch.setattr(auth, "get_service_role_client", lambda fresh=False: service_client)

    current = auth.get_current_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="user-token")
    )

    assert current["id"] == "user-123"
    assert user_client.auth.get_user_calls == ["user-token"]


def test_refresh_token_uses_user_client(monkeypatch) -> None:
    service_client = _FailingServiceClient()
    user_client = _UserClient()

    monkeypatch.setattr(auth, "get_client", lambda: service_client)
    monkeypatch.setattr(auth, "create_user_client", lambda: user_client)

    token = auth.refresh_token(auth.RefreshRequest(refresh="refresh-me"))

    assert token.access == "access-token"
    assert token.refresh == "refresh-token"
    assert user_client.auth.refresh_calls == ["refresh-me"]


def test_refresh_token_returns_503_for_transient_refresh_failures(monkeypatch) -> None:
    class _TransientAuthClient:
        def refresh_session(self, _refresh: str) -> SimpleNamespace:
            raise RuntimeError("temporary auth backend outage")

    transient_client = SimpleNamespace(auth=_TransientAuthClient())

    monkeypatch.setattr(auth, "create_user_client", lambda: transient_client)

    try:
        auth.refresh_token(auth.RefreshRequest(refresh="refresh-me"))
    except auth.HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail == "Unable to refresh session right now"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected refresh_token to raise HTTPException")


def test_refresh_token_returns_401_for_invalid_refresh_failures(monkeypatch) -> None:
    class _InvalidRefreshAuthClient:
        def refresh_session(self, _refresh: str) -> SimpleNamespace:
            raise RuntimeError("Invalid Refresh Token: Already Used")

    invalid_client = SimpleNamespace(auth=_InvalidRefreshAuthClient())

    monkeypatch.setattr(auth, "create_user_client", lambda: invalid_client)

    try:
        auth.refresh_token(auth.RefreshRequest(refresh="refresh-me"))
    except auth.HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "Invalid Refresh Token: Already Used"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected refresh_token to raise HTTPException")


def test_oauth_login_uses_user_client(monkeypatch) -> None:
    service_client = _FailingServiceClient()
    user_client = _UserClient()

    app = FastAPI()
    app.include_router(auth.router)
    client = TestClient(app)

    captured: dict[str, str | None] = {}

    async def _exchange(_code: str, redirect_uri: str | None = None) -> dict[str, str]:
        captured["redirect_uri"] = redirect_uri
        return {"id_token": "header.payload.sig", "access_token": "google-at"}

    monkeypatch.setattr(auth, "get_client", lambda: service_client)
    monkeypatch.setattr(auth, "create_user_client", lambda: user_client)
    monkeypatch.setattr(auth, "get_service_role_client", lambda fresh=False: service_client)
    monkeypatch.setattr(auth, "exchange_google_code", _exchange)
    monkeypatch.setattr(auth, "_decode_jwt_payload", lambda token: {"email": "oauth@example.com"})
    monkeypatch.setattr(
        auth,
        "_ensure_profile_exists",
        lambda user_id, metadata, client=None, provided_name=None: ({"plan": "Pro", "credits": 10}, False),
    )
    monkeypatch.setattr(
        auth,
        "clear_user_deactivation",
        lambda *args, **kwargs: ({}, {"plan": "Pro", "credits": 10}, None),
    )
    monkeypatch.setattr(auth, "_ensure_monthly_credits", lambda user_id, plan, profile: profile)
    monkeypatch.setattr(
        auth,
        "_build_user_state",
        lambda user_id, profile, metadata, created_at=None, auth_user=None: {
            "id": user_id,
            "plan": profile.get("plan"),
            "credits": profile.get("credits", 0),
        },
    )

    response = client.post("/auth/oauth", json={"provider": "google", "token": "auth-code"})

    assert response.status_code == 200
    assert captured["redirect_uri"] is None
    assert user_client.auth.oauth_calls == [
        {"provider": "google", "token": "header.payload.sig", "access_token": "google-at"}
    ]


def test_oauth_login_forwards_google_redirect_uri(monkeypatch) -> None:
    service_client = _FailingServiceClient()
    user_client = _UserClient()

    app = FastAPI()
    app.include_router(auth.router)
    client = TestClient(app)

    captured: dict[str, str | None] = {}

    async def _exchange(_code: str, redirect_uri: str | None = None) -> dict[str, str]:
        captured["redirect_uri"] = redirect_uri
        return {"id_token": "header.payload.sig", "access_token": "google-at"}

    monkeypatch.setattr(auth, "get_client", lambda: service_client)
    monkeypatch.setattr(auth, "create_user_client", lambda: user_client)
    monkeypatch.setattr(auth, "get_service_role_client", lambda fresh=False: service_client)
    monkeypatch.setattr(auth, "exchange_google_code", _exchange)
    monkeypatch.setattr(auth, "_decode_jwt_payload", lambda token: {"email": "oauth@example.com"})
    monkeypatch.setattr(
        auth,
        "_ensure_profile_exists",
        lambda user_id, metadata, client=None, provided_name=None: ({"plan": "Pro", "credits": 10}, False),
    )
    monkeypatch.setattr(
        auth,
        "clear_user_deactivation",
        lambda *args, **kwargs: ({}, {"plan": "Pro", "credits": 10}, None),
    )
    monkeypatch.setattr(auth, "_ensure_monthly_credits", lambda user_id, plan, profile: profile)
    monkeypatch.setattr(
        auth,
        "_build_user_state",
        lambda user_id, profile, metadata, created_at=None, auth_user=None: {
            "id": user_id,
            "plan": profile.get("plan"),
            "credits": profile.get("credits", 0),
        },
    )

    response = client.post(
        "/auth/oauth",
        json={
            "provider": "google",
            "token": "auth-code",
            "redirectUri": "http://localhost:5173",
        },
    )

    assert response.status_code == 200
    assert captured["redirect_uri"] == "http://localhost:5173"
