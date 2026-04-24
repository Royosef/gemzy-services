"""Fallback prompt parser — regex-based activity extraction."""
from __future__ import annotations

import re

TIME_SLOTS = ["morning", "midday", "afternoon", "evening", "late_night"]

SLOT_TEMPLATES = {
    "morning": {
        "activities": ["gym", "breakfast", "morning routine", "mirror selfie", "yoga"],
        "moods": ["energetic", "fresh", "motivated", "calm"],
    },
    "midday": {
        "activities": ["coffee run", "errands", "work", "lunch", "meetings"],
        "moods": ["productive", "casual", "social", "focused"],
    },
    "afternoon": {
        "activities": ["shopping", "laptop work", "creative session", "spa"],
        "moods": ["focused", "relaxed", "creative", "luxurious"],
    },
    "evening": {
        "activities": ["dinner", "sunset", "date night", "rooftop"],
        "moods": ["warm", "romantic", "social", "glamorous"],
    },
    "late_night": {
        "activities": ["home cozy", "reflection", "nightlife", "skyline"],
        "moods": ["intimate", "relaxed", "aesthetic", "mysterious"],
    },
}

KEYWORD_SLOT: dict[str, str] = {
    "gym": "morning", "workout": "morning", "breakfast": "morning",
    "yoga": "morning", "morning": "morning",
    "coffee": "midday", "cafe": "midday",
    "lunch": "midday", "work": "midday", "meeting": "midday",
    "shopping": "afternoon", "mall": "afternoon", "spa": "afternoon",
    "laptop": "afternoon", "creative": "afternoon",
    "dinner": "evening", "sunset": "evening", "date": "evening",
    "restaurant": "evening", "rooftop": "evening",
    "home": "late_night", "night": "late_night", "club": "late_night",
    "party": "late_night", "cozy": "late_night",
}

_KEYWORD_PATTERNS: dict[str, re.Pattern] = {
    kw: re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in KEYWORD_SLOT
}

_SPLIT_PATTERN = re.compile(r"[;,.\n]|->|→")


def parse_activities(description: str) -> list[dict]:
    """Parse user prompt into activities with time slot hints."""
    if not description:
        return []

    parts = [p.strip() for p in _SPLIT_PATTERN.split(description) if p.strip()]
    if not parts:
        parts = [description.strip()]

    activities: list[dict] = []
    used_slots: set[str] = set()

    for i, part in enumerate(parts):
        slot_scores: dict[str, int] = {}
        for keyword, slot in KEYWORD_SLOT.items():
            if _KEYWORD_PATTERNS[keyword].search(part):
                slot_scores[slot] = slot_scores.get(slot, 0) + 1

        if slot_scores:
            matched_slot = max(slot_scores, key=slot_scores.get)  # type: ignore[arg-type]
        else:
            idx = min(i, len(TIME_SLOTS) - 1)
            matched_slot = TIME_SLOTS[idx]

        if matched_slot in used_slots and len(used_slots) < len(TIME_SLOTS):
            for s in TIME_SLOTS:
                if s not in used_slots:
                    matched_slot = s
                    break

        used_slots.add(matched_slot)
        activities.append({"description": part, "time_slot": matched_slot})

    return activities
