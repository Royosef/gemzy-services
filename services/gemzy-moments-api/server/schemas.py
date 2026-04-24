"""Pydantic schemas for the backend API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

try:  # pragma: no cover - dependency optional for tests
    from pydantic import EmailStr as _EmailStr
    import email_validator as _email_validator  # noqa: F401

    EmailStr = _EmailStr
except ImportError:  # pragma: no cover - fallback when email-validator is missing
    EmailStr = str  # type: ignore[misc, assignment]


class MagicLinkRequest(BaseModel):
    """Request payload to send a magic link."""
    email: EmailStr


class VerifyRequest(BaseModel):
    """Payload to verify an emailed one-time code."""
    email: EmailStr
    token: str


class OAuthRequest(BaseModel):
    provider: Literal["google", "apple"]
    token: str
    nonce: str | None = None
    name: str | None = None

class NotificationPreferences(BaseModel):
    """Notification preferences stored for a user."""

    gemzyUpdates: bool = True
    personalUpdates: bool = True
    email: bool = True


class ProfileUpdate(BaseModel):
    """Payload to update mutable profile fields."""

    name: str | None = None
    avatarUrl: str | None = None
    notifications: NotificationPreferences | None = None
    credits: int | None = None
    momentsOnboardingCompleted: bool | None = None

class RefreshRequest(BaseModel):
    """Payload containing a refresh token."""
    refresh: str


class Token(BaseModel):
    """Access and refresh tokens."""
    access: str
    refresh: str


class UserState(BaseModel):
    """User state returned to the mobile app."""

    id: str
    name: str | None = None
    plan: str | None = None
    credits: int = 0
    avatarUrl: str | None = None
    notificationPreferences: NotificationPreferences | None = None
    isAdmin: bool = False
    reactivatedAt: str | None = None
    retentionOfferUsed: bool = False
    retentionOfferUsedAt: str | None = None
    momentsOnboardingCompleted: bool = False


class AuthResponse(BaseModel):
    """Response returned after login or registration."""
    token: Token
    user: UserState
    is_new: bool = False


