import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("GENERATION_APP_URL", "https://app.example")

from prompting import (  # noqa: E402
    PROMPT_TASK_ON_MODEL,
    PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
    PROMPT_TASK_PLANNER_ENRICH,
    resolve_prompt_task,
)


def test_resolve_prompt_task_falls_back_to_default_registry_for_v45() -> None:
    rendered = resolve_prompt_task(
        PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
        {
            "request": {
                "model": {"slug": "model"},
                "style": {
                    "public_version_key": "v4.5",
                    "background": "White Studio",
                    "camera": "Portrait",
                    "image_style": "Natural",
                },
                "looks": 1,
                "items": [{"type": "Ring", "size": "Small"}],
            }
        },
    )

    assert rendered["prompts"]
    prompt = rendered["prompts"][0]
    assert prompt.startswith("HERO\nUltra-realistic editorial jewelry photograph.")
    assert "\nSCENE: White Studio\n" in prompt
    assert "\nJEWELRY TYPE: Ring\n" in prompt
    assert "negative_prompt" in rendered


def test_resolve_prompt_task_builds_planner_enrich_prompt_bundle() -> None:
    rendered = resolve_prompt_task(
        PROMPT_TASK_PLANNER_ENRICH,
        {
            "prompt": "A creative launch day",
            "persona": {"display_name": "Maya", "bio": "Founder"},
            "style_profile": {
                "realism_level": "high",
                "camera_style_tags": ["editorial"],
                "color_palette_tags": ["warm"],
            },
            "preferences": {"stories_per_day": 3, "posts_per_day": 1},
            "world_summary": {
                "location_tags": ["studio", "cafe"],
                "wardrobe_tags": ["linen", "gold"],
            },
        },
    )

    assert rendered["model_name"] == os.getenv("GOOGLE_GEMINI_MODEL", "gemini-2.5-flash")
    assert "expert social media manager" in rendered["system_instruction"]
    assert "Persona Name: Maya" in rendered["user_prompt"]
    assert "Available Locations: studio, cafe" in rendered["user_prompt"]


def test_resolve_prompt_task_supports_task_first_on_model_registry() -> None:
    rendered = resolve_prompt_task(
        PROMPT_TASK_ON_MODEL,
        {
            "request": {
                "model": {"slug": "model"},
                "style": {
                    "task_type": "on-model",
                    "public_version_key": "v4.5",
                    "background": "White Studio",
                    "camera": "Portrait",
                    "image_style": "Natural",
                },
                "looks": 1,
                "items": [{"type": "Ring", "size": "Small"}],
            }
        },
    )

    assert rendered["prompts"]
    assert "White Studio" in rendered["prompts"][0]
