"""Admin router — user, provider, pipeline, logs, metrics management."""
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from ..db import get_conn
from ..auth.middleware import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ── Schemas ───────────────────────────────────────────────────────────────────

class UserUpdate(BaseModel):
    isActive: bool | None = None
    role: str | None = None

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


_global_pipeline = {"selfHealingEnabled": True, "validationEnabled": True}


# ── User Management ───────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: dict = Depends(require_admin),
):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email, role, is_active, created_at FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s",
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
        provider_rows = conn.execute(
            "SELECT id, enabled FROM provider_registry ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        return {
            "users": {"total": total_users, "active": active_users, "admins": admin_count},
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
        "createdAt": row["created_at"],
    }
