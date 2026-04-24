"""World selector — tag-matching, tier-aware, novelty-injecting item selection."""
from __future__ import annotations

import random as _random_module
from datetime import datetime, timezone

from .continuity import compute_score, select_items, update_usage_in_memory


def _compute_tag_overlap(item_tags: list, desired_tags: list[str]) -> float:
    if not desired_tags or not item_tags:
        return 0.0
    item_set = {str(t).lower() for t in item_tags}
    desired_set = {t.lower() for t in desired_tags}
    if not desired_set:
        return 0.0
    matches = len(item_set & desired_set)
    for it in item_set:
        for dt in desired_set:
            if dt in it or it in dt:
                matches += 0.5
    return min(2.0, (matches / len(desired_set)) * 2.0)


def _tier_weight(tier: str) -> float:
    return {"ANCHOR": 0.3, "SEMI_STABLE": 0.0, "FLEX": 0.1}.get(tier, 0.0)


def select_location(
    locations: list[dict],
    usage_map: dict[str, dict],
    now: datetime,
    *,
    desired_tags: list[str] | None = None,
    novelty: bool = False,
    rng: _random_module.Random | None = None,
) -> dict | None:
    """Select a single location guided by AI semantic tags."""
    if not locations:
        return None
    rng = rng or _random_module.Random()
    desired_tags = desired_tags or []
    candidates = locations
    if novelty:
        low_usage = [
            loc for loc in candidates
            if usage_map.get(loc["id"], {}).get("fatigue_score", 0.0) < 0.1
        ]
        if low_usage:
            candidates = low_usage
    tag_bonuses: dict[str, float] = {}
    for loc in candidates:
        item_tags = loc.get("tags", [])
        tier = loc.get("tier", "SEMI_STABLE")
        tag_bonuses[loc["id"]] = (
            _compute_tag_overlap(item_tags, desired_tags)
            + _tier_weight(tier)
        )
    selected = select_items(
        candidates, usage_map, count=1, now=now,
        tag_bonuses=tag_bonuses, rng=rng,
    )
    if selected:
        update_usage_in_memory(usage_map, selected[0]["id"], now)
        return selected[0]
    return None


def select_wardrobe_items(
    wardrobe: list[dict],
    usage_map: dict[str, dict],
    now: datetime,
    *,
    desired_tags: list[str] | None = None,
    count: int = 2,
    novelty: bool = False,
    rng: _random_module.Random | None = None,
) -> list[dict]:
    """Select wardrobe items guided by AI semantic tags."""
    if not wardrobe:
        return []
    rng = rng or _random_module.Random()
    desired_tags = desired_tags or []
    candidates = wardrobe
    if novelty:
        low_usage = [
            w for w in candidates
            if usage_map.get(w["id"], {}).get("fatigue_score", 0.0) < 0.1
        ]
        if low_usage:
            candidates = low_usage
    tag_bonuses: dict[str, float] = {}
    for w in candidates:
        item_tags = w.get("tags", [])
        tier = w.get("tier", "SEMI_STABLE")
        tag_bonuses[w["id"]] = (
            _compute_tag_overlap(item_tags, desired_tags)
            + _tier_weight(tier)
        )
    selected = select_items(
        candidates, usage_map, count=count, now=now,
        tag_bonuses=tag_bonuses, rng=rng,
    )
    for item in selected:
        update_usage_in_memory(usage_map, item["id"], now)
    return selected
