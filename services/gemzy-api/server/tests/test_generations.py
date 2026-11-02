"""Tests for the generation routing module."""

from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server import generations
from server.generation_state import GenerationJob, reset_jobs
from server.schemas import UserState


@pytest.fixture(autouse=True)
def _reset_generation_rate_limiter() -> None:
    """Keep route-level limiter state from leaking across tests."""

    generations.limiter.reset()

@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a test client for the generation router."""

    app = FastAPI()
    app.include_router(generations.router)
    current_user = UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=20,
    )
    app.dependency_overrides[generations.get_current_user] = lambda: current_user
    app.dependency_overrides[generations.get_optional_current_user] = lambda: current_user
    test_client = TestClient(app)
    credit_client = _CreditClient(credits={"user-123": 20})
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)
    monkeypatch.setattr(
        "server.generations._persist_generation_result",
        lambda job, result: result,
    )
    reset_jobs()
    return test_client


@pytest.fixture
def generation_payload() -> dict[str, Any]:
    """Base payload for generation requests used across tests."""

    return {
        "generationServerUrl": "https://override.example",
        "uploads": [
            {
                "id": "upload-1",
                "uri": "https://cdn.example/image.png",
                "base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5W8YQAAAAASUVORK5CYII=",
                "mimeType": "image/png",
                "fileSize": 12345,
                "width": 512,
                "height": 768,
                "name": "image.png",
            }
        ],
        "model": {
            "id": "model-1",
            "slug": "model-slug",
            "name": "Model Name",
            "planTier": "Pro",
            "highlight": None,
            "description": None,
            "tags": ["tag"],
            "spotlightTag": None,
            "imageUri": "https://cdn.example/model.png",
            "imageBase64": None,
        },
        "style": {"tone": "warm"},
        "mode": "ADVANCED",
        "aspect": "16:9",
        "dims": {"w": 1280, "h": 720},
        "looks": 4,
        "quality": "1080p",
        "plan": "Pro",
        "creditsNeeded": 2,
    }


def test_generation_style_resolves_server_managed_fields_from_preset(
    monkeypatch: pytest.MonkeyPatch,
    generation_payload: dict[str, Any],
) -> None:
    preset_id = "0d4cb132-fdd7-4a22-ac19-b67d30a51553"
    monkeypatch.setattr(
        generations,
        "get_client",
        lambda: _PresetClient(
            [
                {
                    "id": preset_id,
                    "task_key": "on-model",
                    "style": {
                        "creative_direction": "SERVER CURATED DIRECTION",
                        "creative_exclusions": "SERVER CURATED EXCLUSIONS",
                        "creative_variation_lanes": "SERVER LANE ONE||SERVER LANE TWO",
                        "creative_object_territory": "Jewelry Presentation Box",
                    },
                }
            ]
        ),
    )
    generation_payload["presetId"] = preset_id
    generation_payload["style"] = {
        "task_type": "on-model",
        "background": "Warm Interior",
        "creative_direction": "CLIENT OVERRIDE",
    }
    payload = generations.CreateGenerationPayload.model_validate(generation_payload)

    resolved = generations._resolve_generation_style(payload)

    assert resolved["background"] == "Warm Interior"
    assert resolved["creative_direction"] == "SERVER CURATED DIRECTION"
    assert resolved["creative_exclusions"] == "SERVER CURATED EXCLUSIONS"
    assert resolved["creative_variation_lanes"] == "SERVER LANE ONE||SERVER LANE TWO"
    assert resolved["creative_object_territory"] == "Jewelry Presentation Box"


def test_generation_style_drops_server_managed_fields_without_preset(
    generation_payload: dict[str, Any],
) -> None:
    generation_payload["style"] = {
        "task_type": "on-model",
        "creative_direction": "CLIENT ONLY DIRECTION",
    }
    payload = generations.CreateGenerationPayload.model_validate(generation_payload)

    resolved = generations._resolve_generation_style(payload)

    assert "creative_direction" not in resolved


def test_generation_style_rejects_preset_for_another_task(
    monkeypatch: pytest.MonkeyPatch,
    generation_payload: dict[str, Any],
) -> None:
    preset_id = "0d4cb132-fdd7-4a22-ac19-b67d30a51553"
    monkeypatch.setattr(
        generations,
        "get_client",
        lambda: _PresetClient(
            [
                {
                    "id": preset_id,
                    "task_key": "pure-jewelry",
                    "style": {"creative_direction": "WRONG TASK"},
                }
            ]
        ),
    )
    generation_payload["presetId"] = preset_id
    generation_payload["style"] = {"task_type": "on-model"}
    payload = generations.CreateGenerationPayload.model_validate(generation_payload)

    with pytest.raises(HTTPException) as exc_info:
        generations._resolve_generation_style(payload)

    assert exc_info.value.status_code == 400


class _MockResponse:
    def __init__(self, status_code: int = 200, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {
            "id": "gen-123",
            "status": "queued",
            "results": [{"url": "https://cdn.example/results/gen-123.png"}],
        }
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._payload


class _MockAsyncClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def __aenter__(self) -> "_MockAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    async def post(
        self, url: str, json: dict[str, Any], headers: dict[str, Any] | None = None
    ) -> _MockResponse:
        self.calls.append((url, json, headers or {}))
        return _MockResponse()


class _PresetQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def select(self, _columns: str) -> "_PresetQuery":
        return self

    def eq(self, _column: str, _value: Any) -> "_PresetQuery":
        return self

    def limit(self, _value: int) -> "_PresetQuery":
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self._rows)


class _PresetClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def table(self, name: str) -> _PresetQuery:
        assert name == "creation_look_presets"
        return _PresetQuery(self._rows)


class _CreditTable:
    def __init__(self, client, name: str):
        self._client = client
        self._name = name
        self._operation = None
        self._filters: list[tuple[str, Any]] = []

    def select(self, columns: str):
        self._operation = ("select", columns)
        return self

    def update(self, data: dict[str, Any], count: str | None = None, returning: Any = None):
        self._operation = ("update", data, count)
        return self

    def insert(self, data: dict[str, Any]):
        self._operation = ("insert", data)
        return self

    def eq(self, column: str, value: Any):
        self._filters.append((column, value))
        return self

    def limit(self, value: int):
        return self

    def execute(self):
        if self._name == "image_edit_feedback":
            if self._operation and self._operation[0] == "insert":
                self._client.feedback_rows.append(self._operation[1])
                return SimpleNamespace(data=[self._operation[1]], count=1)
            return SimpleNamespace(data=[], count=0)

        user_id = next((value for column, value in self._filters if column == "id"), None)
        if self._operation and self._operation[0] == "select":
            if user_id not in self._client.credits:
                return SimpleNamespace(data=[])
            return SimpleNamespace(
                data=[
                    {
                        "credits": self._client.credits[user_id],
                        "trial_credits": self._client.trial_credits.get(user_id, 0),
                        "purchased_credits": self._client.purchased_credits.get(user_id, 0),
                        "edit_mode_trial_edits_remaining": self._client.edit_trials.get(user_id, 0),
                    }
                ],
                count=1,
            )

        if self._operation and self._operation[0] == "update":
            expected = next((value for column, value in self._filters if column == "credits"), None)
            expected_trial = next((value for column, value in self._filters if column == "trial_credits"), None)
            expected_purchased = next((value for column, value in self._filters if column == "purchased_credits"), None)
            expected_trials = next((value for column, value in self._filters if column == "edit_mode_trial_edits_remaining"), None)
            current = self._client.credits.get(user_id)
            current_trial = self._client.trial_credits.get(user_id, 0)
            current_purchased = self._client.purchased_credits.get(user_id, 0)
            current_trials = self._client.edit_trials.get(user_id, 0)
            if self._client.fail_first_update:
                self._client.fail_first_update = False
                self._client.credits[user_id] = self._client.concurrent_credit_value
                self._client.purchased_credits[user_id] = 0
                return SimpleNamespace(data=[], count=0)
            if (
                current is None
                or (expected is not None and current != expected)
                or (expected_trial is not None and current_trial != expected_trial)
                or (expected_purchased is not None and current_purchased != expected_purchased)
                or (expected_trials is not None and current_trials != expected_trials)
            ):
                return SimpleNamespace(data=[], count=0)
            if "credits" in self._operation[1]:
                self._client.credits[user_id] = self._operation[1]["credits"]
            if "trial_credits" in self._operation[1]:
                self._client.trial_credits[user_id] = self._operation[1]["trial_credits"]
            self._client.purchased_credits[user_id] = self._operation[1].get("purchased_credits", current_purchased)
            if "edit_mode_trial_edits_remaining" in self._operation[1]:
                self._client.edit_trials[user_id] = self._operation[1]["edit_mode_trial_edits_remaining"]
            return SimpleNamespace(
                data=[
                    {
                        "credits": self._client.credits[user_id],
                        "trial_credits": self._client.trial_credits.get(user_id, 0),
                        "purchased_credits": self._client.purchased_credits[user_id],
                        "edit_mode_trial_edits_remaining": self._client.edit_trials[user_id],
                    }
                ],
                count=1,
            )

        return SimpleNamespace(data=[], count=0)


class _CreditClient:
    def __init__(
        self,
        *,
        credits: dict[str, int],
        trial_credits: dict[str, int] | None = None,
        purchased_credits: dict[str, int] | None = None,
        edit_trials: dict[str, int] | None = None,
        fail_first_update: bool = False,
        concurrent_credit_value: int = 0,
    ) -> None:
        self.credits = dict(credits)
        self.trial_credits = dict(trial_credits or {})
        self.purchased_credits = dict(purchased_credits or {})
        self.edit_trials = dict(edit_trials or {user_id: 0 for user_id in credits})
        self.feedback_rows: list[dict[str, Any]] = []
        self.generation_refunds: dict[str, tuple[str, int]] = {}
        self.fail_first_update = fail_first_update
        self.concurrent_credit_value = concurrent_credit_value

    def table(self, name: str) -> _CreditTable:
        assert name in {"profiles", "image_edit_feedback"}
        return _CreditTable(self, name)

    def rpc(self, name: str, params: dict[str, Any]):
        assert name == "refund_generation_credits"
        client = self

        class _RefundRpc:
            def execute(self):
                job_id = params["p_job_id"]
                user_id = params["p_user_id"]
                target = max(0, int(params["p_target_refunded_credits"]))
                existing_user, refunded = client.generation_refunds.get(
                    job_id,
                    (user_id, 0),
                )
                if existing_user != user_id:
                    raise RuntimeError("Generation refund owner mismatch")
                delta = max(0, target - refunded)
                client.credits[user_id] += delta
                persisted_refunded = refunded + delta
                client.generation_refunds[job_id] = (
                    user_id,
                    persisted_refunded,
                )
                return SimpleNamespace(
                    data=[
                        {
                            "remaining_credits": client.credits[user_id]
                            + client.purchased_credits.get(user_id, 0),
                            "refunded_credits": persisted_refunded,
                        }
                    ]
                )

        return _RefundRpc()


def test_generation_request_forwards_payload(monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]) -> None:
    """The route should forward the payload to the resolved generation server."""

    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_SERVER_ENDPOINT", "/submit")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")
    monkeypatch.delenv("GENERATION_SERVER_TIMEOUT", raising=False)

    mock_client = _MockAsyncClient()
    configured_timeouts: list[float] = []

    def _client_factory(*_args: Any, **kwargs: Any) -> _MockAsyncClient:
        configured_timeouts.append(float(kwargs["timeout"]))
        return mock_client

    monkeypatch.setattr("server.generations.httpx.AsyncClient", _client_factory)

    response = client.post("/generations", json=generation_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["results"], "Expected at least one generation result"
    first_result = body["results"][0]
    assert first_result["url"] == "https://cdn.example/results/gen-123.png"
    assert first_result.get("base64") is None
    assert body["totalLooks"] == 4
    assert body["progress"] == pytest.approx(body["completedLooks"] / body["totalLooks"])

    assert mock_client.calls, "Expected AsyncClient.post to be called"
    url, forwarded, headers = mock_client.calls[0]
    assert url == "https://override.example/submit"
    assert "request" in forwarded and "user" in forwarded
    assert forwarded["job"]["callbackUrl"] == f"https://app.example/generations/{body['id']}/events"
    assert forwarded["job"]["looks"] == 4
    assert "generationServerUrl" not in forwarded["request"]
    assert forwarded["request"]["quality"] == "1k"
    assert forwarded["request"]["style"]["task_type"] == "on-model"
    assert forwarded["user"]["id"] == "user-123"
    assert forwarded["request"]["model"]["imageUri"] == "https://cdn.example/model.png"
    assert headers["X-Generation-Secret"] == "secret"
    assert configured_timeouts == [120.0]


def test_ftue_guest_intent_wins_over_transitional_authenticated_session(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    generation_payload: dict[str, Any],
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_SERVER_ENDPOINT", "/submit")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setattr(generations, "_check_guest_generation_quota", lambda _request: None)
    mock_client = _MockAsyncClient()
    monkeypatch.setattr(
        "server.generations.httpx.AsyncClient",
        lambda *args, **kwargs: mock_client,
    )

    payload = dict(generation_payload)
    payload.update(
        {
            "generationServerUrl": None,
            "style": {"task_type": "on-model", "onboarding_guest": "true"},
            "aspect": "1:1",
            "dims": {"w": 1080, "h": 1080},
            "looks": generations.GUEST_GENERATION_LOOKS,
            "quality": generations.GUEST_GENERATION_QUALITY,
            "items": [
                {
                    "id": "item-1",
                    "type": "ring",
                    "size": "small",
                    "uploadId": "upload-1",
                }
            ],
        }
    )

    response = client.post("/generations", json=payload)

    assert response.status_code == 200
    forwarded_user = mock_client.calls[0][1]["user"]
    assert forwarded_user["id"].startswith("guest:")
    assert forwarded_user["id"] != "user-123"


def test_ftue_guest_retry_allows_only_missing_look(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    generation_payload: dict[str, Any],
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_SERVER_ENDPOINT", "/submit")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setattr(generations, "_check_guest_generation_quota", lambda _request: None)
    mock_client = _MockAsyncClient()
    monkeypatch.setattr(
        "server.generations.httpx.AsyncClient",
        lambda *args, **kwargs: mock_client,
    )

    payload = dict(generation_payload)
    payload.update(
        {
            "generationServerUrl": None,
            "style": {
                "task_type": "on-model",
                "onboarding_guest": "true",
                "onboarding_guest_retry": "true",
            },
            "aspect": "1:1",
            "dims": {"w": 1080, "h": 1080},
            "looks": 1,
            "quality": generations.GUEST_GENERATION_QUALITY,
            "items": [
                {
                    "id": "item-1",
                    "type": "ring",
                    "size": "small",
                    "uploadId": "upload-1",
                }
            ],
        }
    )

    response = client.post("/generations", json=payload)

    assert response.status_code == 200
    forwarded_request = mock_client.calls[0][1]["request"]
    assert forwarded_request["looks"] == 1
    assert forwarded_request["style"]["onboarding_guest_retry"] == "true"


def test_ftue_guest_request_cannot_customize_look_count_without_retry_marker(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    generation_payload: dict[str, Any],
) -> None:
    monkeypatch.setattr(generations, "_check_guest_generation_quota", lambda _request: None)
    payload = dict(generation_payload)
    payload.update(
        {
            "generationServerUrl": None,
            "style": {"task_type": "on-model", "onboarding_guest": "true"},
            "aspect": "1:1",
            "dims": {"w": 1080, "h": 1080},
            "looks": 1,
            "quality": generations.GUEST_GENERATION_QUALITY,
            "items": [
                {
                    "id": "item-1",
                    "type": "ring",
                    "size": "small",
                    "uploadId": "upload-1",
                }
            ],
        }
    )

    response = client.post("/generations", json=payload)

    assert response.status_code == 403
    assert response.json()["detail"] == "Sign up to customize image count."


def test_adjust_profile_credits_retries_after_compare_and_set_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    credit_client = _CreditClient(
        credits={"user-123": 10},
        fail_first_update=True,
        concurrent_credit_value=8,
    )
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    remaining = generations._adjust_profile_credits("user-123", -4)

    assert remaining == 4
    assert credit_client.credits["user-123"] == 4


def test_adjust_profile_credits_spends_purchased_credits_after_monthly(monkeypatch: pytest.MonkeyPatch) -> None:
    credit_client = _CreditClient(
        credits={"user-123": 3},
        purchased_credits={"user-123": 8},
    )
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    remaining = generations._adjust_profile_credits("user-123", -5)

    assert remaining == 6
    assert credit_client.credits["user-123"] == 0
    assert credit_client.purchased_credits["user-123"] == 6


def test_adjust_profile_credits_spends_trial_credits_first(monkeypatch: pytest.MonkeyPatch) -> None:
    credit_client = _CreditClient(
        credits={"user-123": 0},
        trial_credits={"user-123": 6},
        purchased_credits={"user-123": 8},
    )
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    remaining = generations._adjust_profile_credits("user-123", -10)

    assert remaining == 4
    assert credit_client.trial_credits["user-123"] == 0
    assert credit_client.credits["user-123"] == 0
    assert credit_client.purchased_credits["user-123"] == 4


def test_image_edit_uses_free_trial_before_charging_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    app.dependency_overrides[generations.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=20,
        editModeTrialEditsRemaining=2,
    )
    test_client = TestClient(app)
    credit_client = _CreditClient(
        credits={"user-123": 20},
        edit_trials={"user-123": 2},
    )
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: _MockAsyncClient())
    monkeypatch.setattr("server.generations._persist_generation_result", lambda job, result: result)
    monkeypatch.setattr("server.generations._publish_image_edit_completed_notification", lambda job: None)
    reset_jobs()

    response = test_client.post("/generations/edits", json=_image_edit_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["editTrialApplied"] is True
    assert body["editModeTrialEditsRemaining"] == 1
    assert body["remainingCredits"] == 20
    assert body["editCreditCost"] == 0
    assert credit_client.credits["user-123"] == 20
    assert credit_client.edit_trials["user-123"] == 1


def test_image_edit_charges_credits_after_trials_are_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    app.dependency_overrides[generations.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=20,
        editModeTrialEditsRemaining=0,
    )
    test_client = TestClient(app)
    credit_client = _CreditClient(
        credits={"user-123": 20},
        edit_trials={"user-123": 0},
    )
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: _MockAsyncClient())
    monkeypatch.setattr("server.generations._persist_generation_result", lambda job, result: result)
    monkeypatch.setattr("server.generations._publish_image_edit_completed_notification", lambda job: None)
    reset_jobs()

    response = test_client.post("/generations/edits", json=_image_edit_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["editTrialApplied"] is False
    assert body["editModeTrialEditsRemaining"] is None
    assert body["remainingCredits"] == 16
    assert body["editCreditCost"] == 4
    assert credit_client.credits["user-123"] == 16
    assert credit_client.edit_trials["user-123"] == 0


def test_image_edit_upscale_charges_as_4k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    app.dependency_overrides[generations.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=20,
        editModeTrialEditsRemaining=0,
    )
    test_client = TestClient(app)
    credit_client = _CreditClient(
        credits={"user-123": 20},
        edit_trials={"user-123": 0},
    )
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: _MockAsyncClient())
    monkeypatch.setattr("server.generations._persist_generation_result", lambda job, result: result)
    monkeypatch.setattr("server.generations._publish_image_edit_completed_notification", lambda job: None)
    reset_jobs()

    payload = _image_edit_payload()
    payload["quality"] = "2K"
    payload["edits"] = ["upscale_image"]

    response = test_client.post("/generations/edits", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["editTrialApplied"] is False
    assert body["remainingCredits"] == 13
    assert body["editCreditCost"] == 7
    assert credit_client.credits["user-123"] == 13


def test_image_edit_targets_source_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    app.dependency_overrides[generations.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=20,
        editModeTrialEditsRemaining=0,
    )
    test_client = TestClient(app)
    credit_client = _CreditClient(
        credits={"user-123": 20},
        edit_trials={"user-123": 0},
    )
    checked_collections: list[tuple[str, list[str]]] = []
    target_collections: list[str | None] = []

    def _persist(job: GenerationJob, result: generations.GenerationResultPayload):
        target_collections.append(job.unsaved_collection_id)
        return result.model_copy(update={"collectionId": job.unsaved_collection_id})

    payload = _image_edit_payload()
    payload["source"]["collectionId"] = "collection-123"
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: _MockAsyncClient())
    monkeypatch.setattr("server.generations._persist_generation_result", _persist)
    monkeypatch.setattr("server.generations._publish_image_edit_completed_notification", lambda job: None)
    monkeypatch.setattr(
        "server.generations._ensure_collections_belong",
        lambda user_id, ids: checked_collections.append((user_id, ids)),
    )
    reset_jobs()

    response = test_client.post("/generations/edits", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert checked_collections == [("user-123", ["collection-123"])]
    assert target_collections == ["collection-123"]
    assert body["results"][0]["collectionId"] == "collection-123"


def test_image_edit_prefers_storage_backed_source_upload_over_client_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    app.dependency_overrides[generations.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=20,
        editModeTrialEditsRemaining=0,
    )
    test_client = TestClient(app)
    credit_client = _CreditClient(
        credits={"user-123": 20},
        edit_trials={"user-123": 0},
    )
    mock_client = _MockAsyncClient()

    class _Blob:
        content_type = "image/png"
        size = 68

        def download_as_bytes(self) -> bytes:
            return base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5W8YQAAAAASUVORK5CYII="
            )

    class _Bucket:
        def blob(self, name: str) -> _Blob:
            assert name == "user-123/collections/source-image.png"
            return _Blob()

    monkeypatch.setattr(generations, "get_client", lambda: credit_client)
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)
    monkeypatch.setattr("server.generations._persist_generation_result", lambda job, result: result)
    monkeypatch.setattr("server.generations._publish_image_edit_completed_notification", lambda job: None)
    monkeypatch.setattr(generations, "_get_collections_bucket", lambda: _Bucket())
    reset_jobs()

    payload = _image_edit_payload()
    payload["sourceImage"]["base64"] = (
        "PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0nVVRGLTgnPz48RXJyb3I+PENvZGU+"
        "RXhwaXJlZFRva2VuPC9Db2RlPjxNZXNzYWdlPkludmFsaWQgYXJndW1lbnQuPC9NZXNzYWdl"
        "PjxEZXRhaWxzPlRoZSBwcm92aWRlZCB0b2tlbiBoYXMgZXhwaXJlZC48L0RldGFpbHM+PC9FcnJvcj4="
    )
    payload["source"]["storagePath"] = "user-123/collections/source-image.png"

    response = test_client.post("/generations/edits", json=payload)

    assert response.status_code == 200
    assert mock_client.calls, "Expected the image edit request to be forwarded"
    forwarded = mock_client.calls[0][1]["request"]
    assert (
        forwarded["uploads"][0]["base64"]
        == "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5W8YQAAAAASUVORK5CYII="
    )
    assert forwarded["uploads"][0]["mimeType"] == "image/png"
    assert forwarded["uploads"][0]["fileSize"] == 68


def test_image_edit_forwards_source_metadata_and_real_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    app.dependency_overrides[generations.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=20,
        editModeTrialEditsRemaining=0,
    )
    test_client = TestClient(app)
    credit_client = _CreditClient(
        credits={"user-123": 20},
        edit_trials={"user-123": 0},
    )
    mock_client = _MockAsyncClient()
    captured_jobs: list[GenerationJob] = []

    def _persist(job: GenerationJob, result: generations.GenerationResultPayload):
        captured_jobs.append(job)
        return result

    payload = _image_edit_payload()
    payload["source"].update(
        {
            "modelId": "model-zaya",
            "modelSlug": "zaya-editorial",
            "modelName": "Zaya Amune",
            "modelImageUri": "https://cdn.example/models/zaya.png",
            "modelImageBase64": "emF5YS1tb2RlbA==",
            "style": {
                "task_type": "on-model",
                "background": "Studio",
                "camera": "85mm Portrait",
            },
            "aspect": "4:5",
            "dims": {"w": 1080, "h": 1350},
            "quality": "2K",
        }
    )
    payload["aspect"] = "4:5"
    payload["dims"] = {"w": 1080, "h": 1350}
    payload["quality"] = "2K"

    monkeypatch.setattr(generations, "get_client", lambda: credit_client)
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)
    monkeypatch.setattr("server.generations._persist_generation_result", _persist)
    monkeypatch.setattr("server.generations._publish_image_edit_completed_notification", lambda job: None)
    reset_jobs()

    response = test_client.post("/generations/edits", json=payload)

    assert response.status_code == 200
    assert mock_client.calls
    forwarded = mock_client.calls[0][1]["request"]
    assert forwarded["model"]["slug"] == "image-edit"
    assert forwarded["model"]["name"] == "Zaya Amune"
    assert forwarded["model"]["imageUri"] == "https://cdn.example/models/zaya.png"
    assert forwarded["model"]["imageBase64"] == "emF5YS1tb2RlbA=="
    assert forwarded["aspect"] == "4:5"
    assert forwarded["dims"] == {"w": 1080, "h": 1350}
    assert forwarded["quality"] == "2k"
    assert forwarded["style"]["task_type"] == "on-model/edited"
    assert forwarded["style"]["background"] == "Studio"
    assert forwarded["style"]["edit_ids"] == "jewelry_smaller"
    assert captured_jobs[0].model_id == "model-zaya"
    assert captured_jobs[0].model_name == "Zaya Amune"
    assert captured_jobs[0].style["task_type"] == "on-model/edited"
    assert captured_jobs[0].aspect == "4:5"
    assert captured_jobs[0].dims == {"w": 1080, "h": 1350}


def test_build_image_edit_prompt_uses_registry_definition() -> None:
    payload = generations.CreateImageEditPayload(**_image_edit_payload())
    instructions = [
        generations.ImageEditInstructionPayload(
            id="jewelry_smaller",
            label="Make the jewelry a bit smaller",
            category="jewelry",
            prompt="Reduce scale slightly.",
        )
    ]

    prompt = generations._build_image_edit_prompt(
        payload,
        instructions,
        definition={
            "hero": "Registry hero",
            "pure_jewelry_addendum": "Registry pure addendum",
            "requested_edits_heading": "Registry edits heading",
        },
    )

    assert prompt.startswith("Registry hero")
    assert "Registry pure addendum" in prompt
    assert "Registry edits heading" in prompt
    assert "1. Make the jewelry a bit smaller: Reduce scale slightly." in prompt


def test_build_image_edit_prompt_falls_back_when_definition_missing() -> None:
    payload = generations.CreateImageEditPayload(**_image_edit_payload())
    instructions = [
        generations.ImageEditInstructionPayload(
            id="jewelry_smaller",
            label="Make the jewelry a bit smaller",
            category="jewelry",
            prompt="Reduce scale slightly.",
        )
    ]

    prompt = generations._build_image_edit_prompt(payload, instructions, definition={})

    assert prompt.startswith(generations.FALLBACK_IMAGE_EDIT_HERO_PROMPT)
    assert generations.FALLBACK_IMAGE_EDIT_PURE_JEWELRY_ADDENDUM in prompt
    assert generations.FALLBACK_IMAGE_EDIT_REQUESTED_EDITS_HEADING in prompt


def test_result_metadata_preserves_generation_and_edit_metadata() -> None:
    job = GenerationJob(
        id="edit-job-1",
        user_id="user-123",
        total_looks=1,
        model_id="model-zaya",
        model_name="Zaya Amune",
        style={
            "task_type": "on-model/edited",
            "background": "Studio",
            "edit_ids": "jewelry_smaller,enhance_shine",
        },
        aspect="4:5",
        dims={"w": 1080, "h": 1350},
        quality="2K",
        job_type="image_edit",
        edit_source={"sourceKey": "source-1"},
        edit_instructions=[{"id": "jewelry_smaller", "label": "Make smaller"}],
    )

    metadata = generations._build_result_metadata_payload(job, image_size=123)

    assert metadata["modelName"] == "Zaya Amune"
    assert metadata["style"]["background"] == "Studio"
    assert metadata["style"]["task_type"] == "on-model/edited"
    assert metadata["taskType"] == "on-model/edited"
    assert metadata["aspect"] == "4:5"
    assert metadata["dims"] == {"w": 1080, "h": 1350}
    assert metadata["quality"] == "2K"
    assert metadata["editSource"] == {"sourceKey": "source-1"}
    assert metadata["editInstructions"][0]["id"] == "jewelry_smaller"


def test_submit_image_edit_feedback_persists_row(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(generations.router)
    app.dependency_overrides[generations.get_current_user] = lambda: UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=20,
    )
    test_client = TestClient(app)
    credit_client = _CreditClient(credits={"user-123": 20})
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    response = test_client.post(
        "/generations/edits/job-123/feedback",
        json={
            "rating": "bad",
            "comment": "The ring changed shape.",
            "sourceKey": "source-1",
            "editOptionIds": ["jewelry_smaller"],
            "editLabels": ["Make the jewelry a bit smaller"],
        },
    )

    assert response.status_code == 200
    assert response.json()["id"]
    assert credit_client.feedback_rows[0]["user_id"] == "user-123"
    assert credit_client.feedback_rows[0]["edit_job_id"] == "job-123"
    assert credit_client.feedback_rows[0]["rating"] == "bad"
    assert credit_client.feedback_rows[0]["comment"] == "The ring changed shape."


def _image_edit_payload() -> dict[str, Any]:
    return {
        "generationServerUrl": "https://override.example",
        "sourceImage": {
            "id": "upload-1",
            "uri": "https://cdn.example/image.png",
            "base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5W8YQAAAAASUVORK5CYII=",
            "mimeType": "image/png",
            "fileSize": 12345,
            "width": 512,
            "height": 512,
            "name": "image.png",
        },
        "source": {
            "sourceKey": "source-1",
            "url": "https://cdn.example/source.png",
            "modelSlug": "pure-jewelry",
            "modelName": "Pure Jewelry",
        },
        "edits": ["jewelry_smaller"],
        "aspect": "1:1",
        "dims": {"w": 1080, "h": 1080},
        "quality": "1080p",
    }


def test_generation_refunds_reserved_credits_when_dispatch_fails(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    generation_payload: dict[str, Any],
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_SERVER_ENDPOINT", "/submit")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")

    credit_client = _CreditClient(credits={"user-123": 20})
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    async def _raise_dispatch_error(*_args, **_kwargs):
        raise HTTPException(status_code=503, detail="generation worker unavailable")

    monkeypatch.setattr(generations, "_forward_generation_request", _raise_dispatch_error)

    response = client.post("/generations", json=generation_payload)

    assert response.status_code == 503
    assert credit_client.credits["user-123"] == 20


def test_generation_forwards_uppercase_quality(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    """The router should normalize and forward uppercase quality levels."""

    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_SERVER_ENDPOINT", "/submit")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    mock_client = _MockAsyncClient()
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)

    payload = dict(generation_payload)
    payload["quality"] = "2K"
    payload.pop("generationServerUrl")

    response = client.post("/generations", json=payload)

    assert response.status_code == 200
    url, forwarded, headers = mock_client.calls[0]
    assert url == "https://default.example/submit"
    assert forwarded["request"]["quality"] == "2k"
    assert headers["X-Generation-Secret"] == "secret"


def test_generation_request_requires_server_configuration(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    """The route should reject requests if no generation server is configured."""

    monkeypatch.delenv("GENERATION_SERVER_URL", raising=False)
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    payload = dict(generation_payload)
    payload.pop("generationServerUrl")

    response = client.post("/generations", json=payload)

    assert response.status_code == 503
    assert response.json()["detail"] == "Generation server is not configured"


def test_generation_request_requires_callback_configuration(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    """The route should reject requests if no callback URL is configured."""

    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_SERVER_ENDPOINT", "/submit")
    monkeypatch.delenv("GENERATION_CALLBACK_URL", raising=False)

    response = client.post("/generations", json=generation_payload)

    assert response.status_code == 503
    assert response.json()["detail"] == "Generation callback URL is not configured"


def test_retrieve_generation_status(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    """The API should expose job status via GET."""

    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")

    mock_client = _MockAsyncClient()
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]

    status_response = client.get(f"/generations/{job_id}")
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["id"] == job_id
    assert payload["status"] == "queued"
    assert payload["progress"] == pytest.approx(
        payload["completedLooks"] / payload["totalLooks"]
    )


def test_retrieve_generation_expires_stale_active_job(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv("GENERATION_STALE_TIMEOUT_SECONDS", "60")
    job = generations.create_job("stale-job", "guest:stale-job", 2)
    generations.mark_started(job)
    job.updated_at = datetime.utcnow() - timedelta(seconds=61)

    response = client.get("/generations/stale-job")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["errors"] == ["Generation timed out. Please try again."]


def test_delete_failed_generation_removes_job(client: TestClient) -> None:
    job = generations.create_job("failed-job", "user-123", 1)
    generations.mark_failed(job, "Generation failed. Please try again.")

    response = client.delete("/generations/failed-job")

    assert response.status_code == 204
    assert generations.get_job("failed-job") is None


def test_delete_active_generation_is_rejected(client: TestClient) -> None:
    generations.create_job("active-job", "user-123", 1)

    response = client.delete("/generations/active-job")

    assert response.status_code == 409


def test_generation_server_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    """Worker errors should be logged server-side but not forwarded to the client."""

    class _FailingAsyncClient(_MockAsyncClient):
        async def post(
            self, url: str, json: dict[str, Any], headers: dict[str, Any] | None = None
        ) -> _MockResponse:
            self.calls.append((url, json, headers or {}))
            response = _MockResponse(status_code=500)
            response.text = '{"error":"secret worker details"}'
            return response

    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setattr(
        "server.generations.httpx.AsyncClient", lambda *a, **kw: _FailingAsyncClient()
    )

    response = client.post("/generations", json=generation_payload)

    assert response.status_code == 502
    assert (
        response.json()["detail"]
        == generations.GENERATION_START_FAILURE_MESSAGE
    )


def test_receive_generation_events_updates_state(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    """Callback events should mutate the job state and surface results."""

    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    mock_client = _MockAsyncClient()
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]

    headers = {"X-Generation-Secret": "secret"}

    started = client.post(
        f"/generations/{job_id}/events",
        json={"type": "started"},
        headers=headers,
    )
    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"

    first_result = client.post(
        f"/generations/{job_id}/events",
        json={
            "type": "result",
            "result": {"url": "https://cdn.example/result-1.png"},
            "progress": 0.5,
            "completedLooks": 2,
        },
        headers=headers,
    )
    assert first_result.status_code == 200
    assert first_result.json()["completedLooks"] == 2

    completed = client.post(
        f"/generations/{job_id}/events",
        json={"type": "completed"},
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["progress"] == 1.0


def test_completed_generation_event_publishes_notification(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    mock_client = _MockAsyncClient()
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(
        generations,
        "publish_app_notification",
        lambda **kwargs: published.append(kwargs),
    )

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]

    response = client.post(
        f"/generations/{job_id}/events",
        json={"type": "completed"},
        headers={"X-Generation-Secret": "secret"},
    )

    assert response.status_code == 200
    assert published == [
        {
            "category": "personal",
            "kind": "generation_completed",
            "title": "Generation completed",
            "body": "Tap to view your new looks",
            "entity_key": f"generation:{job_id}",
            "target_user_id": "user-123",
            "action": {
                "pathname": "/generating",
                "params": {"jobId": job_id},
            },
        }
    ]


def test_final_result_event_completes_generation_without_completed_event(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    generation_payload: dict[str, Any],
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    mock_client = _MockAsyncClient()
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(
        generations,
        "publish_app_notification",
        lambda **kwargs: published.append(kwargs),
    )

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]

    response = client.post(
        f"/generations/{job_id}/events",
        json={
            "type": "result",
            "result": {"url": "https://cdn.example/final-result.png"},
            "progress": 1,
            "completedLooks": generation_payload["looks"],
        },
        headers={"X-Generation-Secret": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["progress"] == 1
    assert published[0]["kind"] == "generation_completed"


def test_immediate_completed_generation_response_publishes_notification(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")

    async def _return_completed(*_args, **_kwargs):
        return generations.CreateGenerationResponse(
            id="gen-123",
            status="completed",
            results=[{"url": "https://cdn.example/result-1.png"}],
            progress=1.0,
            totalLooks=4,
            completedLooks=4,
        )

    published: list[dict[str, Any]] = []
    monkeypatch.setattr(generations, "_forward_generation_request", _return_completed)
    monkeypatch.setattr(
        generations,
        "publish_app_notification",
        lambda **kwargs: published.append(kwargs),
    )

    response = client.post("/generations", json=generation_payload)

    assert response.status_code == 200
    job_id = response.json()["id"]
    assert response.json()["status"] == "completed"
    assert published == [
        {
            "category": "personal",
            "kind": "generation_completed",
            "title": "Generation completed",
            "body": "Tap to view your new looks",
            "entity_key": f"generation:{job_id}",
            "target_user_id": "user-123",
            "action": {
                "pathname": "/generating",
                "params": {"jobId": job_id},
            },
        }
    ]


def test_publish_completed_notification_includes_draft_collection_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(
        generations,
        "publish_app_notification",
        lambda **kwargs: published.append(kwargs),
    )

    generations._publish_generation_completed_notification(
        GenerationJob(
            id="job-123",
            user_id="user-123",
            total_looks=1,
            unsaved_collection_id="draft-1",
        )
    )

    assert published == [
        {
            "category": "personal",
            "kind": "generation_completed",
            "title": "Generation completed",
            "body": "Tap to view your new looks",
            "entity_key": "generation:job-123",
            "target_user_id": "user-123",
            "action": {
                "pathname": "/generating",
                "params": {
                    "jobId": "job-123",
                    "collectionId": "draft-1",
                },
            },
        }
    ]


def test_failed_generation_event_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    """Worker callback errors should be replaced with a safe client-facing message."""

    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    mock_client = _MockAsyncClient()
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]

    response = client.post(
        f"/generations/{job_id}/events",
        json={"type": "failed", "error": '{"message":"secret callback details"}'},
        headers={"X-Generation-Secret": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["errors"] == [generations.GENERATION_JOB_FAILURE_MESSAGE]


def test_failed_generation_event_refunds_unfinished_looks_once(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    credit_client = _CreditClient(credits={"user-123": 20})
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    class _QueuedAsyncClient(_MockAsyncClient):
        async def post(
            self, url: str, json: dict[str, Any], headers: dict[str, Any] | None = None
        ) -> _MockResponse:
            self.calls.append((url, json, headers or {}))
            return _MockResponse(payload={"id": "gen-123", "status": "queued", "results": []})

    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: _QueuedAsyncClient())

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]
    assert create_response.json()["remainingCredits"] == 4

    headers = {"X-Generation-Secret": "secret"}
    result_response = client.post(
        f"/generations/{job_id}/events",
        json={
            "type": "result",
            "result": {"url": "https://cdn.example/result-1.png"},
            "completedLooks": 2,
        },
        headers=headers,
    )
    assert result_response.status_code == 200

    failed_response = client.post(
        f"/generations/{job_id}/events",
        json={"type": "failed", "error": "worker failure"},
        headers=headers,
    )

    assert failed_response.status_code == 200
    assert failed_response.json()["status"] == "failed"
    assert failed_response.json()["remainingCredits"] == 12
    assert credit_client.credits["user-123"] == 12

    duplicate_failed_response = client.post(
        f"/generations/{job_id}/events",
        json={"type": "failed", "error": "worker failure again"},
        headers=headers,
    )

    assert duplicate_failed_response.status_code == 200
    assert duplicate_failed_response.json()["remainingCredits"] == 12
    assert credit_client.credits["user-123"] == 12


def test_cancelled_generation_event_refunds_all_unfinished_looks(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    credit_client = _CreditClient(credits={"user-123": 20})
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    class _QueuedAsyncClient(_MockAsyncClient):
        async def post(
            self, url: str, json: dict[str, Any], headers: dict[str, Any] | None = None
        ) -> _MockResponse:
            self.calls.append((url, json, headers or {}))
            return _MockResponse(payload={"id": "gen-123", "status": "queued", "results": []})

    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: _QueuedAsyncClient())

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]
    assert create_response.json()["remainingCredits"] == 4

    cancelled_response = client.post(
        f"/generations/{job_id}/events",
        json={"type": "cancelled"},
        headers={"X-Generation-Secret": "secret"},
    )

    assert cancelled_response.status_code == 200
    assert cancelled_response.json()["status"] == "failed"
    assert cancelled_response.json()["remainingCredits"] == 20
    assert credit_client.credits["user-123"] == 20


def test_user_cancel_generation_refunds_one_unfinished_look(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")

    credit_client = _CreditClient(credits={"user-123": 20})
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    class _QueuedAsyncClient(_MockAsyncClient):
        async def post(
            self, url: str, json: dict[str, Any], headers: dict[str, Any] | None = None
        ) -> _MockResponse:
            self.calls.append((url, json, headers or {}))
            return _MockResponse(payload={"id": "gen-123", "status": "queued", "results": []})

    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: _QueuedAsyncClient())

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]
    assert create_response.json()["remainingCredits"] == 4

    cancel_response = client.post(f"/generations/{job_id}/cancel")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "queued"
    assert cancel_response.json()["totalLooks"] == 3
    assert cancel_response.json()["completedLooks"] == 0
    assert cancel_response.json()["remainingCredits"] == 8
    assert credit_client.credits["user-123"] == 8

    second_cancel_response = client.post(f"/generations/{job_id}/cancel", json={"looks": 1})

    assert second_cancel_response.status_code == 200
    assert second_cancel_response.json()["status"] == "queued"
    assert second_cancel_response.json()["totalLooks"] == 2
    assert second_cancel_response.json()["remainingCredits"] == 12
    assert credit_client.credits["user-123"] == 12


def test_user_cancel_generation_ignores_late_results_for_cancelled_slot(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    credit_client = _CreditClient(credits={"user-123": 20})
    persisted_results: list[str | None] = []
    monkeypatch.setattr(
        generations,
        "_persist_generation_result",
        lambda job, result: (
            persisted_results.append(result.url) or result
        ),
    )
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    class _QueuedAsyncClient(_MockAsyncClient):
        async def post(
            self, url: str, json: dict[str, Any], headers: dict[str, Any] | None = None
        ) -> _MockResponse:
            self.calls.append((url, json, headers or {}))
            return _MockResponse(payload={"id": "gen-123", "status": "queued", "results": []})

    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: _QueuedAsyncClient())

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]

    cancel_response = client.post(f"/generations/{job_id}/cancel")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["totalLooks"] == 3

    final_response = None
    for index in range(4):
        final_response = client.post(
            f"/generations/{job_id}/events",
            json={
                "type": "result",
                "result": {"url": f"https://cdn.example/results/{index}.png"},
                "completedLooks": index + 1,
            },
            headers={"X-Generation-Secret": "secret"},
        )

    assert final_response is not None
    assert final_response.status_code == 200
    assert final_response.json()["status"] == "completed"
    assert final_response.json()["totalLooks"] == 3
    assert final_response.json()["completedLooks"] == 3
    assert len(final_response.json()["results"]) == 3
    assert final_response.json()["remainingCredits"] is None
    assert len(persisted_results) == 3
    assert credit_client.credits["user-123"] == 8


def test_failed_generation_event_publishes_notification(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    mock_client = _MockAsyncClient()
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(
        generations,
        "publish_app_notification",
        lambda **kwargs: published.append(kwargs),
    )

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]

    response = client.post(
        f"/generations/{job_id}/events",
        json={"type": "failed", "error": "worker failure"},
        headers={"X-Generation-Secret": "secret"},
    )

    assert response.status_code == 200
    assert published == [
        {
            "category": "personal",
            "kind": "generation_failed",
            "title": "Generation failed",
            "body": "Tap to review the failed generation",
            "entity_key": f"generation-failed:{job_id}",
            "target_user_id": "user-123",
            "action": {
                "pathname": "/generating",
                "params": {"jobId": job_id},
            },
        }
    ]


def test_immediate_failed_generation_response_publishes_notification(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")

    async def _return_failed(*_args, **_kwargs):
        return generations.CreateGenerationResponse(
            id="gen-123",
            status="failed",
            errors=["worker failure"],
        )

    published: list[dict[str, Any]] = []
    monkeypatch.setattr(generations, "_forward_generation_request", _return_failed)
    monkeypatch.setattr(
        generations,
        "publish_app_notification",
        lambda **kwargs: published.append(kwargs),
    )

    response = client.post("/generations", json=generation_payload)

    assert response.status_code == 200
    job_id = response.json()["id"]
    assert response.json()["status"] == "failed"
    assert response.json()["errors"] == ["worker failure"]
    assert published == [
        {
            "category": "personal",
            "kind": "generation_failed",
            "title": "Generation failed",
            "body": "Tap to review the failed generation",
            "entity_key": f"generation-failed:{job_id}",
            "target_user_id": "user-123",
            "action": {
                "pathname": "/generating",
                "params": {"jobId": job_id},
            },
        }
    ]


def test_generation_event_requires_secret(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]
) -> None:
    """Events must include the shared secret when configured."""

    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    mock_client = _MockAsyncClient()
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)

    create_response = client.post("/generations", json=generation_payload)
    job_id = create_response.json()["id"]

    response = client.post(
        f"/generations/{job_id}/events",
        json={"type": "completed"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid generation signature"


DEMO_MOTION_VIDEO_PATH = Path("C:/gemzy/assets/create-menu/motion.mp4")


def test_motion_credit_costs_are_duration_based() -> None:
    assert generations._motion_credit_cost(5, 1) == 25
    assert generations._motion_credit_cost(8, 1) == 40
    assert generations._motion_credit_cost(8, 2) == 80


def test_generation_config_exposes_authoritative_motion_costs(
    client: TestClient,
) -> None:
    response = client.get("/generations/config")

    assert response.status_code == 200
    assert response.json()["motionCostByDuration"] == {"5": 25, "8": 40}


@pytest.mark.skipif(
    not DEMO_MOTION_VIDEO_PATH.exists(),
    reason="Local Gemzy demo motion video is not available",
)
def test_motion_generation_demo_video_uploads_to_storage_and_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The motion route should queue quickly and eventually store the demo MP4."""

    inserted_payloads: list[dict[str, Any]] = []
    uploaded: list[dict[str, Any]] = []

    class _Blob:
        def __init__(self, name: str) -> None:
            self.name = name
            self.metadata: dict[str, Any] | None = None
            self.cache_control: str | None = None

        def upload_from_string(self, data: bytes, content_type: str | None = None) -> None:
            uploaded.append(
                {
                    "name": self.name,
                    "size": len(data),
                    "content_type": content_type,
                    "metadata": self.metadata,
                }
            )

    class _Bucket:
        def blob(self, name: str) -> _Blob:
            return _Blob(name)

    class _Response:
        def __init__(self, data: list[dict[str, Any]], count: int = 1) -> None:
            self.data = data
            self.count = count

    class _CollectionTable:
        def insert(
            self, payload: dict[str, Any], returning: str | None = None
        ) -> "_CollectionTable":
            self.payload = payload
            self.returning = returning
            return self

        def execute(self) -> _Response:
            inserted_payloads.append(self.payload)
            return _Response(
                [{"id": "motion-item-1", "created_at": "2026-07-02T12:00:00"}]
            )

    credit_client = _CreditClient(credits={"user-123": 50})

    class _Client:
        def table(self, name: str):
            if name == "profiles":
                return _CreditTable(credit_client, name)
            if name == "collection_items":
                return _CollectionTable()
            raise AssertionError(f"Unexpected table {name}")

    class _NoNetworkClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self):
            raise AssertionError("Demo motion flow should not call Segmind")

        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

    app = FastAPI()
    app.include_router(generations.router)
    current_user = UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=50,
    )
    app.dependency_overrides[generations.get_current_user] = lambda: current_user
    app.dependency_overrides[generations.get_optional_current_user] = lambda: current_user
    test_client = TestClient(app)

    monkeypatch.setenv(
        generations.MOTION_DEMO_VIDEO_PATH_ENV,
        str(DEMO_MOTION_VIDEO_PATH),
    )
    monkeypatch.delenv("SEGMIND_KEY", raising=False)
    monkeypatch.setattr(generations, "get_client", lambda: _Client())
    monkeypatch.setattr(generations, "_get_collections_bucket", lambda: _Bucket())
    monkeypatch.setattr(
        generations,
        "_resolve_collection_image_variants",
        lambda _image_url, storage_path, include_signed=False: (
            f"https://signed.example/{storage_path}?preview=1",
            f"https://signed.example/{storage_path}?full=1",
        ),
    )
    monkeypatch.setattr(generations, "ensure_unsaved_collection", lambda _user_id: "draft-1")
    monkeypatch.setattr(generations.httpx, "AsyncClient", _NoNetworkClient)
    reset_jobs()

    response = test_client.post(
        "/generations/motion",
        json={
            "prompt": "slow editorial camera push",
            "firstFrameUrl": "https://cdn.example/source.png",
            "duration": 8,
            "resolution": "720p",
            "aspectRatio": "9:16",
            "videoCount": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"queued", "in_progress", "completed"}
    assert body["remainingCredits"] == 10
    assert body["totalLooks"] == 1
    job_id = body["id"]

    completed_body = body
    deadline = time.time() + 5
    while time.time() < deadline:
        poll_response = test_client.get(f"/generations/{job_id}")
        assert poll_response.status_code == 200
        completed_body = poll_response.json()
        if completed_body["status"] == "completed":
            break
        assert completed_body["status"] != "failed"
        time.sleep(0.05)

    assert completed_body["status"] == "completed"
    assert completed_body["completedLooks"] == 1

    result = completed_body["results"][0]
    assert result["url"].startswith("https://signed.example/user-123/motion/")
    assert not result["url"].startswith("data:")
    assert result["mediaType"] == "video"
    assert result["contentType"] == "video/mp4"
    assert result["storagePath"].startswith("user-123/motion/")
    assert result["collectionId"] == "draft-1"
    assert result["collectionItemId"] == "motion-item-1"
    assert result["previewUrl"] == "https://cdn.example/source.png"
    assert result["metadata"]["source"] == "motion"
    assert result["metadata"]["mediaType"] == "video"
    assert result["metadata"]["provider"] == "demo"
    assert result["metadata"]["previewUrl"] == "https://cdn.example/source.png"

    assert len(uploaded) == 1
    assert uploaded[0]["name"] == result["storagePath"]
    assert uploaded[0]["content_type"] == "video/mp4"
    assert uploaded[0]["size"] == DEMO_MOTION_VIDEO_PATH.stat().st_size
    assert uploaded[0]["metadata"]["source"] == "motion"
    assert uploaded[0]["metadata"]["mediaType"] == "video"

    assert len(inserted_payloads) == 1
    inserted = inserted_payloads[0]
    assert inserted["collection_id"] == "draft-1"
    assert inserted["user_id"] == "user-123"
    assert inserted["external_id"] == result["storagePath"]
    assert inserted["image_url"] == result["storagePath"]
    assert inserted["metadata"]["contentType"] == "video/mp4"
    assert inserted["metadata"]["previewUrl"] == "https://cdn.example/source.png"
    assert inserted["metadata"]["previewUri"] == "https://cdn.example/source.png"
    assert inserted["metadata"]["size"] == DEMO_MOTION_VIDEO_PATH.stat().st_size
    assert inserted["metadata"]["taskType"] == "motion"
    assert credit_client.credits["user-123"] == 10


def test_motion_generation_returns_immediately_with_queued_job(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    scheduled: list[dict[str, Any]] = []

    monkeypatch.setattr(
        generations,
        "_schedule_motion_generation_job",
        lambda job, **kwargs: scheduled.append({"job": job, **kwargs}),
    )
    current_user = UserState(
        id="user-123",
        name="Test User",
        plan="Pro",
        credits=100,
    )
    client.app.dependency_overrides[generations.get_current_user] = lambda: current_user
    credit_client = _CreditClient(credits={"user-123": 100})
    monkeypatch.setattr(generations, "get_client", lambda: credit_client)

    response = client.post(
        "/generations/motion",
        json={
            "prompt": "slow editorial camera push",
            "firstFrameUrl": "https://cdn.example/source.png",
            "duration": 8,
            "resolution": "720p",
            "aspectRatio": "9:16",
            "videoCount": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["results"] == []
    assert body["completedLooks"] == 0
    assert body["totalLooks"] == 2
    assert body["remainingCredits"] == 20
    assert len(scheduled) == 1
    assert scheduled[0]["job"].id == body["id"]
    assert scheduled[0]["job"].total_looks == 2
    assert scheduled[0]["required_credits"] == 80
    assert scheduled[0]["job"].reserved_credit_cost == 80
    assert scheduled[0]["job"].credit_cost_per_look == 40

def test_persist_generation_result_refreshes_draft_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisting a generated image into Draft should refresh the collection cover."""

    inserted_payloads: list[dict[str, Any]] = []

    class _Blob:
        metadata: dict[str, Any] | None = None
        cache_control: str | None = None

        def upload_from_string(self, _data: bytes, content_type: str | None = None) -> None:
            self.content_type = content_type

    class _Bucket:
        def blob(self, _name: str) -> _Blob:
            return _Blob()

    class _Response:
        def __init__(self, data: list[dict[str, Any]]) -> None:
            self.data = data

    class _Table:
        def insert(self, payload: dict[str, Any], returning: str | None = None) -> "_Table":
            self.payload = payload
            self.returning = returning
            return self

        def execute(self) -> _Response:
            inserted_payloads.append(self.payload)
            return _Response(
                [{"id": "item-1", "created_at": "2026-03-23T12:00:00"}]
            )

    class _Client:
        def table(self, name: str) -> _Table:
            assert name == "collection_items"
            return _Table()

    refreshed: list[tuple[str, str | None]] = []
    generated_variants: list[tuple[str, str | None]] = []

    monkeypatch.setattr("server.generations._decode_generation_image", lambda _result: b"png")
    monkeypatch.setattr("server.generations._get_collections_bucket", lambda: _Bucket())
    monkeypatch.setattr(
        "server.generations._generate_public_collection_variants",
        lambda path, content_type=None: generated_variants.append(
            (path, content_type)
        ),
    )
    monkeypatch.setattr(
        "server.generations._resolve_collection_image_variants",
        lambda *_args, **_kwargs: ("https://preview.example/image.png", "https://view.example/image.png"),
    )
    monkeypatch.setattr("server.generations.ensure_unsaved_collection", lambda _user_id: "draft-1")
    monkeypatch.setattr("server.generations.get_client", lambda: _Client())
    monkeypatch.setattr(
        "server.generations._refresh_collection_cover",
        lambda collection_id, user_id=None: refreshed.append((collection_id, user_id)),
    )

    job = GenerationJob(id="job-1", user_id="user-1", total_looks=1)
    result = generations._persist_generation_result(
        job,
        generations.GenerationResultPayload(base64="Zm9v"),
    )

    assert result.collectionId == "draft-1"
    assert result.collectionItemId == "item-1"
    assert refreshed == [("draft-1", "user-1")]
    assert len(generated_variants) == 1
    assert generated_variants[0][0].startswith("user-1/generations/job-1/")
    assert generated_variants[0][1] == "image/png"
    assert len(inserted_payloads) == 1
    assert inserted_payloads[0]["collection_id"] == "draft-1"
    assert inserted_payloads[0]["user_id"] == "user-1"
    assert inserted_payloads[0]["external_id"].startswith("user-1/generations/job-1/")
    assert inserted_payloads[0]["image_url"] == inserted_payloads[0]["external_id"]
    assert inserted_payloads[0]["metadata"]["contentType"] == "image/png"
    assert inserted_payloads[0]["metadata"]["size"] == 3
    assert inserted_payloads[0]["metadata"]["source"] == "generation"
    assert inserted_payloads[0]["metadata"]["jobId"] == "job-1"


def test_decode_generation_image_rejects_base64_like_prompt_text() -> None:
    result = generations.GenerationResultPayload(
        base64="Hereisacloseupstudioshotofthewomanfromtheimagewearingtheringfromtheimage"
    )

    with pytest.raises(HTTPException, match="not a valid image"):
        generations._decode_generation_image(result)
