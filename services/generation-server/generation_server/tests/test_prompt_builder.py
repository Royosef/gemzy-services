import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("GENERATION_APP_URL", "https://app.example")

from generation_server.models import (
    GenerationDimensions,
    GenerationItem,
    GenerationModel,
    GenerationRequest,
    GenerationUpload,
)
from generation_server.prompt_builder import build_negative_prompt, build_prompts


def _request(looks: int = 3, style: dict | None = None) -> GenerationRequest:
    return GenerationRequest(
        uploads=[
            GenerationUpload(
                id="upload-1",
                uri="https://example.com/asset.png",
                base64="ZmFrZQ==",
                mimeType="image/png",
                fileSize=123,
                width=100,
                height=200,
                name="asset.png",
            )
        ],
        model=GenerationModel(
            id="model-1",
            slug="model",
            name="Model",
            planTier="Pro",
            imageUri="https://example.com/model.png",
        ),
        style=style or {
            "product": "Necklace",
            "camera": "Studio",
            "pose": "Profile",
            "background": "Neutral",
            "emotion": "Joy",
            "lighting": "Soft",
        },
        mode="SIMPLE",
        aspect="1:1",
        dims=GenerationDimensions(w=512, h=512),
        looks=looks,
        quality="1k",
        plan="Pro",
        creditsNeeded=looks,
    )


def _pure_jewelry_request(style: dict | None = None, *, size: str = "Medium") -> GenerationRequest:
    request = _request(looks=1, style=style or {})
    request.model = GenerationModel(
        id="pure-jewelry-model",
        slug="pure-jewelry",
        name="Pure Jewelry",
        planTier="Pro",
    )
    request.items = [
        GenerationItem(
            id="item-1",
            type="Ring",
            size=size,
            uploadId="upload-1",
        )
    ]
    return request


def test_build_prompts_matches_look_count() -> None:
    request = _request(looks=4)
    prompts = build_prompts(request)
    assert len(prompts) == 4
    assert prompts[0].startswith("Generate an image of the model wearing")


def test_build_prompts_adds_advanced_style() -> None:
    request = _request(
        looks=1,
        style={
            "product": "Ring",
            "camera": "DSLR",
            "pose": "Hand close-up",
            "background": "Studio",
            "emotion": "Confidence",
            "lighting": "Natural",
            "mood": "Luxury",
        },
    )
    request.mode = "ADVANCED"
    prompt = build_prompts(request)[0]
    assert "Luxury" in prompt
    assert "Hand close-up" in prompt


def test_negative_prompt_appends_custom_entries() -> None:
    text = build_negative_prompt(["overexposed", "grainy"])
    assert "overexposed" in text
    assert "grainy" in text


def test_build_prompts_for_pure_jewelry_v52() -> None:
    request = _pure_jewelry_request(
        style={
            "public_version_key": "v5.2",
            "style_type": "pure-studio",
            "scene": "Studio Color",
            "surface": "Silk",
            "lighting": "Soft Diffused",
            "shadow": "Soft",
            "composition": "Close Up",
            "studioColorHex": "#C0FFEE",
        },
        size="Very Small",
    )

    prompt = build_prompts(request)[0]

    assert "HERO" in prompt
    assert "ATMOSPHERE" in prompt
    assert "JEWELRY TYPE: Ring" in prompt
    assert "JEWELRY SIZE: Very Small" in prompt
    assert "SCENE: Studio Color" in prompt
    assert "#C0FFEE" in prompt
    assert "SURFACE: Silk" in prompt
    assert "COMPOSITION: Close Up" in prompt
    assert "QUALITY CONTROL" in prompt


def test_build_prompts_for_pure_jewelry_v52_accepts_option_ids() -> None:
    request = _pure_jewelry_request(
        style={
            "public_version_key": "v5.2",
            "style_type": "pure-studio",
            "scene": "studio-color",
            "surface": "silk",
            "lighting": "soft-diffused",
            "shadow": "soft",
            "composition": "close-up",
            "studioColorHex": "#C0FFEE",
        },
        size="Very Small",
    )

    prompt = build_prompts(request)[0]

    assert "SCENE: Studio Color" in prompt
    assert "SURFACE: Silk" in prompt
    assert "COMPOSITION: Close Up" in prompt


def test_build_prompts_for_pure_jewelry_legacy_fallback() -> None:
    request = _pure_jewelry_request(
        style={
            "style_type": "studio-shot",
            "background": "Pure white",
            "surface": "Floating",
            "lighting": "Soft diffused",
            "add-ons": "None",
        }
    )

    prompt = build_prompts(request)[0]

    assert "Studio product photography of a single jewelry piece." in prompt
    assert "Background: Pure white." in prompt
