"""Settings router — manage provider API keys + multi-key rotation."""

from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..db import get_conn
from ..auth.middleware import get_current_user
from ...providers.key_manager import key_manager
from ...providers.runtime_keys import RUNTIME_KEYS, get_runtime_key, set_runtime_key, snapshot_runtime_keys
from ..config import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])
_runtime_keys = RUNTIME_KEYS


class ProviderSettings(BaseModel):
    provider: str
    api_key: str = ""
    base_url: str = ""
    scraper_url: str = ""


class UpdateProfileRequest(BaseModel):
    password: str


class KeysPayload(BaseModel):
    # Single-key fields (backward compat)
    groq_key: Optional[str] = None
    anthropic_key: Optional[str] = None
    openai_key: Optional[str] = None
    scraper_url: Optional[str] = None
    scraper_key: Optional[str] = None
    # Feature 3: multi-key array support
    groq_keys: list[str] = []
    anthropic_keys: list[str] = []
    openai_keys: list[str] = []
    openrouter_keys: list[str] = []


@router.get("")
async def get_settings():
    return {
        "default_provider": settings.DEFAULT_PROVIDER,
        "default_model": settings.DEFAULT_MODEL,
        "providers": {
            "groq": {"configured": bool(settings.GROQ_API_KEY or get_runtime_key("GROQ_API_KEY"))},
            "anthropic": {"configured": bool(settings.ANTHROPIC_API_KEY or get_runtime_key("ANTHROPIC_API_KEY"))},
            "openai": {"configured": bool(settings.OPENAI_API_KEY or get_runtime_key("OPENAI_API_KEY"))},
            "openrouter": {"configured": bool(settings.OPENROUTER_API_KEY or get_runtime_key("OPENROUTER_API_KEY"))},
            "scraper": {
                "configured": bool(settings.SCRAPER_URL or get_runtime_key("SCRAPER_URL")),
                "url": get_runtime_key("SCRAPER_URL") or settings.SCRAPER_URL,
            },
        },
    }


@router.get("/stats")
async def get_stats(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM projects WHERE user_id=%s", (user["sub"],)).fetchone()["count"]
        done = conn.execute("SELECT COUNT(*) FROM projects WHERE user_id=%s AND status='COMPLETED'", (user["sub"],)).fetchone()["count"]
        failed = conn.execute("SELECT COUNT(*) FROM projects WHERE user_id=%s AND status='FAILED'", (user["sub"],)).fetchone()["count"]
        progress = conn.execute("SELECT COUNT(*) FROM projects WHERE user_id=%s AND status IN ('GENERATING', 'IDLE')", (user["sub"],)).fetchone()["count"]
        
        # Determine github connection from user table
        github = conn.execute("SELECT github_username, github_connected FROM users WHERE id=%s", (user["sub"],)).fetchone()
        
        return {
            "total": total,
            "done": done,
            "failed": failed,
            "progress": progress,
            "github_username": github["github_username"] if github else "",
            "github_connected": github["github_connected"] if github else False,
        }



@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute("SELECT id, email, github_username, github_connected FROM users WHERE id=%s", (user["sub"],)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        return dict(row)


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


@router.post("/keys")
async def save_keys(payload: KeysPayload):
    """Save API keys to runtime store + key_manager rotation pool."""

    def sync_keys(provider: str, env_name: str, values: list[str]):
        valid = [k for k in values if k.strip()]
        if valid:
            key_manager.add_keys(provider, valid)
            set_runtime_key(env_name, ",".join(valid))
        else:
            key_manager._keys.pop(provider, None)
            key_manager._idx.pop(provider, None)
            set_runtime_key(env_name, "")

    # ── Single-key backward compat ─────────────────────────────────────────
    if payload.groq_key:
        set_runtime_key("GROQ_API_KEY", payload.groq_key)
        key_manager.add_keys("groq", [payload.groq_key])

    if payload.anthropic_key:
        set_runtime_key("ANTHROPIC_API_KEY", payload.anthropic_key)
        key_manager.add_keys("anthropic", [payload.anthropic_key])

    if payload.openai_key:
        set_runtime_key("OPENAI_API_KEY", payload.openai_key)
        key_manager.add_keys("openai", [payload.openai_key])

    if payload.scraper_url:
        set_runtime_key("SCRAPER_URL", payload.scraper_url)

    if payload.scraper_key:
        set_runtime_key("SCRAPER_API_KEY", payload.scraper_key)

    # ── Feature 3: Multi-key arrays ────────────────────────────────────────
    sync_keys("groq", "GROQ_API_KEY", payload.groq_keys)
    sync_keys("anthropic", "ANTHROPIC_API_KEY", payload.anthropic_keys)
    sync_keys("openai", "OPENAI_API_KEY", payload.openai_keys)
    sync_keys("openrouter", "OPENROUTER_API_KEY", payload.openrouter_keys)

    return {"status": "ok", "saved": list(snapshot_runtime_keys().keys())}


@router.get("/keys/status")
async def get_keys_status():
    """Return key_manager rotation status for all providers."""
    return {
        "providers": key_manager.get_status(),
        "scraper_url": get_runtime_key("SCRAPER_URL", settings.SCRAPER_URL or ""),
        "scraper_configured": bool(get_runtime_key("SCRAPER_API_KEY") or settings.SCRAPER_URL),
    }
