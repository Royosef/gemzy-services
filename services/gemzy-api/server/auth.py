"""Authentication routes and helpers."""

from __future__ import annotations
import base64
import binascii
import hashlib
import json
import logging
import mimetypes
import os
import secrets
from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import uuid4
import base64, json

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

import httpx
from fastapi.responses import RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from postgrest.exceptions import APIError
from urllib.parse import quote, unquote
from pydantic import BaseModel, Field

from .schemas import (
    AuthResponse,
    MagicLinkRequest,
    NotificationPreferences,
    OAuthRequest,
    ProfileUpdate,
    RefreshRequest,
    StyleTrialState,
    StyleTrialsUpdate,
    Token,
    UserState,
    VerifyRequest,
)
from .credits import schedule_next_credit_reset
from .plans import get_plan_initial_credits, normalize_plan
from .storage import build_public_url, get_bucket, user_storage_prefix
from .supabase_client import create_user_client, get_client, get_service_role_client
from .user_admin import (
    clear_user_deactivation,
    get_admin_user_metadata,
    schedule_user_deletion,
    update_user_metadata,
)
from .rate_limit import limiter, LIMIT_auth_send, LIMIT_auth_verify, LIMIT_oauth_login

router = APIRouter(prefix="/auth", tags=["auth"])
oauth_router = APIRouter(prefix="/oauth", tags=["oauth"])
security = HTTPBearer()

nonce_store: dict[str, str] = {}
logger = logging.getLogger(__name__)
DEFAULT_STYLE_TRIAL_REMAINING_USES = 3

TEST_LOGIN_USER_ID = "286b4672-8f6e-44cc-945f-7a3d113c50b2"
TEST_LOGIN_EMAIL = "testgemzy@gemzy.co"
TEST_LOGIN_CODE = "123455"
TEST_LOGIN_PASSWORD = "3cb2baca4d"

GCS_PROJECT = os.getenv("GCS_PROJECT")
AVATAR_BUCKET = os.getenv("GCS_AVATARS_BUCKET") or os.getenv(
    "GCS_COLLECTIONS_PUBLIC_BUCKET"
)
AVATAR_PUBLIC_HOST = os.getenv("GCS_AVATARS_PUBLIC_HOST") or os.getenv(
    "GCS_PUBLIC_HOST"
)
AVATAR_CACHE_CONTROL = os.getenv(
    "GCS_AVATARS_CACHE_CONTROL", "public, max-age=604800, immutable"
)
AVATAR_MAX_BYTES = int(os.getenv("GCS_AVATARS_MAX_BYTES", "2097152"))
AVATAR_OWNER_METADATA_KEY = os.getenv("GCS_OWNER_METADATA_KEY", "appUserId")
AVATAR_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}



GOOGLE_WEB_CLIENT_ID = os.getenv("GOOGLE_WEB_CLIENT_ID")
GOOGLE_WEB_CLIENT_SECRET = os.getenv("GOOGLE_WEB_CLIENT_SECRET")


def _get_avatar_bucket():
    return get_bucket(
        AVATAR_BUCKET,
        GCS_PROJECT,
        missing_message="Avatar storage bucket is not configured",
    )


def _resolve_avatar_content_type(upload: UploadFile) -> tuple[str, str]:
    """Return a validated content type and extension for an avatar upload."""

    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if not content_type and upload.filename:
        guessed, _ = mimetypes.guess_type(upload.filename)
        if guessed:
            content_type = guessed.lower()

    if not content_type:
        content_type = "image/jpeg"

    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image uploads are supported",
        )

    if (
        AVATAR_ALLOWED_CONTENT_TYPES
        and content_type not in AVATAR_ALLOWED_CONTENT_TYPES
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported avatar format. Please upload a JPEG, PNG, or WebP image.",
        )

    extension = mimetypes.guess_extension(content_type) or ".jpg"
    if extension == ".jpe":
        extension = ".jpg"

    return content_type, extension


