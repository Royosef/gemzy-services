from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from postgrest.exceptions import APIError

from server.user_admin import (
    clear_user_deactivation,
    process_due_credit_resets,
    process_due_user_deletions,
    schedule_user_deletion,
    update_user_metadata,
)


class FakeResponse:
    def __init__(self, data=None):
        self.data = data


class FakeTable:
    def __init__(self, client, name: str):
        self._client = client
        self._name = name
        self._operation = None
        self._filters: list[tuple[str, str, object]] = []
        self._limit = None

    def upsert(self, data, on_conflict=None):
        self._operation = ("upsert", data, on_conflict)
        return self

    def update(self, data):
        self._operation = ("update", data)
        return self

    def delete(self):
        self._operation = ("delete", None)
        return self

    def select(self, columns="*"):
        self._operation = ("select", columns)
        return self

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def lte(self, column, value):
        self._filters.append(("lte", column, value))
        return self

    def order(self, column, *, desc=False, nullsfirst=None, foreign_table=None):
        self._order = {
            "column": column,
            "desc": desc,
            "nullsfirst": nullsfirst,
            "foreign_table": foreign_table,
        }
        return self

    def limit(self, value):
        self._limit = value
        return self

    def execute(self):
        self._client.calls.append(
            {
                "table": self._name,
                "operation": self._operation,
                "filters": list(self._filters),
                "limit": self._limit,
                "order": getattr(self, "_order", None),
            }
        )
        if (
            getattr(self._client, "fail_on_cancelled_at", False)
            and self._operation
            and self._operation[0] == "update"
            and isinstance(self._operation[1], dict)
            and "cancelled_at" in self._operation[1]
        ):
            raise APIError('column "cancelled_at" does not exist')
        if self._operation and self._operation[0] == "select":
            data = self._client.select_data.get(self._name, [])
            return FakeResponse(data=data)
        return FakeResponse()


class FakeAdmin:
    def __init__(self, metadata=None):
        self.metadata = metadata or {}
        self.updated = None
        self.deleted: list[str] = []

    def get_user_by_id(self, user_id: str):
        return SimpleNamespace(user=SimpleNamespace(user_metadata=dict(self.metadata)))

    def delete_user(self, user_id: str):
        self.deleted.append(user_id)


class NewAdmin(FakeAdmin):
    def update_user_by_id(self, user_id: str, attributes=None):
        self.updated = (user_id, attributes)


class UnauthorizedAdmin(FakeAdmin):
    def update_user_by_id(self, user_id: str, attributes=None):
        raise Exception("supabase user not allowed not admin")


class FakeSupabase:
    def __init__(self, admin, select_data=None):
        self.auth = SimpleNamespace(admin=admin)
        self.calls: list[dict] = []
        self.select_data = select_data or {}
        self.fail_on_cancelled_at = False

    def table(self, name: str):
        return FakeTable(self, name)


def test_update_user_metadata_prefers_new_signature():
    admin = NewAdmin()
    client = FakeSupabase(admin)

    update_user_metadata("user-1", {"hello": "world"}, client=client)

    assert admin.updated == (
        "user-1",
        {"user_metadata": {"hello": "world"}},
    )


def test_schedule_user_deletion_enqueues_and_updates_metadata():
    admin = NewAdmin(metadata={"plan": "Pro"})
    client = FakeSupabase(admin)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    scheduled = schedule_user_deletion(
        "user-1", grace_days=10, now=now, client=client
    )

    assert scheduled == now + timedelta(days=10)
    # First call inserts into the queue table
    queue_call = next(
        call for call in client.calls if call["operation"] and call["operation"][0] == "upsert"
    )
    record = queue_call["operation"][1]
    assert record["user_id"] == "user-1"
    assert record["scheduled_for"].endswith("Z")
    # Metadata retains the original plan and gains deletion flags
    assert admin.updated[1]["user_metadata"]["plan"] == "Pro"
    assert admin.updated[1]["user_metadata"]["deactivated"] is True

    profile_update = next(
        call for call in client.calls if call["table"] == "profiles"
    )
    assert profile_update["operation"][0] == "update"


def test_process_due_user_deletions_executes_hard_delete():
    admin = NewAdmin()
    client = FakeSupabase(
        admin,
        select_data={"user_deletion_queue": [{"user_id": "user-1"}]},
    )
    now = datetime(2024, 2, 1, tzinfo=timezone.utc)

    processed = process_due_user_deletions(
        now=now, client=client, bucket_overrides=[]
    )

    assert processed == 1
    assert admin.deleted == ["user-1"]
    assert any(
        call
        for call in client.calls
        if call["table"] == "user_deletion_queue"
        and call["operation"][0] == "update"
    )


