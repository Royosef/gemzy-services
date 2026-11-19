"""Synced Explore inspirations (/inspirations)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import inspirations
from server.auth import get_current_user
from server.schemas import UserState


class _Table:
    def __init__(self, store: dict, log: list) -> None:
        self.store, self.log = store, log
        self.filters: dict[str, str] = {}
        self.op = "select"
        self.row = None

    def select(self, *_):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def upsert(self, row, on_conflict=None):
        self.op, self.row = "upsert", row
        self.log.append(on_conflict)
        return self

    def delete(self):
        self.op = "delete"
        return self

    def execute(self):
        if self.op == "upsert":
            self.store[(self.row["user_id"], self.row["media_id"])] = self.row
            return SimpleNamespace(data=[self.row])
        keys = [
            k
            for k in self.store
            if k[0] == self.filters.get("user_id")
            and ("media_id" not in self.filters or k[1] == self.filters["media_id"])
        ]
        if self.op == "delete":
            for k in keys:
                del self.store[k]
            return SimpleNamespace(data=[])
        rows = sorted((self.store[k] for k in keys), key=lambda r: r["created_at"], reverse=True)
        return SimpleNamespace(data=rows)


def _client(monkeypatch, user_id="user-1"):
    store: dict = {}
    log: list = []
    monkeypatch.setattr(
        inspirations, "get_client", lambda: SimpleNamespace(table=lambda _n: _Table(store, log))
    )
    app = FastAPI()
    app.include_router(inspirations.router)
    app.dependency_overrides[get_current_user] = lambda: UserState(id=user_id)
    return TestClient(app), store, log


BODY = {
    "lookId": "look-1",
    "lookName": "Golden Hour",
    "taskKey": "on-model",
    "engineId": "engine",
    "kind": "image",
    "uri": "https://public.gemzy.co/a.jpg",
}


def test_save_list_and_delete(monkeypatch):
    client, store, log = _client(monkeypatch)

    assert client.put("/inspirations/m1", json=BODY).status_code == 200
    assert client.put("/inspirations/m1", json=BODY).status_code == 200  # idempotent
    assert log == ["user_id,media_id", "user_id,media_id"]
    listed = client.get("/inspirations").json()["inspirations"]
    assert [i["id"] for i in listed] == ["m1"]
    assert listed[0]["lookName"] == "Golden Hour"

    assert client.delete("/inspirations/m1").status_code == 204
    assert client.get("/inspirations").json()["inspirations"] == []


def test_non_https_media_is_rejected(monkeypatch):
    client, store, _ = _client(monkeypatch)
    res = client.put("/inspirations/m1", json={**BODY, "uri": "javascript:alert(1)"})
    assert res.status_code == 422
    assert store == {}


def test_import_keeps_original_saved_time(monkeypatch):
    client, _, _ = _client(monkeypatch)
    res = client.put("/inspirations/m1", json={**BODY, "createdAt": "2026-03-01T10:00:00Z"})
    assert res.json()["createdAt"].startswith("2026-03-01T10:00:00")