def _parse_iso_datetime(value: object | None) -> datetime | None:
    """Parse ISO formatted timestamps, returning UTC datetimes."""

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _month_start(value: datetime) -> datetime:
    """Return the start of the month for the provided datetime."""

    return value.astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


def _extract_avatar(profile: dict) -> str | None:
    """Resolve the avatar URL stored on the profile record."""

    candidate = profile.get("avatar_url")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


def _decode_jwt_payload(token: str | None) -> dict | None:
    """Decode a JWT payload without verification."""

    if not token or "." not in token:
        return None
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return None



def _normalize_notifications(value: object | None):
    """Return validated notification preferences."""

    if value is None:
        return None
    if isinstance(value, dict):
        try:
            return NotificationPreferences.parse_obj(value)
        except Exception:  # pragma: no cover - defensive
            return NotificationPreferences()
    if isinstance(value, NotificationPreferences):
        return value
    return None


def _normalize_email(email: object | None) -> str:
    """Return a normalized email string for comparisons."""

    return str(email or "").strip().lower()


def _clean_text(value: object | None) -> str | None:
    """Return a stripped string or None when the value is empty."""

    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _auth_user_created_at(user: object | None) -> str | None:
    """Return an auth user's created_at value as an ISO string when available."""

    if not user:
        return None

    value = getattr(user, "created_at", None)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _auth_user_email(user: object | None, metadata: dict | None = None) -> str | None:
    """Return the auth user's email when available."""

    email = _clean_text(getattr(user, "email", None))
    if email is not None:
        return email

    metadata = metadata or {}
    return _metadata_text(metadata, "email")


def _metadata_text(metadata: dict, *keys: str) -> str | None:
    """Return the first populated string value from metadata for the given keys."""

    for key in keys:
        value = _clean_text(metadata.get(key))
        if value is not None:
            return value
    return None


def _metadata_notifications(metadata: dict) -> NotificationPreferences | None:
    """Return notification preferences from legacy or current metadata keys."""

    for key in ("notification_preferences", "notificationPreferences"):
        value = _normalize_notifications(metadata.get(key))
        if value is not None:
            return value
    return None


def _build_new_profile_payload(
    user_id: str,
    metadata: dict,
    *,
    provided_name: str | None = None,
) -> dict[str, object]:
    """Build the initial profile row for a newly authenticated user."""

    allocation = get_plan_initial_credits("Free")
    payload: dict[str, object] = {
        "id": user_id,
        "plan": "Free",
        "credits": allocation,
        "next_credit_reset_at": schedule_next_credit_reset(),
    }

    name = _clean_text(provided_name) or _metadata_text(metadata, "name", "full_name")
    avatar_url = _metadata_text(metadata, "avatar_url", "avatarUrl", "picture")
    notifications = _metadata_notifications(metadata)

    if name is not None:
        payload["name"] = name
    if avatar_url is not None:
        payload["avatar_url"] = avatar_url
    if notifications is not None:
        payload["notification_preferences"] = notifications.dict()

    return payload


def _ensure_profile_exists(
    user_id: str,
    metadata: dict,
    *,
    client=None,
    provided_name: str | None = None,
) -> tuple[dict, bool]:
    """Ensure the app-owned profile row exists for the authenticated user."""

    sb = client or get_client()
    profile = _user_profile(user_id, client=sb)
    if profile:
        return profile, False

    payload = _build_new_profile_payload(
        user_id, metadata, provided_name=provided_name
    )

    try:
        sb.table("profiles").insert(payload).execute()
    except Exception:
        # A DB trigger or concurrent request may have created the row already.
        pass

    profile = _user_profile(user_id, client=sb)
    if not profile:
        raise RuntimeError(f"Failed to ensure profile for user {user_id}")
    return profile, True


