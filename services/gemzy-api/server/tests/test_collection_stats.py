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


class _Query:
    def __init__(self, table: str, counts: dict[str, int], log: list) -> None:
        self.table = table
        self.counts = counts
        self.log = log
        self.filters: list[tuple] = []

    def select(self, *_args, **kwargs):
        assert kwargs.get("head") is True and kwargs.get("count") == "exact"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def or_(self, expression):
        self.filters.append(("or", expression))
        return self

    def execute(self):
        self.log.append((self.table, list(self.filters)))
        key = self.table + (":video" if any(f[0] == "or" for f in self.filters) else "")
        return SimpleNamespace(data=[], count=self.counts[key])


def test_collection_stats_counts_per_user(monkeypatch) -> None:
    log: list = []
    counts = {"collections": 24, "collection_items": 263, "collection_items:video": 12}
    monkeypatch.setattr(
        content,
        "get_client",
        lambda: SimpleNamespace(table=lambda name: _Query(name, counts, log)),
    )
    app = FastAPI()
    app.include_router(content.collections_router)
    app.dependency_overrides[get_current_user] = lambda: UserState(id="user-1")

    res = TestClient(app).get("/collections/stats")

    assert res.status_code == 200
    assert res.json() == {"campaigns": 24, "images": 251, "videos": 12}
    assert all(("eq", "user_id", "user-1") in filters for _, filters in log)
    video_filter = next(f for _, filters in log for f in filters if f[0] == "or")[1]
    assert "metadata->>mediaType.eq.video" in video_filter
