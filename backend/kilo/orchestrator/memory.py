# Standalone AgentMemory implementation.
# This file contains the logic for managing conversation context,
# including deferred summarization and context preservation.
from typing import Optional, List, Dict

# NOTE: memory_ref.py is kept as a reference for advanced LangChain-based
# features, but this file implements its own high-performance logic.


# ── AgentMemory: Configuration ────────────────────────────────────────────────
COMPRESS_TRIGGER_FRACTION = 0.85
DEFAULT_MAX_TOKENS = 64000  # Supports large initial builds (25-30 files)
DEFAULT_KEEP_MESSAGES = 6   # How many recent messages to keep after summary
APPROX_CHARS_PER_TOKEN = 4

# CONTEXT PRESERVATION RULES:
# We MUST preserve the FIRST TWO messages in the conversation history:
# 1. System Prompt (personality, tools, architectural rules)
# 2. Initial User Request (the project's core goal/spec)
# This prevents the AI from losing track of its identity or its mission.


def _count_tokens_approximately(messages: list[dict]) -> int:
    """Approximate token count for a message list."""
    total = 0
    for m in messages:
        content = m.get("content", "") or ""
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") if isinstance(c, dict) else str(c)
                for c in content
            )
        total += max(1, len(str(content)) // APPROX_CHARS_PER_TOKEN)
    return total

from ..agents.codegen.prompts import get_summarization_prompt


class AgentMemory:
    """
    Conversation memory with context-aware summarization and preservation.
    This implementation handles token counting and intelligent compression.
    """

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        trigger_fraction: float = COMPRESS_TRIGGER_FRACTION,
        keep_messages: int = DEFAULT_KEEP_MESSAGES,
    ) -> None:
        self._messages: list[dict] = []
        self._max_tokens = max_tokens
        self._trigger_threshold = int(max_tokens * trigger_fraction)
        self._keep_messages = keep_messages

    def add_message(self, role: str, content: str) -> None:
        """Append a message to the conversation history."""
        self._messages.append({"role": role, "content": content})

    def pop_message(self) -> Optional[dict]:
        """Remove and return the last message from the history."""
        if self._messages:
            return self._messages.pop()
        return None

    def get_context(self) -> list[dict]:
        """Return the full message list (effective context for the model)."""
        return list(self._messages)

    def clear_chat_history(self) -> None:
        """Clear all messages except the first system prompt."""
        if self._messages and self._messages[0].get("role") == "system":
            self._messages = [self._messages[0]]
        else:
            self._messages = []

    def needs_compression(self) -> bool:
        """Check whether token usage exceeds the compression trigger threshold."""
        total = _count_tokens_approximately(self._messages)
        return total >= self._trigger_threshold

    async def compress(self, provider, model_id: str) -> None:
        """Summarize old messages while preserving the initial project context."""
        if len(self._messages) <= self._keep_messages + 2:
            return

        # Keep system prompt (index 0) and first user request (index 1)
        # This prevents the AI from losing sight of the "First Prompt"
        initial_context = self._messages[:2]

        cutoff = max(2, len(self._messages) - self._keep_messages)
        to_summarize = self._messages[2:cutoff]
        to_keep = self._messages[cutoff:]

        history_text = "\n".join(
            f"{m['role'].upper()}: {str(m['content'])[:500]}"
            for m in to_summarize
        )
        summary_prompt = [
            {
                "role": "user",
                "content": get_summarization_prompt(history_text),
            }
        ]

        summary_text = ""
        try:
            from ..providers import is_provider_status_token
            async for token in provider.stream(summary_prompt, model_id):
                if is_provider_status_token(token):
                    continue
                summary_text += token
        except Exception:
            summary_text = "Intermediate conversation steps (tool calls and results) were compressed."

        summary_msg = {
            "role": "user",
            "content": f"[Conversation summary]\n{summary_text}",
        }
        self._messages = initial_context + [summary_msg] + to_keep

    @property
    def message_count(self) -> int:
        """Total number of messages in history."""
        return len(self._messages)

    @property
    def estimated_tokens(self) -> int:
        """Approximate token count of the current context."""
        return _count_tokens_approximately(self._messages)


__all__ = ["AgentMemory"]
