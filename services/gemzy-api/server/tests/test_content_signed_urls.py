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


class _DraftResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _DraftCollectionsTable:
    def __init__(
        self,
        rows: list[dict[str, Any]],
        inserted: list[dict[str, Any]],
        *,
        fail_insert: bool = False,
    ) -> None:
        self._rows = rows
        self._inserted = inserted
        self._filters: list[tuple[str, Any]] = []
        self._insert_payload: dict[str, Any] | None = None
        self._update_payload: dict[str, Any] | None = None
        self._fail_insert = fail_insert

    def select(self, *_args: Any, **_kwargs: Any) -> "_DraftCollectionsTable":
        return self

    def eq(self, key: str, value: Any) -> "_DraftCollectionsTable":
        self._filters.append((key, value))
        return self

    def in_(self, key: str, values: list[Any]) -> "_DraftCollectionsTable":
        self._filters.append((key, set(values)))
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> "_DraftCollectionsTable":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_DraftCollectionsTable":
        return self

    def insert(
        self,
        payload: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> "_DraftCollectionsTable":
        self._insert_payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> "_DraftCollectionsTable":
        self._update_payload = payload
        return self

    def execute(self) -> _DraftResponse:
        if self._insert_payload is not None:
            if self._fail_insert:
                self._rows.append(self._insert_payload)
                raise RuntimeError("duplicate key")
            self._inserted.append(self._insert_payload)
            self._rows.append(self._insert_payload)
            return _DraftResponse([self._insert_payload])

        rows = self._rows
        for key, value in self._filters:
            if isinstance(value, set):
                rows = [row for row in rows if row.get(key) in value]
            else:
                rows = [row for row in rows if row.get(key) == value]

        if self._update_payload is not None:
            for row in rows:
                row.update(self._update_payload)
            return _DraftResponse(rows)

        return _DraftResponse(rows[:1])


class _DraftClient:
    def __init__(
        self,
        rows: list[dict[str, Any]],
        inserted: list[dict[str, Any]],
        *,
        fail_insert: bool = False,
    ) -> None:
        self._rows = rows
        self._inserted = inserted
        self._fail_insert = fail_insert

    def table(self, name: str) -> _DraftCollectionsTable:
        assert name == "collections"
        return _DraftCollectionsTable(
            self._rows,
            self._inserted,
            fail_insert=self._fail_insert,
        )


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


def test_normalize_storage_path_strips_known_bucket_from_gcs_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(content, "COLLECTIONS_APP_BUCKET", "app.gemzy.co")
    monkeypatch.setattr(content, "COLLECTIONS_PUBLIC_BUCKET", "public.gemzy.co")

    normalized = content._normalize_storage_path(
        "https://storage.googleapis.com/app.gemzy.co/user-123/items/photo.png?X-Goog-Signature=abc"
    )

    assert normalized == "user-123/items/photo.png"


def test_resolve_collection_image_variants_resigns_gcs_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(content, "COLLECTIONS_APP_BUCKET", "app.gemzy.co")
    monkeypatch.setattr(content, "COLLECTIONS_PUBLIC_BUCKET", "public.gemzy.co")
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

    preview, full = content._resolve_collection_image_variants(
        "https://storage.googleapis.com/app.gemzy.co/user-123/items/photo.png?X-Goog-Signature=old",
        None,
        include_signed=True,
    )

    assert preview == "https://signed.example/object.png"
    assert full == "https://signed.example/object.png"


def test_ensure_unsaved_collection_creates_deterministic_draft_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[dict[str, Any]] = []
    inserted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        content,
        "get_client",
        lambda: _DraftClient(rows, inserted),
    )

    draft_id = content.ensure_unsaved_collection("user-123")

    assert draft_id == content._draft_collection_id("user-123")
    assert inserted == [
        {
            "id": draft_id,
            "user_id": "user-123",
            "name": "Draft Images",
            "liked": False,
        }
    ]


def test_ensure_unsaved_collection_recovers_from_concurrent_draft_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_id = content._draft_collection_id("user-123")
    rows: list[dict[str, Any]] = []
    inserted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        content,
        "get_client",
        lambda: _DraftClient(rows, inserted, fail_insert=True),
    )

    resolved_id = content.ensure_unsaved_collection("user-123")

    assert resolved_id == draft_id
    assert inserted == []