def _ensure_monthly_credits(
    user_id: str,
    plan: str | None,
    profile: dict,
) -> dict:
    """Ensure the stored credits align with the current monthly allocation."""

    profile = dict(profile)
    now = datetime.now(timezone.utc)
    next_reset = _parse_iso_datetime(profile.get("next_credit_reset_at"))
    allocation = get_plan_initial_credits(plan)
    sb = get_client()

    if next_reset is None:
        # Older profiles may not have a reset timestamp yet. Initialize the schedule
        # without granting credits immediately so a missing timestamp does not act as a top-up.
        new_next_reset = schedule_next_credit_reset(now=now)
        sb.table("profiles").update({
            "next_credit_reset_at": new_next_reset
        }).eq("id", user_id).execute()
        profile["next_credit_reset_at"] = new_next_reset
        return profile

    if next_reset <= now:
        new_next_reset = schedule_next_credit_reset(now=now)
        sb.table("profiles").update({
            "credits": allocation,
            "next_credit_reset_at": new_next_reset
        }).eq("id", user_id).execute()
        profile["credits"] = allocation
        profile["next_credit_reset_at"] = new_next_reset

    return profile


def _user_profile(user_id: str, *, client=None) -> dict:
    """Fetch user profile from Supabase. Returns {} if not found."""
    sb = client or get_client()
    try:
        resp = (
            sb.table("profiles")
            .select(
                "id,name,plan,credits,avatar_url,notification_preferences,is_admin,deactivated_at,retention_offer_used,retention_offer_used_at,rc_last_event_ms,subscription_expires_at,onboarding_completed,next_credit_reset_at,on_model_style_trials,pure_jewelry_style_trials"
            )
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except APIError as e:
        # Treat "no content"/similar as "not found"
        # Some client versions surface a 204 here.
        if getattr(e, "code", None) in ("204", 204):
            return {}
        logger.exception(
            "profiles lookup failed user_id=%s code=%s details=%s",
            user_id,
            getattr(e, "code", None),
            getattr(e, "details", None),
        )
        raise

    data = resp.data or []
    if isinstance(data, list) and data:
        return data[0]
    return {}


def _user_metadata(user: object | None) -> dict:
    """Return arbitrary metadata stored on a Supabase auth user object."""

    if not user:
        return {}
    return getattr(user, "user_metadata", None) or {}

def _normalize_credits(value: object | None) -> int:
    """Convert credit balances into integers, defaulting to zero."""

    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 0


def _build_user_state(
    user_id: str,
    profile: dict | None,
    metadata: dict | None = None,
    *,
    created_at: str | None = None,
    auth_user: object | None = None,
) -> UserState:
    """Normalize Supabase profile data into the shape expected by the app."""

    profile = profile or {}
    metadata = metadata or {}

    name = _clean_text(profile.get("name"))
    plan = profile.get("plan")
    credits = profile.get("credits")
    avatar = _extract_avatar(profile)
    notifications = _normalize_notifications(profile.get("notification_preferences"))
    is_admin = bool(profile.get("is_admin"))
    style_trials = {
        "onModel": _normalize_style_trial_state(profile.get("on_model_style_trials")),
        "pureJewelry": _normalize_style_trial_state(profile.get("pure_jewelry_style_trials")),
    }

    return UserState(
        id=user_id,
        email=_auth_user_email(auth_user, metadata),
        name=name,
        plan=normalize_plan(plan),
        credits=_normalize_credits(credits),
        createdAt=created_at,
        avatarUrl=avatar,
        notificationPreferences=notifications,
        isAdmin=is_admin,
        reactivatedAt=metadata.get("reactivatedAt"),
        retentionOfferUsed=bool(profile.get("retention_offer_used")),
        retentionOfferUsedAt=profile.get("retention_offer_used_at"),
        onboardingCompleted=bool(profile.get("onboarding_completed")),
        styleTrials=style_trials,
    )


@router.post("/send")
@limiter.limit(LIMIT_auth_send)
def send_magic_link(request: Request, data: MagicLinkRequest) -> dict:
    """Send a passwordless sign-in link/code to the user."""

    if _normalize_email(data.email) == TEST_LOGIN_EMAIL:
        return {"ok": True}

    sb = create_user_client()
    try:
        sb.auth.sign_in_with_otp({"email": data.email})
    except Exception as exc:  # pragma: no cover - network failure
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"ok": True}


