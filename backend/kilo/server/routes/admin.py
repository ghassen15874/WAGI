"""Admin router — user, provider, pipeline, logs, metrics management."""
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from ..billing import ensure_user_subscription, get_plan, list_plans, set_plan_api_key, set_user_plan
from ..db import get_conn
from ..auth.middleware import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ── Schemas ───────────────────────────────────────────────────────────────────

class UserUpdate(BaseModel):
    isActive: bool | None = None
    role: str | None = None
    planId: str | None = None

class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str = "USER"

class PipelineGlobalUpdate(BaseModel):
    selfHealingEnabled: bool = True
    validationEnabled: bool = True

class ProviderUpdate(BaseModel):
    enabled: bool

class ModelUpdate(BaseModel):
    enabled: bool

class CreateModelRequest(BaseModel):
    id: str
    provider: str
    enabled: bool = True

class PlanUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    provider: str | None = None
    model: str | None = None
    limitStrategy: str | None = None
    dailyTokenLimit: int | None = None
    totalTokenLimit: int | None = None
    monthlyPriceCents: int | None = None
    monthlyRequestLimit: int | None = None
    inputTokenPricePerMillion: float | None = None
    outputTokenPricePerMillion: float | None = None
    stripePriceId: str | None = None
    active: bool | None = None
    sortOrder: int | None = None
    apiKey: str | None = None


_global_pipeline = {"selfHealingEnabled": True, "validationEnabled": True}


def _normalize_stripe_price_id(value: str | None) -> str:
    return str(value or "").strip()


def _normalize_limit_strategy(value: str | None) -> str:
    strategy = str(value or "").strip().lower()
    if strategy not in {"daily", "monthly", "total"}:
        raise HTTPException(400, "limitStrategy must be one of: daily, monthly, total")
    return strategy


# ── User Management ───────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: dict = Depends(require_admin),
):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.email, u.role, u.is_active, u.created_at, us.plan_id
            FROM users u
            LEFT JOIN user_subscriptions us ON us.user_id = u.id
            ORDER BY u.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, skip),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
        return {
            "users": [_fmt_user(dict(r)) for r in rows],
            "total": total,
            "skip": skip,
            "limit": limit,
        }


@router.post("/users", status_code=201)
async def create_user(req: CreateUserRequest, _admin: dict = Depends(require_admin)):
    import bcrypt
    email = req.email.lower().strip()
    with get_conn() as conn:
        if conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone():
            raise HTTPException(400, "Email already exists")
        user_id = str(uuid.uuid4())
        pw_hash = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO users (id, email, password_hash, role, is_active, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (user_id, email, pw_hash, req.role.upper(), True, now, now),
        )
        conn.execute("INSERT INTO pipeline_configs (id, user_id) VALUES (%s,%s)", (str(uuid.uuid4()), user_id))
        conn.execute(
            "INSERT INTO logs (id, user_id, event, detail, level) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), _admin["sub"], "admin.create_user", f"email={email}", "info"),
        )
        conn.commit()
    ensure_user_subscription(user_id)
    return {"id": user_id, "email": email, "role": req.role.upper()}


