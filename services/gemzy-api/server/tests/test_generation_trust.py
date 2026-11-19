"""Server-side trust for generation requests (generation target, look count, model plan)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from server import generations
from server.schemas import MAX_GENERATION_LOOKS, CreateGenerationPayload

TIERS = {"Free": 0, "Starter": 1, "Pro": 2, "Designer": 3}
MODEL_ID = "3f2b1c9e-8a7d-4e6f-9b0a-1c2d3e4f5a6b"


def _payload(**overrides):
    base = {
        "uploads": [],
        "items": [],
        "model": {"id": MODEL_ID, "slug": "m", "name": "M", "planTier": "Free"},
        "style": {},
        "mode": "SIMPLE",
        "aspect": "9:16",
        "dims": {"w": 1080, "h": 1920},
        "looks": 2,
        "quality": "1080p",
        "plan": "Free",
        "creditsNeeded": 8,
    }
    base.update(overrides)
    return base


# --- generationServerUrl -------------------------------------------------------------------


def test_client_generation_target_is_ignored_by_default(monkeypatch):
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://gen.internal")
    monkeypatch.delenv("ALLOW_GENERATION_SERVER_OVERRIDE", raising=False)
    monkeypatch.delenv("GENERATION_SERVER_ENDPOINT", raising=False)
    assert generations._resolve_generation_url("https://attacker.example") == "https://gen.internal/generate"


def test_client_generation_target_allowed_in_development(monkeypatch):
    monkeypatch.setenv("GENERATION_SERVER_URL", "https://gen.internal")
    monkeypatch.setenv("ALLOW_GENERATION_SERVER_OVERRIDE", "true")
    monkeypatch.delenv("GENERATION_SERVER_ENDPOINT", raising=False)
    assert generations._resolve_generation_url("https://my.ngrok.app/") == "https://my.ngrok.app/generate"


# --- looks ---------------------------------------------------------------------------------


@pytest.mark.parametrize("looks", [1, 2, 4, 6, 8])
def test_app_look_counts_are_accepted(looks):
    assert CreateGenerationPayload(**_payload(looks=looks)).looks == looks


@pytest.mark.parametrize("looks", [0, -4, MAX_GENERATION_LOOKS + 1, 1000])
def test_out_of_range_look_counts_are_rejected(looks):
    with pytest.raises(ValidationError):
        CreateGenerationPayload(**_payload(looks=looks))


# --- model plan ----------------------------------------------------------------------------


def _model_payload(model_id: str, client_tier: str):
    return SimpleNamespace(model=SimpleNamespace(id=model_id, planTier=client_tier))


def test_catalogue_plan_overrides_a_lower_client_plan():
    payload = _model_payload(MODEL_ID, "Free")
    assert generations._required_model_tier(payload, TIERS, {"plan": "Pro"}) == "Pro"


def test_higher_client_plan_is_kept():
    payload = _model_payload(MODEL_ID, "Pro")
    assert generations._required_model_tier(payload, TIERS, {"plan": "Free"}) == "Pro"


def test_non_catalogue_model_keeps_client_plan():
    payload = _model_payload("pure-jewelry-model", "Free")
    assert generations._required_model_tier(payload, TIERS, None) == "Free"


def test_non_uuid_ids_skip_the_lookup():
    assert generations._catalogue_model("pure-jewelry-model") is None


def test_catalogue_photo_replaces_the_client_photo():
    payload = CreateGenerationPayload(
        **_payload(
            model={
                "id": MODEL_ID,
                "slug": "m",
                "name": "M",
                "planTier": "Free",
                "imageUri": "https://evil.example/pro-model.png",
                "imageBase64": "aGVsbG8=",
            }
        )
    )
    out = generations._with_catalogue_model_image(
        payload, {"plan": "Free", "image_url": "https://storage.googleapis.com/b/m.png"}
    )
    assert out.model.imageUri == "https://storage.googleapis.com/b/m.png"
    assert out.model.imageBase64 is None


def test_non_catalogue_model_photo_is_untouched():
    payload = CreateGenerationPayload(**_payload())
    assert generations._with_catalogue_model_image(payload, None) is payload
