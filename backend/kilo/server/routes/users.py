"""Users router — API keys (BYOK) and pipeline configuration."""
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..db import get_conn
from ..auth.middleware import get_current_user
from ..auth.encryption import encrypt_key, decrypt_key

router = APIRouter(prefix="/api/users", tags=["users"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class AddApiKeyRequest(BaseModel):
    provider: str
    api_key: str
    label: str = ""


class UpdateProfileRequest(BaseModel):
    password: str


class PipelineConfigUpdate(BaseModel):
    clearSandboxEnabled: bool = True
    designSystemEnabled: bool = True
    systemPromptEnabled: bool = True
    builderEnabled: bool = True
    autoInstallEnabled: bool = True
    projectBuildEnabled: bool = True
    integrationTestEnabled: bool = False
    linterEnabled: bool = True
    runtimeEnabled: bool = True
    featureValidatorEnabled: bool = True
    selfHealingEnabled: bool = True
    summaryEnabled: bool = True
    useSharedModels: bool = True
    sharedModels: list[str] = []
    maxIter: int = 70
    maxHealingAttempts: int = 20
    activeMemoryEnabled: bool = True
    planningModels: list[str] = []
    architectureModels: list[str] = []
    frontendModels: list[str] = []
    backendModels: list[str] = []
    validationModels: list[str] = []


def _join_model_list(values: list[str]) -> str:
    return ",".join(v.strip() for v in values if v.strip())


def _split_model_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


# ── API Keys ──────────────────────────────────────────────────────────────────

@router.get("/api-keys")
async def list_keys(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, provider, label, created_at FROM api_keys WHERE user_id = %s ORDER BY provider ASC, created_at ASC, id ASC",
            (user["sub"],),
        ).fetchall()
        return {"keys": [dict(r) for r in rows]}


@router.post("/api-keys", status_code=201)
async def add_key(req: AddApiKeyRequest, user: dict = Depends(get_current_user)):
    if not req.api_key.strip():
        raise HTTPException(400, "api_key cannot be empty")
    with get_conn() as conn:
        key_id = str(uuid.uuid4())
        encrypted = encrypt_key(req.api_key.strip())
        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO api_keys (id, user_id, provider, encrypted_key, label, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (key_id, user["sub"], req.provider.lower(), encrypted, req.label, now),
        )
        conn.commit()
        return {"id": key_id, "provider": req.provider.lower(), "label": req.label, "created_at": now}


@router.delete("/api-keys/{key_id}", status_code=204)
async def delete_key(key_id: str, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM api_keys WHERE id = %s AND user_id = %s", (key_id, user["sub"])).fetchone()
        if not row:
            raise HTTPException(404, "Key not found")
        conn.execute("DELETE FROM api_keys WHERE id = %s", (key_id,))
        conn.commit()


@router.get("/api-keys/{key_id}/reveal")
async def reveal_key(key_id: str, user: dict = Depends(get_current_user)):
    """Return decrypted key for one-time display."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT encrypted_key, provider FROM api_keys WHERE id = %s AND user_id = %s",
            (key_id, user["sub"])
        ).fetchone()
        if not row:
            raise HTTPException(404, "Key not found")
        return {"provider": row["provider"], "key": decrypt_key(row["encrypted_key"])}


# ── Pipeline Config ───────────────────────────────────────────────────────────

@router.get("/pipeline")
async def get_pipeline(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM pipeline_configs WHERE user_id = %s", (user["sub"],)).fetchone()
        if not row:
            return _default_pipeline()
        r = dict(row)
        return {
            "clearSandboxEnabled": bool(r.get("clear_sandbox_enabled", True)),
            "designSystemEnabled": bool(r.get("design_system_enabled", True)),
            "systemPromptEnabled": bool(r.get("system_prompt_enabled", True)),
            "builderEnabled": bool(r.get("builder_enabled", True)),
            "autoInstallEnabled": bool(r.get("auto_install_enabled", True)),
            "projectBuildEnabled": bool(r.get("project_build_enabled", True)),
            "integrationTestEnabled": bool(r.get("integration_test_enabled", False)),
            "linterEnabled": bool(r.get("linter_enabled", True)),
            "runtimeEnabled": bool(r.get("runtime_enabled", True)),
            "featureValidatorEnabled": bool(r.get("feature_validator_enabled", True)),
            "selfHealingEnabled": bool(r["self_healing_enabled"]),
            "summaryEnabled": bool(r.get("summary_enabled", True)),
            "useSharedModels": bool(r.get("use_shared_models", True)),
            "sharedModels": _split_model_list(r.get("shared_models", "")),
            "maxIter": int(r.get("max_iter", 70)),
            "maxHealingAttempts": int(r.get("max_healing_attempts", 20)),
            "activeMemoryEnabled": bool(r.get("active_memory_enabled", True)),
            "planningModels": _split_model_list(r["planning_model"]),
            "architectureModels": _split_model_list(r["architecture_model"]),
            "frontendModels": _split_model_list(r["frontend_model"]),
            "backendModels": _split_model_list(r["backend_model"]),
            "validationModels": _split_model_list(r["validation_model"]),
        }


@router.put("/pipeline")
async def update_pipeline(req: PipelineConfigUpdate, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        now = datetime.utcnow().isoformat()
        existing = conn.execute("SELECT id FROM pipeline_configs WHERE user_id = %s", (user["sub"],)).fetchone()
        if existing:
            conn.execute("""
                UPDATE pipeline_configs SET
                    clear_sandbox_enabled=%s, design_system_enabled=%s, system_prompt_enabled=%s,
                    builder_enabled=%s, auto_install_enabled=%s,
                    project_build_enabled=%s, integration_test_enabled=%s, linter_enabled=%s,
                    runtime_enabled=%s, feature_validator_enabled=%s, self_healing_enabled=%s,
                    summary_enabled=%s,
                    use_shared_models=%s, shared_models=%s,
                    planning_model=%s, architecture_model=%s, frontend_model=%s,
                    backend_model=%s, validation_model=%s, max_iter=%s, max_healing_attempts=%s,
                    active_memory_enabled=%s, updated_at=%s
                WHERE user_id=%s
            """, (
                req.clearSandboxEnabled, req.designSystemEnabled, req.systemPromptEnabled,
                req.builderEnabled, req.autoInstallEnabled,
                req.projectBuildEnabled, req.integrationTestEnabled, req.linterEnabled,
                req.runtimeEnabled, req.featureValidatorEnabled, req.selfHealingEnabled,
                req.summaryEnabled,
                req.useSharedModels, _join_model_list(req.sharedModels),
                _join_model_list(req.planningModels), _join_model_list(req.architectureModels), _join_model_list(req.frontendModels),
                _join_model_list(req.backendModels), _join_model_list(req.validationModels), req.maxIter, req.maxHealingAttempts,
                req.activeMemoryEnabled, now, user["sub"],
            ))
        else:
            conn.execute("""
                INSERT INTO pipeline_configs (id, user_id, clear_sandbox_enabled, design_system_enabled,
                system_prompt_enabled, builder_enabled,
                auto_install_enabled, project_build_enabled, integration_test_enabled, linter_enabled,
                runtime_enabled, feature_validator_enabled, self_healing_enabled,
                summary_enabled,
                use_shared_models, shared_models,
                planning_model, architecture_model, frontend_model, backend_model, validation_model,
                max_iter, max_healing_attempts, active_memory_enabled, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                str(uuid.uuid4()), user["sub"],
                req.clearSandboxEnabled, req.designSystemEnabled, req.systemPromptEnabled,
                req.builderEnabled, req.autoInstallEnabled,
                req.projectBuildEnabled, req.integrationTestEnabled, req.linterEnabled,
                req.runtimeEnabled, req.featureValidatorEnabled, req.selfHealingEnabled,
                req.summaryEnabled,
                req.useSharedModels, _join_model_list(req.sharedModels),
                _join_model_list(req.planningModels), _join_model_list(req.architectureModels), _join_model_list(req.frontendModels),
                _join_model_list(req.backendModels), _join_model_list(req.validationModels), req.maxIter, req.maxHealingAttempts,
                req.activeMemoryEnabled, now,
            ))
        conn.commit()
    return {"status": "ok"}


# ── User Profile ──────────────────────────────────────────────────────────────

@router.put("/profile")
async def update_profile(req: UpdateProfileRequest, user: dict = Depends(get_current_user)):
    import bcrypt
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    with get_conn() as conn:
        pw_hash = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        now = datetime.utcnow().isoformat()
        conn.execute("UPDATE users SET password_hash=%s, updated_at=%s WHERE id=%s", (pw_hash, now, user["sub"]))
        conn.commit()
    return {"status": "ok"}


def _default_pipeline() -> dict:
    return {
        "clearSandboxEnabled": True, "designSystemEnabled": True, "systemPromptEnabled": True,
        "builderEnabled": True, "autoInstallEnabled": True,
        "projectBuildEnabled": True, "integrationTestEnabled": False, "linterEnabled": True,
        "runtimeEnabled": True, "featureValidatorEnabled": True, "selfHealingEnabled": True,
        "summaryEnabled": True,
        "useSharedModels": True, "sharedModels": [],
        "planningModels": [], "architectureModels": [], "frontendModels": [],
        "backendModels": [], "validationModels": [],
        "maxIter": 70, "maxHealingAttempts": 20, "activeMemoryEnabled": True
    }
