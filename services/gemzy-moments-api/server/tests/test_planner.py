"""Tests for the refactored planner package.

Covers: continuity engine, prompt parser, world selector, outfit builder,
block allocator, and integration.

The planner package has a deep transitive import chain through auth → storage
which requires google-cloud packages. We intercept this by mocking both
`server.storage` and all `google.*` modules before importing planner modules.
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import random as _random_module

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Pre-mock all problematic modules ─────────────────────
_goog = MagicMock()
for mod_name in [
    "google", "google.cloud", "google.cloud.storage",
    "google.auth", "google.auth.default", "google.auth.credentials",
    "google.auth.iam", "google.auth.transport", "google.auth.transport.requests",
    "google.oauth2", "google.oauth2.service_account",
]:
    sys.modules.setdefault(mod_name, _goog)

_fake_storage = ModuleType("server.storage")
for _attr in [
    "build_public_url", "get_bucket", "maybe_get_bucket",
    "user_storage_prefix", "upload_file", "generate_signed_url",
    "delete_file", "list_files",
]:
    setattr(_fake_storage, _attr, MagicMock())
sys.modules["server.storage"] = _fake_storage

from server.planner import continuity, prompt_parser, world_selector, outfit_builder, block_allocator


# ═══════════════════════════════════════════════════════════
#  Test: continuity.compute_score
# ═══════════════════════════════════════════════════════════

class TestComputeScore:
    def test_fresh_item_scores_high(self):
        item = {"id": "item-1", "tier": "ANCHOR", "reuse_weight": 1.0}
        now = datetime.now(timezone.utc)
        score = continuity.compute_score(item, {}, now)
        assert isinstance(score, (int, float))
        assert score > 0

    def test_heavily_used_item_scores_lower(self):
        now = datetime.now(timezone.utc)
        item = {"id": "item-2", "tier": "FLEX", "reuse_weight": 0.5}
        usage_map = {
            "item-2": {
                "fatigue_score": 0.9,
                "last_used_at": now.isoformat(),
            }
        }
        fresh_score = continuity.compute_score(
            {"id": "item-3", "tier": "FLEX", "reuse_weight": 0.5}, {}, now
        )
        used_score = continuity.compute_score(item, usage_map, now)
        assert fresh_score >= used_score

    def test_anchor_tier_via_reuse_weight(self):
        now = datetime.now(timezone.utc)
        anchor = {"id": "a", "tier": "ANCHOR", "reuse_weight": 1.0}
        flex = {"id": "b", "tier": "FLEX", "reuse_weight": 0.5}
        assert continuity.compute_score(anchor, {}, now) >= continuity.compute_score(flex, {}, now)


# ═══════════════════════════════════════════════════════════
#  Test: continuity.select_items
# ═══════════════════════════════════════════════════════════

class TestSelectItems:
    def test_select_single(self):
        items = [
            {"id": "1", "tier": "ANCHOR", "reuse_weight": 1.0},
            {"id": "2", "tier": "FLEX", "reuse_weight": 0.5},
        ]
        selected = continuity.select_items(items, {}, count=1)
        assert len(selected) == 1

    def test_select_multiple_unique(self):
        items = [
            {"id": f"item-{i}", "tier": "SEMI_STABLE", "reuse_weight": 1.0}
            for i in range(5)
        ]
        selected = continuity.select_items(items, {}, count=3)
        assert len(selected) == 3
        assert len(set(s["id"] for s in selected)) == 3

    def test_select_from_empty(self):
        assert continuity.select_items([], {}, count=2) == []

    def test_select_more_than_available(self):
        items = [{"id": "only", "tier": "ANCHOR", "reuse_weight": 1.0}]
        assert len(continuity.select_items(items, {}, count=5)) <= 1

    def test_seeded_deterministic(self):
        """Same seed produces same output."""
        items = [
            {"id": f"item-{i}", "tier": "SEMI_STABLE", "reuse_weight": 1.0}
            for i in range(10)
        ]
        rng1 = _random_module.Random(42)
        rng2 = _random_module.Random(42)
        sel1 = continuity.select_items(items, {}, count=3, rng=rng1)
        sel2 = continuity.select_items(items, {}, count=3, rng=rng2)
        assert [s["id"] for s in sel1] == [s["id"] for s in sel2]


# ═══════════════════════════════════════════════════════════
#  Test: continuity — fatigue decay
# ═══════════════════════════════════════════════════════════

class TestFatigueDecay:
    def test_fatigue_decays_over_time(self):
        """Fatigue should reduce significantly after 14+ hours."""
        now = datetime.now(timezone.utc)
        item = {"id": "x", "reuse_weight": 1.0}

        usage_recent = {
            "x": {"fatigue_score": 1.0, "last_used_at": now.isoformat()},
        }
        score_recent = continuity.compute_score(item, usage_recent, now)

        future = now + timedelta(hours=24)
        score_later = continuity.compute_score(item, usage_recent, future)
        assert score_later > score_recent

    def test_fatigue_halves_in_about_14_hours(self):
        decay = math.exp(-continuity.FATIGUE_DECAY_RATE * 14)
        assert 0.45 < decay < 0.55


# ═══════════════════════════════════════════════════════════
#  Test: continuity — in-memory usage update
# ═══════════════════════════════════════════════════════════

class TestUsageMapUpdate:
    def test_usage_map_updated_in_memory(self):
        usage_map: dict[str, dict] = {}
        now = datetime.now(timezone.utc)

        continuity.update_usage_in_memory(usage_map, "item-1", now)
        assert "item-1" in usage_map
        assert usage_map["item-1"]["fatigue_score"] == pytest.approx(0.1)

        continuity.update_usage_in_memory(usage_map, "item-1", now)
        assert usage_map["item-1"]["fatigue_score"] == pytest.approx(0.2)


# ═══════════════════════════════════════════════════════════
#  Test: prompt_parser
# ═══════════════════════════════════════════════════════════

class TestParseActivities:
    def test_basic_keywords(self):
        result = prompt_parser.parse_activities("Morning coffee at the cafe then gym workout")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_empty_prompt(self):
        assert prompt_parser.parse_activities("") == []

    def test_comma_separated(self):
        result = prompt_parser.parse_activities("gym, coffee, dinner")
        assert len(result) == 3

    def test_arrow_separated(self):
        result = prompt_parser.parse_activities("breakfast → work → dinner")
        assert len(result) == 3

    def test_slot_assignment(self):
        result = prompt_parser.parse_activities("gym, dinner, coffee")
        slots = [a["time_slot"] for a in result]
        assert "morning" in slots
        assert "evening" in slots

    def test_regex_split_multiple_delimiters(self):
        """Mixed delimiters should all be split correctly."""
        result = prompt_parser.parse_activities(
            "Gym in the morning, coffee run -> work session; sunset dinner"
        )
        assert len(result) >= 4

    def test_keyword_word_boundary(self):
        """'nightingale' should NOT match 'night' slot."""
        result = prompt_parser.parse_activities("nightingale singing")
        assert result[0]["time_slot"] != "late_night"


# ═══════════════════════════════════════════════════════════
#  Test: world_selector
# ═══════════════════════════════════════════════════════════

class TestWorldSelector:
    def test_select_location_basic(self):
        locations = [
            {"id": "loc-1", "name": "Gym", "tags": ["gym", "fitness"], "tier": "ANCHOR", "reuse_weight": 1.0},
            {"id": "loc-2", "name": "Office", "tags": ["office", "work"], "tier": "SEMI_STABLE", "reuse_weight": 1.0},
        ]
        now = datetime.now(timezone.utc)
        loc = world_selector.select_location(locations, {}, now)
        assert loc is not None
        assert loc["id"] in ("loc-1", "loc-2")

    def test_location_tag_filtering(self):
        """Gym activity should prefer gym-tagged location."""
        locations = [
            {"id": "loc-1", "name": "Gym", "tags": ["gym", "fitness"], "tier": "SEMI_STABLE", "reuse_weight": 1.0},
            {"id": "loc-2", "name": "Restaurant", "tags": ["dining", "evening"], "tier": "SEMI_STABLE", "reuse_weight": 1.0},
        ]
        now = datetime.now(timezone.utc)
        rng = _random_module.Random(42)

        gym_count = 0
        for _ in range(20):
            rng_run = _random_module.Random(rng.randint(0, 10000))
            loc = world_selector.select_location(
                locations, {}, now,
                desired_tags=["gym", "fitness"],
                rng=rng_run,
            )
            if loc and loc["id"] == "loc-1":
                gym_count += 1

        assert gym_count > 10, f"Gym selected only {gym_count}/20 times"

    def test_novelty_selects_low_usage_items(self):
        """When novelty fires, it should prefer items with low fatigue."""
        locations = [
            {"id": "used", "name": "Used", "tags": [], "tier": "SEMI_STABLE", "reuse_weight": 1.0},
            {"id": "fresh", "name": "Fresh", "tags": [], "tier": "SEMI_STABLE", "reuse_weight": 1.0},
        ]
        usage_map = {
            "used": {"fatigue_score": 0.5, "last_used_at": datetime.now(timezone.utc).isoformat()},
        }
        now = datetime.now(timezone.utc)
        rng = _random_module.Random(42)

        loc = world_selector.select_location(
            locations, usage_map, now, novelty=True, rng=rng,
        )
        assert loc is not None
        assert loc["id"] == "fresh"


# ═══════════════════════════════════════════════════════════
#  Test: outfit_builder
# ═══════════════════════════════════════════════════════════

class TestOutfitBuilder:
    def test_outfit_valid_composition(self):
        """Outfit should be top+bottom, dress, or set."""
        wardrobe = [
            {"id": "w-1", "name": "White Tee", "category": "top", "tags": ["casual"], "tier": "SEMI_STABLE", "reuse_weight": 1.0},
            {"id": "w-2", "name": "Black Jeans", "category": "bottom", "tags": ["casual"], "tier": "SEMI_STABLE", "reuse_weight": 1.0},
            {"id": "w-3", "name": "Sneakers", "category": "shoes", "tags": ["casual"], "tier": "FLEX", "reuse_weight": 1.0},
        ]
        now = datetime.now(timezone.utc)
        rng = _random_module.Random(42)

        result = outfit_builder.build_outfit(wardrobe, {}, now, rng=rng)
        assert len(result.items) >= 2
        categories = {it.get("category") for it in result.items}
        assert "top" in categories
        assert "bottom" in categories

    def test_dress_only_outfit(self):
        wardrobe = [
            {"id": "d-1", "name": "Black Dress", "category": "dress", "tags": ["elegant"], "tier": "SEMI_STABLE", "reuse_weight": 1.0},
            {"id": "s-1", "name": "Heels", "category": "shoes", "tags": ["elegant"], "tier": "FLEX", "reuse_weight": 1.0},
        ]
        now = datetime.now(timezone.utc)
        rng = _random_module.Random(42)

        result = outfit_builder.build_outfit(wardrobe, {}, now, rng=rng)
        assert any(it.get("category") == "dress" for it in result.items)
        assert result.composition_type == "dress"

    def test_empty_wardrobe(self):
        result = outfit_builder.build_outfit([], {}, datetime.now(timezone.utc))
        assert result.items == []
        assert result.composition_type == "empty"


# ═══════════════════════════════════════════════════════════
#  Test: block_allocator
# ═══════════════════════════════════════════════════════════

class TestBlockAllocator:
    def test_distribution_sums_to_target(self):
        result = block_allocator.distribute_formats(
            total_stories=3, total_posts=1,
            block_slots=["morning", "midday", "afternoon", "evening"],
        )
        total_stories = sum(v["stories"] for v in result.values())
        total_posts = sum(v["posts"] for v in result.values())
        assert total_stories + total_posts == 4

    def test_no_slots(self):
        assert block_allocator.distribute_formats(3, 1, []) == {}

    def test_single_slot(self):
        result = block_allocator.distribute_formats(2, 1, ["morning"])
        assert result["morning"]["stories"] + result["morning"]["posts"] == 3

    def test_exact_distribution_no_overshoot(self):
        result = block_allocator.distribute_formats(
            total_stories=2, total_posts=1,
            block_slots=["morning", "midday", "afternoon", "evening", "late_night"],
        )
        total = sum(v["stories"] + v["posts"] for v in result.values())
        assert total == 3

    def test_generate_default_activities(self):
        distribution = {"morning": 0.3, "midday": 0.2, "afternoon": 0.2, "evening": 0.2, "late_night": 0.1}
        activities = block_allocator.generate_default_activities(distribution, 4)
        assert len(activities) == 4
        assert all("time_slot" in a for a in activities)


# ═══════════════════════════════════════════════════════════
#  Test: outfit hash
# ═══════════════════════════════════════════════════════════

class TestOutfitHash:
    def test_deterministic(self):
        r1 = outfit_builder.OutfitResult(
            [{"id": "a"}, {"id": "b"}, {"id": "c"}], composition_type="top+bottom"
        )
        r2 = outfit_builder.OutfitResult(
            [{"id": "a"}, {"id": "b"}, {"id": "c"}], composition_type="top+bottom"
        )
        assert r1.hash == r2.hash

    def test_order_independent(self):
        r1 = outfit_builder.OutfitResult(
            [{"id": "a"}, {"id": "b"}, {"id": "c"}], composition_type="top+bottom"
        )
        r2 = outfit_builder.OutfitResult(
            [{"id": "c"}, {"id": "a"}, {"id": "b"}], composition_type="top+bottom"
        )
        assert r1.hash == r2.hash

    def test_different_inputs(self):
        r1 = outfit_builder.OutfitResult([{"id": "a"}], composition_type="dress")
        r2 = outfit_builder.OutfitResult([{"id": "b"}], composition_type="dress")
        assert r1.hash != r2.hash
