"""Billing helpers: plan resolution, usage limits, and subscription state."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from .auth.encryption import decrypt_key, encrypt_key
from .db import get_conn

PLAN_ORDER = {
    "free": 0,
    "plus": 1,
    "pro": 2,
}

ACTIVE_SUBSCRIPTION_STATUSES = {
    "active",
    "trialing",
    "past_due",
    "incomplete",
    "incomplete_expired",
}


def period_key_utc(now: datetime | None = None, strategy: str = "monthly") -> str:
    base = now or datetime.now(timezone.utc)
    if strategy == "daily":
        return base.strftime("%Y-%m-%d")
    return base.strftime("%Y-%m-%0m") if strategy == "monthly" else base.strftime("%Y-%m")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:
        return default


def _normalized_plan_id(plan_id: str | None) -> str:
    return str(plan_id or "").strip().lower()


def _plan_rank(plan_id: str | None) -> int:
    return PLAN_ORDER.get(_normalized_plan_id(plan_id), 0)


def _public_plan_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row.get("name", row["id"].title()),
        "description": row.get("description", "") or "",
        "provider": row["provider_id"],
        "model": row["model_id"],
        "monthlyPriceCents": _as_int(row.get("monthly_price_cents"), 0),
        "monthlyRequestLimit": _as_int(row.get("monthly_request_limit"), 0),
        "inputTokenPricePerMillion": _as_float(row.get("input_token_price_per_million"), 0.0),
        "outputTokenPricePerMillion": _as_float(row.get("output_token_price_per_million"), 0.0),
        "stripePriceId": row.get("stripe_price_id", "") or "",
        "active": bool(row.get("active", True)),
        "sortOrder": _as_int(row.get("sort_order"), 0),
        "limitStrategy": row.get("limit_strategy", "monthly"),
        "dailyTokenLimit": _as_int(row.get("daily_token_limit"), 0),
        "totalTokenLimit": _as_int(row.get("total_token_limit"), 0),
        "apiKeyConfigured": bool(row.get("encrypted_api_key", "") or ""),
    }


def list_plans(*, active_only: bool = False) -> list[dict]:
    with get_conn() as conn:
        if active_only:
            rows = conn.execute(
                """
                SELECT *
                FROM subscription_plans
                WHERE active = TRUE
                ORDER BY sort_order ASC, id ASC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM subscription_plans
                ORDER BY sort_order ASC, id ASC
                """
            ).fetchall()

    return [dict(r) for r in rows]


def get_plan(plan_id: str, *, active_only: bool = False) -> dict | None:
    normalized = _normalized_plan_id(plan_id)
    if not normalized:
        return None

    with get_conn() as conn:
        if active_only:
            row = conn.execute(
                "SELECT * FROM subscription_plans WHERE id = %s AND active = TRUE",
                (normalized,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM subscription_plans WHERE id = %s",
                (normalized,),
            ).fetchone()
    return dict(row) if row else None


def ensure_user_subscription(user_id: str) -> None:
    if not user_id:
        return

    with get_conn() as conn:
        free_plan = conn.execute(
            "SELECT id FROM subscription_plans WHERE id = 'free'",
        ).fetchone()
        if not free_plan:
            raise RuntimeError("Missing required 'free' subscription plan. Initialize DB seed first.")

        conn.execute(
            """
            INSERT INTO user_subscriptions (user_id, plan_id, status)
            VALUES (%s, 'free', 'active')
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,),
        )
        conn.commit()


