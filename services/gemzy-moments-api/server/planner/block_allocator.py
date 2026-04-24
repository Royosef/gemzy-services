"""Block allocator — proportional story/post distribution."""
from __future__ import annotations

from .prompt_parser import TIME_SLOTS, SLOT_TEMPLATES


def _distribute_exact(weights: dict[str, float], total: int) -> dict[str, int]:
    """Distribute total across keys proportional to weights (largest-remainder)."""
    if not weights or total <= 0:
        return {}
    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        per_key = total // len(weights)
        remainder = total - per_key * len(weights)
        result = {k: per_key for k in weights}
        for i, k in enumerate(result):
            if i < remainder:
                result[k] += 1
        return result
    raw = {k: (v / weight_sum) * total for k, v in weights.items()}
    floored = {k: int(v) for k, v in raw.items()}
    remainder = total - sum(floored.values())
    fractional = sorted(raw.keys(), key=lambda k: raw[k] - floored[k], reverse=True)
    for i in range(remainder):
        floored[fractional[i]] += 1
    return floored


def distribute_formats(
    total_stories: int,
    total_posts: int,
    block_slots: list[str],
) -> dict[str, dict[str, int]]:
    """Distribute stories and posts across blocks proportionally."""
    if not block_slots:
        return {}
    total = total_stories + total_posts
    n_blocks = len(block_slots)
    if total <= 0:
        return {slot: {"stories": 0, "posts": 0} for slot in block_slots}
    weights = {slot: 1.0 / n_blocks for slot in block_slots}
    block_counts = _distribute_exact(weights, total)
    result: dict[str, dict[str, int]] = {}
    stories_left = total_stories
    posts_left = total_posts
    for slot in block_slots:
        count = block_counts.get(slot, 0)
        if stories_left + posts_left > 0:
            story_share = round(count * total_stories / total) if total > 0 else 0
            story_share = min(story_share, stories_left)
            story_share = max(story_share, count - posts_left)
            story_share = max(0, min(story_share, count))
            post_share = count - story_share
            post_share = min(post_share, posts_left)
            story_share = count - post_share
        else:
            story_share = count
            post_share = 0
        stories_left -= story_share
        posts_left -= post_share
        result[slot] = {"stories": story_share, "posts": post_share}
    return result


def generate_default_activities(
    distribution: dict[str, float],
    total_target: int,
) -> list[dict]:
    """Generate default activities from distribution profile."""
    slot_counts = _distribute_exact(distribution, total_target)
    activities: list[dict] = []
    for slot in TIME_SLOTS:
        count = slot_counts.get(slot, 0)
        if count <= 0:
            continue
        template = SLOT_TEMPLATES.get(slot, {})
        typical = template.get("activities", ["daily moment"])
        for i in range(count):
            activities.append({
                "description": typical[i % len(typical)],
                "time_slot": slot,
            })
    return activities