@router.post("/verify", response_model=AuthResponse)
@limiter.limit(LIMIT_auth_verify)
def verify_magic_link(request: Request, data: VerifyRequest) -> AuthResponse:
    """Verify an emailed one-time code and return tokens/profile."""

    otp_client = create_user_client()

    if _normalize_email(data.email) == TEST_LOGIN_EMAIL and data.token == TEST_LOGIN_CODE:
        res = otp_client.auth.sign_in_with_password(
            credentials={"email": TEST_LOGIN_EMAIL, "password": TEST_LOGIN_PASSWORD}
        )

        # Add 20 credits to the test user
        admin_client = get_service_role_client(fresh=True)
        admin_client.table("profiles").update({"credits": 20}).eq("id", TEST_LOGIN_USER_ID).execute()
    else:
        res = otp_client.auth.verify_otp(
            {"email": data.email, "token": data.token, "type": "email"}
        )

    if res.user is None or res.session is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code"
        )
        
    admin_client = get_service_role_client(fresh=True)
    metadata = dict(_user_metadata(res.user))
    try:
        profile, is_new = _ensure_profile_exists(
            res.user.id,
            metadata,
            client=admin_client,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile creation failed",
        ) from exc

    metadata, profile, _ = clear_user_deactivation(
        res.user.id, metadata=metadata, profile=profile, client=admin_client
    )
    profile = profile or {}

    profile = _ensure_monthly_credits(res.user.id, profile.get("plan"), profile)
    return AuthResponse(
        token=Token(access=res.session.access_token, refresh=res.session.refresh_token),
        user=_build_user_state(
            res.user.id,
            profile,
            metadata,
            created_at=_auth_user_created_at(res.user),
            auth_user=res.user,
        ),
        is_new=is_new,
    )


@router.post("/refresh", response_model=Token)
def refresh_token(data: RefreshRequest) -> Token:
    """Exchange a refresh token for new access and refresh tokens."""
    sb = create_user_client()
    try:
        res = sb.auth.refresh_session(data.refresh)
    except Exception as exc:  # pragma: no cover - network failure
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    if res.session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    return Token(access=res.session.access_token, refresh=res.session.refresh_token)


@oauth_router.get("/{provider}")
def oauth_redirect(
    request: Request,
    provider: str,
    redirect_uri: str = Query(..., alias="redirectUri"),
    client_id: str = Query(..., alias="clientId"),
) -> RedirectResponse:
    callback = str(request.url_for("oauth_callback", provider=provider))

    raw_nonce = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    hashed = hashlib.sha256(raw_nonce.encode()).hexdigest()

    state = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")
    nonce_store[state] = raw_nonce

    payload = quote(json.dumps({"url": redirect_uri, "state": state}), safe="")

    if provider == "google":
        url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={client_id}"
            f"&redirect_uri={quote(callback, safe='')}"
            "&response_type=id_token"
            "&response_mode=form_post"
            "&scope=openid%20email%20profile"
            f"&state={payload}"
            f"&nonce={hashed}"
            "&prompt=consent"
        )
    elif provider == "apple":
        url = (
            "https://appleid.apple.com/auth/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={quote(callback, safe='')}"
            "&response_type=code%20id_token"
            "&response_mode=form_post"
            "&scope=name%20email"
            f"&state={payload}"
            f"&nonce={hashed}"
        )
    else:
        raise HTTPException(status_code=404, detail="Unsupported provider")
    return RedirectResponse(url)