@router.patch("/users/{user_id}")
async def update_user(user_id: str, req: UserUpdate, _admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = %s", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        now = datetime.utcnow().isoformat()
        if req.isActive is not None:
            conn.execute("UPDATE users SET is_active=%s, updated_at=%s WHERE id=%s", (req.isActive, now, user_id))
        if req.role is not None:
            conn.execute("UPDATE users SET role=%s, updated_at=%s WHERE id=%s", (req.role.upper(), now, user_id))
        
        conn.execute(
            "INSERT INTO logs (id, user_id, event, detail, level) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), _admin["sub"], "admin.update_user", f"target={user_id}", "info"),
        )
        conn.commit()

    if req.planId is not None:
        set_user_plan(user_id=user_id, plan_id=req.planId, status="active")

    return {"status": "ok"}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, _admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM users WHERE id = %s", (user_id,)).fetchone():
            raise HTTPException(404, "User not found")
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.execute(
            "INSERT INTO logs (id, user_id, event, detail, level) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), _admin["sub"], "admin.delete_user", f"target={user_id}", "warn"),
        )
        conn.commit()


# ── Providers ─────────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers(_admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, enabled FROM provider_registry ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        return {"providers": [dict(r) for r in rows]}


@router.patch("/providers/{provider_id}")
async def update_provider(provider_id: str, req: ProviderUpdate, _admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM provider_registry WHERE id = %s", (provider_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Unknown provider: {provider_id}")

        conn.execute(
            "UPDATE provider_registry SET enabled=%s, updated_at=NOW() WHERE id=%s",
            (req.enabled, provider_id),
        )
        conn.execute(
            "INSERT INTO logs (id, user_id, event, detail, level) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), _admin["sub"], "admin.update_provider", f"provider={provider_id}, enabled={req.enabled}", "info"),
        )
        conn.commit()

    return {"provider": provider_id, "enabled": req.enabled}


# ── Models ───────────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models(_admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, model_id AS "modelId", provider_id AS provider, enabled
            FROM model_registry
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        return {"models": [dict(r) for r in rows]}


@router.patch("/models/{model_id:path}")
async def update_model(model_id: str, req: ModelUpdate, _admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, model_id, provider_id AS provider FROM model_registry WHERE id = %s",
            (model_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Model not found")

        conn.execute(
            "UPDATE model_registry SET enabled=%s, updated_at=NOW() WHERE id=%s",
            (req.enabled, model_id),
        )
        conn.execute(
            "INSERT INTO logs (id, user_id, event, detail, level) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), _admin["sub"], "admin.update_model", f"model={row['model_id']}, enabled={req.enabled}", "info"),
        )
        conn.commit()
        return {"id": model_id, "modelId": row["model_id"], "provider": row["provider"], "enabled": req.enabled}


@router.post("/models", status_code=201)
async def create_model(req: CreateModelRequest, _admin: dict = Depends(require_admin)):
    model_name = req.id.strip()
    provider_id = req.provider.strip()
    if not model_name:
        raise HTTPException(400, "Model id cannot be empty")

    with get_conn() as conn:
        provider = conn.execute(
            "SELECT id FROM provider_registry WHERE id = %s",
            (provider_id,),
        ).fetchone()
        if not provider:
            raise HTTPException(404, "Provider not found")

        existing = conn.execute(
            "SELECT id FROM model_registry WHERE provider_id = %s AND model_id = %s",
            (provider_id, model_name),
        ).fetchone()
        if existing:
            raise HTTPException(400, "Model already exists for this provider")

        next_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM model_registry"
        ).fetchone()["next_sort"]
        registry_id = f"{provider_id}:{model_name}"
        conn.execute(
            """
            INSERT INTO model_registry (id, model_id, provider_id, enabled, sort_order)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (registry_id, model_name, provider_id, req.enabled, next_sort),
        )
        conn.execute(
            "INSERT INTO logs (id, user_id, event, detail, level) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), _admin["sub"], "admin.create_model", f"model={model_name}, provider={provider_id}", "info"),
        )
        conn.commit()

    return {"id": registry_id, "modelId": model_name, "provider": provider_id, "enabled": req.enabled}


# ── Plans ────────────────────────────────────────────────────────────────────

@router.get("/plans")
async def list_subscription_plans(_admin: dict = Depends(require_admin)):
    plans = list_plans(active_only=False)
    payload = []
    for row in plans:
        payload.append(
            {
                "id": row["id"],
                "name": row.get("name", row["id"].title()),
                "description": row.get("description", "") or "",
                "provider": row["provider_id"],
                "model": row["model_id"],
                "limitStrategy": row.get("limit_strategy", "monthly") or "monthly",
                "dailyTokenLimit": int(row.get("daily_token_limit", 0) or 0),
                "totalTokenLimit": int(row.get("total_token_limit", 0) or 0),
                "monthlyPriceCents": int(row.get("monthly_price_cents", 0) or 0),
                "monthlyRequestLimit": int(row.get("monthly_request_limit", 0) or 0),
                "inputTokenPricePerMillion": float(row.get("input_token_price_per_million", 0) or 0),
                "outputTokenPricePerMillion": float(row.get("output_token_price_per_million", 0) or 0),
                "stripePriceId": row.get("stripe_price_id", "") or "",
                "active": bool(row.get("active", True)),
                "sortOrder": int(row.get("sort_order", 0) or 0),
                "apiKeyConfigured": bool(row.get("encrypted_api_key", "") or ""),
            }
        )
    return {"plans": payload}


@router.patch("/plans/{plan_id}")
async def update_subscription_plan(plan_id: str, req: PlanUpdate, _admin: dict = Depends(require_admin)):
    normalized_plan_id = plan_id.strip().lower()
    existing = get_plan(normalized_plan_id, active_only=False)
    if not existing:
        raise HTTPException(404, "Plan not found")

    with get_conn() as conn:
        provider_id = (req.provider or existing["provider_id"]).strip().lower()
        model_id = (req.model or existing["model_id"]).strip()
        stripe_price_id = _normalize_stripe_price_id(
            req.stripePriceId if req.stripePriceId is not None else existing.get("stripe_price_id", "")
        )
        limit_strategy = _normalize_limit_strategy(
            req.limitStrategy if req.limitStrategy is not None else existing.get("limit_strategy", "monthly")
        )
        daily_token_limit = int(req.dailyTokenLimit if req.dailyTokenLimit is not None else existing.get("daily_token_limit", 0) or 0)
        total_token_limit = int(req.totalTokenLimit if req.totalTokenLimit is not None else existing.get("total_token_limit", 0) or 0)

        provider_row = conn.execute(
            "SELECT id FROM provider_registry WHERE id = %s",
            (provider_id,),
        ).fetchone()
        if not provider_row:
            raise HTTPException(404, f"Unknown provider: {provider_id}")

        model_row = conn.execute(
            """
            SELECT id
            FROM model_registry
            WHERE provider_id = %s AND model_id = %s
            """,
            (provider_id, model_id),
        ).fetchone()
        if not model_row:
            raise HTTPException(404, f"Model '{model_id}' is not registered for provider '{provider_id}'")

        conn.execute(
            """
            UPDATE subscription_plans SET
                name = %s,
                description = %s,
                provider_id = %s,
                model_id = %s,
                limit_strategy = %s,
                daily_token_limit = %s,
                total_token_limit = %s,
                monthly_price_cents = %s,
                monthly_request_limit = %s,
                input_token_price_per_million = %s,
                output_token_price_per_million = %s,
                stripe_price_id = %s,
                active = %s,
                sort_order = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                (req.name if req.name is not None else existing.get("name", normalized_plan_id.title())).strip(),
                (req.description if req.description is not None else existing.get("description", "")).strip(),
                provider_id,
                model_id,
                limit_strategy,
                daily_token_limit,
                total_token_limit,
                int(req.monthlyPriceCents if req.monthlyPriceCents is not None else existing.get("monthly_price_cents", 0) or 0),
                int(req.monthlyRequestLimit if req.monthlyRequestLimit is not None else existing.get("monthly_request_limit", 0) or 0),
                float(req.inputTokenPricePerMillion if req.inputTokenPricePerMillion is not None else existing.get("input_token_price_per_million", 0) or 0),
                float(req.outputTokenPricePerMillion if req.outputTokenPricePerMillion is not None else existing.get("output_token_price_per_million", 0) or 0),
                stripe_price_id,
                bool(req.active if req.active is not None else existing.get("active", True)),
                int(req.sortOrder if req.sortOrder is not None else existing.get("sort_order", 0) or 0),
                normalized_plan_id,
            ),
        )
        conn.execute(
            "INSERT INTO logs (id, user_id, event, detail, level) VALUES (%s,%s,%s,%s,%s)",
            (
                str(uuid.uuid4()),
                _admin["sub"],
                "admin.update_plan",
                f"plan={normalized_plan_id}, provider={provider_id}, model={model_id}",
                "info",
            ),
        )
        conn.commit()

    if req.apiKey is not None:
        set_plan_api_key(normalized_plan_id, req.apiKey)

    updated = get_plan(normalized_plan_id, active_only=False)
    return {
        "plan": {
            "id": updated["id"],
            "name": updated.get("name", updated["id"].title()),
            "description": updated.get("description", "") or "",
            "provider": updated["provider_id"],
            "model": updated["model_id"],
            "limitStrategy": updated.get("limit_strategy", "monthly") or "monthly",
            "dailyTokenLimit": int(updated.get("daily_token_limit", 0) or 0),
            "totalTokenLimit": int(updated.get("total_token_limit", 0) or 0),
            "monthlyPriceCents": int(updated.get("monthly_price_cents", 0) or 0),
            "monthlyRequestLimit": int(updated.get("monthly_request_limit", 0) or 0),
            "inputTokenPricePerMillion": float(updated.get("input_token_price_per_million", 0) or 0),
            "outputTokenPricePerMillion": float(updated.get("output_token_price_per_million", 0) or 0),
            "stripePriceId": updated.get("stripe_price_id", "") or "",
            "active": bool(updated.get("active", True)),
            "sortOrder": int(updated.get("sort_order", 0) or 0),
            "apiKeyConfigured": bool(updated.get("encrypted_api_key", "") or ""),
        }
    }


# ── Pipeline Global Control ────────────────────────────────────────────────────

@router.get("/pipeline")
async def get_pipeline(_admin: dict = Depends(require_admin)):
    return _global_pipeline


@router.patch("/pipeline")
async def update_pipeline(req: PipelineGlobalUpdate, _admin: dict = Depends(require_admin)):
    _global_pipeline["selfHealingEnabled"] = req.selfHealingEnabled
    _global_pipeline["validationEnabled"] = req.validationEnabled
    
    # Audit log
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO logs (id, user_id, event, detail, level) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), _admin["sub"], "admin.update_pipeline", f"shealing={req.selfHealingEnabled}, valid={req.validationEnabled}", "info"),
        )
        conn.commit()
        
    return {"status": "ok", "pipeline": _global_pipeline}


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs")
async def get_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    level: str = Query("", description="Filter by level: info|warn|error"),
    _admin: dict = Depends(require_admin),
):
    with get_conn() as conn:
        if level:
            rows = conn.execute(
                "SELECT * FROM logs WHERE level=%s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (level, limit, skip),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS total FROM logs WHERE level=%s", (level,)).fetchone()["total"]
        else:
            rows = conn.execute(
                "SELECT * FROM logs ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, skip),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS total FROM logs").fetchone()["total"]
        return {"logs": [dict(r) for r in rows], "total": total}


