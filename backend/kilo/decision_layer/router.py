"""
Decision Layer — Decision Router

Orchestrates the full two-pass decision pipeline:

  1. First pass  — call DecisionLayerService without project context.
  2. If requires_project_context — fulfill context requests via ProjectContextBuilder.
  3. Second pass — call DecisionLayerService again with the collected context.
  4. Dispatch to the correct handler (NormalChatHandler or ProjectActionExecutor).

The existing generation path is invoked via a `generate_fn` callback so that
the original generate.py code is never modified.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Callable, Awaitable

from .context_builder import ProjectContextBuilder
from .service import DecisionLayerService
from .types import DecisionResult

logger = logging.getLogger("decision_layer.router")


class DecisionRouter:
    """
    Orchestrates the two-pass decision pipeline and dispatches to handlers.

    Parameters
    ----------
    provider:
        LLM provider (same interface used everywhere in kilo).
    model_id:
        Model identifier for Decision Layer calls.
    sandbox_dir:
        Absolute path to the project sandbox (empty string if no project).
    generate_fn:
        Callback that starts a generation task.
        Signature: ``async generate_fn(prompt: str) -> {"session_id": str, "status": str}``
    """

    def __init__(
        self,
        provider: object,
        model_id: str,
        sandbox_dir: str,
        generate_fn: Callable[[str], Awaitable[dict]],
    ) -> None:
        self._provider = provider
        self._model_id = model_id
        self._sandbox_dir = sandbox_dir
        self._generate_fn = generate_fn
        self._service = DecisionLayerService(provider, model_id)

    async def route(
        self,
        message: str,
        *,
        project_id: str = "",
        chat_history: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """
        Run the full decision pipeline and yield response chunks.

        This is the single public entry point for the /api/chat route.

        Yields
        ------
        str chunks that the API route will wrap in SSE frames.
        Special chunk ``{"type":"generation_started",...}`` signals the route
        layer to return a JSON response instead of streaming.
        """
        has_project = bool(project_id and self._sandbox_dir and project_id.strip())

        # ── First Pass ────────────────────────────────────────────────
        first_decision = await self._service.decide(
            message,
            has_project=has_project,
            chat_history=chat_history,
        )

        logger.info(
            "[router] First pass: intent=%s route=%s confidence=%.2f",
            first_decision.get("intent"),
            first_decision.get("route"),
            first_decision.get("confidence", 0.0),
        )

        # Fast path — no context needed
        if not first_decision.get("requires_project_context", False):
            async for chunk in self._dispatch(first_decision, message, "", chat_history):
                yield chunk
            return

        # ── Context Collection ────────────────────────────────────────
        context = ""
        if has_project and self._sandbox_dir:
            builder = ProjectContextBuilder(self._sandbox_dir)
            context_requests = first_decision.get("context_requests", [])

            if context_requests:
                logger.debug(
                    "[router] Collecting context: %s",
                    [r.get("type") for r in context_requests],
                )
                context = builder.fulfill_context_requests(context_requests)
            else:
                # Default: get file tree when no specific requests were made
                context = builder.get_file_tree()

        # ── Second Pass ───────────────────────────────────────────────
        if context:
            second_decision = await self._service.decide_with_context(
                message,
                has_project=has_project,
                project_context=context,
                chat_history=chat_history,
            )
            logger.info(
                "[router] Second pass: intent=%s route=%s confidence=%.2f",
                second_decision.get("intent"),
                second_decision.get("route"),
                second_decision.get("confidence", 0.0),
            )
            final_decision = second_decision
        else:
            # No context could be collected; use first pass result
            final_decision = first_decision

        async for chunk in self._dispatch(final_decision, message, context, chat_history):
            yield chunk

    # ------------------------------------------------------------------
    # Internal dispatcher
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        decision: DecisionResult,
        message: str,
        project_context: str,
        chat_history: list[dict] | None,
    ) -> AsyncIterator[str]:
        """Route to the correct handler based on decision.route."""
        from .chat_handler import NormalChatHandler
        from .project_action_executor import ProjectActionExecutor

        route = decision.get("route", "clarification_path")

        # ── New generation → existing pipeline (unchanged) ────────────
        if route == "existing_generation_path":
            result = await self._generate_fn(message)
            session_id = result.get("session_id", "")
            status = result.get("status", "")
            # Yield a sentinel chunk that the API layer detects and converts
            # to the standard {session_id, status} JSON response
            yield f'\x00GENERATION_STARTED:{session_id}:{status}'
            return

        # ── Normal chat ───────────────────────────────────────────────
        if route == "normal_chat_path":
            handler = NormalChatHandler(self._provider, self._model_id)
            async for chunk in handler.stream(message, chat_history):
                yield chunk
            return

        # ── All project-level actions ─────────────────────────────────
        executor = ProjectActionExecutor(
            provider=self._provider,
            model_id=self._model_id,
            sandbox_dir=self._sandbox_dir,
            generate_fn=self._generate_fn,
        )
        async for chunk in executor.execute(decision, message, project_context, chat_history):
            yield chunk


__all__ = ["DecisionRouter"]
