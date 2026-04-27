"""
API Route — /api/chat

New endpoint that wraps the Decision Layer around the existing generation path.
The existing POST /api/generate route is NOT modified.

Flow:
  POST /api/chat  →  DecisionRouter.route()
    → existing_generation_path  : returns {session_id, status} JSON (same as /api/generate)
    → normal_chat_path          : returns SSE token stream
    → project action (explain / modify / delete / …): returns SSE token stream
"""

from __future__ import annotations

import json
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ...decision_layer import DecisionRouter
from ...orchestrator.session_service import (
    cancel_other_user_generations,
    cancel_project_execution,
    hydrate_user_provider_keys,
    start_generation_task,
    validate_registry_selection,
)
from ...providers import get_provider, register_provider_keys
from ...providers.runtime_keys import get_runtime_key
from ...session.runtime import BuildSessionRuntime
from ...shared.design.engine import DesignEngine
from ...tools.registry import ToolRegistry
from ..billing import enforce_usage_limits, get_plan_api_key, get_user_plan_bundle, increment_request_usage
from ..auth.middleware import get_current_user_optional
from ..config import settings
from ..db import get_conn

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Sentinel prefix emitted by DecisionRouter when generation is started
_GENERATION_SENTINEL = "\x00GENERATION_STARTED:"


class ChatRequest(BaseModel):
    message: str
    provider: str = settings.DEFAULT_PROVIDER
    model: str = settings.DEFAULT_MODEL
    model_id: str = ""
    api_key: str = ""
    scraper_url: str = ""
    projectId: str = ""
    chat_history: list[dict] = []
    resume: bool = False
    plan_id: str = ""

    def resolved_model(self) -> str:
        return self.model_id.strip() or self.model.strip()