def test_process_due_credit_resets_only_queries_due_rows(monkeypatch):
    admin = NewAdmin(metadata={"plan": "Pro"})
    client = FakeSupabase(
        admin,
        select_data={
            "profiles": [{"id": "user-1", "plan": "Pro", "next_credit_reset_at": "2024-01-01T00:00:00Z"}]
        },
    )

    monkeypatch.setattr("server.plans.get_plan_initial_credits", lambda *_: 120)

    processed = process_due_credit_resets(
        now=datetime(2024, 2, 1, tzinfo=timezone.utc),
        client=client,
    )

    assert processed == 1
    assert admin.updated is None
    select_call = next(
        call
        for call in client.calls
        if call["table"] == "profiles" and call["operation"][0] == "select"
    )
    assert ("lte", "next_credit_reset_at", "2024-02-01T00:00:00+00:00") in select_call["filters"]
    assert select_call["order"]["column"] == "next_credit_reset_at"
    assert select_call["order"]["nullsfirst"] is None


def test_clear_user_deactivation_updates_metadata_and_profile():
    admin = NewAdmin(
        metadata={"deactivated": True, "deactivatedAt": "2024-01-01T00:00:00Z"}
    )
    profile = {"deactivated_at": "2024-01-01T00:00:00Z"}
    client = FakeSupabase(admin)
    now = datetime(2024, 3, 1, tzinfo=timezone.utc)

    metadata, updated_profile, reactivated_at = clear_user_deactivation(
        "user-1", metadata=admin.metadata, profile=profile, now=now, client=client
    )

    assert metadata["deactivated"] is False
    assert metadata["deactivatedAt"] is None
    assert metadata["reactivatedAt"].endswith("Z")
    assert metadata["deleteCancelledAt"].endswith("Z")
    assert metadata["deleteRequestedAt"] is None
    assert metadata["deleteScheduledFor"] is None
    assert metadata["deleteGracePeriodDays"] is None
    assert reactivated_at == metadata["reactivatedAt"]
    assert updated_profile is not None
    assert updated_profile["deactivated_at"] is None
    assert admin.updated == (
        "user-1",
        {
            "user_metadata": {
                "deactivated": False,
                "deactivatedAt": None,
                "reactivatedAt": metadata["reactivatedAt"],
                "deleteCancelledAt": metadata["deleteCancelledAt"],
                "deleteRequestedAt": None,
                "deleteScheduledFor": None,
                "deleteGracePeriodDays": None,
            }
        },
    )
    profile_update = next(
        call
        for call in client.calls
        if call["table"] == "profiles" and call["operation"][0] == "update"
    )
    assert profile_update["operation"][1] == {"deactivated_at": None}


def test_clear_user_deactivation_cancels_queue_without_timestamp_column():
    admin = NewAdmin(
        metadata={"deactivated": True, "deactivatedAt": "2024-01-01T00:00:00Z"}
    )
    client = FakeSupabase(admin)
    client.fail_on_cancelled_at = True

    metadata, _, reactivated_at = clear_user_deactivation(
        "user-1",
        metadata=dict(admin.metadata),
        profile={"deactivated_at": "2024-01-01T00:00:00Z"},
        now=datetime(2024, 3, 1, tzinfo=timezone.utc),
        client=client,
    )

    assert metadata["deactivated"] is False
    assert reactivated_at is not None

    queue_calls = [
        call for call in client.calls if call["table"] == "user_deletion_queue"
    ]
    assert len(queue_calls) == 2

    status_call = queue_calls[0]["operation"]
    assert status_call[0] == "update"
    assert status_call[1]["status"] == "cancelled"
    assert "cancelled_at" not in status_call[1]

    cancelled_call = queue_calls[1]["operation"]
    assert cancelled_call[0] == "update"
    assert "cancelled_at" in cancelled_call[1]


def test_clear_user_deactivation_recovers_from_user_scoped_client(monkeypatch):
    metadata = {
        "deactivated": True,
        "deactivatedAt": "2024-01-01T00:00:00Z",
    }
    user_admin = UnauthorizedAdmin(metadata=metadata)
    user_client = FakeSupabase(user_admin)
    service_admin = NewAdmin(metadata=metadata)
    service_client = FakeSupabase(service_admin)

    calls = []

    def fake_get_service_role_client(fresh=False):
        calls.append(fresh)
        return service_client

    monkeypatch.setattr(
        "server.user_admin.get_service_role_client", fake_get_service_role_client
    )

    metadata_out, profile_out, timestamp = clear_user_deactivation(
        "user-1",
        metadata=dict(metadata),
        profile={"deactivated_at": "2024-01-01T00:00:00Z"},
        now=datetime(2024, 3, 1, tzinfo=timezone.utc),
        client=user_client,
    )

    assert service_admin.updated[0] == "user-1"
    assert metadata_out["deactivated"] is False
    assert timestamp is not None
    # Fallback should have been invoked exactly once with a fresh client.
    assert calls == [True]
    assert profile_out["deactivated_at"] is None


def test_clear_user_deactivation_noop_when_active():
    admin = NewAdmin(metadata={"plan": "Pro"})
    client = FakeSupabase(admin)

    metadata, updated_profile, reactivated_at = clear_user_deactivation(
        "user-1", metadata=admin.metadata, profile={}, client=client
    )

    assert metadata["plan"] == "Pro"
    assert updated_profile == {}
    assert reactivated_at is None
    assert admin.updated is None
    assert not any(call for call in client.calls if call["table"] == "user_deletion_queue")
