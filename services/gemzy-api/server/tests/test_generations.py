"""Tests for the generation routing module."""

from __future__ import annotations

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


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a test client for the generation router."""

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
                        "purchased_credits": self._client.purchased_credits.get(user_id, 0),
                        "edit_mode_trial_edits_remaining": self._client.edit_trials.get(user_id, 0),
                    }
                ],
                count=1,
            )

        if self._operation and self._operation[0] == "update":
            expected = next((value for column, value in self._filters if column == "credits"), None)
            expected_purchased = next((value for column, value in self._filters if column == "purchased_credits"), None)
            expected_trials = next((value for column, value in self._filters if column == "edit_mode_trial_edits_remaining"), None)
            current = self._client.credits.get(user_id)
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
                or (expected_purchased is not None and current_purchased != expected_purchased)
                or (expected_trials is not None and current_trials != expected_trials)
            ):
                return SimpleNamespace(data=[], count=0)
            if "credits" in self._operation[1]:
                self._client.credits[user_id] = self._operation[1]["credits"]
            self._client.purchased_credits[user_id] = self._operation[1].get("purchased_credits", current_purchased)
            if "edit_mode_trial_edits_remaining" in self._operation[1]:
                self._client.edit_trials[user_id] = self._operation[1]["edit_mode_trial_edits_remaining"]
            return SimpleNamespace(
                data=[
                    {
                        "credits": self._client.credits[user_id],
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
        purchased_credits: dict[str, int] | None = None,
        edit_trials: dict[str, int] | None = None,
        fail_first_update: bool = False,
        concurrent_credit_value: int = 0,
    ) -> None:
        self.credits = dict(credits)
        self.purchased_credits = dict(purchased_credits or {})
        self.edit_trials = dict(edit_trials or {user_id: 0 for user_id in credits})
        self.feedback_rows: list[dict[str, Any]] = []
        self.fail_first_update = fail_first_update
        self.concurrent_credit_value = concurrent_credit_value

    def table(self, name: str) -> _CreditTable:
        assert name in {"profiles", "image_edit_feedback"}
        return _CreditTable(self, name)


def test_generation_request_forwards_payload(monkeypatch: pytest.MonkeyPatch, client: TestClient, generation_payload: dict[str, Any]) -> None:
    """The route should forward the payload to the resolved generation server."""

    monkeypatch.setenv("GENERATION_SERVER_URL", "https://default.example")
    monkeypatch.setenv("GENERATION_SERVER_ENDPOINT", "/submit")
    monkeypatch.setenv("GENERATION_CALLBACK_URL", "https://app.example")
    monkeypatch.setenv("GENERATION_SHARED_SECRET", "secret")

    mock_client = _MockAsyncClient()
    monkeypatch.setattr("server.generations.httpx.AsyncClient", lambda *a, **kw: mock_client)

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
    assert body["remainingCredits"] == 12
    assert body["editCreditCost"] == 8
    assert credit_client.credits["user-123"] == 12
    assert credit_client.edit_trials["user-123"] == 0


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

    monkeypatch.setattr("server.generations._decode_generation_image", lambda _result: b"png")
    monkeypatch.setattr("server.generations._get_collections_bucket", lambda: _Bucket())
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
    assert len(inserted_payloads) == 1
    assert inserted_payloads[0]["collection_id"] == "draft-1"
    assert inserted_payloads[0]["user_id"] == "user-1"
    assert inserted_payloads[0]["external_id"].startswith("user-1/generations/job-1/")
    assert inserted_payloads[0]["image_url"] == inserted_payloads[0]["external_id"]
    assert inserted_payloads[0]["metadata"]["contentType"] == "image/png"
    assert inserted_payloads[0]["metadata"]["size"] == 3
    assert inserted_payloads[0]["metadata"]["source"] == "generation"
    assert inserted_payloads[0]["metadata"]["jobId"] == "job-1"