def _load_subscription_with_plan(user_id: str) -> dict:
    ensure_user_subscription(user_id)

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                us.user_id,
                us.plan_id,
                us.status,
                us.stripe_customer_id,
                us.stripe_subscription_id,
                us.stripe_checkout_session_id,
                us.current_period_start,
                us.current_period_end,
                us.cancel_at_period_end,
                us.custom_token_limit,
                us.updated_at,
                p.id AS plan_row_id,
                p.name AS plan_name,
                p.description AS plan_description,
                p.provider_id AS plan_provider_id,
                p.model_id AS plan_model_id,
                p.monthly_price_cents AS plan_monthly_price_cents,
                p.monthly_request_limit AS plan_monthly_request_limit,
                p.input_token_price_per_million AS plan_input_token_price_per_million,
                p.output_token_price_per_million AS plan_output_token_price_per_million,
                p.stripe_price_id AS plan_stripe_price_id,
                p.active AS plan_active,
                p.sort_order AS plan_sort_order,
                p.limit_strategy AS plan_limit_strategy,
                p.daily_token_limit AS plan_daily_token_limit,
                p.total_token_limit AS plan_total_token_limit,
                p.encrypted_api_key AS plan_encrypted_api_key
            FROM user_subscriptions us
            JOIN subscription_plans p ON p.id = us.plan_id
            WHERE us.user_id = %s
            """,
            (user_id,),
        ).fetchone()

    if row:
        return dict(row)

    # Fallback to free if the currently linked plan was deleted or corrupted.
    set_user_plan(user_id=user_id, plan_id="free", status="active")
    return _load_subscription_with_plan(user_id)


def get_user_plan_bundle(user_id: str, requested_plan_id: str = "") -> dict:
    subscription = _load_subscription_with_plan(user_id)
    all_plans = list_plans(active_only=True)
    plans_by_id = {row["id"]: row for row in all_plans}

    current_plan_id = _normalized_plan_id(subscription.get("plan_id", "free")) or "free"
    current_status = str(subscription.get("status", "active") or "active").lower()

    # Non-active subscriptions fall back to free entitlements.
    if current_status not in ACTIVE_SUBSCRIPTION_STATUSES:
        current_plan_id = "free"

    current_plan = plans_by_id.get(current_plan_id) or get_plan(current_plan_id) or get_plan("free")
    if not current_plan:
        raise HTTPException(500, "Billing plan configuration is missing.")

    current_rank = _plan_rank(current_plan["id"])
    allowed_plan_ids = [
        row["id"]
        for row in all_plans
        if row.get("active", True) and _plan_rank(row["id"]) <= current_rank
    ]
    if "free" not in allowed_plan_ids:
        allowed_plan_ids.append("free")

    selected_plan = current_plan
    requested = _normalized_plan_id(requested_plan_id)
    if requested:
        requested_plan = plans_by_id.get(requested) or get_plan(requested, active_only=True)
        if not requested_plan:
            raise HTTPException(404, f"Unknown plan: {requested}")
        if _plan_rank(requested_plan["id"]) > current_rank:
            raise HTTPException(
                403,
                f"Your current subscription does not include '{requested_plan['name']}'. Upgrade required.",
            )
        selected_plan = requested_plan

    return {
        "subscription": subscription,
        "current_plan": current_plan,
        "selected_plan": selected_plan,
        "available_plans": all_plans,
        "allowed_plan_ids": allowed_plan_ids,
    }


def get_plan_api_key(plan_row: dict) -> str:
    encrypted = str(plan_row.get("encrypted_api_key", "") or "").strip()
    if not encrypted:
        return ""
    try:
        return decrypt_key(encrypted)
    except Exception:
        return ""


def set_plan_api_key(plan_id: str, api_key: str) -> None:
    normalized = _normalized_plan_id(plan_id)
    if not normalized:
        raise HTTPException(400, "Plan id is required")

    encrypted = encrypt_key(api_key.strip()) if api_key.strip() else ""
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM subscription_plans WHERE id = %s", (normalized,)).fetchone()
        if not row:
            raise HTTPException(404, "Plan not found")
        conn.execute(
            "UPDATE subscription_plans SET encrypted_api_key=%s, updated_at=NOW() WHERE id=%s",
            (encrypted, normalized),
        )
        conn.commit()


def get_usage_snapshot(user_id: str, plan_row: dict, *, period_key: str | None = None) -> dict:
    strategy = plan_row.get("limit_strategy", "monthly")
    current_key = period_key or period_key_utc(strategy=strategy)

    with get_conn() as conn:
        usage_row = conn.execute(
            """
            SELECT requests_used, input_tokens, output_tokens
            FROM usage_counters
            WHERE user_id = %s AND period_key = %s
            """,
            (user_id, current_key),
        ).fetchone()

        sub_row = conn.execute(
            "SELECT total_tokens_used, custom_token_limit FROM user_subscriptions WHERE user_id = %s",
            (user_id,),
        ).fetchone()

    used_requests = _as_int(usage_row["requests_used"], 0) if usage_row else 0
    input_tokens = _as_int(usage_row["input_tokens"], 0) if usage_row else 0
    output_tokens = _as_int(usage_row["output_tokens"], 0) if usage_row else 0
    total_tokens_used = _as_int(sub_row["total_tokens_used"], 0) if sub_row else 0
    custom_token_limit = _as_int(sub_row["custom_token_limit"], 0) if sub_row else 0

    limit_requests = max(0, _as_int(plan_row.get("monthly_request_limit"), 0))
    limit_daily_tokens = max(0, _as_int(plan_row.get("daily_token_limit"), 0))
    
    # If a custom limit is set (purchased credits), use it. Otherwise use the plan default.
    limit_total_tokens = custom_token_limit if custom_token_limit > 0 else max(0, _as_int(plan_row.get("total_token_limit"), 0))

    return {
        "periodKey": current_key,
        "strategy": strategy,
        "requestsUsed": used_requests,
        "requestsLimit": limit_requests,
        "dailyTokensUsed": input_tokens + output_tokens,
        "dailyTokensLimit": limit_daily_tokens,
        "totalTokensUsed": total_tokens_used,
        "totalTokensLimit": limit_total_tokens,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
    }


def enforce_usage_limits(user_id: str, plan_row: dict) -> dict:
    usage = get_usage_snapshot(user_id, plan_row)
    strategy = usage["strategy"]

    # 1. Enforce Daily Token Limit (Free Plan typical)
    if strategy == "daily" and usage["dailyTokensLimit"] > 0:
        if usage["dailyTokensUsed"] >= usage["dailyTokensLimit"]:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Daily token limit reached for {plan_row.get('name', 'Free plan')}. "
                    "Wait until tomorrow or upgrade to Plus/Pro for more tokens."
                ),
            )

    # 2. Enforce Total Token Bucket (Plus/Pro typical)
    if strategy == "total" and usage["totalTokensLimit"] > 0:
        if usage["totalTokensUsed"] >= usage["totalTokensLimit"]:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Total token bucket exhausted for {plan_row.get('name', 'Paid plan')}. "
                    "Upgrade your plan or purchase a new token bundle."
                ),
            )

    # 3. Legacy Monthly Request Limit (only if specifically using monthly strategy)
    limit_req = usage["requestsLimit"]
    if strategy == "monthly" and limit_req > 0:
        if usage["requestsUsed"] >= limit_req:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Monthly request limit reached for {plan_row.get('name', plan_row.get('id', 'plan'))}. "
                    "Upgrade your plan or wait for the next monthly reset."
                ),
            )

    return usage


def increment_token_usage(
    user_id: str, input_tokens: int = 0, output_tokens: int = 0, requests_amount: int = 0
) -> dict:
    if input_tokens <= 0 and output_tokens <= 0 and requests_amount <= 0:
        return {}

    # Update daily counter
    day_key = period_key_utc(strategy="daily")
    # Update monthly counter
    month_key = period_key_utc(strategy="monthly")

    with get_conn() as conn:
        for p_key in (day_key, month_key):
            conn.execute(
                """
                INSERT INTO usage_counters (
                    id, user_id, period_key, requests_used, input_tokens, output_tokens, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (user_id, period_key)
                DO UPDATE SET
                    requests_used = usage_counters.requests_used + EXCLUDED.requests_used,
                    input_tokens = usage_counters.input_tokens + EXCLUDED.input_tokens,
                    output_tokens = usage_counters.output_tokens + EXCLUDED.output_tokens,
                    updated_at = NOW()
                """,
                (str(uuid.uuid4()), user_id, p_key, requests_amount, input_tokens, output_tokens),
            )

        # Update total tokens in user_subscriptions for 'total' strategy
        conn.execute(
            """
            UPDATE user_subscriptions
            SET total_tokens_used = total_tokens_used + %s,
                updated_at = NOW()
            WHERE user_id = %s
            """,
            (input_tokens + output_tokens, user_id),
        )
        conn.commit()

    return {"status": "success"}


def increment_request_usage(user_id: str, amount: int = 1) -> dict:
    return increment_token_usage(user_id, requests_amount=amount)


def increment_purchased_tokens(user_id: str, amount: int) -> None:
    """Atomically increment the custom token limit (purchased credits) for a user."""
    if amount <= 0:
        return
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE user_subscriptions
            SET custom_token_limit = custom_token_limit + %s,
                updated_at = NOW()
            WHERE user_id = %s
            """,
            (amount, user_id),
        )
        conn.commit()


