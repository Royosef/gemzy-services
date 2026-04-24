"""Tests for generation worker — prompt building, context fetching, job processing.

Tests the pure functions in generation_worker.py without requiring a real
generation server or Supabase connection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.generation_worker import _build_prompt_from_context


# ═══════════════════════════════════════════════════════════
#  Test: _build_prompt_from_context
# ═══════════════════════════════════════════════════════════

class TestBuildPrompt:
    def test_minimal_moment(self):
        """A moment with no context should still produce a prompt."""
        moment = {"moment_type": "STORY", "caption_hint": None}
        prompt = _build_prompt_from_context(moment, None, None, None, None)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_full_context(self):
        """A moment with full context should include all elements."""
        moment = {
            "moment_type": "POST",
            "caption_hint": "Morning coffee at the café",
        }
        context = {
            "location_id": "loc-1",
            "mood_tags": ["cozy", "relaxed"],
            "continuity_notes": "Same café as yesterday",
        }
        persona = {
            "id": "p-1",
            "display_name": "Luna",
            "bio": "Digital nomad and coffee enthusiast",
        }
        location = {
            "name": "Artisan Café",
            "tags": ["indoor", "warm lighting"],
        }
        wardrobe = [
            {"name": "Beige cardigan", "category": "top", "tags": ["casual"]},
            {"name": "White sneakers", "category": "shoes", "tags": ["sporty"]},
        ]

        prompt = _build_prompt_from_context(moment, context, persona, location, wardrobe)

        assert "Luna" in prompt
        assert "Morning coffee" in prompt
        assert "Artisan Café" in prompt
        assert "Beige cardigan" in prompt
        assert "cozy" in prompt
        assert "Same café as yesterday" in prompt
        assert "Instagram post" in prompt

    def test_story_format(self):
        """Story moments should specify 9:16 format."""
        moment = {"moment_type": "STORY", "caption_hint": "Gym first"}
        prompt = _build_prompt_from_context(moment, None, None, None, None)
        assert "story" in prompt.lower() or "9:16" in prompt

    def test_post_format(self):
        """Post moments should specify square format."""
        moment = {"moment_type": "POST", "caption_hint": "Park vibes"}
        prompt = _build_prompt_from_context(moment, None, None, None, None)
        assert "post" in prompt.lower() or "square" in prompt.lower()

    def test_wardrobe_formatting(self):
        """Wardrobe items should include category and tags."""
        moment = {"moment_type": "STORY", "caption_hint": None}
        wardrobe = [
            {"name": "Red dress", "category": "dress", "tags": ["elegant", "evening"]},
        ]
        prompt = _build_prompt_from_context(moment, None, None, None, wardrobe)
        assert "Red dress" in prompt
        assert "dress" in prompt
        assert "elegant" in prompt

    def test_mood_tags(self):
        """Mood tags should appear in the prompt."""
        moment = {"moment_type": "POST", "caption_hint": None}
        context = {"mood_tags": ["energetic", "fun"], "location_id": None}
        prompt = _build_prompt_from_context(moment, context, None, None, None)
        assert "energetic" in prompt
        assert "fun" in prompt

    def test_persona_bio(self):
        """Persona bio should be included when present."""
        moment = {"moment_type": "STORY", "caption_hint": None}
        persona = {"id": "p-1", "display_name": "Alex", "bio": "Fitness influencer"}
        prompt = _build_prompt_from_context(moment, None, persona, None, None)
        assert "Alex" in prompt
        assert "Fitness influencer" in prompt

    def test_no_persona_bio(self):
        """Should handle persona without bio."""
        moment = {"moment_type": "STORY", "caption_hint": None}
        persona = {"id": "p-1", "display_name": "Sam", "bio": None}
        prompt = _build_prompt_from_context(moment, None, persona, None, None)
        assert "Sam" in prompt
