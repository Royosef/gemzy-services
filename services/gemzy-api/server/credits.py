"""Shared helpers for credit reset scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

CREDIT_RESET_INTERVAL = timedelta(days=30)


def isoformat_utc(value: datetime) -> str:
    """Return a normalized UTC ISO-8601 timestamp."""

    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def schedule_next_credit_reset(*, now: datetime | None = None) -> str:
    """Return the next monthly credit reset timestamp."""

    base = now or datetime.now(timezone.utc)
    return isoformat_utc(base + CREDIT_RESET_INTERVAL)


__all__ = ["CREDIT_RESET_INTERVAL", "isoformat_utc", "schedule_next_credit_reset"]