@router.post("")
async def chat(req: ChatRequest, current_user: dict = Depends(get_current_user_optional)):
    """
    Decision-Layer-powered chat endpoint.

    - If the Decision Layer routes to 'existing_generation_path', returns the same
      JSON as POST /api/generate so the frontend can transparently subscribe to logs.
    - Otherwise, returns an SSE stream with token chunks and a final 'done' event.
    """

    # ── Resolve API key (mirrors generate.py logic exactly) ───────────
    explicit_fields = set(getattr(req, "model_fields_set", set()) or getattr(req, "__fields_set__", set()) or set())
    explicit_api_key_supplied = "api_key" in explicit_fields
    api_key = req.api_key.strip()
    pipeline_config: dict = {}
    user_provider_keys: dict[str, str] = {}
    resolved_provider = req.provider
    resolved_model = req.resolved_model()
    selected_plan = None
    byok_mode = bool(current_user and req.plan_id == "byok")

    if current_user:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_configs WHERE user_id=%s",
                (current_user["sub"],),
            ).fetchone()
        if row:
            pipeline_config = dict(row)
        user_provider_keys = hydrate_user_provider_keys(current_user["sub"])
        if byok_mode:
            selected_plan = None
            resolved_provider = req.provider
            resolved_model = req.resolved_model()
        else:
            plan_bundle = get_user_plan_bundle(current_user["sub"], req.plan_id)
            selected_plan = plan_bundle["selected_plan"]
            resolved_provider = selected_plan["provider_id"]
            resolved_model = selected_plan["model_id"]
            enforce_usage_limits(current_user["sub"], selected_plan)

    key_name_map = {
        "groq": "GROQ_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "scraper": "SCRAPER_API_KEY",
    }
    key_env_name = key_name_map.get(resolved_provider, f"{resolved_provider.upper()}_API_KEY")

    if current_user:
        if selected_plan:
            api_key = get_plan_api_key(selected_plan).strip()
            if not api_key:
                raise HTTPException(
                    400,
                    (
                        f"No admin API key configured for plan '{selected_plan.get('name', selected_plan.get('id', 'plan'))}'. "
                        "Ask admin to add the plan API key in Admin > Plans."
                    ),
                )
        elif not api_key:
            api_key = user_provider_keys.get(resolved_provider, "").strip()
            if byok_mode and not api_key:
                raise HTTPException(
                    400,
                    (
                        f"No BYOK key found for provider '{resolved_provider}'. "
                        "Add your provider key in Dashboard > Settings > API Keys."
                    ),
                )
        if not api_key and not byok_mode:
            runtime_key = get_runtime_key(key_env_name)
            if runtime_key:
                api_key = runtime_key
            else:
                api_key = str(getattr(settings, key_env_name, "") or "").strip()
    else:
        if not explicit_api_key_supplied and not api_key:
            runtime_key = get_runtime_key(key_env_name)
            if runtime_key:
                api_key = runtime_key
            else:
                api_key = str(getattr(settings, key_env_name, "") or "").strip()
        # If explicit, use as-is

    if api_key and resolved_provider not in ("scraper", "auto"):
        register_provider_keys(resolved_provider, api_key)

    validate_registry_selection(
        resolved_provider,
        resolved_model if not byok_mode else "",
        require_registered_model=not byok_mode,
    )

    try:
        provider = get_provider(resolved_provider, api_key, scraper_url=req.scraper_url or settings.SCRAPER_URL)
    except ValueError:
        # Graceful degradation: use a stub provider that returns a polite error
        provider = _NoKeyProvider(resolved_provider)

    if current_user and selected_plan:
        increment_request_usage(current_user["sub"], 1)

    # ── Resolve project / sandbox ─────────────────────────────────────
    session_id = req.projectId.strip()
    sandbox = ""
    if session_id:
        sandbox = os.path.join(settings.SANDBOX_BASE_DIR, session_id)

    # ── Build the generate_fn callback (delegates to existing pipeline) ─
    async def _generate_fn(prompt: str, target_files: list[str] | None = None) -> dict:
        """Start a generation task exactly as /api/generate does."""
        nonlocal session_id, sandbox

        resolve_session_id = session_id
        if resolve_session_id and current_user:
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT id FROM projects WHERE id=%s AND user_id=%s",
                    (resolve_session_id, current_user["sub"]),
                ).fetchone()
                if not row:
                    resolve_session_id = ""

        if not resolve_session_id and current_user:
            resolve_session_id = str(uuid.uuid4())
            with get_conn() as conn:
                name = (prompt[:30] + "...") if len(prompt) > 30 else prompt
                conn.execute(
                    "INSERT INTO projects (id, user_id, name, status) VALUES (%s, %s, %s, 'GENERATING')",
                    (resolve_session_id, current_user["sub"], name or "Chat Project"),
                )
                conn.commit()
        elif not resolve_session_id:
            resolve_session_id = f"project_local_{uuid.uuid4().hex[:8]}"

        resolve_sandbox = os.path.join(settings.SANDBOX_BASE_DIR, resolve_session_id)
        os.makedirs(resolve_sandbox, exist_ok=True)

        pipeline_config["_request_provider"] = resolved_provider
        pipeline_config["_request_model"] = resolved_model
        pipeline_config["_request_api_key"] = api_key
        pipeline_config["_request_scraper_url"] = req.scraper_url or settings.SCRAPER_URL
        pipeline_config["_user_provider_keys"] = user_provider_keys
        pipeline_config["_selected_plan_id"] = req.plan_id if req.plan_id == "byok" else (selected_plan or {}).get("id", "")
        if current_user:
            pipeline_config["user_id"] = current_user["sub"]
        pipeline_config["target_files_override"] = target_files or []

        if req.resume:
            log_path = os.path.join(resolve_sandbox, ".lovable", "build.log")
            try:
                from ..orchestrator.session_service import resume_iteration_from_log
                pipeline_config["resume_iteration"] = resume_iteration_from_log(log_path)
            except Exception:
                pass
            pipeline_config["clear_sandbox_enabled"] = False

        await cancel_project_execution(resolve_session_id, resolve_sandbox, status_after_cancel=None, narration="")
        if current_user:
            await cancel_other_user_generations(current_user["sub"], resolve_session_id)

        session_runtime = BuildSessionRuntime(
            provider=provider,
            tool_registry=ToolRegistry(base_dir=resolve_sandbox),
            design_engine=DesignEngine(),
            model_id=resolved_model,
            pipeline_config=pipeline_config,
        )
        start_generation_task(session_runtime, prompt, resolve_session_id, resolve_sandbox, resume=req.resume)
        return {"session_id": resolve_session_id, "status": "GENERATING"}

    # ── Build router and run ──────────────────────────────────────────
    decision_router = DecisionRouter(
        provider=provider,
        model_id=resolved_model,
        sandbox_dir=sandbox,
        generate_fn=_generate_fn,
    )

    # Collect the first chunk to detect generation vs. streaming
    first_chunk: str | None = None
    first_chunk_is_generation = False
    generation_session_id = ""
    generation_status = ""

    async def _collect_and_stream():
        nonlocal first_chunk, first_chunk_is_generation, generation_session_id, generation_status

        async for chunk in decision_router.route(
            req.message,
            project_id=session_id,
            chat_history=req.chat_history,
        ):
            # Detect the generation sentinel
            if chunk.startswith(_GENERATION_SENTINEL):
                parts = chunk[len(_GENERATION_SENTINEL):].split(":")
                generation_session_id = parts[0] if parts else ""
                generation_status = parts[1] if len(parts) > 1 else "GENERATING"
                first_chunk_is_generation = True
                return

            # Stream all other chunks as SSE tokens
            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    # We need to peek at the first event to decide response type.
    # Build a generator and eagerly execute it.
    gen = _collect_and_stream()
    chunks_buffer: list[str] = []

    try:
        first = await anext(gen)
        chunks_buffer.append(first)
    except StopAsyncIteration:
        pass

    if first_chunk_is_generation and not chunks_buffer:
        # Pure generation path — return JSON exactly like /api/generate
        return JSONResponse({"session_id": generation_session_id, "status": generation_status})

    # Streaming path — replay buffered chunks and continue
    async def _replay_then_stream():
        for c in chunks_buffer:
            yield c
        if not first_chunk_is_generation:
            async for c in gen:
                yield c

    return StreamingResponse(
        _replay_then_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ---------------------------------------------------------------------------
# Stub provider — used when no API key is configured
# ---------------------------------------------------------------------------

class _NoKeyProvider:
    """
    Fallback provider used when no API key is available.
    Returns a user-friendly error message instead of crashing.
    """

    def __init__(self, provider_name: str) -> None:
        self._name = provider_name

    async def stream(self, messages, model_id):
        msg = (
            f"⚠️ No API key configured for provider '{self._name}'. "
            "Please add your key in Dashboard → Settings → API Keys."
        )
        for word in msg.split():
            yield word + " "
