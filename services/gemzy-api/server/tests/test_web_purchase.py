"""Web purchase intents, QR link opens and waitlist (/web-purchase)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import analytics, web_purchase
from server.auth import get_current_user
from server.rate_limit import limiter
from server.schemas import UserState

USER = "456061a1-3a93-40aa-9c40-946c26aa64ba"
INTENT = "7d1f3c1e-2b8a-4f39-9a51-1f0c3a9d2e10"


class _Query:
    """Tiny stand-in for the supabase query builder; records calls, returns canned rows."""

    def __init__(self, db: "_Db", table: str) -> None:
        self.db, self.table = db, table
        self.op, self.payload, self.filters = "select", None, {}

    def select(self, *_):
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, row):
        self.op, self.payload = "update", row
        return self

    def upsert(self, row, **kwargs):
        self.op, self.payload = "upsert", (row, kwargs)
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def is_(self, column, value):
        self.filters[f"is:{column}"] = value
        return self

    def gte(self, column, value):
        self.filters[f"gte:{column}"] = value
        return self

    def lte(self, column, value):
        self.filters[f"lte:{column}"] = value
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        self.db.calls.append((self.table, self.op, self.payload, dict(self.filters)))
        return SimpleNamespace(data=self.db.responses.get((self.table, self.op), []))


class _Db:
    def __init__(self) -> None:
        self.calls: list = []
        self.responses: dict = {}

    def table(self, name):
        return _Query(self, name)


@pytest.fixture
def db(monkeypatch):
    fake = _Db()
    monkeypatch.setattr(web_purchase, "get_client", lambda: fake)
    return fake


@pytest.fixture
def client(db):
    limiter.enabled = False
    app = FastAPI()
    app.include_router(web_purchase.router)
    app.dependency_overrides[get_current_user] = lambda: UserState(id=USER, email="a@b.co")
    yield TestClient(app)
    limiter.enabled = True


def test_intent_is_recorded_and_reports_waitlist(client, db):
    db.responses[("web_purchase_intents", "insert")] = [{"id": INTENT}]
    db.responses[("web_purchase_waitlist", "select")] = [{"created_at": "2026-11-23T10:00:00Z"}]
    res = client.post("/web-purchase/intent", json={"product": "credits:300", "source": "credits_page"})
    assert res.status_code == 200
    assert res.json() == {"id": INTENT, "waitlisted": True}
    table, op, row, _ = db.calls[0]
    assert (table, op) == ("web_purchase_intents", "insert")
    assert row == {"user_id": USER, "product": "credits:300", "source": "credits_page"}


@pytest.mark.parametrize("product", ["", "Credits 300", "x" * 61, "credits/../x"])
def test_intent_rejects_malformed_product(client, product):
    res = client.post("/web-purchase/intent", json={"product": product, "source": "credits_page"})
    assert res.status_code == 422


def test_open_records_first_open_and_redirects(client, db, monkeypatch):
    enqueue = Mock()
    monkeypatch.setattr(analytics, "enqueue", enqueue)
    db.responses[("web_purchase_intents", "update")] = [
        {"user_id": USER, "product": "plan:pro:monthly", "source": "billing_page"}
    ]
    res = client.get(f"/web-purchase/open?i={INTENT}", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == web_purchase.DEFAULT_APP_LINK
    _, op, _, filters = db.calls[0]
    assert op == "update"
    assert filters == {"id": INTENT, "is:app_link_opened_at": "null"}
    assert enqueue.call_args.args[:3] == ("Web App Link Clicked", USER, f"web-app-link:{INTENT}")
    assert enqueue.call_args.args[3]["method"] == "qr"
    client.get(f"/web-purchase/open?i={INTENT}&m=button", follow_redirects=False)
    assert enqueue.call_args.args[3]["method"] == "button"


@pytest.mark.parametrize("query", ["", "?i=not-a-uuid", "?i=https://evil.example"])
def test_open_with_bad_id_still_redirects_to_fixed_link(client, db, query):
    res = client.get(f"/web-purchase/open{query}", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == web_purchase.DEFAULT_APP_LINK
    assert db.calls == []


def test_open_survives_db_errors(client, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(web_purchase, "get_client", boom)
    res = client.get(f"/web-purchase/open?i={INTENT}", follow_redirects=False)
    assert res.status_code == 302


def test_app_link_env_must_be_https(monkeypatch):
    monkeypatch.setenv("APP_SMART_LINK", "javascript:alert(1)")
    assert web_purchase.app_link() == web_purchase.DEFAULT_APP_LINK
    monkeypatch.setenv("APP_SMART_LINK", "https://gemzy.co/get")
    assert web_purchase.app_link() == "https://gemzy.co/get"


def test_join_waitlist_keeps_first_join(client, db):
    db.responses[("web_purchase_waitlist", "select")] = [{"created_at": "2026-11-20T10:00:00Z"}]
    res = client.post("/web-purchase/waitlist", json={"product": "credits:700", "source": "credits_page"})
    assert res.json() == {"joined": True, "joinedAt": "2026-11-20T10:00:00Z"}
    table, op, (row, kwargs), _ = db.calls[0]
    assert (table, op) == ("web_purchase_waitlist", "upsert")
    assert row["user_id"] == USER
    assert kwargs == {"on_conflict": "user_id", "ignore_duplicates": True}


def test_get_waitlist_not_joined(client):
    assert client.get("/web-purchase/waitlist").json() == {"joined": False, "joinedAt": None}


def test_recent_intent_queries_the_seven_days_before_purchase(db):
    db.responses[("web_purchase_intents", "select")] = [{"product": "credits:300"}]
    purchased = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    assert web_purchase.recent_intent(USER, purchased) == {"product": "credits:300"}
    filters = db.calls[0][3]
    assert filters["gte:created_at"] == "2026-11-16T12:00:00+00:00"
    assert filters["lte:created_at"] == purchased.isoformat()


def test_app_purchase_is_tagged_with_web_intent(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    enqueue = Mock()
    monkeypatch.setattr(analytics, "enqueue", enqueue)
    monkeypatch.setattr(
        web_purchase,
        "recent_intent",
        lambda *_: {"product": "credits:300", "source": "out_of_credits", "created_at": "x"},
    )
    analytics.record_revenue({
        "id": "rc-1", "app_user_id": USER, "type": "NON_RENEWING_PURCHASE",
        "store": "APP_STORE", "purchased_at_ms": 1_795_000_000_000,
    })
    props = enqueue.call_args.args[3]
    assert props["web_purchase_intent_within_7d"] is True
    assert props["web_purchase_intent_product"] == "credits:300"


def test_renewals_are_not_attributed(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    enqueue = Mock()
    monkeypatch.setattr(analytics, "enqueue", enqueue)
    lookup = Mock()
    monkeypatch.setattr(web_purchase, "recent_intent", lookup)
    analytics.record_revenue({"id": "rc-2", "app_user_id": USER, "type": "RENEWAL"})
    lookup.assert_not_called()
    assert "web_purchase_intent_within_7d" not in enqueue.call_args.args[3]