@oauth_router.api_route(
    "/{provider}/callback", methods=["GET", "POST"], name="oauth_callback"
)
async def oauth_callback(request: Request, provider: str) -> RedirectResponse:
    payload: str | None = None
    id_token: str | None = None

    if request.method == "POST":
        form = await request.form()
        payload = form.get("state")
        id_token = form.get("id_token")
    else:
        payload = request.query_params.get("state")
        id_token = request.query_params.get("id_token")

    if not payload or not id_token:
        raise HTTPException(status_code=400, detail="Missing token")

    decoded = unquote(payload)
    data = json.loads(decoded)
    url = data.get("url")
    state = data.get("state")

    if not url or not state:
        raise HTTPException(status_code=400, detail="Missing redirect target")

    return RedirectResponse(f"{url}?id_token={id_token}&state={state}")

async def exchange_google_code(auth_code: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": auth_code,
                "client_id": GOOGLE_WEB_CLIENT_ID,
                "client_secret": GOOGLE_WEB_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": "",  # allowed when no web redirect uri is used :contentReference[oaicite:2]{index=2}
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if r.status_code != 200:
        raise HTTPException(400, f"Google token exchange failed: {r.text}")

    return r.json()

@router.post("/oauth", response_model=AuthResponse)
@limiter.limit(LIMIT_oauth_login)
async def oauth_login(request: Request, data: OAuthRequest) -> AuthResponse:
    sb = create_user_client()

    if not data.token:
        raise HTTPException(400, "Missing token")

    raw_id_token: str | None = None

    if data.provider == "apple":
        payload = {"provider": data.provider, "token": data.token}
        
        if not data.nonce:
            raise HTTPException(400, "Missing nonce for Apple")
        payload["nonce"] = data.nonce
        raw_id_token = data.token
        res = sb.auth.sign_in_with_id_token(payload)
        
    elif data.provider == "google":
        tokens = await exchange_google_code(data.token)
        id_token = tokens.get("id_token")
        access_token = tokens.get("access_token")
        if not id_token or not access_token:
            raise HTTPException(400, "Google exchange did not return id_token/access_token")

        raw_id_token = id_token
        res = sb.auth.sign_in_with_id_token(
            {"provider": "google", "token": id_token, "access_token": access_token}
        )
    else:
        raise HTTPException(400, "Unsupported provider")

    email = None
    payload = _decode_jwt_payload(raw_id_token)
    if isinstance(payload, dict):
        email = payload.get("email") or payload.get("sub")
    if not email and res.user is not None:
        email = getattr(res.user, "email", None) or _user_metadata(res.user).get("email")



    if res.user is None or res.session is None:
        raise HTTPException(status_code=400, detail="Invalid token")
        
    metadata = dict(_user_metadata(res.user))
    admin_client = get_service_role_client(fresh=True)
    try:
        profile, is_new = _ensure_profile_exists(
            res.user.id,
            metadata,
            client=admin_client,
            provided_name=data.name,
        )
    except APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile lookup failed",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile creation failed",
        ) from exc

    metadata, profile, _ = clear_user_deactivation(
        res.user.id, metadata=metadata, profile=profile, client=admin_client
    )
    profile = profile or {}

    profile = _ensure_monthly_credits(res.user.id, profile.get("plan"), profile)
    
    loggedUser = _build_user_state(
        res.user.id,
        profile,
        metadata,
        created_at=_auth_user_created_at(res.user),
        auth_user=res.user,
    )
    
    return AuthResponse(
        token=Token(access=res.session.access_token, refresh=res.session.refresh_token),
        user=loggedUser,
        is_new=is_new,
    )

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UserState:
    """Verify bearer token and return the associated user."""
    sb = create_user_client()
    try:
        res = sb.auth.get_user(credentials.credentials)
    except Exception as exc:  # pragma: no cover - network failure
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    metadata = dict(_user_metadata(res.user))
    admin_client = get_service_role_client(fresh=True)
    try:
        profile, _ = _ensure_profile_exists(
            res.user.id,
            metadata,
            client=admin_client,
        )
    except APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile lookup failed",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile creation failed",
        ) from exc
    metadata, profile, _ = clear_user_deactivation(
        res.user.id, metadata=metadata, profile=profile, client=admin_client
    )
    profile = profile or {}
    profile = _ensure_monthly_credits(res.user.id, profile.get("plan"), profile)
    return _build_user_state(
        res.user.id,
        profile,
        metadata,
        created_at=_auth_user_created_at(res.user),
        auth_user=res.user,
    )


