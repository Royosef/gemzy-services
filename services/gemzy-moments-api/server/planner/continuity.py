"""Continuity engine — fatigue decay, scoring, and in-memory usage tracking.

Shared by world_selector and outfit_builder.
"""
from __future__ import annotations

import math
import random as _random_module
from datetime import datetime, timezone


# Fatigue halves every ~14 hours  (decay_rate = 0.05 / hour)
FATIGUE_DECAY_RATE = 0.05

# Fatigue increment per use within a single planning run
FATIGUE_INCREMENT = 0.1


def compute_score(
    item: dict,
    usage_map: dict[str, dict],
    now: datetime,
    *,
    tag_bonus: float = 0.0,
) -> float:
    """Score a world item for selection.

    score = reuse_weight + tag_bonus - effective_fatigue - cooldown_penalty
    Higher = more likely to be selected.
    """
    item_id = item["id"]
    reuse_w = item.get("reuse_weight", 1.0)
    cooldown_h = item.get("cooldown_hours", 0)

    stats = usage_map.get(item_id, {})
    raw_fatigue = stats.get("fatigue_score", 0.0)
    last_used = stats.get("last_used_at")

    # Fatigue decay
    effective_fatigue = raw_fatigue
    if last_used and raw_fatigue > 0:
        if isinstance(last_used, str):
            last_used = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
        hours_since = (now - last_used).total_seconds() / 3600
        effective_fatigue = raw_fatigue * math.exp(-FATIGUE_DECAY_RATE * hours_since)

    # Cooldown penalty
    cooldown_penalty = 0.0
    if last_used and cooldown_h > 0:
        if isinstance(last_used, str):
            last_used = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
        hours_since = (now - last_used).total_seconds() / 3600
        if hours_since < cooldown_h:
            cooldown_penalty = 100.0

    return reuse_w + tag_bonus - effective_fatigue - cooldown_penalty


def select_items(
    items: list[dict],
    usage_map: dict[str, dict],
    count: int = 1,
    now: datetime | None = None,
    *,
    tag_bonuses: dict[str, float] | None = None,
    rng: _random_module.Random | None = None,
) -> list[dict]:
    """Select top-N items by score, with controlled randomness."""
    if not items:
        return []

    now = now or datetime.now(timezone.utc)
    rng = rng or _random_module.Random()
    tag_bonuses = tag_bonuses or {}

    scored = [
        (item, compute_score(item, usage_map, now, tag_bonus=tag_bonuses.get(item["id"], 0.0)))
        for item in items
    ]

    available = [(it, s) for it, s in scored if s > -50]
    if not available:
        available = scored

    available.sort(key=lambda x: x[1] + rng.uniform(0, 0.3), reverse=True)

    return [it for it, _ in available[:count]]


def update_usage_in_memory(
    usage_map: dict[str, dict],
    item_id: str,
    now: datetime,
) -> None:
    """Mutate usage_map in place after selecting an item."""
    if item_id not in usage_map:
        usage_map[item_id] = {}

    stats = usage_map[item_id]
    stats["last_used_at"] = now.isoformat()
    stats["fatigue_score"] = stats.get("fatigue_score", 0.0) + FATIGUE_INCREMENT
