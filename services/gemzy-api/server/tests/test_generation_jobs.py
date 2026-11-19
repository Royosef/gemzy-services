"""GET /generations/jobs: the signed-in user's recent jobs across devices."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import generations
from server.generation_state import create_job, reset_jobs
from server.schemas import UserState


def test_job_list_returns_only_the_users_recent_jobs():
    app = FastAPI()
    app.include_router(generations.router)
    app.dependency_overrides[generations.get_current_user] = lambda: UserState(
        id="user-1", name="U", plan="Pro", credits=10
    )
    reset_jobs()
    try:
        mine = create_job(
            "job-mine", "user-1", 2, style={"task_type": "on-model"}, unsaved_collection_id="c1"
        )
        create_job("job-other", "user-2", 1)
        response = TestClient(app).get("/generations/jobs")
    finally:
        reset_jobs()

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [job["id"] for job in jobs] == [mine.id]
    assert jobs[0]["taskType"] == "on-model"
    assert jobs[0]["collectionId"] == "c1"
    assert jobs[0]["totalLooks"] == 2
    assert jobs[0]["createdAt"].endswith("Z")
