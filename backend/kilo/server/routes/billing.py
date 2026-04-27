"""Billing router — plans, usage stats, Stripe checkout, and Stripe webhooks."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth.middleware import get_current_user
from ..billing import (
    PLAN_ORDER,
    ensure_user_subscription,
    find_user_id_by_customer_id,
    find_user_id_by_subscription_id,
    get_plan,
    get_user_billing_snapshot,
    get_user_plan_bundle,
    increment_purchased_tokens,
    mark_webhook_event_processed,
    set_user_plan,
)
from ..config import settings
from ..db import get_conn

router = APIRouter(prefix="/api/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    planId: str
    successUrl: str = ""
    cancelUrl: str = ""


def _to_plain_dict(value: Any) -> dict:
    """Normalize Stripe SDK objects to plain dict payloads."""
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            converted = to_dict()
            if isinstance(converted, dict):
                return converted
        except Exception:
            return {}
    return {}


def _stripe_error_message(exc: Exception) -> str:
    user_message = str(getattr(exc, "user_message", "") or "").strip()
    if user_message:
        return user_message
    message = str(getattr(exc, "message", "") or "").strip()
    if message:
        return message
    return str(exc).strip() or "Unknown Stripe error"


def _stripe_client():
    api_key = str(getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    if not api_key:
        raise HTTPException(400, "Stripe is not configured on this server.")
    try:
        import stripe  # type: ignore
    except Exception as exc:
        raise HTTPException(500, "Stripe SDK is not installed on backend.") from exc

    stripe.api_key = api_key
    return stripe


def _frontend_default_url() -> str:
    return str(getattr(settings, "FRONTEND_URL", "") or "http://localhost:5173").rstrip("/")


def _to_datetime(epoch_seconds: int | None) -> datetime | None:
    if not epoch_seconds:
        return None
    try:
        return datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc)
    except Exception:
        return None


def _plan_id_from_price(price_id: str) -> str | None:
    if not price_id:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM subscription_plans WHERE stripe_price_id = %s",
            (price_id,),
        ).fetchone()
    return str(row["id"]) if row else None


def _plan_id_from_subscription(subscription: dict) -> str | None:
    subscription = _to_plain_dict(subscription)
    items = ((subscription or {}).get("items") or {}).get("data") or []
    for item in items:
        price_id = str(((item or {}).get("price") or {}).get("id") or "")
        if not price_id:
            continue
        plan_id = _plan_id_from_price(price_id)
        if plan_id:
            return plan_id
    return None


def _upsert_checkout_metadata(user_id: str, customer_id: str, checkout_session_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_subscriptions (user_id, plan_id, status, stripe_customer_id, stripe_checkout_session_id)
            VALUES (%s, 'free', 'active', %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET
                stripe_customer_id = EXCLUDED.stripe_customer_id,
                stripe_checkout_session_id = EXCLUDED.stripe_checkout_session_id,
                updated_at = NOW()
            """,
            (user_id, customer_id or "", checkout_session_id or ""),
        )
        conn.commit()


@router.get("/me")
async def billing_me(current_user: dict = Depends(get_current_user)):
    ensure_user_subscription(current_user["sub"])
    return get_user_billing_snapshot(current_user["sub"])


