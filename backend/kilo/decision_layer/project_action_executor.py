"""
Decision Layer — Project Action Executor

Executes the final action after the Decision Router has determined the route
and (optionally) collected project context.

Each action method is a generator that yields SSE-compatible text chunks.
Actions that require code modification delegate back to the existing
generation pipeline via the provided `generate_fn` callback — they never
modify files directly.
"""

from __future__ import annotations

import logging
import os
from typing import AsyncIterator, Callable, Awaitable

from .types import DecisionResult

logger = logging.getLogger("decision_layer.executor")


# System prompt for project-aware Q&A (explain / ask / summary)
_PROJECT_QA_SYSTEM = """\
You are WAGI, an expert software engineering assistant.
You have been provided with relevant project context (file tree, file contents,
dependency graph, etc.) to answer the user's question accurately.

Guidelines:
- Be concise and precise.
- Reference specific files or functions when appropriate.
- Do not invent code that doesn't exist in the provided context.
- If the context is insufficient, say so and suggest what the user can check.
"""


class ProjectActionExecutor:
    """
    Executes project-level actions after routing.

    Parameters
    ----------
    provider:
        LLM provider with ``async stream(messages, model_id)``.
    model_id:
        Model identifier.
    sandbox_dir:
        Absolute path to the project sandbox.
    generate_fn:
        Async callable that starts a new generation task and returns
        ``{"session_id": str, "status": str}``.
        Signature: ``generate_fn(prompt: str, **kwargs) -> dict``
    """

    def __init__(
        self,
        provider: object,
        model_id: str,
        sandbox_dir: str,
        generate_fn: Callable[..., Awaitable[dict]],
    ) -> None:
        self._provider = provider
        self._model_id = model_id
        self._sandbox_dir = sandbox_dir
        self._generate_fn = generate_fn

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    async def execute(
        self,
        decision: DecisionResult,
        message: str,
        project_context: str,
        chat_history: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """
        Dispatch to the correct handler based on the decision route.
        Yields text chunks (not SSE-wrapped; wrapping is done by the route layer).
        """
        route = decision.get("route", "clarification_path")
        intent = decision.get("intent", "unknown")

        if route == "existing_generation_path":
            # Delegate to generation system — yield a placeholder and return the
            # session_id as a structured message (handled by the API route layer)
            result = await self._generate_fn(message)
            yield f'\x00GENERATION_STARTED:{result.get("session_id","")}:{result.get("status","")}'

        elif route in ("project_modification_path", "project_context_builder") and intent in (
            "modify_project", "add_feature",
        ):
            # Modifications are sent to the existing generation pipeline with context
            enriched_prompt = _build_modification_prompt(message, project_context, decision)
            targets = decision.get("target_files", [])
            if not targets:
                targets = _extract_paths_from_context(message + " " + str(decision.get("proposed_action", "")))
            result = await self._generate_fn(enriched_prompt, target_files=targets)
            yield f'\x00GENERATION_STARTED:{result.get("session_id","")}:{result.get("status","")}'

        elif route == "delete_file_path" or intent == "delete_file":
            async for chunk in self._handle_delete(decision, project_context):
                yield chunk

        elif route in ("project_explanation_path", "project_context_builder") and intent in (
            "explain_file", "ask_about_project",
        ):
            async for chunk in self._handle_qa(message, project_context, chat_history):
                yield chunk

        elif route == "project_summary_path" or intent == "generate_project_summary":
            async for chunk in self._handle_qa(
                f"Generate a comprehensive summary/README for this project.\n\n{message}",
                project_context,
                chat_history,
            ):
                yield chunk

        elif route == "inspect_project_path" or intent == "inspect_project":
            # Return the file tree directly
            from .context_builder import ProjectContextBuilder
            builder = ProjectContextBuilder(self._sandbox_dir)
            yield builder.get_file_tree()

        elif route == "clarification_path":
            yield _build_clarification_message(decision)

        else:
            # Unknown / needs_more_context fallback
            async for chunk in self._handle_qa(message, project_context, chat_history):
                yield chunk

    # ------------------------------------------------------------------
    # Private action handlers
    # ------------------------------------------------------------------

    async def _handle_qa(
        self,
        message: str,
        project_context: str,
        chat_history: list[dict] | None,
    ) -> AsyncIterator[str]:
        """Stream an LLM answer grounded in project context."""
        context_block = f"\n\n## Project Context\n{project_context}" if project_context else ""
        system_content = _PROJECT_QA_SYSTEM + context_block

        messages: list[dict] = [{"role": "system", "content": system_content}]
        for turn in (chat_history or [])[-6:]:
            role = turn.get("role", "user")
            content = str(turn.get("content", ""))[:800]
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
            logger.warning("[executor] QA stream error: %s", exc)
            yield f"\n⚠️ Error generating response: {exc}"

    async def _handle_delete(
        self,
        decision: DecisionResult,
        project_context: str,
    ) -> AsyncIterator[str]:
        """
        Delete a target file from the sandbox if it can be safely identified.
        Yields a confirmation or error message.
        """
        target_files = decision.get("target_files", [])

        # If LLM already resolved the path, use it; otherwise search context
        if not target_files:
            target_files = _extract_paths_from_context(project_context)

        if not target_files:
            yield (
                "⚠️ Could not identify which file to delete from the context. "
                "Please specify the exact file path (e.g. `src/components/OldNavbar.tsx`)."
            )
            return

        deleted: list[str] = []
        errors: list[str] = []

        for rel_path in target_files[:3]:  # Safety: max 3 files per action
            clean = os.path.normpath(rel_path).lstrip(os.sep)
            full_path = os.path.join(self._sandbox_dir, clean)
            # Directory traversal guard
            if not os.path.realpath(full_path).startswith(os.path.realpath(self._sandbox_dir)):
                errors.append(f"Skipped {rel_path}: path traversal not allowed.")
                continue
            if not os.path.isfile(full_path):
                errors.append(f"{rel_path}: file not found.")
                continue
            try:
                os.remove(full_path)
                deleted.append(rel_path)
                logger.info("[executor] Deleted file: %s", full_path)
            except Exception as exc:
                errors.append(f"{rel_path}: {exc}")

        if deleted:
            yield "✅ Deleted:\n" + "\n".join(f"- `{p}`" for p in deleted)
        if errors:
            yield "\n⚠️ Issues:\n" + "\n".join(f"- {e}" for e in errors)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_modification_prompt(
    message: str,
    project_context: str,
    decision: DecisionResult,
) -> str:
    """Build an enriched prompt that includes project context for modification."""
    parts = [message]
    if decision.get("proposed_action"):
        parts.append(f"\n[Intended action: {decision['proposed_action']}]")
    if project_context:
        parts.append(f"\n\n## Current Project Context\n{project_context[:4000]}")
    return "\n".join(parts)


def _build_clarification_message(decision: DecisionResult) -> str:
    """Return a short clarifying question to the user."""
    reason = decision.get("reason", "")
    action = decision.get("proposed_action", "")
    if action:
        return f"Could you clarify: {action}"
    if reason:
        return f"I'm not sure what you'd like to do. {reason} Could you be more specific?"
    return (
        "I'm not sure what you'd like to do. Could you clarify? "
        "For example: 'Add a dark mode toggle', 'Explain the auth flow', "
        "or 'Generate a project summary'."
    )


def _extract_paths_from_context(context: str) -> list[str]:
    """
    Attempt to extract file paths from a project context string.
    Used as a fallback when target_files is empty.
    """
    import re
    # Match common source file patterns
    pattern = re.compile(r"(?:^|\s)([\w./\-]+\.(?:tsx?|jsx?|py|css|html|json|md))", re.MULTILINE)
    matches = pattern.findall(context)
    seen: set[str] = set()
    results: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            results.append(m)
    return results[:5]


__all__ = ["ProjectActionExecutor"]
