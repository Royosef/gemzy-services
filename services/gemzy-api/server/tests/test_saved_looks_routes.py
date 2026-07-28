"""Route compatibility tests for saved looks."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import looks
from server.schemas import UserState


class _EmptySavedLooksQuery:
    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class _EmptySavedLooksClient:
    def table(self, name: str) -> _EmptySavedLooksQuery:
        assert name == "saved_looks"
        return _EmptySavedLooksQuery()


def test_saved_looks_accepts_both_trailing_slash_forms_without_redirects(
    monkeypatch,
) -> None:
    monkeypatch.setattr(looks, "get_client", lambda: _EmptySavedLooksClient())

    app = FastAPI()
    app.include_router(looks.router)
    app.dependency_overrides[looks.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Free",
        credits=0,
    )

    with TestClient(app, follow_redirects=False) as client:
        without_slash = client.get("/looks")
        with_slash = client.get("/looks/")

    assert without_slash.status_code == 200
    assert without_slash.json() == []
    assert with_slash.status_code == 200
    assert with_slash.json() == []
