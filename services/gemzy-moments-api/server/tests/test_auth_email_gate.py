"""Tests for email gate checks in auth routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, status
from fastapi.testclient import TestClient
import pytest

import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import auth


class _FakeAdmin:
    def __init__(self, users: list[dict[str, Any]] | None = None, *, raise_error: bool = False):
        self._users = users or []
        self._raise_error = raise_error

    def list_users(self, params: dict[str, Any]) -> SimpleNamespace:
        if self._raise_error:
            raise RuntimeError("admin failure")
        return SimpleNamespace(users=self._users)


class _FakeAuth:
    def __init__(self, users: list[dict[str, Any]] | None = None, *, raise_error: bool = False):
        self.admin = _FakeAdmin(users, raise_error=raise_error)
        self.otp_calls: list[dict[str, str]] = []

    def sign_in_with_otp(self, payload: dict[str, str]) -> None:
        self.otp_calls.append(payload)


class _FakeTable:
    def __init__(self, data: list[dict[str, str]] | None = None, *, raise_error: bool = False):
        self._data = data or []
        self._raise_error = raise_error

    def select(self, *args: Any, **kwargs: Any) -> "_FakeTable":
        return self

    def eq(self, *args: Any, **kwargs: Any) -> "_FakeTable":
        return self

    def limit(self, *args: Any, **kwargs: Any) -> "_FakeTable":
        return self

    def execute(self) -> SimpleNamespace:
        if self._raise_error:
            raise RuntimeError("table failure")
        return SimpleNamespace(data=self._data)


class _FakeClient:
    def __init__(
        self,
        users: list[dict[str, Any]] | None = None,
        waitlist: list[dict[str, str]] | None = None,
        *,
        table_error: bool = False,
        admin_error: bool = False,
    ):
        self.auth = _FakeAuth(users, raise_error=admin_error)
        self.waitlist = waitlist or []
        self._table_error = table_error

    def table(self, name: str) -> _FakeTable:  # pragma: no cover - passthrough
        return _FakeTable(self.waitlist, raise_error=self._table_error)


@pytest.fixture()
def app() -> TestClient:
    fast_app = FastAPI()
    fast_app.include_router(auth.router)
    return TestClient(fast_app)


def test_email_allowed_for_existing_auth_user(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(users=[{"email": "user@example.com"}])
    monkeypatch.setattr(auth, "get_service_role_client", lambda fresh=False: client)

    assert auth._is_email_allowed("user@example.com")
    assert auth._is_email_allowed("USER@example.com")


def test_email_allowed_for_waitlist_user(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(waitlist=[{"email": "waitlist@example.com"}])
    monkeypatch.setattr(auth, "get_service_role_client", lambda fresh=False: client)

    assert auth._is_email_allowed("waitlist@example.com")


def test_email_rejected_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(auth, "get_service_role_client", lambda fresh=False: client)

    assert auth._is_email_allowed("missing@example.com") is False


def test_send_magic_link_blocks_unknown_email(
    monkeypatch: pytest.MonkeyPatch, app: TestClient
) -> None:
    service_client = _FakeClient()
    otp_client = _FakeClient()
    monkeypatch.setattr(auth, "get_service_role_client", lambda fresh=False: service_client)
    monkeypatch.setattr(auth, "get_client", lambda: otp_client)

    response = app.post("/auth/send", json={"email": "new@example.com"})
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert otp_client.auth.otp_calls == []


def test_verify_magic_link_blocks_unknown_email(
    monkeypatch: pytest.MonkeyPatch, app: TestClient
) -> None:
    service_client = _FakeClient()
    user_client = _FakeClient()
    monkeypatch.setattr(auth, "get_service_role_client", lambda fresh=False: service_client)
    monkeypatch.setattr(auth, "create_user_client", lambda: user_client)

    response = app.post("/auth/verify", json={"email": "new@example.com", "token": "123456"})
    assert response.status_code == status.HTTP_403_FORBIDDEN