@router.get("/me", response_model=UserState)
def me(current: UserState = Depends(get_current_user)) -> UserState:
    """Return the authenticated user's profile."""
    return current


@router.patch("/me", response_model=UserState)
def update_me(
    data: ProfileUpdate, current: UserState = Depends(get_current_user)
) -> UserState:
    """Update the current user's profile and return the new state."""
    sb = get_client()
    updates: dict[str, object] = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.avatarUrl is not None:
        updates["avatar_url"] = data.avatarUrl
    if data.notifications is not None:
        updates["notification_preferences"] = data.notifications.dict()
    if updates:
        sb.table("profiles").update(updates).eq("id", current.id).execute()

    profile = _user_profile(current.id)
    profile = _ensure_monthly_credits(current.id, profile.get("plan"), profile)
    return _build_user_state(
        current.id,
        profile,
        {"reactivatedAt": current.reactivatedAt, "email": current.email},
        created_at=current.createdAt,
        auth_user=None,
    )


@router.patch("/style-trials", response_model=UserState)
def update_style_trials(
    data: StyleTrialsUpdate, current: UserState = Depends(get_current_user)
) -> UserState:
    """Persist style trial state for the authenticated user."""

    updates: dict[str, object] = {}
    if data.onModel is not None:
        updates["on_model_style_trials"] = _normalize_style_trial_state(data.onModel)
    if data.pureJewelry is not None:
        updates["pure_jewelry_style_trials"] = _normalize_style_trial_state(
            data.pureJewelry
        )

    if updates:
        get_client().table("profiles").update(updates).eq("id", current.id).execute()

    profile = _user_profile(current.id)
    profile = _ensure_monthly_credits(current.id, profile.get("plan"), profile)
    return _build_user_state(
        current.id,
        profile,
        {"reactivatedAt": current.reactivatedAt, "email": current.email},
        created_at=current.createdAt,
        auth_user=None,
    )


@router.post("/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_account(current: UserState = Depends(get_current_user)) -> Response:
    """Deactivate the current user without deleting their data."""

    sb = get_client()
    metadata = dict(get_admin_user_metadata(current.id, client=sb))
    now_iso = datetime.now(timezone.utc).isoformat()
    metadata["deactivated"] = True
    metadata["deactivatedAt"] = now_iso

    try:
        update_user_metadata(current.id, metadata, client=sb)
    except Exception as exc:  # pragma: no cover - admin API optional
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    try:
        sb.table("profiles").update({"deactivated_at": now_iso}).eq(
            "id", current.id
        ).execute()
    except APIError:  # pragma: no cover - column may be absent
        pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(current: UserState = Depends(get_current_user)) -> Response:
    """Permanently delete the current user account."""

    sb = get_client()

    try:
        schedule_user_deletion(current.id, client=sb)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)


ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _infer_content_type_and_ext(
    name: Optional[str], explicit_type: Optional[str]
) -> Tuple[str, str]:
    """
    Decide content-type and extension from provided 'type' or filename.
    Defaults to image/jpeg if uncertain.
    """
    ct = (
        explicit_type or (mimetypes.guess_type(name or "")[0]) or "image/jpeg"
    ).lower()
    if ct not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported avatar content-type: {ct}",
        )
    ext_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    return ct, ext_map[ct]


def _decode_base64_image(b64: str) -> bytes:
    """
    Accepts raw base64 or data-URL form like 'data:image/png;base64,AAAA...'
    """
    s = b64.strip()
    if s.startswith("data:"):
        # strip data URL prefix
        try:
            s = s.split(",", 1)[1]
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid data URL format for avatar",
            )
    try:
        return base64.b64decode(s, validate=True)
    except binascii.Error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 payload for avatar",
        )


