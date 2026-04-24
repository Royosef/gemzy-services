"""Outfit builder — category-aware wardrobe composition."""
from __future__ import annotations

import hashlib
import random as _random_module
from datetime import datetime, timezone
from typing import Any

from .continuity import select_items, update_usage_in_memory

BASE_COMBOS: list[list[str]] = [
    ["top", "bottom"],
    ["dress"],
    ["set"],
]

OPTIONAL_CATEGORIES = ["shoes", "accessory", "outerwear"]


def _compute_tag_overlap(item_tags: list, desired_tags: list[str]) -> float:
    if not desired_tags or not item_tags:
        return 0.0
    item_set = {str(t).lower() for t in item_tags}
    desired_set = {t.lower() for t in desired_tags}
    matches = len(item_set & desired_set)
    for it in item_set:
        for dt in desired_set:
            if dt in it or it in dt:
                matches += 0.5
    return min(2.0, (matches / max(1, len(desired_set))) * 2.0)


def _tier_weight(tier: str) -> float:
    return {"ANCHOR": 0.3, "SEMI_STABLE": 0.0, "FLEX": 0.1}.get(tier, 0.0)


class OutfitResult:
    """Result of outfit assembly."""

    def __init__(self, items: list[dict], *, composition_type: str):
        self.items = items
        self.composition_type = composition_type

    @property
    def item_ids(self) -> list[str]:
        return [it["id"] for it in self.items]

    @property
    def item_names(self) -> list[str]:
        return [it.get("name", "") for it in self.items]

    @property
    def hash(self) -> str:
        return hashlib.md5(
            ",".join(sorted(self.item_ids)).encode()
        ).hexdigest()[:12]

    def to_composition_dict(self) -> dict[str, Any]:
        return {
            "type": self.composition_type,
            "items": self.item_names,
            "categories": [it.get("category", "") for it in self.items],
            "hash": self.hash,
        }


def build_outfit(
    wardrobe: list[dict],
    usage_map: dict[str, dict],
    now: datetime,
    *,
    desired_tags: list[str] | None = None,
    rng: _random_module.Random | None = None,
    novelty: bool = False,
) -> OutfitResult:
    """Assemble a valid outfit from the wardrobe catalog."""
    if not wardrobe:
        return OutfitResult([], composition_type="empty")

    rng = rng or _random_module.Random()
    desired_tags = desired_tags or []

    by_category: dict[str, list[dict]] = {}
    for item in wardrobe:
        cat = item.get("category", "")
        by_category.setdefault(cat, []).append(item)

    tag_bonuses: dict[str, float] = {}
    for item in wardrobe:
        item_tags = item.get("tags", [])
        tier = item.get("tier", "SEMI_STABLE")
        tag_bonuses[item["id"]] = (
            _compute_tag_overlap(item_tags, desired_tags) + _tier_weight(tier)
        )

    selected_items: list[dict] = []
    composition_type = "fallback"

    for combo in BASE_COMBOS:
        if all(cat in by_category for cat in combo):
            items_for_combo: list[dict] = []
            for cat in combo:
                candidates = by_category[cat]
                if novelty:
                    low_usage = [
                        w for w in candidates
                        if usage_map.get(w["id"], {}).get("fatigue_score", 0.0) < 0.1
                    ]
                    if low_usage:
                        candidates = low_usage
                cat_bonuses = {w["id"]: tag_bonuses.get(w["id"], 0.0) for w in candidates}
                picked = select_items(
                    candidates, usage_map, count=1, now=now,
                    tag_bonuses=cat_bonuses, rng=rng,
                )
                if picked:
                    items_for_combo.append(picked[0])
            if len(items_for_combo) == len(combo):
                selected_items = items_for_combo
                composition_type = "+".join(combo)
                break

    for opt_cat in OPTIONAL_CATEGORIES:
        if opt_cat in by_category and rng.random() > 0.4:
            candidates = by_category[opt_cat]
            cat_bonuses = {w["id"]: tag_bonuses.get(w["id"], 0.0) for w in candidates}
            picked = select_items(
                candidates, usage_map, count=1, now=now,
                tag_bonuses=cat_bonuses, rng=rng,
            )
            if picked:
                selected_items.append(picked[0])

    if not selected_items:
        candidates = wardrobe
        if novelty:
            low_usage = [
                w for w in candidates
                if usage_map.get(w["id"], {}).get("fatigue_score", 0.0) < 0.1
            ]
            if low_usage:
                candidates = low_usage
        selected_items = select_items(
            candidates, usage_map, count=2, now=now,
            tag_bonuses=tag_bonuses, rng=rng,
        )

    for item in selected_items:
        update_usage_in_memory(usage_map, item["id"], now)

    return OutfitResult(selected_items, composition_type=composition_type)
