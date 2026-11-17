from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server import analytics
from server.generation_state import GenerationJob

USER = "456061a1-3a93-40aa-9c40-946c26aa64ba"


@pytest.fixture(autouse=True)
def enable(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")


def test_registration_does_not_depend_on_missing_profile(monkeypatch):
    sb = Mock()
    monkeypatch.setattr(analytics, "get_service_role_client", lambda: sb)
    analytics.record_registration(USER, "email", "2026-11-16", {"followed_anonymous_demo": True})
    args = sb.rpc.call_args.args
    assert args[0] == "record_analytics_registration"
    assert args[1]["p_event_id"] == analytics.registration_event_id(USER)
    assert args[1]["p_properties"]["application_context_received"] is True


@pytest.mark.parametrize("kind,period,expected", [
    ("INITIAL_PURCHASE", "TRIAL", "Trial Started"),
    ("INITIAL_PURCHASE", "NORMAL", "Subscription Purchase Completed"),
    ("RENEWAL", "NORMAL", "Subscription Renewed"),
    ("CANCELLATION", "NORMAL", "Subscription Canceled"),
    ("NON_RENEWING_PURCHASE", None, "Credit Pack Purchase Completed"),
])
def test_revenue_mapping_and_stable_retry_key(monkeypatch, kind, period, expected):
    enqueue = Mock()
    monkeypatch.setattr(analytics, "enqueue", enqueue)
    event = {"id": "rc-event-1", "app_user_id": USER, "type": kind, "period_type": period}
    analytics.record_revenue(event)
    analytics.record_revenue(event)
    assert enqueue.call_args_list[0] == enqueue.call_args_list[1]
    assert enqueue.call_args.args[:3] == (expected, USER, "revenuecat:rc-event-1")


def test_revenue_ignores_unmapped_store_anonymous_customer(monkeypatch):
    enqueue = Mock()
    monkeypatch.setattr(analytics, "enqueue", enqueue)
    analytics.record_revenue({"id": "1", "app_user_id": "$RCAnonymousID:1", "type": "RENEWAL"})
    enqueue.assert_not_called()


def test_generation_counts_requests_outputs_and_net_credits(monkeypatch):
    enqueue = Mock()
    monkeypatch.setattr(analytics, "enqueue", enqueue)
    start = datetime(2026, 11, 16)
    job = GenerationJob(id="request-1", user_id=USER, total_looks=100, status="completed",
                        created_at=start, updated_at=start + timedelta(seconds=4),
                        results=[object()] * 100, reserved_credit_cost=200, refunded_credit_cost=4,
                        analytics_context={"jewelry_ids": ["jewelry-1"]}, quality="2K")
    analytics.record_generation(job, terminal=True)
    enqueue.assert_called_once()
    event, distinct_id, key, props, timestamp = enqueue.call_args.args
    assert event == "Generation Completed"
    assert distinct_id == USER
    assert props["output_count"] == 100
    assert props["jewelry_ids"] == ["jewelry-1"]
    assert props["credits_consumed"] == 196
    assert props["duration_ms"] == 4000
    assert props["event_unit"] == "generation_request"


def test_demo_uses_original_anonymous_identity(monkeypatch):
    enqueue = Mock()
    monkeypatch.setattr(analytics, "enqueue", enqueue)
    job = GenerationJob(id="demo-1", user_id="guest:demo-1", total_looks=2,
                        analytics_context={"anonymous_id": "sdk-anon-1"})
    analytics.record_generation(job)
    assert enqueue.call_count == 2
    assert all(call.args[1] == "sdk-anon-1" for call in enqueue.call_args_list)
    assert enqueue.call_args.args[0] == "Demo Generation Started"


def test_generation_ignores_non_supabase_authenticated_identity(monkeypatch):
    enqueue = Mock()
    monkeypatch.setattr(analytics, "enqueue", enqueue)
    job = GenerationJob(id="test-job", user_id="user-123", total_looks=1)
    analytics.record_generation(job)
    enqueue.assert_not_called()


def test_delivery_keeps_events_pending_on_network_failure(monkeypatch):
    monkeypatch.setenv("POSTHOG_API_KEY", "test-key")
    query = Mock()
    query.select.return_value.is_.return_value.lt.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[{
        "id": analytics.event_id("1"), "event": "Signup Completed", "distinct_id": USER,
        "properties": {}, "occurred_at": "2026-11-16T00:00:00Z",
    }])
    sb = Mock()
    sb.table.return_value = query
    monkeypatch.setattr(analytics, "get_service_role_client", lambda: sb)
    monkeypatch.setattr(analytics.httpx, "post", Mock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="offline"):
        analytics.drain_outbox()
    query.update.assert_not_called()


def test_context_enrichment_failure_does_not_fail_authentication(monkeypatch):
    monkeypatch.setattr(analytics, "get_service_role_client", Mock(side_effect=RuntimeError("offline")))
    analytics.record_registration(USER, "google", None, {})


def test_delivery_preserves_uuid_and_occurrence_time(monkeypatch):
    monkeypatch.setenv("POSTHOG_API_KEY", "test-key")
    query = Mock()
    row = {"id": analytics.event_id("retry"), "event": "Signup Completed", "distinct_id": USER,
           "properties": {}, "occurred_at": "2026-11-16T00:00:00Z"}
    query.select.return_value.is_.return_value.lt.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[row])
    sb = Mock()
    sb.table.return_value = query
    monkeypatch.setattr(analytics, "get_service_role_client", lambda: sb)
    post = Mock()
    monkeypatch.setattr(analytics.httpx, "post", post)
    assert analytics.drain_outbox() == 1
    payload = post.call_args.kwargs["json"]["batch"][0]
    assert payload["uuid"] == row["id"]
    assert payload["timestamp"] == row["occurred_at"]
    query.update.assert_called_once()


def test_terminal_snapshot_retries_after_enqueue_failure(monkeypatch):
    from server import generation_state
    record = Mock(side_effect=RuntimeError("database unavailable"))
    monkeypatch.setattr(generation_state, "record_generation", record)
    job = GenerationJob(id="failed-1", user_id=USER, total_looks=1, status="failed")
    with pytest.raises(RuntimeError):
        generation_state.to_response(job, strict_analytics=True)
    assert job.analytics_terminal_pending
    assert not job.analytics_terminal_recorded
    record.side_effect = None
    generation_state.to_response(job, strict_analytics=True)
    assert job.analytics_terminal_recorded
    calls = record.call_count
    generation_state.to_response(job)
    assert record.call_count == calls


def test_revenue_webhook_requires_configured_auth_when_analytics_enabled(monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from server import payments
    monkeypatch.setattr(payments, "RC_WEBHOOK_AUTH", None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(payments.rc_webhook(SimpleNamespace(headers={})))
    assert error.value.status_code == 503
