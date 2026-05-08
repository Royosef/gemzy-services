from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, Depends, Query

from .auth import get_current_user
from .dashboard_common import dashboard_table, ensure_dashboard_admin
from .dashboard_fx import get_usd_to_ils_rate
from .schemas import (
    DashboardRevenueCohortPointResponse,
    DashboardRevenueCohortRetentionResponse,
    DashboardRevenueCohortRowResponse,
    DashboardRevenueChartPointResponse,
    DashboardRevenueChartResponse,
    DashboardRevenueConversionBucketsResponse,
    DashboardRevenueMonthlyToYearlyResponse,
    DashboardRevenueOverviewResponse,
    DashboardRevenuePackBreakdownItemResponse,
    DashboardRevenuePackBreakdownResponse,
    DashboardRevenuePlanBreakdownItemResponse,
    DashboardRevenuePlanBreakdownResponse,
    DashboardRevenueSubscriberDetailPurchaseResponse,
    DashboardRevenueSubscriberDetailResponse,
    DashboardRevenueSubscriberDetailSubscriptionResponse,
    DashboardRevenueSubscriberListResponse,
    DashboardRevenueSubscriberRowResponse,
    UserState,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard/revenuecat", tags=["dashboard-revenue"])

_V2_BASE = "https://api.revenuecat.com/v2"
_WALK_TTL_MS = 5 * 60 * 1000
_CONTEXT_TTL_MS = 15 * 60 * 1000

_walk_cache: dict[str, Any] | None = None
_context_cache: dict[str, Any] | None = None


class RevenueCatApiError(RuntimeError):
    def __init__(self, message: str, status: int, url: str, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.url = url
        self.code = code


def _read_env(name: str) -> str | None:
    raw = os.getenv(name)
    if not raw:
        return None
    value = raw.strip().strip("'").strip('"')
    return value or None


def get_project_id() -> str | None:
    return _read_env("REVENUECAT_PROJECT_ID") or _read_env("VITE_REVENUECAT_PROJECT_ID")


def is_configured() -> bool:
    return bool(_read_env("REVENUECAT_API_KEY") and get_project_id())


def _project_path(suffix: str) -> str:
    project_id = get_project_id()
    if not project_id:
        logger.error(
            "dashboard revenue misconfigured: missing REVENUECAT_PROJECT_ID",
            extra={"fallbackEnv": "VITE_REVENUECAT_PROJECT_ID", "suffix": suffix},
        )
        raise RevenueCatApiError(
            "RevenueCat project id not configured. Set REVENUECAT_PROJECT_ID.",
            0,
            f"{_V2_BASE}/projects/{{id}}{suffix}",
        )
    return f"/projects/{project_id}{suffix}"


def _rc_fetch(path: str) -> dict[str, Any]:
    api_key = _read_env("REVENUECAT_API_KEY")
    if not api_key:
        logger.error(
            "dashboard revenue misconfigured: missing REVENUECAT_API_KEY",
            extra={"path": path},
        )
        raise RevenueCatApiError(
            "RevenueCat API key not configured. Set REVENUECAT_API_KEY.",
            0,
            f"{_V2_BASE}{path}",
        )

    url = f"{_V2_BASE}{path}"
    response = httpx.get(
        url,
        timeout=15.0,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    if response.status_code >= 400:
        detail = f"{response.status_code} {response.reason_phrase}"
        code = None
        try:
            body = response.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            if isinstance(body.get("message"), str):
                detail = body["message"]
            elif isinstance(body.get("error"), str):
                detail = body["error"]
            if isinstance(body.get("code"), str):
                code = body["code"]
            elif isinstance(body.get("type"), str):
                code = body["type"]
        raise RevenueCatApiError(detail, response.status_code, url, code)
    return response.json()


def _range_for_days(days: int) -> dict[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    resolution = "day" if days <= 14 else "week" if days <= 90 else "month"
    return {
        "startDate": start.date().isoformat(),
        "endDate": end.date().isoformat(),
        "resolution": resolution,
    }


def _bucket_date_for_resolution(unix_ms: float, resolution: str) -> str:
    dt = datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)
    if resolution == "day":
        return dt.date().isoformat()
    if resolution == "month":
        return f"{dt.year}-{str(dt.month).zfill(2)}-01"

    weekday = dt.weekday()
    monday = dt - timedelta(days=weekday)
    return monday.date().isoformat()


def _build_chart_query(range_days: int, filters: dict[str, str] | None = None) -> str:
    chart_range = _range_for_days(range_days)
    params = {
        "start_date": chart_range["startDate"],
        "end_date": chart_range["endDate"],
        "resolution": chart_range["resolution"],
    }
    if filters:
        params.update(filters)
    return "&".join(f"{key}={value}" for key, value in params.items())


def get_overview() -> dict[str, Any]:
    raw = _rc_fetch(_project_path("/metrics/overview"))
    items = raw.get("metrics")
    metrics: list[dict[str, Any]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            value = item.get("value")
            if not isinstance(item_id, str) or not isinstance(value, (int, float)):
                continue
            metrics.append(
                {
                    "id": item_id,
                    "value": float(value),
                    "unit": item.get("unit") if isinstance(item.get("unit"), str) else "",
                    "period": item.get("period") if isinstance(item.get("period"), str) else "",
                    "name": item.get("name") if isinstance(item.get("name"), str) else None,
                    "description": item.get("description")
                    if isinstance(item.get("description"), str)
                    else None,
                }
            )
    return {"metrics": metrics}


def get_chart(chart_name: str, range_days: int, filters: dict[str, str] | None = None) -> DashboardRevenueChartResponse:
    query = _build_chart_query(range_days, filters)
    chart_range = _range_for_days(range_days)
    raw = _rc_fetch(_project_path(f"/charts/{chart_name}?{query}"))
    values: list[DashboardRevenueChartPointResponse] = []
    if isinstance(raw.get("values"), list):
        for item in raw["values"]:
            if not isinstance(item, dict):
                continue
            cohort = item.get("cohort")
            value = item.get("value")
            if not isinstance(cohort, (int, float)) or not isinstance(value, (int, float)):
                continue
            values.append(
                DashboardRevenueChartPointResponse(
                    cohort=int(cohort),
                    date=datetime.fromtimestamp(float(cohort), tz=timezone.utc).date().isoformat(),
                    value=float(value),
                    incomplete=bool(item.get("incomplete")),
                    measure=int(item.get("measure") or 0),
                )
            )
    resolution = raw.get("resolution") if isinstance(raw.get("resolution"), str) else chart_range["resolution"]
    yaxis_currency = raw.get("yaxis_currency") if isinstance(raw.get("yaxis_currency"), str) else None
    return DashboardRevenueChartResponse(
        chartName=chart_name,
        resolution=resolution,
        values=values,
        yaxisCurrency=yaxis_currency,
    )


def list_products() -> list[dict[str, Any]]:
    raw = _rc_fetch(_project_path("/products?limit=200"))
    items = raw.get("items")
    products: list[dict[str, Any]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            product_id = item.get("id")
            store_identifier = item.get("store_identifier")
            if not isinstance(product_id, str) or not isinstance(store_identifier, str):
                continue
            subscription = item.get("subscription")
            duration = None
            if isinstance(subscription, dict) and isinstance(subscription.get("duration"), str):
                duration = subscription["duration"]
            products.append(
                {
                    "id": product_id,
                    "storeIdentifier": store_identifier,
                    "type": item.get("type") if isinstance(item.get("type"), str) else "unknown",
                    "displayName": item.get("display_name")
                    if isinstance(item.get("display_name"), str)
                    else None,
                    "duration": duration,
                }
            )
    return products


def list_customers_page(limit: int = 1000, starting_after: str | None = None) -> dict[str, Any]:
    query = f"limit={limit}"
    if starting_after:
        query += f"&starting_after={starting_after}"
    raw = _rc_fetch(_project_path(f"/customers?{query}"))
    customers: list[dict[str, Any]] = []
    items = raw.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            customer_id = item.get("id")
            if not isinstance(customer_id, str):
                continue
            customers.append(
                {
                    "id": customer_id,
                    "firstSeenAt": item.get("first_seen_at") if isinstance(item.get("first_seen_at"), (int, float)) else None,
                    "lastSeenAt": item.get("last_seen_at") if isinstance(item.get("last_seen_at"), (int, float)) else None,
                    "lastSeenCountry": item.get("last_seen_country")
                    if isinstance(item.get("last_seen_country"), str)
                    else None,
                    "lastSeenPlatform": item.get("last_seen_platform")
                    if isinstance(item.get("last_seen_platform"), str)
                    else None,
                }
            )

    next_cursor = None
    next_page = raw.get("next_page")
    if isinstance(next_page, str):
        try:
            parsed = urlparse(next_page)
            next_cursor = parse_qs(parsed.query).get("starting_after", [None])[0]
        except Exception:
            next_cursor = None
    return {"items": customers, "nextCursor": next_cursor}


def list_customer_subscriptions(customer_id: str) -> list[dict[str, Any]]:
    raw = _rc_fetch(
        _project_path(f"/customers/{customer_id}/subscriptions?limit=50")
    )
    out: list[dict[str, Any]] = []
    items = raw.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            product_id = item.get("product_id")
            if not isinstance(product_id, str):
                continue
            entitlement_keys: list[str] = []
            entitlements = item.get("entitlements")
            ent_items = entitlements.get("items") if isinstance(entitlements, dict) else None
            if isinstance(ent_items, list):
                for entitlement in ent_items:
                    if isinstance(entitlement, dict) and isinstance(entitlement.get("lookup_key"), str):
                        entitlement_keys.append(entitlement["lookup_key"])
            out.append(
                {
                    "productId": product_id,
                    "status": item.get("status") if isinstance(item.get("status"), str) else None,
                    "givesAccess": item.get("gives_access") is True,
                    "endsAt": item.get("ends_at") if isinstance(item.get("ends_at"), (int, float)) else None,
                    "startsAt": item.get("starts_at") if isinstance(item.get("starts_at"), (int, float)) else None,
                    "autoRenewStatus": item.get("auto_renewal_status")
                    if isinstance(item.get("auto_renewal_status"), str)
                    else None,
                    "entitlementLookupKeys": entitlement_keys,
                }
            )
    return out


def list_customer_purchases(customer_id: str) -> list[dict[str, Any]]:
    raw = _rc_fetch(_project_path(f"/customers/{customer_id}/purchases?limit=50"))
    out: list[dict[str, Any]] = []
    items = raw.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            product_id = item.get("product_id")
            if not isinstance(product_id, str):
                continue
            revenue_in_usd = item.get("revenue_in_usd")
            gross = revenue_in_usd.get("gross") if isinstance(revenue_in_usd, dict) else 0
            out.append(
                {
                    "productId": product_id,
                    "status": item.get("status") if isinstance(item.get("status"), str) else None,
                    "purchasedAt": item.get("purchased_at") if isinstance(item.get("purchased_at"), (int, float)) else None,
                    "quantity": int(item.get("quantity") or 1),
                    "revenueUsd": float(gross) if isinstance(gross, (int, float)) else 0.0,
                    "environment": item.get("environment")
                    if isinstance(item.get("environment"), str)
                    else None,
                }
            )
    return out


def walk_all_customers() -> dict[str, Any]:
    cursor = None
    customers: list[dict[str, Any]] = []
    for _ in range(50):
        page = list_customers_page(limit=1000, starting_after=cursor)
        customers.extend(page["items"])
        cursor = page["nextCursor"]
        if not cursor:
            break

    subscriptions: list[dict[str, Any]] = []
    purchases: list[dict[str, Any]] = []
    for customer in customers:
        customer_id = customer["id"]
        for sub in list_customer_subscriptions(customer_id):
            subscriptions.append({**sub, "customerId": customer_id})
        for purchase in list_customer_purchases(customer_id):
            purchases.append({**purchase, "customerId": customer_id})

    return {
        "customers": customers,
        "subscriptions": subscriptions,
        "purchases": purchases,
        "customerCount": len(customers),
    }


def clear_revenue_caches() -> None:
    global _walk_cache, _context_cache
    _walk_cache = None
    _context_cache = None


def load_walk() -> dict[str, Any]:
    global _walk_cache
    if _walk_cache and time.time() * 1000 < _walk_cache["expiresAt"]:
        return _walk_cache

    walk = walk_all_customers()
    products = list_products()
    _walk_cache = {
        "expiresAt": time.time() * 1000 + _WALK_TTL_MS,
        "walk": walk,
        "products": products,
    }
    return _walk_cache


def _classify_product(store_id: str) -> dict[str, str] | None:
    lower = store_id.lower()
    if lower.startswith("credits"):
        return None
    plan = "Other"
    if "designer" in lower:
        plan = "Designer"
    elif "pro" in lower:
        plan = "Pro"
    elif "starter" in lower:
        plan = "Starter"

    cadence = "Unknown"
    if "yearly" in lower:
        cadence = "Yearly"
    elif "monthly" in lower:
        cadence = "Monthly"
    return {"plan": plan, "cadence": cadence}


def _classify_credit_pack(store_id: str) -> str | None:
    lower = store_id.lower()
    if not lower.startswith("credits"):
        return None
    tail = lower.removeprefix("credits").lstrip("._-")
    if tail == "xl":
        return "XL"
    if tail == "l":
        return "L"
    if tail == "m":
        return "M"
    if tail == "s":
        return "S"
    return None


def _is_active_now(sub: dict[str, Any]) -> bool:
    if not sub.get("givesAccess"):
        return False
    if sub.get("status") != "active":
        return False
    ends_at = sub.get("endsAt")
    if isinstance(ends_at, (int, float)) and ends_at < time.time() * 1000:
        return False
    return True


def _is_production_purchase(purchase: dict[str, Any]) -> bool:
    return purchase.get("environment") != "sandbox"


def _ref_from_id(customer_id: str) -> str:
    return customer_id[-4:].upper() if len(customer_id) > 4 else customer_id


def _pick_status(subs: list[dict[str, Any]]) -> str:
    if not subs:
        return "never"
    now_ms = time.time() * 1000
    any_active = any(
        sub.get("givesAccess")
        and sub.get("status") == "active"
        and (
            sub.get("endsAt") is None
            or (isinstance(sub.get("endsAt"), (int, float)) and float(sub["endsAt"]) >= now_ms)
        )
        for sub in subs
    )
    if any_active:
        return "active"
    any_grace = any(sub.get("status") in {"in_grace_period", "grace_period"} for sub in subs)
    if any_grace:
        return "grace_period"
    return "cancelled"


def _classify_for_row(sub: dict[str, Any], product_by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    product = product_by_id.get(str(sub.get("productId") or ""))
    classified = _classify_product(product["storeIdentifier"]) if product else None
    if classified:
        return classified
    lookup = str((sub.get("entitlementLookupKeys") or [""])[0]).lower()
    plan = "Designer" if "designer" in lookup else "Pro" if "pro" in lookup else "Starter" if "starter" in lookup else "Other"
    cadence = (
        "Yearly"
        if product and product.get("duration") == "P1Y"
        else "Monthly"
        if product and product.get("duration") == "P1M"
        else "Unknown"
    )
    return {"plan": plan, "cadence": cadence}


def build_subscriber_rows(walk: dict[str, Any], products: list[dict[str, Any]]) -> list[DashboardRevenueSubscriberRowResponse]:
    product_by_id = {product["id"]: product for product in products}
    subs_by_customer: dict[str, list[dict[str, Any]]] = {}
    for sub in walk["subscriptions"]:
        subs_by_customer.setdefault(str(sub["customerId"]), []).append(sub)
    purchases_by_customer: dict[str, list[dict[str, Any]]] = {}
    for purchase in walk["purchases"]:
        if not _is_production_purchase(purchase):
            continue
        purchases_by_customer.setdefault(str(purchase["customerId"]), []).append(purchase)

    rows: list[DashboardRevenueSubscriberRowResponse] = []
    for customer in walk["customers"]:
        customer_id = str(customer["id"])
        subs = subs_by_customer.get(customer_id, [])
        purchases = purchases_by_customer.get(customer_id, [])
        if not subs and not purchases:
            continue
        status = _pick_status(subs)
        sorted_subs = sorted(subs, key=lambda sub: float(sub.get("startsAt") or 0), reverse=True)
        headline = next(
            (
                sub
                for sub in sorted_subs
                if sub.get("givesAccess")
                and sub.get("status") == "active"
                and (
                    sub.get("endsAt") is None
                    or float(sub.get("endsAt") or 0) >= time.time() * 1000
                )
            ),
            sorted_subs[0] if sorted_subs else None,
        )
        classified = _classify_for_row(headline, product_by_id) if headline else None
        started_at = None
        if subs:
            starts = [float(sub["startsAt"]) for sub in subs if isinstance(sub.get("startsAt"), (int, float))]
            if starts:
                started_at = int(min(starts))
        credits_revenue = round(sum(float(purchase.get("revenueUsd") or 0) for purchase in purchases), 2)
        rows.append(
            DashboardRevenueSubscriberRowResponse(
                customerId=customer_id,
                ref=_ref_from_id(customer_id),
                plan=classified["plan"] if classified else None,
                cadence=classified["cadence"] if classified else None,
                startedAt=started_at,
                status=status,
                creditsRevenueUsdLifetime=credits_revenue,
                subscriptionsCount=len(subs),
                firstSeenAt=int(customer["firstSeenAt"]) if isinstance(customer.get("firstSeenAt"), (int, float)) else None,
                lastSeenAt=int(customer["lastSeenAt"]) if isinstance(customer.get("lastSeenAt"), (int, float)) else None,
                country=customer.get("lastSeenCountry") if isinstance(customer.get("lastSeenCountry"), str) else None,
                platform=customer.get("lastSeenPlatform") if isinstance(customer.get("lastSeenPlatform"), str) else None,
            )
        )
    return rows


def build_subscriber_detail(
    customer_id: str, walk: dict[str, Any], products: list[dict[str, Any]]
) -> DashboardRevenueSubscriberDetailResponse | None:
    customer = next((item for item in walk["customers"] if item["id"] == customer_id), None)
    if not customer:
        return None
    product_by_id = {product["id"]: product for product in products}
    subs = [sub for sub in walk["subscriptions"] if sub["customerId"] == customer_id]
    purchases = [
        purchase
        for purchase in walk["purchases"]
        if purchase["customerId"] == customer_id and _is_production_purchase(purchase)
    ]
    subscription_months_active = 0.0
    for sub in subs:
        starts_at = sub.get("startsAt")
        if not isinstance(starts_at, (int, float)):
            continue
        ends_at = sub.get("endsAt") if isinstance(sub.get("endsAt"), (int, float)) else time.time() * 1000
        if ends_at < starts_at:
            continue
        subscription_months_active += (float(ends_at) - float(starts_at)) / (30 * 24 * 60 * 60 * 1000)
    return DashboardRevenueSubscriberDetailResponse(
        customerId=customer_id,
        ref=_ref_from_id(customer_id),
        firstSeenAt=int(customer["firstSeenAt"]) if isinstance(customer.get("firstSeenAt"), (int, float)) else None,
        lastSeenAt=int(customer["lastSeenAt"]) if isinstance(customer.get("lastSeenAt"), (int, float)) else None,
        country=customer.get("lastSeenCountry") if isinstance(customer.get("lastSeenCountry"), str) else None,
        platform=customer.get("lastSeenPlatform") if isinstance(customer.get("lastSeenPlatform"), str) else None,
        creditsRevenueUsdLifetime=round(sum(float(p.get("revenueUsd") or 0) for p in purchases), 2),
        subscriptionMonthsActive=round(subscription_months_active, 1),
        averageMrrContributionUsd=None,
        subscriptions=[
            DashboardRevenueSubscriberDetailSubscriptionResponse(
                productId=str(sub["productId"]),
                plan=_classify_for_row(sub, product_by_id)["plan"],
                cadence=_classify_for_row(sub, product_by_id)["cadence"],
                status=sub.get("status") if isinstance(sub.get("status"), str) else None,
                startsAt=int(sub["startsAt"]) if isinstance(sub.get("startsAt"), (int, float)) else None,
                endsAt=int(sub["endsAt"]) if isinstance(sub.get("endsAt"), (int, float)) else None,
                givesAccess=bool(sub.get("givesAccess")),
            )
            for sub in sorted(subs, key=lambda item: float(item.get("startsAt") or 0), reverse=True)
        ],
        purchases=[
            DashboardRevenueSubscriberDetailPurchaseResponse(
                productId=str(purchase["productId"]),
                purchasedAt=int(purchase["purchasedAt"]) if isinstance(purchase.get("purchasedAt"), (int, float)) else None,
                revenueUsd=float(purchase.get("revenueUsd") or 0),
                quantity=int(purchase.get("quantity") or 0),
                pack=_classify_credit_pack(product_by_id.get(str(purchase["productId"]), {}).get("storeIdentifier", "")),
            )
            for purchase in sorted(purchases, key=lambda item: float(item.get("purchasedAt") or 0), reverse=True)
        ],
    )


def _month_key(unix_ms: float) -> str:
    dt = datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}-01"


def _month_label(month_key: str) -> str:
    dt = datetime.fromisoformat(f"{month_key}T00:00:00+00:00")
    return f"Started {dt.strftime('%b')} {dt.year}"


def _months_between(from_month_key: str, to_month_key: str) -> int:
    a = datetime.fromisoformat(f"{from_month_key}T00:00:00+00:00")
    b = datetime.fromisoformat(f"{to_month_key}T00:00:00+00:00")
    return (b.year - a.year) * 12 + (b.month - a.month)


def _add_months(month_key: str, n: int) -> str:
    dt = datetime.fromisoformat(f"{month_key}T00:00:00+00:00")
    year = dt.year + ((dt.month - 1 + n) // 12)
    month = ((dt.month - 1 + n) % 12) + 1
    return f"{year:04d}-{month:02d}-01"


def build_cohort_retention(walk: dict[str, Any]) -> DashboardRevenueCohortRetentionResponse:
    earliest_start_by_customer: dict[str, float] = {}
    for sub in walk["subscriptions"]:
        starts_at = sub.get("startsAt")
        if not isinstance(starts_at, (int, float)):
            continue
        customer_id = str(sub["customerId"])
        prior = earliest_start_by_customer.get(customer_id)
        if prior is None or starts_at < prior:
            earliest_start_by_customer[customer_id] = float(starts_at)
    if not earliest_start_by_customer:
        return DashboardRevenueCohortRetentionResponse()
    customers_by_cohort: dict[str, list[str]] = {}
    for customer_id, starts_at in earliest_start_by_customer.items():
        customers_by_cohort.setdefault(_month_key(starts_at), []).append(customer_id)
    windows_by_customer: dict[str, list[tuple[float, float]]] = {}
    for sub in walk["subscriptions"]:
        starts_at = sub.get("startsAt")
        if not isinstance(starts_at, (int, float)):
            continue
        ends_at = (
            float(sub["endsAt"])
            if isinstance(sub.get("endsAt"), (int, float))
            else float("inf")
            if sub.get("givesAccess") and sub.get("status") == "active"
            else float(starts_at)
        )
        windows_by_customer.setdefault(str(sub["customerId"]), []).append((float(starts_at), ends_at))
    now_month = _month_key(time.time() * 1000)
    cohort_keys = sorted(customers_by_cohort.keys())[-6:]
    cohorts: list[DashboardRevenueCohortRowResponse] = []
    for cohort_key in cohort_keys:
        members = customers_by_cohort.get(cohort_key, [])
        cohort_size = len(members)
        months_since = _months_between(cohort_key, now_month)
        points: list[DashboardRevenueCohortPointResponse] = []
        for month_index in range(months_since + 1):
            check_month = _add_months(cohort_key, month_index)
            check_start_ms = datetime.fromisoformat(f"{check_month}T00:00:00+00:00").timestamp() * 1000
            next_month = _add_months(cohort_key, month_index + 1)
            check_end_ms = datetime.fromisoformat(f"{next_month}T00:00:00+00:00").timestamp() * 1000
            incomplete = check_end_ms > time.time() * 1000
            active = 0
            for customer_id in members:
                overlaps = any(
                    starts_at < check_end_ms and ends_at > check_start_ms
                    for starts_at, ends_at in windows_by_customer.get(customer_id, [])
                )
                if overlaps:
                    active += 1
            retention_pct = round((active / cohort_size) * 100, 1) if cohort_size > 0 else 0.0
            points.append(
                DashboardRevenueCohortPointResponse(
                    monthIndex=month_index,
                    activeCount=active,
                    retentionPct=retention_pct,
                    incomplete=incomplete,
                )
            )
        cohorts.append(
            DashboardRevenueCohortRowResponse(
                cohortMonth=cohort_key,
                cohortLabel=_month_label(cohort_key),
                cohortSize=cohort_size,
                points=points,
            )
        )
    return DashboardRevenueCohortRetentionResponse(cohorts=cohorts)


def _empty_conversion_buckets() -> DashboardRevenueConversionBucketsResponse:
    return DashboardRevenueConversionBucketsResponse()


def _infer_cadence(sub: dict[str, Any]) -> str:
    lower = str(sub.get("productId") or "").lower()
    if "yearly" in lower:
        return "Yearly"
    if "monthly" in lower:
        return "Monthly"
    return "Unknown"


def build_monthly_to_yearly_conversions(
    walk: dict[str, Any], range_days: int
) -> DashboardRevenueMonthlyToYearlyResponse:
    start_ms = time.time() * 1000 - range_days * 24 * 60 * 60 * 1000
    monthly_by_customer: dict[str, float] = {}
    yearly_by_customer: dict[str, float] = {}
    for sub in walk["subscriptions"]:
        starts_at = sub.get("startsAt")
        if not isinstance(starts_at, (int, float)):
            continue
        cadence = _infer_cadence(sub)
        customer_id = str(sub["customerId"])
        if cadence == "Monthly":
            prior = monthly_by_customer.get(customer_id)
            if prior is None or starts_at < prior:
                monthly_by_customer[customer_id] = float(starts_at)
        elif cadence == "Yearly":
            prior = yearly_by_customer.get(customer_id)
            if prior is None or starts_at < prior:
                yearly_by_customer[customer_id] = float(starts_at)
    monthly_in_range = sum(1 for starts_at in monthly_by_customer.values() if starts_at >= start_ms)
    conversions = 0
    buckets = _empty_conversion_buckets()
    for customer_id, monthly_start in monthly_by_customer.items():
        yearly_start = yearly_by_customer.get(customer_id)
        if not yearly_start or yearly_start <= monthly_start or yearly_start < start_ms:
            continue
        conversions += 1
        gap_months = (yearly_start - monthly_start) / (30 * 24 * 60 * 60 * 1000)
        if gap_months <= 1:
            buckets.withinOneMonth += 1
        elif gap_months <= 3:
            buckets.oneToThree += 1
        elif gap_months <= 6:
            buckets.threeToSix += 1
        else:
            buckets.sixPlus += 1
    conversion_rate = round(conversions / monthly_in_range, 3) if monthly_in_range > 0 else 0.0
    return DashboardRevenueMonthlyToYearlyResponse(
        conversions=conversions,
        monthlySubscribersInRange=monthly_in_range,
        conversionRate=conversion_rate,
        timeToConversionBuckets=buckets,
    )


def derive_plan_breakdown() -> DashboardRevenuePlanBreakdownResponse:
    cached = load_walk()
    walk = cached["walk"]
    products = cached["products"]
    product_by_id = {product["id"]: product for product in products}

    rows: dict[str, DashboardRevenuePlanBreakdownItemResponse] = {}
    total_active = 0
    for sub in walk["subscriptions"]:
        if not _is_active_now(sub):
            continue
        total_active += 1
        product = product_by_id.get(sub["productId"])
        classified = _classify_product(product["storeIdentifier"]) if product else None
        if not classified:
            lookup = str((sub.get("entitlementLookupKeys") or [""])[0]).lower()
            plan = "Designer" if "designer" in lookup else "Pro" if "pro" in lookup else "Starter" if "starter" in lookup else "Other"
            cadence = "Yearly" if product and product.get("duration") == "P1Y" else "Monthly" if product and product.get("duration") == "P1M" else "Unknown"
            classified = {"plan": plan, "cadence": cadence}
        key = f"{classified['plan']}::{classified['cadence']}"
        row = rows.get(key) or DashboardRevenuePlanBreakdownItemResponse(
            plan=classified["plan"],
            cadence=classified["cadence"],
            count=0,
        )
        row.count += 1
        rows[key] = row

    return DashboardRevenuePlanBreakdownResponse(
        plans=sorted(rows.values(), key=lambda row: row.count, reverse=True),
        totalActiveSubscribers=total_active,
    )


def derive_credits_by_package(range_days: int) -> DashboardRevenuePackBreakdownResponse:
    cached = load_walk()
    walk = cached["walk"]
    products = cached["products"]
    product_by_id = {product["id"]: product for product in products}
    chart_range = _range_for_days(range_days)
    start_ms = datetime.fromisoformat(f"{chart_range['startDate']}T00:00:00+00:00").timestamp() * 1000
    end_ms = datetime.fromisoformat(f"{chart_range['endDate']}T23:59:59+00:00").timestamp() * 1000

    tally: dict[str, dict[str, float | int]] = {
        "XL": {"revenue": 0.0, "units": 0},
        "L": {"revenue": 0.0, "units": 0},
        "M": {"revenue": 0.0, "units": 0},
        "S": {"revenue": 0.0, "units": 0},
    }
    for purchase in walk["purchases"]:
        if not _is_production_purchase(purchase):
            continue
        purchased_at = purchase.get("purchasedAt")
        if not isinstance(purchased_at, (int, float)) or purchased_at < start_ms or purchased_at > end_ms:
            continue
        product = product_by_id.get(purchase["productId"])
        if not product:
            continue
        size = _classify_credit_pack(product["storeIdentifier"])
        if not size:
            continue
        tally[size]["revenue"] = float(tally[size]["revenue"]) + float(purchase.get("revenueUsd") or 0)
        tally[size]["units"] = int(tally[size]["units"]) + int(purchase.get("quantity") or 0)

    return DashboardRevenuePackBreakdownResponse(
        packs=[
            DashboardRevenuePackBreakdownItemResponse(
                size=size,
                revenue=float(tally[size]["revenue"]),
                units=int(tally[size]["units"]),
            )
            for size in ("XL", "L", "M", "S")
        ]
    )


def derive_credits_revenue_timeseries(range_days: int) -> DashboardRevenueChartResponse:
    cached = load_walk()
    walk = cached["walk"]
    products = cached["products"]
    product_by_id = {product["id"]: product for product in products}
    chart_range = _range_for_days(range_days)
    start_ms = datetime.fromisoformat(f"{chart_range['startDate']}T00:00:00+00:00").timestamp() * 1000
    end_ms = datetime.fromisoformat(f"{chart_range['endDate']}T23:59:59+00:00").timestamp() * 1000

    buckets: dict[str, float] = {}
    for purchase in walk["purchases"]:
        if not _is_production_purchase(purchase):
            continue
        purchased_at = purchase.get("purchasedAt")
        if not isinstance(purchased_at, (int, float)) or purchased_at < start_ms or purchased_at > end_ms:
            continue
        product = product_by_id.get(purchase["productId"])
        if not product or not _classify_credit_pack(product["storeIdentifier"]):
            continue
        bucket = _bucket_date_for_resolution(float(purchased_at), chart_range["resolution"])
        buckets[bucket] = buckets.get(bucket, 0.0) + float(purchase.get("revenueUsd") or 0)

    values = [
        DashboardRevenueChartPointResponse(
            cohort=int(datetime.fromisoformat(f"{date}T00:00:00+00:00").timestamp()),
            date=date,
            value=round(value, 2),
            incomplete=False,
            measure=0,
        )
        for date, value in sorted(buckets.items())
    ]
    return DashboardRevenueChartResponse(
        chartName="revenue",
        resolution=chart_range["resolution"],
        values=values,
        yaxisCurrency="USD",
    )


def _safe_overview_metrics() -> list[dict[str, Any]]:
    try:
        return get_overview()["metrics"]
    except RevenueCatApiError as error:
        if error.status in {0, 404}:
            return []
        raise


def _safe_chart(chart_name: str, range_days: int, filters: dict[str, str] | None = None) -> DashboardRevenueChartResponse:
    try:
        return get_chart(chart_name, range_days, filters)
    except RevenueCatApiError as error:
        if error.status in {400, 404}:
            chart_range = _range_for_days(range_days)
            return DashboardRevenueChartResponse(
                chartName=chart_name,
                resolution=chart_range["resolution"],
                values=[],
                yaxisCurrency=None,
            )
        raise


def _chart_points_to_daily(values: list[DashboardRevenueChartPointResponse], key: str) -> list[dict[str, Any]]:
    return [{ "date": point.date, key: round(point.value, 2)} for point in values if not point.incomplete]


def build_revenue_context() -> dict[str, Any]:
    global _context_cache
    if _context_cache and time.time() * 1000 < _context_cache["expiresAt"]:
        return _context_cache["context"]

    overview = _safe_overview_metrics()
    walk = load_walk()
    mrr_chart = _safe_chart("mrr", 90)
    actives_chart = _safe_chart("actives", 90)
    revenue_chart = _safe_chart("revenue", 90)
    churn_chart = _safe_chart("churn", 365)

    metrics_by_id = {metric["id"]: metric for metric in overview}
    mrr = metrics_by_id.get("mrr", {}).get("value")
    active_subs = metrics_by_id.get("active_subscriptions", {}).get("value")
    active_trials = metrics_by_id.get("active_trials", {}).get("value")
    revenue_28d = metrics_by_id.get("revenue", {}).get("value")
    active_users = metrics_by_id.get("active_users", {}).get("value")
    new_customers = metrics_by_id.get("new_customers", {}).get("value")

    credits_packages = derive_credits_by_package(30)
    credits_revenue_30d = round(sum(pack.revenue for pack in credits_packages.packs), 2)
    active_subscriber_count = int(active_subs) if isinstance(active_subs, (int, float)) else None
    credits_revenue_per_subscriber = (
        round(credits_revenue_30d / active_subscriber_count, 2)
        if active_subscriber_count and active_subscriber_count > 0
        else None
    )

    plan_breakdown = derive_plan_breakdown()
    ad_spend_last_30d = 0.0
    try:
        ads = dashboard_table("ads").select("spend").execute().data or []
        for ad in ads:
            try:
                ad_spend_last_30d += float(ad.get("spend") or 0)
            except (TypeError, ValueError):
                continue
        if (os.getenv("META_AD_ACCOUNT_CURRENCY") or "ILS").upper() != "USD":
            fx = get_usd_to_ils_rate()
            if fx.rate > 0:
                ad_spend_last_30d = ad_spend_last_30d / fx.rate
    except Exception:
        logger.exception("Failed to load ad spend for revenue context")

    context = {
        "mrrUsd": float(mrr) if isinstance(mrr, (int, float)) else None,
        "activeSubscribersCount": active_subscriber_count,
        "churnRateLast30d": churn_chart.values[-1].value if churn_chart.values else None,
        "planMix": [
            {
                "planTier": row.plan.lower(),
                "monthly": row.count if row.cadence == "Monthly" else 0,
                "yearly": row.count if row.cadence == "Yearly" else 0,
            }
            for row in plan_breakdown.plans
        ],
        "creditsRevenueLast30dUsd": credits_revenue_30d,
        "creditsRevenuePerActiveSubscriberLast30dUsd": credits_revenue_per_subscriber,
        "mrrTimeseries": _chart_points_to_daily(mrr_chart.values, "mrrUsd"),
        "activeSubscribersTimeseries": _chart_points_to_daily(actives_chart.values, "count"),
        "creditsRevenueTimeseries": _chart_points_to_daily(
            derive_credits_revenue_timeseries(90).values,
            "revenueUsd",
        ),
        "churnRateTimeseries": _chart_points_to_daily(churn_chart.values, "rate"),
        "adSpendLast30dUsd": round(ad_spend_last_30d, 2),
        "roasLast30d": round(float(revenue_28d) / ad_spend_last_30d, 2)
        if isinstance(revenue_28d, (int, float)) and ad_spend_last_30d > 0
        else None,
        "newCustomersLast30d": int(new_customers) if isinstance(new_customers, (int, float)) else 0,
        "activeUsersLast30d": int(active_users) if isinstance(active_users, (int, float)) else 0,
        "topCampaigns": [],
        "hasCampaignAttribution": False,
        "activeTrials": int(active_trials) if isinstance(active_trials, (int, float)) else None,
        "asOf": datetime.now(timezone.utc).isoformat(),
        "currency": "USD",
    }
    _context_cache = {"expiresAt": time.time() * 1000 + _CONTEXT_TTL_MS, "context": context}
    return context


def summarize_revenue_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "asOf": context.get("asOf"),
        "currency": context.get("currency", "USD"),
        "snapshot": {
            "mrrUsd": context.get("mrrUsd"),
            "activeSubscribersCount": context.get("activeSubscribersCount"),
            "churnRateLast30d": context.get("churnRateLast30d"),
            "creditsRevenueLast30dUsd": context.get("creditsRevenueLast30dUsd", 0),
            "creditsRevenuePerActiveSubscriberLast30dUsd": context.get(
                "creditsRevenuePerActiveSubscriberLast30dUsd"
            ),
            "adSpendLast30dUsd": context.get("adSpendLast30dUsd", 0),
            "roasLast30d": context.get("roasLast30d"),
            "newCustomersLast30d": context.get("newCustomersLast30d", 0),
        },
        "planMix": context.get("planMix", []),
        "campaigns": {
            "topByspend": context.get("topCampaigns", []),
            "hasAttribution": context.get("hasCampaignAttribution", False),
            "sentence": "Top campaign summary is not yet available in gemzy-api.",
        },
    }


@router.get("/configured")
def configured(current: UserState = Depends(get_current_user)) -> dict[str, bool]:
    ensure_dashboard_admin(current)
    return {"configured": is_configured()}


@router.get("/overview", response_model=DashboardRevenueOverviewResponse)
def revenue_overview(current: UserState = Depends(get_current_user)) -> DashboardRevenueOverviewResponse:
    ensure_dashboard_admin(current)
    try:
        metrics = _safe_overview_metrics()
    except RevenueCatApiError:
        raise

    metrics_by_id = {metric["id"]: metric["value"] for metric in metrics}
    return DashboardRevenueOverviewResponse(
        mrr=float(metrics_by_id["mrr"]) if "mrr" in metrics_by_id else None,
        revenue28d=float(metrics_by_id["revenue"]) if "revenue" in metrics_by_id else None,
        activeSubscriptions=int(metrics_by_id["active_subscriptions"])
        if "active_subscriptions" in metrics_by_id
        else None,
        activeTrials=int(metrics_by_id["active_trials"]) if "active_trials" in metrics_by_id else None,
        newCustomers28d=int(metrics_by_id["new_customers"]) if "new_customers" in metrics_by_id else None,
        activeUsers28d=int(metrics_by_id["active_users"]) if "active_users" in metrics_by_id else None,
    )


@router.get("/charts/mrr", response_model=DashboardRevenueChartResponse)
def mrr_timeseries(
    rangeDays: int = Query(default=90, ge=1, le=3650),
    current: UserState = Depends(get_current_user),
) -> DashboardRevenueChartResponse:
    ensure_dashboard_admin(current)
    return _safe_chart("mrr", rangeDays)


@router.get("/charts/active-subs", response_model=DashboardRevenueChartResponse)
def active_subs_timeseries(
    rangeDays: int = Query(default=90, ge=1, le=3650),
    current: UserState = Depends(get_current_user),
) -> DashboardRevenueChartResponse:
    ensure_dashboard_admin(current)
    return _safe_chart("actives", rangeDays)


@router.get("/charts/revenue", response_model=DashboardRevenueChartResponse)
def revenue_timeseries(
    rangeDays: int = Query(default=90, ge=1, le=3650),
    type: str = Query(default="all"),
    current: UserState = Depends(get_current_user),
) -> DashboardRevenueChartResponse:
    ensure_dashboard_admin(current)
    chart = _safe_chart("revenue", rangeDays)
    chart.type = type
    return chart


@router.get("/charts/credits-revenue", response_model=DashboardRevenueChartResponse)
def credits_revenue_timeseries(
    rangeDays: int = Query(default=90, ge=1, le=3650),
    current: UserState = Depends(get_current_user),
) -> DashboardRevenueChartResponse:
    ensure_dashboard_admin(current)
    return derive_credits_revenue_timeseries(rangeDays)


@router.get("/charts/churn", response_model=DashboardRevenueChartResponse)
def churn_timeseries(
    rangeDays: int = Query(default=365, ge=1, le=3650),
    current: UserState = Depends(get_current_user),
) -> DashboardRevenueChartResponse:
    ensure_dashboard_admin(current)
    return _safe_chart("churn", rangeDays)


@router.get("/plan-breakdown", response_model=DashboardRevenuePlanBreakdownResponse)
def plan_breakdown(
    current: UserState = Depends(get_current_user),
) -> DashboardRevenuePlanBreakdownResponse:
    ensure_dashboard_admin(current)
    try:
        return derive_plan_breakdown()
    except RevenueCatApiError as error:
        if error.status == 404:
            return DashboardRevenuePlanBreakdownResponse(plans=[], totalActiveSubscribers=0)
        raise


@router.get("/credits-by-package", response_model=DashboardRevenuePackBreakdownResponse)
def credits_by_package(
    rangeDays: int = Query(default=90, ge=1, le=3650),
    current: UserState = Depends(get_current_user),
) -> DashboardRevenuePackBreakdownResponse:
    ensure_dashboard_admin(current)
    try:
        return derive_credits_by_package(rangeDays)
    except RevenueCatApiError as error:
        if error.status == 404:
            return DashboardRevenuePackBreakdownResponse(
                packs=[
                    DashboardRevenuePackBreakdownItemResponse(size=size, revenue=0, units=0)
                    for size in ("XL", "L", "M", "S")
                ]
            )
        raise


@router.get("/subscribers", response_model=DashboardRevenueSubscriberListResponse)
def list_subscribers(
    search: str = Query(default=""),
    plan: str = Query(default="all"),
    period: str = Query(default="all"),
    status: str = Query(default="active"),
    sort: str = Query(default="newest"),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=100),
    current: UserState = Depends(get_current_user),
) -> DashboardRevenueSubscriberListResponse:
    ensure_dashboard_admin(current)
    cached = load_walk()
    rows = build_subscriber_rows(cached["walk"], cached["products"])

    def _matches(row: DashboardRevenueSubscriberRowResponse) -> bool:
        if plan != "all" and row.plan != plan:
            return False
        if period != "all" and row.cadence != period:
            return False
        if status != "all":
            if status == "active" and row.status != "active":
                return False
            if status == "cancelled" and row.status == "active":
                return False
        query = search.strip().lower()
        if query and query not in row.customerId.lower() and query not in row.ref.lower():
            return False
        return True

    filtered = [row for row in rows if _matches(row)]
    if sort == "oldest":
        filtered.sort(key=lambda row: row.startedAt or 0)
    elif sort == "lifetime_desc":
        filtered.sort(key=lambda row: row.creditsRevenueUsdLifetime, reverse=True)
    else:
        filtered.sort(key=lambda row: row.startedAt or 0, reverse=True)
    total = len(filtered)
    start_idx = (page - 1) * pageSize
    return DashboardRevenueSubscriberListResponse(
        items=filtered[start_idx : start_idx + pageSize],
        total=total,
        page=page,
        pageSize=pageSize,
    )


@router.get("/subscribers/{customer_id}", response_model=DashboardRevenueSubscriberDetailResponse | None)
def get_subscriber_detail(
    customer_id: str,
    current: UserState = Depends(get_current_user),
) -> DashboardRevenueSubscriberDetailResponse | None:
    ensure_dashboard_admin(current)
    cached = load_walk()
    return build_subscriber_detail(customer_id, cached["walk"], cached["products"])


@router.get("/cohort-retention", response_model=DashboardRevenueCohortRetentionResponse)
def get_cohort_retention(current: UserState = Depends(get_current_user)) -> DashboardRevenueCohortRetentionResponse:
    ensure_dashboard_admin(current)
    cached = load_walk()
    return build_cohort_retention(cached["walk"])


@router.get("/monthly-to-yearly", response_model=DashboardRevenueMonthlyToYearlyResponse)
def get_monthly_to_yearly(
    rangeDays: int = Query(default=365, ge=1, le=3650),
    current: UserState = Depends(get_current_user),
) -> DashboardRevenueMonthlyToYearlyResponse:
    ensure_dashboard_admin(current)
    cached = load_walk()
    return build_monthly_to_yearly_conversions(cached["walk"], rangeDays)
