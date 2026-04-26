"""
Decision Layer — Normal Chat Handler

Handles the normal_chat route: streams a conversational assistant response
without triggering any project generation or modification.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

logger = logging.getLogger("decision_layer.chat_handler")

CHAT_SYSTEM_PROMPT = """\
You are WAGI, a friendly AI assistant that helps developers build web applications.

Current context: The user is not currently working on a specific project, or they
just want to have a general conversation.

Guidelines:
- Be helpful, concise, and friendly.
- If the user describes a project they want to build, let them know they can use
  the "Generate App" button or just describe it and you will start building it.
- Do not generate code unless explicitly asked.
- Do not make up facts about their codebase if you have no project context.
"""


class NormalChatHandler:
    """
    Streams a conversational assistant reply for normal_chat intent.

    Parameters
    ----------
    provider:
        An LLM provider with ``async stream(messages, model_id)`` method.
    model_id:
        The model to use.
    """

    def __init__(self, provider: object, model_id: str) -> None:
        self._provider = provider
        self._model_id = model_id

    async def stream(
        self,
        message: str,
        chat_history: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """
        Yield token strings forming the assistant's conversational reply.

        Args:
            message:      The user's latest message.
            chat_history: Optional bounded previous turns.
        """
        messages: list[dict] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]

        # Include bounded history (last 8 turns)
        for turn in (chat_history or [])[-8:]:
            role = turn.get("role", "user")
            content = str(turn.get("content", ""))[:1000]
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": message})

        try:
            from ..providers import is_provider_status_token  # type: ignore

            async for token in self._provider.stream(messages, self._model_id):
                if is_provider_status_token(token):
                    continue
                yield token
        except Exception as exc:
            logger.warning("[chat_handler] Stream error: %s", exc)
            yield f"\n⚠️ Chat error: {exc}"


__all__ = ["NormalChatHandler"]
