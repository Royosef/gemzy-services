from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import auth, web_session

WEB_ORIGIN = "https://studio.gemzy.test"
WEB_HEADERS = {"Origin": WEB_ORIGIN, "X-Gemzy-Client": "web"}


class _FakeAuth:
    def __init__(self) -> None:
        self.refresh_calls: list[str] = []

    def refresh_session(self, refresh_token: str) -> SimpleNamespace:
        self.refresh_calls.append(refresh_token)
        return SimpleNamespace(
            session=SimpleNamespace(access_token="new-access", refresh_token="new-refresh")
        )


@pytest.fixture()
def fake_auth(monkeypatch) -> _FakeAuth:
    fake = _FakeAuth()
    monkeypatch.setattr(auth, "create_user_client", lambda: SimpleNamespace(auth=fake))
    monkeypatch.setenv("WEB_SESSION_ORIGINS", f"{WEB_ORIGIN},http://localhost:5173")
    monkeypatch.delenv("WEB_SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("WEB_SESSION_COOKIE_DOMAIN", raising=False)
    return fake


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(auth.router)
    return TestClient(app, base_url="https://api.gemzy.test")


def test_native_refresh_is_unchanged(client: TestClient, fake_auth: _FakeAuth) -> None:
    res = client.post("/auth/refresh", json={"refresh": "native-refresh"})

    assert res.status_code == 200
    assert res.json() == {"access": "new-access", "refresh": "new-refresh"}
    assert "set-cookie" not in res.headers
    assert fake_auth.refresh_calls == ["native-refresh"]


def test_web_refresh_reads_cookie_and_rotates_it(client: TestClient, fake_auth: _FakeAuth) -> None:
    client.cookies.set("gemzy_rt", "cookie-refresh", domain="api.gemzy.test", path="/auth")

    res = client.post("/auth/refresh", headers=WEB_HEADERS)

    assert res.status_code == 200
    assert res.json() == {"access": "new-access", "refresh": ""}
    assert fake_auth.refresh_calls == ["cookie-refresh"]
    cookie = res.headers["set-cookie"].lower()
    assert "gemzy_rt=new-refresh" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "path=/auth" in cookie
    assert res.headers["cache-control"] == "no-store"


def test_cookie_ignored_for_unlisted_origin(client: TestClient, fake_auth: _FakeAuth) -> None:
    client.cookies.set("gemzy_rt", "cookie-refresh", domain="api.gemzy.test", path="/auth")

    res = client.post(
        "/auth/refresh",
        headers={"Origin": "https://evil.example", "X-Gemzy-Client": "web"},
    )

    assert res.status_code == 401
    assert fake_auth.refresh_calls == []


def test_cookie_ignored_without_client_header(client: TestClient, fake_auth: _FakeAuth) -> None:
    client.cookies.set("gemzy_rt", "cookie-refresh", domain="api.gemzy.test", path="/auth")

    res = client.post("/auth/refresh", headers={"Origin": WEB_ORIGIN})

    assert res.status_code == 401
    assert fake_auth.refresh_calls == []


def test_logout_clears_cookie(client: TestClient, fake_auth: _FakeAuth) -> None:
    res = client.post("/auth/logout", headers=WEB_HEADERS)

    assert res.status_code == 204
    cookie = res.headers["set-cookie"].lower()
    assert 'gemzy_rt=""' in cookie or "gemzy_rt=;" in cookie
    assert "max-age=0" in cookie


def test_secure_flag_can_be_disabled_for_local_http(monkeypatch, fake_auth: _FakeAuth) -> None:
    monkeypatch.setenv("WEB_SESSION_COOKIE_SECURE", "false")
    app = FastAPI()
    app.include_router(auth.router)
    local = TestClient(app, base_url="http://localhost:5050")
    local.cookies.set("gemzy_rt", "cookie-refresh", domain="localhost.local", path="/auth")

    res = local.post(
        "/auth/refresh",
        headers={"Origin": "http://localhost:5173", "X-Gemzy-Client": "web"},
        json={"refresh": "body-refresh"},
    )

    assert res.status_code == 200
    assert "secure" not in res.headers["set-cookie"].lower()


def test_is_web_session_request_requires_both_conditions(monkeypatch) -> None:
    monkeypatch.setenv("WEB_SESSION_ORIGINS", WEB_ORIGIN)

    def req(headers: dict) -> SimpleNamespace:
        return SimpleNamespace(headers={k.lower(): v for k, v in headers.items()})

    assert web_session.is_web_session_request(req(WEB_HEADERS))
    assert not web_session.is_web_session_request(req({"Origin": WEB_ORIGIN}))
    assert not web_session.is_web_session_request(req({"X-Gemzy-Client": "web"}))
    assert not web_session.is_web_session_request(
        req({"Origin": WEB_ORIGIN + ".evil.example", "X-Gemzy-Client": "web"})
    )