def set_user_plan(
    *,
    user_id: str,
    plan_id: str,
    status: str = "active",
    stripe_customer_id: str = "",
    stripe_subscription_id: str = "",
    stripe_checkout_session_id: str = "",
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    cancel_at_period_end: bool = False,
) -> None:
    normalized_plan = _normalized_plan_id(plan_id)
    if not normalized_plan:
        raise HTTPException(400, "Plan id is required")

    plan = get_plan(normalized_plan)
    if not plan:
        raise HTTPException(404, f"Unknown plan: {normalized_plan}")

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_subscriptions (
                user_id,
                plan_id,
                status,
                stripe_customer_id,
                stripe_subscription_id,
                stripe_checkout_session_id,
                current_period_start,
                current_period_end,
                cancel_at_period_end,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                plan_id = EXCLUDED.plan_id,
                status = EXCLUDED.status,
                stripe_customer_id = EXCLUDED.stripe_customer_id,
                stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                stripe_checkout_session_id = EXCLUDED.stripe_checkout_session_id,
                current_period_start = EXCLUDED.current_period_start,
                current_period_end = EXCLUDED.current_period_end,
                cancel_at_period_end = EXCLUDED.cancel_at_period_end,
                updated_at = NOW()
            """,
            (
                user_id,
                normalized_plan,
                str(status or "active").lower(),
                stripe_customer_id or "",
                stripe_subscription_id or "",
                stripe_checkout_session_id or "",
                current_period_start,
                current_period_end,
                bool(cancel_at_period_end),
            ),
        )
        conn.commit()


def get_user_billing_snapshot(user_id: str) -> dict:
    bundle = get_user_plan_bundle(user_id)
    current_plan = bundle["current_plan"]
    usage = get_usage_snapshot(user_id, current_plan)

    plans_payload = []
    allowed_ids = set(bundle["allowed_plan_ids"])
    current_id = current_plan["id"]

    for plan in bundle["available_plans"]:
        payload = _public_plan_row(plan)
        payload["isCurrent"] = payload["id"] == current_id
        payload["canUse"] = payload["id"] in allowed_ids
        plans_payload.append(payload)

    subscription = bundle["subscription"]
    return {
        "currentPlan": {
            **_public_plan_row(current_plan),
            "status": str(subscription.get("status", "active") or "active").lower(),
            "currentPeriodStart": subscription.get("current_period_start"),
            "currentPeriodEnd": subscription.get("current_period_end"),
            "cancelAtPeriodEnd": bool(subscription.get("cancel_at_period_end", False)),
        },
        "usage": usage,
        "plans": plans_payload,
    }


def find_user_id_by_customer_id(customer_id: str) -> str | None:
    if not customer_id:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM user_subscriptions WHERE stripe_customer_id = %s",
            (customer_id,),
        ).fetchone()
    return str(row["user_id"]) if row else None


def find_user_id_by_subscription_id(subscription_id: str) -> str | None:
    if not subscription_id:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM user_subscriptions WHERE stripe_subscription_id = %s",
            (subscription_id,),
        ).fetchone()
    return str(row["user_id"]) if row else None


def mark_webhook_event_processed(event_id: str) -> bool:
    """Return False if event has already been processed."""
    if not event_id:
        return True
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM stripe_webhook_events WHERE id = %s",
            (event_id,),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO stripe_webhook_events (id, processed_at) VALUES (%s, NOW())",
            (event_id,),
        )
        conn.commit()
    return True