# ── Metrics ───────────────────────────────────────────────────────────────────

@router.get("/metrics")
async def get_metrics(_admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
        active_users = conn.execute("SELECT COUNT(*) AS total FROM users WHERE is_active=TRUE").fetchone()["total"]
        admin_count = conn.execute("SELECT COUNT(*) AS total FROM users WHERE role='ADMIN'").fetchone()["total"]
        total_keys = conn.execute("SELECT COUNT(*) AS total FROM api_keys").fetchone()["total"]
        total_logs = conn.execute("SELECT COUNT(*) AS total FROM logs").fetchone()["total"]
        error_logs = conn.execute("SELECT COUNT(*) AS total FROM logs WHERE level='error'").fetchone()["total"]
        
        # User count by plan
        plan_counts = conn.execute(
            """
            SELECT plan_id, COUNT(*) as count 
            FROM user_subscriptions 
            GROUP BY plan_id
            """
        ).fetchall()
        
        provider_rows = conn.execute(
            "SELECT id, enabled FROM provider_registry ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        
        return {
            "users": {"total": total_users, "active": active_users, "admins": admin_count},
            "subscriptions": {row["plan_id"]: row["count"] for row in plan_counts},
            "api_keys": {"total": total_keys},
            "logs": {"total": total_logs, "errors": error_logs},
            "providers": {row["id"]: bool(row["enabled"]) for row in provider_rows},
            "pipeline": _global_pipeline,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_user(row: dict) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "isActive": bool(row["is_active"]),
        "planId": row.get("plan_id", "free") or "free",
        "createdAt": row["created_at"],
    }
