import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...orchestrator.session_service import (
    cancel_other_user_generations,
    cancel_project_execution,
    hydrate_user_provider_keys,
    iter_project_logs,
    resume_iteration_from_log,
    start_generation_task,
    validate_registry_selection,
)
from ...providers import get_provider, register_provider_keys
from ...providers.runtime_keys import get_runtime_key
from ...session.runtime import BuildSessionRuntime
from ...shared.design.engine import DesignEngine
from ...tools.registry import ToolRegistry
from ..auth.middleware import get_current_user, get_current_user_optional
from ..config import settings
from ..db import get_conn

router = APIRouter(prefix="/api/generate", tags=["generate"])


class GenerateRequest(BaseModel):
    prompt: str
    provider: str = settings.DEFAULT_PROVIDER
    model: str = settings.DEFAULT_MODEL
    model_id: str = ""
    api_key: str = ""
    scraper_url: str = ""
    projectId: str = ""
    resume: bool = False

    def resolved_model(self) -> str:
        return self.model_id.strip() or self.model.strip()


@router.post("")
async def generate(req: GenerateRequest, current_user: dict = Depends(get_current_user_optional)):
    explicit_fields = set(getattr(req, "model_fields_set", set()) or getattr(req, "__fields_set__", set()) or set())
    explicit_api_key_supplied = "api_key" in explicit_fields

    api_key = req.api_key.strip()
    key_source = "explicit_request" if explicit_api_key_supplied else "unset"
    pipeline_config = None
    user_provider_keys: dict[str, str] = {}
    if current_user:
        with get_conn() as conn:
            pipeline_config = conn.execute(
                "SELECT * FROM pipeline_configs WHERE user_id=%s",
                (current_user["sub"],),
            ).fetchone()
        user_provider_keys = hydrate_user_provider_keys(current_user["sub"])

    pipeline_config = dict(pipeline_config) if pipeline_config else {}

    key_name_map = {
        "groq": "GROQ_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "scraper": "SCRAPER_API_KEY",
    }
    key_env_name = key_name_map.get(req.provider, f"{req.provider.upper()}_API_KEY")

    if current_user:
        api_key = user_provider_keys.get(req.provider, "").strip()
        key_source = "user_db" if api_key else "none"
    else:
        if not explicit_api_key_supplied and not api_key:
            runtime_key = get_runtime_key(key_env_name)
            if runtime_key:
                api_key = runtime_key
                key_source = "runtime_settings"
            else:
                api_key = str(getattr(settings, key_env_name, "") or "").strip()
                key_source = "server_env" if api_key else "none"
        elif explicit_api_key_supplied:
            key_source = "explicit_request"

    if not api_key and req.provider not in ("scraper", "auto"):
        if current_user:
            raise HTTPException(400, f"No stored API keys found for {req.provider}. Add keys in Dashboard > API Keys.")
        if explicit_api_key_supplied:
            raise HTTPException(400, f"Explicit API key override was empty for {req.provider}.")
        raise HTTPException(400, f"No API key provided for {req.provider}")

    validate_registry_selection(req.provider, req.resolved_model())

    try:
        provider = get_provider(req.provider, api_key, scraper_url=req.scraper_url or settings.SCRAPER_URL)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    session_id = req.projectId.strip()
    if session_id and current_user:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM projects WHERE id=%s AND user_id=%s",
                (session_id, current_user["sub"]),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Project not found")
            conn.execute(
                "UPDATE projects SET updated_at=NOW(), status='GENERATING', error_message='', last_narration=%s WHERE id=%s",
                ("Resuming build from existing files." if req.resume else "Starting build.", session_id),
            )
            conn.commit()
    elif not session_id and current_user:
        session_id = str(uuid.uuid4())
        with get_conn() as conn:
            name = (req.prompt[:30] + "...") if len(req.prompt) > 30 else req.prompt
            if not name.strip():
                name = "Untitled Project"
            conn.execute(
                "INSERT INTO projects (id, user_id, name, status) VALUES (%s, %s, %s, 'GENERATING')",
                (session_id, current_user["sub"], name),
            )
            conn.commit()
    else:
        if not session_id:
            session_id = f"project_local_{uuid.uuid4().hex[:8]}"

    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, session_id)
    os.makedirs(sandbox, exist_ok=True)
    log_path = os.path.join(sandbox, ".lovable", "build.log")

    cancelled_other_builds = 0
    if current_user:
        cancelled_other_builds = await cancel_other_user_generations(current_user["sub"], session_id)

    if api_key and req.provider not in ("scraper", "auto"):
        register_provider_keys(req.provider, api_key)

    await cancel_project_execution(session_id, sandbox, status_after_cancel=None, narration="")

    if req.resume:
        pipeline_config["clear_sandbox_enabled"] = False
        pipeline_config["resume_iteration"] = resume_iteration_from_log(log_path)

    pipeline_config["_request_provider"] = req.provider
    pipeline_config["_request_model"] = req.resolved_model()
    pipeline_config["_request_api_key"] = api_key
    pipeline_config["_request_scraper_url"] = req.scraper_url or settings.SCRAPER_URL
    pipeline_config["_user_provider_keys"] = user_provider_keys
    pipeline_config["_resolved_key_source"] = key_source
    pipeline_config["_resolved_key_count"] = len([key for key in api_key.split(",") if key.strip()])
    pipeline_config["_auto_cancelled_builds"] = cancelled_other_builds

    session_runtime = BuildSessionRuntime(
        provider=provider,
        tool_registry=ToolRegistry(base_dir=sandbox),
        design_engine=DesignEngine(),
        model_id=req.resolved_model(),
        pipeline_config=pipeline_config,
    )

    start_generation_task(session_runtime, req.prompt, session_id, sandbox, resume=req.resume)
    return {"session_id": session_id, "status": "GENERATING"}


@router.post("/{project_id}/cancel")
async def cancel_generation(project_id: str, current_user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id=%s AND user_id=%s",
            (project_id, current_user["sub"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, project_id)
    stopped = await cancel_project_execution(
        project_id,
        sandbox,
        status_after_cancel="CANCELLED",
        narration="Build cancelled by user.",
    )
    return {"success": True, "stopped": stopped}


@router.get("/{project_id}/logs")
async def get_logs(project_id: str, current_user: dict = Depends(get_current_user_optional), from_end: bool = False, last_event_id: str = Header(default="", alias="Last-Event-ID")):
    sandbox = os.path.join(settings.SANDBOX_BASE_DIR, project_id)
    log_path = os.path.join(sandbox, ".lovable", "build.log")

    # Parse byte offset from Last-Event-ID header (sent automatically by browser on SSE reconnect)
    byte_offset = 0
    if last_event_id:
        try:
            byte_offset = int(last_event_id)
        except (ValueError, TypeError):
            byte_offset = 0

    return StreamingResponse(
        iter_project_logs(project_id, sandbox, log_path, from_end=from_end, byte_offset=byte_offset),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
