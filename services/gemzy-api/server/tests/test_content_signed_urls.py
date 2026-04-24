from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import content
from server.schemas import UserState


class _StubBlob:
    def generate_signed_url(self, **_kwargs: Any) -> str:
        return "https://signed.example/object.png"


class _StubBucket:
    def __init__(self, expected_path: str) -> None:
        self.expected_path = expected_path

    def blob(self, path: str) -> _StubBlob:
        assert path == self.expected_path
        return _StubBlob()


class _StubTable:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self._data = data
        self._filters: list[tuple[str, Any]] = []

    def select(self, *_args: Any, **_kwargs: Any) -> _StubTable:
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> _StubTable:
        if _args:
            self._filters.append((_args[0], _args[1] if len(_args) > 1 else None))
        elif _kwargs:
            key, value = next(iter(_kwargs.items()))
            self._filters.append((key, value))
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> _StubTable:
        return self

    def execute(self) -> SimpleNamespace:
        rows = self._data
        for key, value in self._filters:
            rows = [row for row in rows if row.get(key) == value]
        return SimpleNamespace(data=rows)


class _StubClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def table(self, name: str) -> _StubTable:
        assert name == "collection_items"
        return _StubTable(self._rows)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    api = FastAPI()
    api.include_router(content.collections_router)
    api.dependency_overrides[content.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=10,
    )

    monkeypatch.setattr(
        content,
        "get_client",
        lambda: _StubClient([{"external_id": "user-123/items/photo.png", "user_id": "user-123"}]),
    )
    monkeypatch.setattr(
        content,
        "_maybe_get_collections_bucket",
        lambda: _StubBucket("user-123/items/photo.png"),
    )
    monkeypatch.setattr(
        content,
        "generate_signed_read_url_v4",
        lambda *_args, **_kwargs: "https://signed.example/object.png",
    )
    return api


def test_generate_signed_url_success(app: FastAPI) -> None:
    client = TestClient(app)
    response = client.get("/collections/items/user-123/items/photo.png/signed-url")
    assert response.status_code == 200
    payload = response.json()
    assert payload["url"] == "https://signed.example/object.png"
    assert "expiresAt" in payload


def test_generate_signed_url_rejects_other_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(content.collections_router)
    app.dependency_overrides[content.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=10,
    )
    monkeypatch.setattr(
        content,
        "get_client",
        lambda: _StubClient(
            [{"external_id": "someone-else/items/photo.png", "user_id": "someone-else"}]
        ),
    )
    monkeypatch.setattr(
        content,
        "_maybe_get_collections_bucket",
        lambda: _StubBucket("user-123/items/photo.png"),
    )
    monkeypatch.setattr(
        content,
        "generate_signed_read_url_v4",
        lambda *_args, **_kwargs: "https://signed.example/object.png",
    )

    client = TestClient(app)
    response = client.get("/collections/items/user-123/items/photo.png/signed-url")
    assert response.status_code == 404