@router.post("/checkout")
async def create_checkout(req: CheckoutRequest, current_user: dict = Depends(get_current_user)):
    target_plan_id = (req.planId or "").strip().lower()
    if not target_plan_id:
        raise HTTPException(400, "planId is required")

    ensure_user_subscription(current_user["sub"])
    bundle = get_user_plan_bundle(current_user["sub"])
    current_plan = bundle["current_plan"]
    current_rank = PLAN_ORDER.get(current_plan["id"], 0)

    target_plan = get_plan(target_plan_id, active_only=True)
    if not target_plan:
        raise HTTPException(404, "Plan not found or inactive")

    target_rank = PLAN_ORDER.get(target_plan["id"], 0)
    if target_plan["id"] == current_plan["id"]:
        return {
            "status": "already_on_plan",
            "planId": current_plan["id"],
        }

    if target_rank <= current_rank:
        # Downgrades are immediate in-app and do not require Stripe.
        set_user_plan(
            user_id=current_user["sub"],
            plan_id=target_plan["id"],
            status="active",
            stripe_customer_id=str(bundle["subscription"].get("stripe_customer_id", "") or ""),
            stripe_subscription_id=str(bundle["subscription"].get("stripe_subscription_id", "") or ""),
            stripe_checkout_session_id=str(bundle["subscription"].get("stripe_checkout_session_id", "") or ""),
            current_period_start=bundle["subscription"].get("current_period_start"),
            current_period_end=bundle["subscription"].get("current_period_end"),
            cancel_at_period_end=False,
        )
        return {
            "status": "downgraded",
            "planId": target_plan["id"],
        }

    stripe_price_id = str(target_plan.get("stripe_price_id", "") or "").strip()
    if not stripe_price_id:
        # User requested ValueError guard for Stripe sessions
        raise ValueError(f"Stripe price ID not configured for plan: {target_plan['id']}")

    stripe = _stripe_client()

    existing_customer = str(bundle["subscription"].get("stripe_customer_id", "") or "").strip()
    customer_id = existing_customer
    if not customer_id:
        try:
            customer = stripe.Customer.create(
                email=current_user["email"],
                metadata={"user_id": current_user["sub"]},
            )
        except Exception as exc:
            raise HTTPException(400, f"Stripe customer creation failed: {_stripe_error_message(exc)}") from exc
        customer_id = customer.id

    base_url = _frontend_default_url()
    success_url = (req.successUrl or "").strip() or f"{base_url}/dashboard?tab=billing&billing=success"
    cancel_url = (req.cancelUrl or "").strip() or f"{base_url}/dashboard?tab=billing&billing=cancel"

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            customer=customer_id,
            line_items=[{"price": stripe_price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=current_user["sub"],
            metadata={
                "user_id": current_user["sub"],
                "plan_id": target_plan["id"],
            },
            allow_promotion_codes=True,
        )
    except Exception as exc:
        raise HTTPException(400, f"Stripe checkout failed: {_stripe_error_message(exc)}") from exc

    _upsert_checkout_metadata(current_user["sub"], customer_id, session.id)
    return {
        "status": "checkout_created",
        "checkoutUrl": session.url,
    }


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    event: dict

    stripe = _stripe_client()
    webhook_secret = str(getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or "").strip()
    signature = request.headers.get("stripe-signature", "")

    if webhook_secret:
        try:
            event = stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=webhook_secret)
            event = _to_plain_dict(event)
        except Exception as exc:
            raise HTTPException(400, f"Invalid Stripe webhook signature: {exc}") from exc
    else:
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(400, f"Invalid webhook payload: {exc}") from exc

    event_id = str(event.get("id", "") or "")
    if event_id and not mark_webhook_event_processed(event_id):
        return {"status": "duplicate"}

    event_type = str(event.get("type", "") or "")
    data_object = ((event.get("data") or {}).get("object") or {})

    if event_type == "checkout.session.completed":
        metadata = data_object.get("metadata") or {}
        user_id = str(metadata.get("user_id") or data_object.get("client_reference_id") or "").strip()
        customer_id = str(data_object.get("customer") or "").strip()
        subscription_id = str(data_object.get("subscription") or "").strip()
        requested_plan_id = str(metadata.get("plan_id") or "").strip().lower()

        if user_id:
            # For one-time payments, we activate the plan immediately.
            # We don't have a recurring subscription_id in mode="payment".
            try:
                # If there is a subscription ID (e.g. if we switch back to sub later), retrieve it.
                # Otherwise use the requested_plan_id from metadata.
                subscription_id = str(data_object.get("subscription") or "").strip()
                plan_id = requested_plan_id or "free"
                
                if subscription_id:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    subscription = _to_plain_dict(subscription)
                    plan_id = _plan_id_from_subscription(subscription) or plan_id
                
                # Pay-as-you-go: If the plan has a total token limit, increment the user bucket.
                plan_row = get_plan(plan_id)
                if plan_row and plan_row.get("limit_strategy") == "total":
                    token_limit = int(plan_row.get("total_token_limit", 0) or 0)
                    if token_limit > 0:
                        increment_purchased_tokens(user_id, token_limit)

                set_user_plan(
                    user_id=user_id,
                    plan_id=plan_id,
                    status="active",
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    stripe_checkout_session_id=str(data_object.get("id") or ""),
                    current_period_start=datetime.now(timezone.utc),
                    current_period_end=None, # One-time payments don't have an end date typically
                    cancel_at_period_end=False,
                )
            except Exception:
                # Keep webhook robust: store customer/session even if plan lookup fails.
                _upsert_checkout_metadata(user_id, customer_id, str(data_object.get("id") or ""))

    if event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        subscription = data_object
        subscription_id = str(subscription.get("id") or "").strip()
        customer_id = str(subscription.get("customer") or "").strip()

        metadata = subscription.get("metadata") or {}
        user_id = str(metadata.get("user_id") or "").strip()
        if not user_id:
            user_id = find_user_id_by_subscription_id(subscription_id) or find_user_id_by_customer_id(customer_id) or ""

        if user_id:
            if event_type == "customer.subscription.deleted":
                set_user_plan(
                    user_id=user_id,
                    plan_id="free",
                    status="active",
                    stripe_customer_id=customer_id,
                    stripe_subscription_id="",
                    stripe_checkout_session_id="",
                    current_period_start=None,
                    current_period_end=None,
                    cancel_at_period_end=False,
                )
            else:
                plan_id = _plan_id_from_subscription(subscription) or "free"
                set_user_plan(
                    user_id=user_id,
                    plan_id=plan_id,
                    status=str(subscription.get("status") or "active").lower(),
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    stripe_checkout_session_id="",
                    current_period_start=_to_datetime(subscription.get("current_period_start")),
                    current_period_end=_to_datetime(subscription.get("current_period_end")),
                    cancel_at_period_end=bool(subscription.get("cancel_at_period_end", False)),
                )

    return {"status": "ok", "type": event_type}
