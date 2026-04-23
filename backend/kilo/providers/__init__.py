# Provider models — Groq, Anthropic, OpenAI-compatible, Scraper
# Each implements provider.stream(messages, model_id) -> AsyncIterator[str]

import json
import asyncio
import os
import re
import aiohttp
from dataclasses import dataclass
from typing import AsyncIterator, Iterable

from .key_manager import key_manager
from .runtime_keys import get_runtime_key, get_runtime_keys

PROVIDER_ENV_VARS = {
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

KNOWN_PROVIDER_NAMES = set(PROVIDER_ENV_VARS) | {"auto", "scraper"}
PROVIDER_STATUS_PREFIXES = (
    "🔑 Groq key pool active:",
    "↪️ Groq 429 on key",
    "🔁 Groq rotation restarted from the first key.",
    "⏳ All Groq keys are rate-limited.",
    "⏳ Groq cooldown:",
    "📉 Groq token budget adjusted:",
)


def normalize_provider_name(provider_name: str) -> str:
    return provider_name.replace("_API_KEY", "").strip().lower()


def is_provider_status_token(token: str) -> bool:
    text = str(token or "").lstrip()
    return any(text.startswith(prefix) for prefix in PROVIDER_STATUS_PREFIXES)


def _runtime_key_store() -> dict[str, str]:
    return get_runtime_keys()


def register_provider_keys(provider_name: str, raw_keys: str | Iterable[str]) -> list[str]:
    provider_slug = normalize_provider_name(provider_name)
    if isinstance(raw_keys, str):
        keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    else:
        keys = [str(k).strip() for k in raw_keys if str(k).strip()]

    if keys and provider_slug in PROVIDER_ENV_VARS:
        key_manager.add_keys(provider_slug, keys)
    return keys


def get_provider_key_source(provider_name: str, explicit_api_key: str = "") -> str:
    provider_slug = normalize_provider_name(provider_name)
    env_var = PROVIDER_ENV_VARS.get(provider_slug)

    if explicit_api_key:
        register_provider_keys(provider_slug, explicit_api_key)
        return explicit_api_key

    if not env_var:
        return ""

    runtime_keys = _runtime_key_store()
    raw_value = runtime_keys.get(env_var) or os.getenv(env_var, "")
    if raw_value:
        register_provider_keys(provider_slug, raw_value)
    return raw_value


def resolve_provider_api_key(provider_name: str, explicit_api_key: str = "") -> str:
    provider_slug = normalize_provider_name(provider_name)
    env_var = PROVIDER_ENV_VARS.get(provider_slug)
    get_provider_key_source(provider_slug, explicit_api_key)

    if env_var:
        return get_key(env_var)
    return explicit_api_key.strip()


def registered_key_count(provider_name: str, explicit_api_key: str = "") -> int:
    provider_slug = normalize_provider_name(provider_name)
    get_provider_key_source(provider_slug, explicit_api_key)
    return len(key_manager._keys.get(provider_slug, []))


def is_auth_error(error: Exception | str) -> bool:
    err_str = str(error).lower()
    return any(token in err_str for token in ("401", "unauthorized", "invalid api key", "auth failed", "authentication"))


def is_rate_limit_error(error: Exception | str) -> bool:
    err_str = str(error).lower()
    return any(token in err_str for token in ("429", "rate limit", "too many requests"))


def _approximate_message_tokens(messages: list[dict]) -> int:
    total = 0
    for message in messages:
        content = message.get("content", "") or ""
        if isinstance(content, list):
            content = " ".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        total += max(1, len(str(content)) // 4)
        total += 8
    return total


@dataclass(frozen=True)
class ModelCandidate:
    provider: str
    model: str


def parse_model_candidates(
    raw_models: str | list[str] | None,
    default_provider: str,
    fallback_model: str = "",
) -> list[ModelCandidate]:
    if isinstance(raw_models, list):
        tokens = [str(item).strip() for item in raw_models if str(item).strip()]
    else:
        raw = str(raw_models or "")
        tokens = [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]

    candidates: list[ModelCandidate] = []
    seen: set[tuple[str, str]] = set()

    for token in tokens:
        provider = normalize_provider_name(default_provider)
        model = token

        if ":" in token:
            maybe_provider, maybe_model = token.split(":", 1)
            if normalize_provider_name(maybe_provider) in KNOWN_PROVIDER_NAMES and maybe_model.strip():
                provider = normalize_provider_name(maybe_provider)
                model = maybe_model.strip()

        key = (provider, model)
        if model and key not in seen:
            seen.add(key)
            candidates.append(ModelCandidate(provider=provider, model=model))

    fallback_key = (normalize_provider_name(default_provider), fallback_model.strip())
    if fallback_model.strip() and fallback_key not in seen:
        candidates.append(ModelCandidate(provider=fallback_key[0], model=fallback_key[1]))

    return candidates


def get_key(name: str) -> str:
    """
    Priority: settings page runtime keys → key_manager rotation → env var.
    """
    provider_name = name.replace("_API_KEY", "").lower()

    # 1. Sync runtime keys into key_manager
    val = get_runtime_key(name)
    if val:
        keys = [k.strip() for k in val.split(",") if k.strip()]
        if keys:
            current_keys = key_manager._keys.get(provider_name, [])
            if set(keys) != set(current_keys):
                key_manager.add_keys(provider_name, keys)

    # 2. Get rotated key
    rotated = key_manager.get_key(provider_name)
    if rotated:
        return rotated

    # 3. Fallback to raw env var if key_manager has zero configured keys
    if not key_manager._keys.get(provider_name):
        return os.getenv(name, "")
        
    return ""


class BaseProvider:
    """Base class for all LLM providers."""

    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        raise NotImplementedError


class GroqProvider(BaseProvider):
    """Groq API provider — primary free provider for fast inference."""
    provider_name = "groq"

    def __init__(self, api_key: str, wait_on_rate_limit: bool = True):
        self.api_key = api_key
        self.base_url = "https://api.groq.com/openai/v1"
        self.wait_on_rate_limit = wait_on_rate_limit
        self.tpm_limit = 12000
        self.min_completion_tokens = 256

    def _planned_max_tokens(self, messages: list[dict], requested_max_tokens: int = 8192) -> int:
        prompt_tokens = _approximate_message_tokens(messages)
        available = self.tpm_limit - prompt_tokens - 512
        if available <= self.min_completion_tokens:
            return self.min_completion_tokens
        return max(self.min_completion_tokens, min(requested_max_tokens, available))

    def _parse_tpm_limit_error(self, error: str) -> tuple[int | None, int | None]:
        limit_match = re.search(r"limit\s+(\d+)", error, re.IGNORECASE)
        requested_match = re.search(r"requested\s+(\d+)", error, re.IGNORECASE)
        limit = int(limit_match.group(1)) if limit_match else None
        requested = int(requested_match.group(1)) if requested_match else None
        return limit, requested

    def _adjusted_max_tokens_from_error(
        self,
        messages: list[dict],
        current_max_tokens: int,
        error: str,
    ) -> int | None:
        limit, requested = self._parse_tpm_limit_error(error)
        if limit and requested and requested > limit:
            over_by = requested - limit
            candidate = max(self.min_completion_tokens, current_max_tokens - over_by - 256)
            if candidate < current_max_tokens:
                return candidate

        candidate = self._planned_max_tokens(messages, current_max_tokens // 2)
        if candidate < current_max_tokens:
            return candidate
        return None

    def _is_tpm_budget_error(self, error: str) -> bool:
        lowered = str(error or "").lower()
        return (
            "request too large for model" in lowered
            or "tokens per minute" in lowered
            or "tpm" in lowered
            or "413" in lowered and "requested" in lowered and "limit" in lowered
        )

    async def _raw_stream(
        self,
        api_key: str,
        messages: list[dict],
        model_id: str,
        *,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        from groq import AsyncGroq
        
        # Filter out system messages for models that don't support them
        clean_messages = []
        for m in messages:
            if m["role"] == "system":
                # Convert system to first user message
                clean_messages.append({"role": "user", "content": f"[SYSTEM]\n{m['content']}\n[/SYSTEM]"})
            else:
                clean_messages.append(m)

        client = AsyncGroq(api_key=api_key.strip())
        
        try:
            stream = await client.chat.completions.create(
                model=model_id,
                messages=clean_messages,
                stream=True,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    content = chunk.choices[0].delta.content
                    if content:
                        yield content
        except Exception as e:
            err_str = str(e).lower()
            status_code = getattr(e, "status_code", None)

            # Preserve precise status classification before falling back to text matching.
            if status_code == 429:
                raise Exception("429 Too Many Requests")
            if status_code == 401:
                raise Exception("401 Unauthorized")
            if status_code == 403:
                if "1010" in err_str or "cloudflare" in err_str or "access denied" in err_str:
                    raise Exception("403 Forbidden (Cloudflare 1010 / network access blocked)")
                raise Exception("403 Forbidden")
            if status_code == 413:
                raise Exception(f"413 Groq TPM budget exceeded: {e}")

            if "429" in err_str or "too many requests" in err_str or "rate limit" in err_str:
                raise Exception("429 Too Many Requests")
            elif "401" in err_str or "unauthorized" in err_str or "invalid api key" in err_str:
                raise Exception("401 Unauthorized")
            elif "403" in err_str or "1010" in err_str or "cloudflare" in err_str or "access denied" in err_str:
                raise Exception("403 Forbidden (Cloudflare 1010 / network access blocked)")
            elif self._is_tpm_budget_error(str(e)):
                raise Exception(f"413 Groq TPM budget exceeded: {e}")
            else:
                raise Exception(f"Groq API error: {e}")

    async def _wait_with_progress(self, provider_name: str) -> AsyncIterator[str]:
        """Yield countdown updates while waiting for a cooled-down key."""
        key_count = len(key_manager._keys.get(provider_name, []))
        announced = False

        while True:
            remaining = key_manager.seconds_until_available(provider_name)
            if remaining <= 0:
                break

            if not announced:
                yield (
                    f"\n⏳ All {provider_name.title()} keys are rate-limited. "
                    f"Retrying from key 1/{key_count or 1} in ~{remaining}s...\n"
                )
                announced = True
            else:
                yield f"⏳ {provider_name.title()} cooldown: ~{remaining}s remaining...\n"

            await asyncio.sleep(min(5, max(1, remaining)))

    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        get_provider_key_source(self.provider_name, self.api_key)
        last_error = None
        announced_pool = False
        requested_max_tokens = self._planned_max_tokens(messages)
        
        while True:
            total_keys = key_manager.total_keys(self.provider_name)
            if total_keys and not announced_pool:
                yield f"🔑 Groq key pool active: {total_keys} key(s) loaded.\n"
                announced_pool = True

            key = key_manager.get_key(self.provider_name) or resolve_provider_api_key(
                self.provider_name,
                self.api_key,
            )
            if not key:
                registered_keys = key_manager._keys.get(self.provider_name, [])
                if registered_keys and self.wait_on_rate_limit:
                    async for status in self._wait_with_progress(self.provider_name):
                        yield status
                    wait_key = await key_manager.wait_for_available_key(
                        self.provider_name,
                        max_wait=70,
                        restart_from_first=True,
                    )
                    if wait_key:
                        key_manager.reset_rotation(self.provider_name)
                        yield "🔁 Groq rotation restarted from the first key.\n"
                        continue
                raise ValueError("No Groq API key available.")
            
            try:
                async for t in self._raw_stream(
                    key,
                    messages,
                    model_id,
                    max_tokens=requested_max_tokens,
                ):
                    yield t
                key_manager.mark_used(self.provider_name, key)
                return  # Success
                
            except Exception as e:
                last_error = e
                err_str = str(e)

                if self._is_tpm_budget_error(err_str):
                    adjusted = self._adjusted_max_tokens_from_error(messages, requested_max_tokens, err_str)
                    if adjusted and adjusted < requested_max_tokens:
                        requested_max_tokens = adjusted
                        yield (
                            f"📉 Groq token budget adjusted: retrying same key with max_tokens={requested_max_tokens}.\n"
                        )
                        continue
                    raise Exception(
                        "413 Groq TPM budget exceeded: prompt/context is too large even after reducing output budget. "
                        "Reduce prompt size, context size, or batch scope."
                    )
                
                if is_rate_limit_error(err_str):
                    current_slot, slot_total = key_manager.key_slot(self.provider_name, key)
                    # Rate limited — mark key and get next
                    key_manager.mark_rate_limited(self.provider_name, key, 62)
                    next_key = key_manager.get_key(self.provider_name)
                    
                    if next_key and next_key != key:
                        next_slot, _ = key_manager.key_slot(self.provider_name, next_key)
                        yield (
                            f"↪️ Groq 429 on key {current_slot}/{slot_total or total_keys or 1}. "
                            f"Trying key {next_slot}/{slot_total or total_keys or 1}...\n"
                        )
                        print(f"[GROQ] Rate limited on current key — rotating to next available key")
                        continue
                    else:
                        if self.wait_on_rate_limit:
                            async for status in self._wait_with_progress(self.provider_name):
                                yield status
                            wait_key = await key_manager.wait_for_available_key(
                                self.provider_name,
                                max_wait=70,
                                restart_from_first=True,
                            )
                            if wait_key:
                                key_manager.reset_rotation(self.provider_name)
                                print(f"[GROQ] All keys were used — restarting rotation from the first key")
                                yield "🔁 Groq rotation restarted from the first key.\n"
                                continue
                            raise e
                        else:
                            raise e
                elif is_auth_error(err_str):
                    key_manager.mark_invalid(self.provider_name, key)
                    next_key = key_manager.get_key(self.provider_name) or resolve_provider_api_key(self.provider_name)
                    if next_key:
                        continue
                    raise ValueError("All Groq keys are invalid.")
                else:
                    raise
        if last_error:
            raise last_error


class AnthropicProvider(BaseProvider):
    """Anthropic Claude API provider."""
    provider_name = "anthropic"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1"

    async def _raw_stream(self, api_key: str, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Separate system message
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        user_messages = [m for m in messages if m["role"] != "system"]
        system_text = "\n\n".join(system_parts) if system_parts else None

        payload = {
            "model": model_id or "claude-3-5-haiku-latest",
            "messages": user_messages,
            "stream": True,
            "max_tokens": 8192,
        }
        if system_text:
            payload["system"] = system_text

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise Exception(f"Anthropic API error {resp.status}: {error[:200]}")

                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            content = delta.get("text", "")
                            if content:
                                yield content
                    except (json.JSONDecodeError, KeyError):
                        continue

    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        get_provider_key_source(self.provider_name, self.api_key)
        last_error = None

        while True:
            key = key_manager.get_key(self.provider_name) or resolve_provider_api_key(self.provider_name, self.api_key)
            if not key:
                raise ValueError("No Anthropic API key available.")

            try:
                async for token in self._raw_stream(key, messages, model_id):
                    yield token
                key_manager.mark_used(self.provider_name, key)
                return
            except Exception as e:
                last_error = e
                if is_rate_limit_error(e):
                    key_manager.mark_rate_limited(self.provider_name, key, 62)
                    next_key = key_manager.get_key(self.provider_name) or resolve_provider_api_key(self.provider_name)
                    if next_key and next_key != key:
                        continue
                    wait_key = await key_manager.wait_for_available_key(self.provider_name, max_wait=70, restart_from_first=True)
                    if wait_key:
                        continue
                elif is_auth_error(e):
                    key_manager.mark_invalid(self.provider_name, key)
                    if key_manager.get_key(self.provider_name) or resolve_provider_api_key(self.provider_name):
                        continue
                raise

        if last_error:
            raise last_error


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI-compatible API (OpenRouter, Together, local OpenAI-compat servers)."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", provider_name: str = "openai"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.provider_name = normalize_provider_name(provider_name)

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = str(os.getenv(name, "")).strip()
        if not raw:
            return default
        try:
            value = int(raw)
            return value if value > 0 else default
        except Exception:
            return default

    def _compute_max_output_tokens(self, model_id: str) -> int:
        """
        Decide completion budget for OpenAI-compatible providers.
        Defaults are overridable via environment variables:
          - KILO_COMPAT_MAX_OUTPUT_TOKENS (default: 8192)
          - KILO_COMPAT_REASONING_MAX_OUTPUT_TOKENS (default: 128000)
          - KILO_COMPAT_DEEPSEEK_MAX_OUTPUT_TOKENS (default: 65536, DeepSeek only)
        """
        regular_default = self._env_int("KILO_COMPAT_MAX_OUTPUT_TOKENS", 8192)
        reasoning_default = self._env_int("KILO_COMPAT_REASONING_MAX_OUTPUT_TOKENS", 128000)
        normalized = str(model_id or "").lower()
        reasoning_markers = ("reasoning", "reasoner", "r1", "o1", "o3", "gpt-5")
        budget = reasoning_default if any(marker in normalized for marker in reasoning_markers) else regular_default

        # DeepSeek hard-caps max_tokens at 65536 (or a lower value depending on model).
        # Keep OpenAI high, but prevent DeepSeek from ever getting an out-of-range default.
        if self.provider_name == "deepseek":
            deepseek_cap = self._env_int("KILO_COMPAT_DEEPSEEK_MAX_OUTPUT_TOKENS", 65536)
            if deepseek_cap > 0:
                budget = min(budget, deepseek_cap)

        return max(1, int(budget))

    @staticmethod
    def _extract_max_tokens_upper_bound(error: Exception | str) -> int | None:
        text = str(error or "")
        patterns = (
            r"valid range of max_tokens is \[\s*\d+\s*,\s*(\d+)\s*\]",
            r"valid range of max_completion_tokens is \[\s*\d+\s*,\s*(\d+)\s*\]",
            r"max_tokens.*?\[\s*\d+\s*,\s*(\d+)\s*\]",
            r"max_completion_tokens.*?\[\s*\d+\s*,\s*(\d+)\s*\]",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            try:
                value = int(match.group(1))
                if value > 0:
                    return value
            except Exception:
                continue
        return None

    async def _raw_stream(
        self,
        api_key: str,
        messages: list[dict],
        model_id: str,
        *,
        max_output_override: int | None = None,
    ) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        max_output = max(1, int(max_output_override or self._compute_max_output_tokens(model_id)))
            
        payload = {
            "model": model_id,
            "messages": messages,
            "stream": True,
            "temperature": 0.3,
        }
        
        # Modern OpenAI models (GPT-5+, o1, o3) use max_completion_tokens
        # We only apply this to the official openai provider to avoid breaking other compat providers like DeepSeek
        is_modern_openai = (self.provider_name == "openai" and 
                           any(model_id.startswith(p) for p in ["gpt-5", "o1", "o3"]))
        
        if is_modern_openai:
            payload["max_completion_tokens"] = max_output
        else:
            payload["max_tokens"] = max_output

        timeout = aiohttp.ClientTimeout(total=3600)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise Exception(f"API error {resp.status}: {error[:200]}")

                length_stopped = False
                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        choice0 = data["choices"][0]
                        if choice0.get("finish_reason") == "length":
                            length_stopped = True
                        delta = choice0.get("delta", {}) or {}
                        
                        # Handle reasoning_content for DeepSeek R1
                        reasoning = delta.get("reasoning_content", "")
                        if reasoning:
                            # We don't yield reasoning to the code parser, but we could if we wanted to log it.
                            continue

                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                if length_stopped:
                    raise Exception(
                        f"Model stopped due to output limit (finish_reason=length, requested_max_tokens={max_output})."
                    )

    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        get_provider_key_source(self.provider_name, self.api_key)
        last_error = None
        max_output_override: int | None = None

        while True:
            key = key_manager.get_key(self.provider_name) or resolve_provider_api_key(self.provider_name, self.api_key)
            if not key:
                raise ValueError(f"No {self.provider_name} API key available.")

            try:
                async for token in self._raw_stream(
                    key,
                    messages,
                    model_id,
                    max_output_override=max_output_override,
                ):
                    yield token
                key_manager.mark_used(self.provider_name, key)
                return
            except Exception as e:
                last_error = e
                # Auto-recover from provider-side max_tokens range rejections.
                upper_bound = self._extract_max_tokens_upper_bound(e)
                if upper_bound:
                    current_budget = int(max_output_override or self._compute_max_output_tokens(model_id))
                    if upper_bound < current_budget:
                        max_output_override = max(1, upper_bound)
                        continue
                if is_rate_limit_error(e):
                    key_manager.mark_rate_limited(self.provider_name, key, 62)
                    next_key = key_manager.get_key(self.provider_name) or resolve_provider_api_key(self.provider_name)
                    if next_key and next_key != key:
                        continue
                    wait_key = await key_manager.wait_for_available_key(self.provider_name, max_wait=70, restart_from_first=True)
                    if wait_key:
                        continue
                elif is_auth_error(e):
                    key_manager.mark_invalid(self.provider_name, key)
                    if key_manager.get_key(self.provider_name) or resolve_provider_api_key(self.provider_name):
                        continue
                raise

        if last_error:
            raise last_error


class ScraperProvider(BaseProvider):
    # Feature 2 + 3: mark as scraper so loop uses scraper-specific prompt
    is_scraper = True
    provider_name = "scraper"
    """
    Self-hosted scraper gateway provider.
    The gateway exposes a standard OpenAI-compatible /v1/chat/completions endpoint.
    Auth uses X-API-Key header (NOT Bearer).

    Source-confirmed from:
      API/app/main.py → /v1/chat/completions with Depends(verify_api_key)
      API/app/config.py → API_KEYS env var, header X-API-Key
      Live test: 4 workers online, chatgpt/deepseek/gemini/groq all available.
    """

    DEFAULT_URL = "http://localhost:5300"
    DEFAULT_KEY = "your-secret-key-1"

    SCRAPER_MODELS = {
        "claude-scraper",
        "deepseek",
        "chatgpt-scraper",
        "gemini-scraper",
    }

    def __init__(self, api_key: str = "", scraper_url: str = ""):
        self.api_key = api_key or self.DEFAULT_KEY
        self.base_url = (scraper_url or self.DEFAULT_URL).rstrip("/")

    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

        # Use a sensible default model name if not specified
        if not model_id or model_id == "scraper":
            model_id = "chatgpt-scraper"

        # Clean messages — strip non-BMP characters (emojis, etc.) that
        # ChromeDriver cannot handle when pasting text into the browser.
        def _to_bmp(text: str) -> str:
            return "".join(c for c in str(text) if ord(c) <= 0xFFFF)

        clean_messages = []
        for m in messages:
            clean_messages.append({
                "role": m.get("role", "user"),
                "content": _to_bmp(m.get("content", "")),
            })

        payload = {
            "model": model_id,
            "messages": clean_messages,
            "max_tokens": 8192,
            "temperature": 0.3,
        }

        max_retries = 3
        retry_delay = 15
        last_error = None

        for attempt in range(max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=600)  # scraper can be slow
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as resp:
                        if resp.status == 401:
                            raise Exception(f"Scraper gateway auth failed — check X-API-Key. Got 401.")
                        if resp.status in (500, 502, 503, 504):
                            body = await resp.text()
                            raise Exception(
                                f"Scraper gateway error {resp.status}: {body[:300]}"
                            )
                        if resp.status != 200:
                            body = await resp.text()
                            raise Exception(f"Scraper gateway error {resp.status}: {body[:300]}")

                        data = await resp.json(content_type=None)

                        # Check for error embedded in 200 response (worker_failed)
                        if "error" in data and isinstance(data["error"], dict):
                            err_msg = data["error"].get("message", "unknown gateway error")
                            raise Exception(f"Scraper gateway worker error: {err_msg}")

                        try:
                            content = data["choices"][0]["message"]["content"]
                        except (KeyError, IndexError, TypeError):
                            raise Exception(f"Unexpected gateway response format: {str(data)[:200]}")

                        content = self._clean_response(content)

                        chunk_size = 200
                        for i in range(0, len(content), chunk_size):
                            yield content[i:i + chunk_size]
                            await asyncio.sleep(0)  # allow event loop to breathe
                        return  # Success — exit retry loop

            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                # Permanent errors — don't retry
                is_permanent = any(kw in err_str for kw in ["401", "auth failed", "400"])
                if is_permanent or attempt >= max_retries - 1:
                    raise
                # Transient — retry
                print(f"[SCRAPER] Attempt {attempt + 1}/{max_retries} failed: {e} — retrying in {retry_delay}s")
                await asyncio.sleep(retry_delay)

    def _clean_response(self, text: str) -> str:
        import re
        if not text:
            return text
            
        # Do NOT strip backticks here anymore; ResponseParser needs them
        # text = re.sub(r'```[\w]*\n?', '', text)
        # text = re.sub(r'```', '', text)
        
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.lstrip()
            spaces = len(line) - len(stripped)
            if spaces >= 16:
                indent_level = spaces // 4
                line = ('  ' * min(indent_level, 4)) + stripped
            cleaned.append(line)
        text = '\n'.join(cleaned)
        
        text = re.sub(r'(<write_file>)', r'\n\1\n', text)
        text = re.sub(r'(</write_file>)', r'\n\1\n', text)
        text = re.sub(r'(<path>)', r'\n\1', text)
        text = re.sub(r'(</content>)', r'\n\1', text)
        
        if '<write_file>' in text:
            first_tag = text.find('<write_file>')
            preamble = text[:first_tag].strip()
            if len(preamble) > 0 and len(preamble) < 200:
                text = text[first_tag:]
        
        return text.strip()


class AutoProvider(BaseProvider):
    """
    Zero-cost auto mode: tries providers in priority order.
    Groq (free tier) → Scraper (self-hosted, free) → Anthropic.
    """
    def __init__(self, api_key: str = "", **kwargs):
        pass

    async def stream(self, messages: list[dict], model_id: str = "") -> AsyncIterator[str]:
        errors = []

        # 1. Try Groq (fastest, free tier)
        groq_key = get_key("GROQ_API_KEY")
        if groq_key:
            try:
                gm = model_id or "llama-3.3-70b-versatile"
                async for t in GroqProvider(groq_key, wait_on_rate_limit=False).stream(messages, gm):
                    yield t
                return
            except Exception as e:
                errors.append(f"Groq: {e}")
                print(f"[AUTO] Groq failed: {e}")
                # Fall through to scraper

        # 2. Try scraper models (self-hosted, zero cloud cost)
        scraper_url = get_runtime_key("SCRAPER_URL", "")
        scraper_key = get_runtime_key("SCRAPER_API_KEY", "")
        scraper_url = scraper_url or os.getenv("SCRAPER_URL", "http://localhost:5300")
        scraper_key = scraper_key or os.getenv("SCRAPER_API_KEY", "your-secret-key-1")

        for model_name in ["deepseek", "chatgpt-scraper", "claude-scraper", "gemini-scraper"]:
            try:
                s = ScraperProvider(api_key=scraper_key, scraper_url=scraper_url)
                # Quick availability check (10s timeout)
                import aiohttp as _ah
                try:
                    async with _ah.ClientSession(timeout=_ah.ClientTimeout(total=10)) as sess:
                        async with sess.get(f"{scraper_url}/health") as r:
                            if r.status not in (200, 404):
                                raise Exception(f"gateway status {r.status}")
                except Exception:
                    break  # scraper not reachable — skip all models

                full = ""
                async for t in s.stream(messages, model_name):
                    full += t
                for i in range(0, len(full), 50):
                    yield full[i:i + 50]
                return
            except Exception as e:
                errors.append(f"Scraper/{model_name}: {e}")
                print(f"[AUTO] Scraper/{model_name} failed → {e}")
                continue

        # 3. Try Anthropic
        ant_key = get_key("ANTHROPIC_API_KEY")
        if ant_key:
            try:
                am = model_id or "claude-3-5-haiku-latest"
                async for t in AnthropicProvider(ant_key).stream(messages, am):
                    yield t
                return
            except Exception as e:
                errors.append(f"Anthropic: {e}")

        raise RuntimeError("[AUTO] All providers failed:\n" + "\n".join(errors))


class FailoverProvider(BaseProvider):
    """
    Tries an ordered list of provider/model pairs until one succeeds.
    Useful for per-stage model sequences such as:
    groq:llama-3.3-70b-versatile,openai:gpt-4o-mini
    """

    def __init__(
        self,
        candidates: list[ModelCandidate],
        *,
        scraper_url: str = "",
        explicit_api_keys: dict[str, str] | None = None,
    ):
        self.candidates = candidates
        self.scraper_url = scraper_url
        self.explicit_api_keys = {
            normalize_provider_name(provider): value
            for provider, value in (explicit_api_keys or {}).items()
            if value
        }
        self.last_model_id = candidates[0].model if candidates else ""
        self.last_provider = candidates[0].provider if candidates else ""
        self._next_index = 0

    async def stream(self, messages: list[dict], model_id: str = "") -> AsyncIterator[str]:
        candidates = self.candidates or parse_model_candidates(model_id, "groq", model_id)
        errors: list[str] = []
        total = len(candidates)
        if total == 0:
            raise RuntimeError("No model candidates configured.")

        start_index = self._next_index % total
        ordered = [candidates[(start_index + offset) % total] for offset in range(total)]

        for offset, candidate in enumerate(ordered):
            provider_name = normalize_provider_name(candidate.provider)
            api_key = self.explicit_api_keys.get(provider_name, "")
            provider = get_provider(
                provider_name,
                api_key,
                scraper_url=self.scraper_url,
            )

            try:
                self.last_provider = provider_name
                self.last_model_id = candidate.model
                async for token in provider.stream(messages, candidate.model):
                    yield token
                self._next_index = (start_index + offset + 1) % total
                return
            except Exception as exc:
                errors.append(f"{provider_name}:{candidate.model} -> {exc}")
                continue

        raise RuntimeError("All configured model candidates failed:\n" + "\n".join(errors))


def get_provider(provider_name: str, api_key: str, **kwargs) -> BaseProvider:
    """Factory for getting a provider by name."""

    if api_key:
        register_provider_keys(provider_name, api_key)

    if provider_name.lower() == "groq":
        import os
        from dotenv import load_dotenv
        load_dotenv()  # force reload .env
        
        actual_key = get_key("GROQ_API_KEY")
        env_key = os.getenv("GROQ_API_KEY", "")
        
        
        import reprlib

        km_key = key_manager.get_key("groq")
        
    providers = {
        "auto": lambda: AutoProvider(""),
        "groq": lambda: GroqProvider(api_key),
        "anthropic": lambda: AnthropicProvider(api_key),
        "openai": lambda: OpenAICompatibleProvider(api_key, kwargs.get("base_url", "https://api.openai.com/v1"), provider_name="openai"),
        "openrouter": lambda: OpenAICompatibleProvider(api_key, "https://openrouter.ai/api/v1", provider_name="openrouter"),
        "deepseek": lambda: OpenAICompatibleProvider(api_key, "https://api.deepseek.com/v1", provider_name="deepseek"),
        "scraper": lambda: ScraperProvider(
            api_key=api_key,
            scraper_url=kwargs.get("scraper_url", "")
        ),
    }
    factory = providers.get(provider_name.lower())
    if not factory:
        raise ValueError(f"Unknown provider: {provider_name}. Available: {list(providers.keys())}")
    return factory()


async def stream_response(messages: list[dict], model_config: dict, api_key: str = ""):
    """
    Unified stream_response:
    - provider='auto' → AutoProvider
    - provider='groq' → Groq with 429 key rotation
    - all others      → unchanged behaviour
    """
    provider_name = model_config.get("provider", "groq")
    model_id = model_config.get("model_id", "")

    # Feature 3: Groq with multi-key 429 retry
    if provider_name == "groq":
        # Hydrate key manager directly from payload if the frontend beamed over a CSV array
        if api_key:
            register_provider_keys("groq", api_key)

        key = resolve_provider_api_key("groq", api_key)
        if not key:
            raise ValueError("No Groq API key configuration found.")
        async for t in GroqProvider(key).stream(messages, model_id):
            yield t
        return

    # All other providers including Auto
    provider = get_provider(provider_name, api_key)
    async for token in provider.stream(messages, model_id):
        yield token