class AvatarJson(BaseModel):
    name: Optional[str] = Field(
        None, description="Original filename, used to hint extension"
    )
    type: Optional[str] = Field(None, description="MIME type, e.g. image/jpeg")
    base64: str = Field(
        ..., description="Base64-encoded image bytes (optionally data: URL)"
    )


@router.post("/avatar", response_model=UserState)
async def upload_avatar(
    payload: AvatarJson,
    current: UserState = Depends(get_current_user),
) -> UserState:
    """Upload a new avatar for the current user and persist the URL (JSON + base64)."""

    data = _decode_base64_image(payload.base64)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Avatar file is empty",
        )

    content_type, extension = _infer_content_type_and_ext(payload.name, payload.type)

    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Avatar exceeds the maximum allowed size",
        )

    prefix = user_storage_prefix(current.id)
    object_path = f"avatars/{prefix}/{uuid4().hex}{extension}"

    bucket = _get_avatar_bucket()
    blob = bucket.blob(object_path)
    blob.content_type = content_type
    if AVATAR_CACHE_CONTROL:
        blob.cache_control = AVATAR_CACHE_CONTROL

    metadata = {"appUserId": current.id}
    owner_key = AVATAR_OWNER_METADATA_KEY
    if owner_key and owner_key != "appUserId":
        metadata[owner_key] = current.id
    blob.metadata = metadata

    try:
        blob.upload_from_string(data, content_type=content_type)
    except Exception as exc:  # pragma: no cover - upstream failure
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to upload avatar",
        ) from exc

    # 4) Persist the public URL in the app profile record
    public_url = build_public_url(
        object_path,
        AVATAR_BUCKET,
        public_host=AVATAR_PUBLIC_HOST,
    )

    sb = get_client()
    sb.table("profiles").update({"avatar_url": public_url}).eq(
        "id", current.id
    ).execute()

    profile = _user_profile(current.id)
    profile = _ensure_monthly_credits(current.id, profile.get("plan"), profile)

    return _build_user_state(
        current.id,
        profile,
        {"reactivatedAt": current.reactivatedAt},
    )

def jwt_payload_unverified(token: str) -> dict:
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64).decode())
    except Exception:
        return {}


@router.post("/retention-offer-used", status_code=status.HTTP_204_NO_CONTENT)
def mark_retention_offer_used(
    current: UserState = Depends(get_current_user),
) -> Response:
    """Mark the one-time retention offer as used (idempotent)."""

    sb = get_client()
    sb.table("profiles").update({
        "retention_offer_used": True,
        "retention_offer_used_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", current.id).execute()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/complete-onboarding", response_model=UserState)
def complete_onboarding(
    current: UserState = Depends(get_current_user),
) -> UserState:
    """Mark onboarding as completed for the current user."""

    sb = get_client()
    sb.table("profiles").update({"onboarding_completed": True}).eq(
        "id", current.id
    ).execute()
    
    # Update current state to reflect change
    current.onboardingCompleted = True
    return current

def _default_style_trial_state() -> dict[str, object]:
    return {
        "pendingSelectionKeys": [],
        "remainingUses": DEFAULT_STYLE_TRIAL_REMAINING_USES,
    }


def _normalize_style_trial_state(value: object | None) -> dict[str, object]:
    if isinstance(value, StyleTrialState):
        payload = value.dict()
    elif isinstance(value, dict):
        payload = value
    else:
        return _default_style_trial_state()

    pending_keys_raw = payload.get("pendingSelectionKeys")
    if isinstance(pending_keys_raw, list):
        pending_keys = [str(item) for item in pending_keys_raw if isinstance(item, str)]
    else:
        pending_keys = []

    remaining_raw = payload.get("remainingUses")
    try:
        remaining_uses = int(remaining_raw)
    except (TypeError, ValueError):
        remaining_uses = DEFAULT_STYLE_TRIAL_REMAINING_USES

    return {
        "pendingSelectionKeys": pending_keys,
        "remainingUses": max(0, min(DEFAULT_STYLE_TRIAL_REMAINING_USES, remaining_uses)),
    }
