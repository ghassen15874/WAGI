from fastapi import APIRouter, Body

from ...providers import (
    AnthropicProvider,
    GroqProvider,
    OpenAICompatibleProvider,
    ScraperProvider,
    register_provider_keys,
    resolve_provider_api_key,
)
from ...providers.runtime_keys import get_runtime_key
from ..db import get_conn

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def list_providers():
    with get_conn() as conn:
        provider_rows = conn.execute(
            """
            SELECT id, name
            FROM provider_registry
            WHERE enabled = TRUE
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        model_rows = conn.execute(
            """
            SELECT model_id, provider_id
            FROM model_registry
            WHERE enabled = TRUE
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()

    models_by_provider: dict[str, list[str]] = {}
    for row in model_rows:
        models_by_provider.setdefault(row["provider_id"], []).append(row["model_id"])

    providers = []
    for row in provider_rows:
        models = models_by_provider.get(row["id"], [])
        if row["id"] != "auto" and not models:
            continue
        providers.append({
            "id": row["id"],
            "name": row["name"],
            "models": models,
        })

    return {"providers": providers}


@router.get("/test")
@router.post("/test")
async def test_provider(
    provider: str | None = None,
    model_id: str = "",
    payload: dict | None = Body(default=None),
):
    """Test if a provider is reachable. Works with GET or POST."""
    try:
        provider = provider or (payload or {}).get("provider", "")
        model_id = model_id or (payload or {}).get("model_id", "") or (payload or {}).get("model", "")
        api_key = (payload or {}).get("api_key", "")
        scraper_url = (payload or {}).get("scraper_url", "")

        if provider == "groq":
            if api_key:
                register_provider_keys("groq", api_key)
            key = resolve_provider_api_key("groq", api_key)
            if not key:
                return {"status": "error", "message": "No Groq key in .env"}
            result = ""
            async for t in GroqProvider(key).stream(
                [{"role": "user", "content": "Reply with exactly: ok"}],
                model_id or "llama-3.3-70b-versatile"
            ):
                result += t
                if len(result) > 3:
                    break
            return {"status": "ok", "provider": "groq", "preview": result[:50]}

        if provider == "scraper":
            import os
            url = scraper_url or get_runtime_key("SCRAPER_URL") or os.getenv("SCRAPER_URL", "http://localhost:5300")
            key = api_key or get_runtime_key("SCRAPER_API_KEY") or os.getenv("SCRAPER_API_KEY", "your-secret-key-1")
            ScraperProvider(api_key=key, scraper_url=url)
            return {
                "status": "ok",
                "provider": "scraper",
                "message": "online",
            }

        if provider == "openai":
            if api_key:
                register_provider_keys("openai", api_key)
            key = resolve_provider_api_key("openai", api_key)
            if not key:
                return {"status": "error", "message": "No OpenAI key"}
            result = ""
            async for t in OpenAICompatibleProvider(key).stream(
                [{"role": "user", "content": "Reply with exactly: ok"}],
                model_id or "gpt-4o-mini"
            ):
                result += t
                if len(result) > 3:
                    break
            return {"status": "ok", "provider": "openai", "preview": result[:50]}

        if provider == "anthropic":
            if api_key:
                register_provider_keys("anthropic", api_key)
            key = resolve_provider_api_key("anthropic", api_key)
            if not key:
                return {"status": "error", "message": "No Anthropic key"}
            result = ""
            async for t in AnthropicProvider(key).stream(
                [{"role": "user", "content": "Reply with exactly: ok"}],
                model_id or "claude-3-5-haiku-latest"
            ):
                result += t
                if len(result) > 3:
                    break
            return {"status": "ok", "provider": "anthropic", "preview": result[:50]}

        if provider == "openrouter":
            if api_key:
                register_provider_keys("openrouter", api_key)
            key = resolve_provider_api_key("openrouter", api_key)
            if not key:
                return {"status": "error", "message": "No OpenRouter key"}
            result = ""
            async for t in OpenAICompatibleProvider(key, "https://openrouter.ai/api/v1", provider_name="openrouter").stream(
                [{"role": "user", "content": "Reply with exactly: ok"}],
                model_id or "anthropic/claude-3.5-sonnet"
            ):
                result += t
                if len(result) > 3:
                    break
            return {"status": "ok", "provider": "openrouter", "preview": result[:50]}

        if provider == "deepseek":
            if api_key:
                register_provider_keys("deepseek", api_key)
            key = resolve_provider_api_key("deepseek", api_key)
            if not key:
                return {"status": "error", "message": "No DeepSeek key"}
            result = ""
            async for t in OpenAICompatibleProvider(key, "https://api.deepseek.com/v1", provider_name="deepseek").stream(
                [{"role": "user", "content": "Reply with exactly: ok"}],
                model_id or "deepseek-chat"
            ):
                result += t
                if len(result) > 3:
                    break
            return {"status": "ok", "provider": "deepseek", "preview": result[:50]}

        if provider == "auto":
            import os
            groq_key = os.getenv("GROQ_API_KEY", "")
            scraper_url = os.getenv("SCRAPER_URL", "")
            return {
                "status": "ok",
                "provider": "auto",
                "groq_available": bool(groq_key),
                "scraper_url": scraper_url,
                "message": "Auto mode active",
            }

        return {"status": "error", "message": f"Unknown provider: {provider}"}

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "provider": provider,
            "message": str(e),
            "type": type(e).__name__,
            "detail": traceback.format_exc()[-300:],
        }
