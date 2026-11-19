from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import content
from server.auth import get_current_user
from server.schemas import UserState


def _row(index: int, *, video: bool = False) -> dict:
    ext = "mp4" if video else "png"
    return {
        "collection_id": f"col-{index % 2}",
        "external_id": f"https://cdn.example.com/item-{index}.{ext}",
        "id": f"row-{index}",
        "image_url": f"https://cdn.example.com/item-{index}.{ext}",
        "category": None,
        "is_new": False,
        "is_favorite": False,
        "metadata": {"mediaType": "video"} if video else {},
        # Newest first: larger index = older.
        "created_at": f"2026-01-01T00:{59 - index:02d}:00",
        "model_id": None,
        "model_name": None,
    }


class _Query:
    def __init__(self, rows: list[dict], log: list) -> None:
        self.rows = rows
        self.log = log
        self.filters: list[tuple] = []
        self._limit = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def or_(self, expression):
        self.filters.append(("or", expression))
        return self

    def lt(self, column, value):
        self.filters.append(("lt", column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, value):
        self._limit = value
        return self

    def execute(self):
        self.log.append(list(self.filters))
        rows = [r for r in self.rows if r["created_at"]]
        for kind, *args in self.filters:
            if kind == "or":
                rows = [r for r in rows if r["metadata"].get("mediaType") == "video"]
            if kind == "lt":
                rows = [r for r in rows if r["created_at"] < args[1]]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return SimpleNamespace(data=rows[: self._limit])


def _client(monkeypatch, rows: list[dict]) -> tuple[TestClient, list]:
    log: list = []
    monkeypatch.setattr(
        content,
        "get_client",
        lambda: SimpleNamespace(table=lambda _name: _Query(rows, log)),
    )
    monkeypatch.setattr(content, "_fetch_model_records", lambda _ids: {}, raising=False)
    app = FastAPI()
    app.include_router(content.collections_router)
    app.dependency_overrides[get_current_user] = lambda: UserState(id="user-1")
    return TestClient(app), log


def test_video_feed_filters_in_query_and_scopes_to_user(monkeypatch) -> None:
    rows = [_row(i, video=i % 3 == 0) for i in range(9)]
    client, log = _client(monkeypatch, rows)

    res = client.get("/collections/items", params={"mediaType": "video", "limit": 10})

    assert res.status_code == 200
    body = res.json()
    assert [item["id"] for item in body["items"]] == [rows[i]["external_id"] for i in (0, 3, 6)]
    assert body["nextCursor"] is None
    assert all(("eq", "user_id", "user-1") in filters for filters in log)
    assert any(f[0] == "or" for f in log[0])


def test_image_feed_skips_videos_and_paginates(monkeypatch) -> None:
    rows = [_row(i, video=i % 2 == 1) for i in range(12)]  # 6 images, 6 videos
    client, _ = _client(monkeypatch, rows)

    first = client.get("/collections/items", params={"mediaType": "image", "limit": 4}).json()
    assert [item["id"] for item in first["items"]] == [rows[i]["external_id"] for i in (0, 2, 4, 6)]
    assert all(item.get("mediaType") != "video" for item in first["items"])
    assert first["nextCursor"]

    second = client.get(
        "/collections/items",
        params={"mediaType": "image", "limit": 4, "cursor": first["nextCursor"]},
    ).json()
    assert [item["id"] for item in second["items"]] == [rows[i]["external_id"] for i in (8, 10)]
    assert second["nextCursor"] is None


def test_items_route_is_not_shadowed_by_collection_id(monkeypatch) -> None:
    client, _ = _client(monkeypatch, [_row(0)])
    res = client.get("/collections/items")
    assert res.status_code == 200
    assert "items" in res.json()


def test_invalid_cursor_is_rejected(monkeypatch) -> None:
    client, _ = _client(monkeypatch, [])
    res = client.get("/collections/items", params={"cursor": "garbage"})
    assert res.status_code == 400


class _FavoriteQuery(_Query):
    """Understands the favourite OR-group: is_favorite or collection_id in (...)."""

    def execute(self):
        self.log.append(list(self.filters))
        rows = list(self.rows)
        for kind, *args in self.filters:
            if kind == "or" and args[0].startswith("is_favorite"):
                liked = set()
                if "collection_id.in.(" in args[0]:
                    liked = set(args[0].split("collection_id.in.(", 1)[1].rstrip(")").split(","))
                rows = [r for r in rows if r["is_favorite"] or r["collection_id"] in liked]
            elif kind == "or":
                rows = [r for r in rows if r["metadata"].get("mediaType") == "video"]
            elif kind == "lt":
                rows = [r for r in rows if r["created_at"] < args[1]]
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return SimpleNamespace(data=rows[: self._limit])


def _favorite_client(monkeypatch, rows, liked_collections):
    log: list = []
    collections = [{"id": cid} for cid in liked_collections]

    def table(name):
        return _FavoriteQuery(collections if name == "collections" else rows, log)

    monkeypatch.setattr(content, "get_client", lambda: SimpleNamespace(table=table))
    monkeypatch.setattr(content, "_fetch_model_records", lambda _ids: {}, raising=False)
    app = FastAPI()
    app.include_router(content.collections_router)
    app.dependency_overrides[get_current_user] = lambda: UserState(id="user-1")
    return TestClient(app), log


def test_favorite_feed_has_flagged_items_and_liked_campaigns(monkeypatch) -> None:
    rows = [_row(i, video=i == 4) for i in range(6)]  # col-0: 0,2,4  col-1: 1,3,5
    rows[3]["is_favorite"] = True
    client, log = _favorite_client(monkeypatch, rows, ["col-0"])

    images = client.get("/collections/items", params={"favorite": "true", "mediaType": "image"})
    videos = client.get("/collections/items", params={"favorite": "true", "mediaType": "video"})

    assert [i["id"] for i in images.json()["items"]] == [rows[n]["external_id"] for n in (0, 2, 3)]
    assert [i["id"] for i in videos.json()["items"]] == [rows[4]["external_id"]]
    # Never two OR-groups in one query.
    assert all(sum(1 for f in filters if f[0] == "or") <= 1 for filters in log)


def test_favorite_feed_without_liked_campaigns(monkeypatch) -> None:
    rows = [_row(i) for i in range(3)]
    rows[1]["is_favorite"] = True
    client, _ = _favorite_client(monkeypatch, rows, [])
    body = client.get("/collections/items", params={"favorite": "true"}).json()
    assert [i["id"] for i in body["items"]] == [rows[1]["external_id"]]
