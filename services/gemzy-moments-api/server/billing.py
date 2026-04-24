"""Billing, Wallets, Entitlements — app-scoped credit system.

Operates against `public.user_wallets`, `public.credit_ledger`,
`public.user_entitlements`, `public.app_plans`.

Key design: credits and subscriptions are scoped per app_id (core/moments/people).
A user can be Pro in Moments but Free in Core simultaneously.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from .auth import require_user
from .moments_schemas import (
    AppPlanResponse,
    CreditLedgerResponse,
    EntitlementResponse,
    WalletResponse,
)
from .supabase_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _db():
    return get_client()


# ═══════════════════════════════════════════════════════════
#  WALLETS
# ═══════════════════════════════════════════════════════════

@router.get("/wallets", response_model=list[WalletResponse])
async def get_wallets(user=Depends(require_user)):
    """Get all wallet balances for this user (one per app)."""
    result = (
        _db()
        .table("user_wallets")
        .select("*")
        .eq("user_id", user.id)
        .execute()
    )
    return result.data


@router.get("/wallets/{app_id}", response_model=WalletResponse)
async def get_wallet(app_id: str, user=Depends(require_user)):
    """Get wallet balance for a specific app."""
    result = (
        _db()
        .table("user_wallets")
        .select("*")
        .eq("user_id", user.id)
        .eq("app_id", app_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        # Auto-create with 0 balance
        row = {
            "user_id": user.id,
            "app_id": app_id,
            "credit_balance": 0,
        }
        result = _db().table("user_wallets").insert(row).execute()
        return result.data[0]
    return result.data


@router.get("/wallets/{app_id}/balance")
async def get_balance(app_id: str, user=Depends(require_user)):
    """Quick balance check — returns {balance: int}."""
    wallet = await get_wallet(app_id, user)
    return {"balance": wallet.get("credit_balance", 0) if isinstance(wallet, dict) else wallet.credit_balance}


# ═══════════════════════════════════════════════════════════
#  CREDIT LEDGER
# ═══════════════════════════════════════════════════════════

@router.get("/ledger/{app_id}", response_model=list[CreditLedgerResponse])
async def get_ledger(
    app_id: str,
    limit: int = 50,
    user=Depends(require_user),
):
    """Get credit transaction history for an app."""
    result = (
        _db()
        .table("credit_ledger")
        .select("*")
        .eq("user_id", user.id)
        .eq("app_id", app_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


# ═══════════════════════════════════════════════════════════
#  ENTITLEMENTS
# ═══════════════════════════════════════════════════════════

@router.get("/entitlements", response_model=list[EntitlementResponse])
async def get_entitlements(user=Depends(require_user)):
    """Get all entitlements for this user."""
    result = (
        _db()
        .table("user_entitlements")
        .select("*")
        .eq("user_id", user.id)
        .execute()
    )
    return result.data


@router.get("/entitlements/{app_id}", response_model=EntitlementResponse)
async def get_entitlement(app_id: str, user=Depends(require_user)):
    """Get entitlement for a specific app (defaults to 'free')."""
    result = (
        _db()
        .table("user_entitlements")
        .select("*")
        .eq("user_id", user.id)
        .eq("app_id", app_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        return {
            "user_id": user.id,
            "app_id": app_id,
            "entitlement": "free",
            "status": "active",
            "expires_at": None,
            "source": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return result.data


# ═══════════════════════════════════════════════════════════
#  APP PLANS (public config)
# ═══════════════════════════════════════════════════════════

@router.get("/plans", response_model=list[AppPlanResponse])
async def get_app_plans(app_id: str | None = None):
    """Get plan configs. Public endpoint (no auth required)."""
    q = _db().table("app_plans").select("*")
    if app_id:
        q = q.eq("app_id", app_id)
    result = q.execute()
    return result.data


@router.get("/plans/{app_id}/{entitlement}", response_model=AppPlanResponse)
async def get_app_plan(app_id: str, entitlement: str):
    """Get specific plan limits."""
    result = (
        _db()
        .table("app_plans")
        .select("*")
        .eq("app_id", app_id)
        .eq("entitlement", entitlement)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(404, f"No plan config for {app_id}/{entitlement}")
    return result.data


# ═══════════════════════════════════════════════════════════
#  INTERNAL: Credit Operations (called by other services)
# ═══════════════════════════════════════════════════════════

async def spend_credits(
    user_id: str,
    app_id: str,
    amount: int,
    reason: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> int:
    """Debit credits from a user's wallet.

    Returns the new balance.
    Raises HTTPException(402) if insufficient credits.
    """
    # Check current balance
    wallet = (
        _db()
        .table("user_wallets")
        .select("credit_balance")
        .eq("user_id", user_id)
        .eq("app_id", app_id)
        .maybe_single()
        .execute()
    )

    current = wallet.data["credit_balance"] if wallet.data else 0
    if current < amount:
        raise HTTPException(
            402,
            f"Insufficient {app_id} credits: have {current}, need {amount}",
        )

    new_balance = current - amount

    # Update wallet
    _db().table("user_wallets").upsert({
        "user_id": user_id,
        "app_id": app_id,
        "credit_balance": new_balance,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    # Write ledger entry
    ledger_row = {
        "user_id": user_id,
        "app_id": app_id,
        "delta": -amount,
        "reason": reason,
        "ref_type": ref_type,
        "ref_id": ref_id,
    }
    _db().table("credit_ledger").insert(ledger_row).execute()

    return new_balance


async def grant_credits(
    user_id: str,
    app_id: str,
    amount: int,
    reason: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> int:
    """Credit a user's wallet. Returns the new balance."""
    wallet = (
        _db()
        .table("user_wallets")
        .select("credit_balance")
        .eq("user_id", user_id)
        .eq("app_id", app_id)
        .maybe_single()
        .execute()
    )

    current = wallet.data["credit_balance"] if wallet.data else 0
    new_balance = current + amount

    _db().table("user_wallets").upsert({
        "user_id": user_id,
        "app_id": app_id,
        "credit_balance": new_balance,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    _db().table("credit_ledger").insert({
        "user_id": user_id,
        "app_id": app_id,
        "delta": amount,
        "reason": reason,
        "ref_type": ref_type,
        "ref_id": ref_id,
    }).execute()

    return new_balance


async def check_entitlement_limit(
    user_id: str,
    app_id: str,
    limit_key: str,
) -> int | None:
    """Check a limit from the user's current entitlement tier.

    Returns the limit value, or None if unlimited.
    """
    entitlement = (
        _db()
        .table("user_entitlements")
        .select("entitlement")
        .eq("user_id", user_id)
        .eq("app_id", app_id)
        .eq("status", "active")
        .maybe_single()
        .execute()
    )

    tier = entitlement.data["entitlement"] if entitlement.data else "free"

    plan = (
        _db()
        .table("app_plans")
        .select("*")
        .eq("app_id", app_id)
        .eq("entitlement", tier)
        .maybe_single()
        .execute()
    )

    if not plan.data:
        return 0

    # Check direct column first, then features jsonb
    val = plan.data.get(limit_key)
    if val is not None:
        return val

    features = plan.data.get("features", {})
    return features.get(limit_key)
