"""Tests for generation worker - prompt building, context fetching, job processing.

Tests the pure functions in generation_worker.py without requiring a real
generation server or Supabase connection.
"""
from __future__ import annotations

import sys
from pathlib import Path

from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import generation_worker
from server.generation_worker import _build_prompt_from_context


class TestBuildPrompt:
    def test_minimal_moment(self):
        moment = {"moment_type": "STORY", "caption_hint": None}
        prompt = _build_prompt_from_context(moment, None, None, None, None)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_full_context(self):
        moment = {
            "moment_type": "POST",
            "caption_hint": "Morning coffee at the cafe",
        }
        context = {
            "location_id": "loc-1",
            "mood_tags": ["cozy", "relaxed"],
            "continuity_notes": "Same cafe as yesterday",
        }
        persona = {
            "id": "p-1",
            "display_name": "Luna",
            "bio": "Digital nomad and coffee enthusiast",
        }
        location = {
            "name": "Artisan Cafe",
            "tags": ["indoor", "warm lighting"],
            "description": "A small corner cafe with warm wood and soft window light",
        }
        wardrobe = [
            {"name": "Beige cardigan", "category": "top", "tags": ["casual"]},
            {"name": "White sneakers", "category": "shoes", "tags": ["sporty"]},
        ]

        prompt = _build_prompt_from_context(moment, context, persona, location, wardrobe)

        assert "PERSONA LOCK: Luna." in prompt
        assert "Morning coffee at the cafe" in prompt
        assert "Artisan Cafe" in prompt
        assert "OUTFIT BLOCK:" in prompt
        assert "Beige cardigan" in prompt
        assert "MOOD: cozy, relaxed" in prompt
        assert "Same cafe as yesterday" in prompt
        assert "Aspect Ratio: square 1:1 image intended as a hero Instagram post." in prompt

    def test_story_format(self):
        moment = {"moment_type": "STORY", "caption_hint": "Gym first"}
        prompt = _build_prompt_from_context(moment, None, None, None, None)
        assert "Aspect Ratio: vertical 9:16 image intended as a Story." in prompt

    def test_post_format(self):
        moment = {"moment_type": "POST", "caption_hint": "Park vibes"}
        prompt = _build_prompt_from_context(moment, None, None, None, None)
        assert "Aspect Ratio: square 1:1 image intended as a hero Instagram post." in prompt

    def test_wardrobe_formatting(self):
        moment = {"moment_type": "STORY", "caption_hint": None}
        wardrobe = [
            {"name": "Red dress", "category": "dress", "tags": ["elegant", "evening"]},
        ]
        prompt = _build_prompt_from_context(moment, None, None, None, wardrobe)
        assert "OUTFIT BLOCK:" in prompt
        assert "Red dress" in prompt
        assert "elegant" in prompt

    def test_mood_tags(self):
        moment = {"moment_type": "POST", "caption_hint": None}
        context = {"mood_tags": ["energetic", "fun"], "location_id": None}
        prompt = _build_prompt_from_context(moment, context, None, None, None)
        assert "MOOD: energetic, fun" in prompt

    def test_persona_bio(self):
        moment = {"moment_type": "STORY", "caption_hint": None}
        persona = {"id": "p-1", "display_name": "Alex", "bio": "Fitness influencer"}
        prompt = _build_prompt_from_context(moment, None, persona, None, None)
        assert "PERSONA LOCK: Alex." in prompt
        assert "Fitness influencer" in prompt

    def test_no_persona_bio(self):
        moment = {"moment_type": "STORY", "caption_hint": None}
        persona = {"id": "p-1", "display_name": "Sam", "bio": None}
        prompt = _build_prompt_from_context(moment, None, persona, None, None)
        assert "PERSONA LOCK: Sam." in prompt

    def test_camera_prompt_spec_prioritizes_first_sentence(self):
        moment = {"moment_type": "STORY", "caption_hint": "Gym mirror check-in"}
        context = {
            "outfit_composition": {
                "planner_prompt_spec": {
                    "camera_type": "mirror_selfie",
                    "camera_perspective": "Mirror selfie captured on her phone rear camera. The image IS the mirror reflection from that single phone.",
                }
            }
        }
        prompt = _build_prompt_from_context(
            moment,
            context,
            {"id": "p-1", "display_name": "Nia"},
            None,
            None,
        )
        assert prompt.startswith("Mirror selfie captured on her phone rear camera.")

    def test_environment_only_prompt_excludes_persona(self):
        moment = {"moment_type": "STORY", "caption_hint": "Hotel room arrival"}
        context = {
            "outfit_composition": {
                "planner_prompt_spec": {
                    "camera_type": "environment_only",
                }
            }
        }
        prompt = _build_prompt_from_context(
            moment,
            context,
            {"id": "p-1", "display_name": "Nia"},
            None,
            None,
        )
        assert "is not in frame" in prompt


def test_reference_assets_missing_error_detected():
    exc = APIError(
        {
            "message": "Could not find the table 'people.reference_assets' in the schema cache",
            "code": "PGRST205",
            "hint": None,
            "details": None,
        }
    )

    assert generation_worker._is_reference_assets_missing_error(exc) is True
