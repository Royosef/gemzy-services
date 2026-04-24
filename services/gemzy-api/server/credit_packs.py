"""Shared credit pack configuration for server and client consumers."""
from __future__ import annotations

from typing import TypedDict


class CreditPackConfig(TypedDict):
    code: str
    credits: int
    aliases: list[str]
    compare_at_multiplier: float
    badge: str | None
    is_default: bool


CREDIT_PACKS: tuple[CreditPackConfig, ...] = (
    {
        "code": "small",
        "credits": 100,
        "aliases": ["credits_s", "credits_S"],
        "compare_at_multiplier": 4 / 3,
        "badge": None,
        "is_default": False,
    },
    {
        "code": "medium",
        "credits": 300,
        "aliases": ["credits_m", "credits_M"],
        "compare_at_multiplier": 4 / 3,
        "badge": "Most popular",
        "is_default": True,
    },
    {
        "code": "large",
        "credits": 700,
        "aliases": ["cresits_l", "credits_L"],
        "compare_at_multiplier": 4 / 3,
        "badge": None,
        "is_default": False,
    },
    {
        "code": "extra_large",
        "credits": 1500,
        "aliases": ["credits_xl", "credits_XL"],
        "compare_at_multiplier": 4 / 3,
        "badge": "Best value",
        "is_default": False,
    },
)


def get_credit_pack_configs() -> list[CreditPackConfig]:
    return [dict(pack) for pack in CREDIT_PACKS]


def match_credit_pack(identifier: str | None) -> CreditPackConfig | None:
    if not identifier:
        return None

    normalized_identifier = identifier.strip().lower()

    for pack in CREDIT_PACKS:
        for alias in pack["aliases"]:
            if normalized_identifier == alias.lower():
                return dict(pack)

    return None


__all__ = ["CreditPackConfig", "get_credit_pack_configs", "match_credit_pack"]
