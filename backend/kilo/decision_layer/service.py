"""
Decision Layer — Service

Calls the LLM to classify user intent and return a structured DecisionResult.
Supports two passes:
  1. First pass  — no project context, fast classification.
  2. Second pass — with collected project context, precise classification.

Internal chain-of-thought is never surfaced; only the structured JSON result is
logged at DEBUG level.
"""

from __future__ import annotations

import json
import logging
import re

from .prompt import build_decision_messages
from .types import DecisionResult, fallback_decision, validate_decision

logger = logging.getLogger("decision_layer.service")


class DecisionLayerService:
    """
    Wraps LLM calls to produce structured routing decisions.

    Parameters
    ----------
    provider:
        An LLM provider object that implements ``async stream(messages, model_id)``
        yielding token strings (same interface as the rest of the kilo codebase).
    model_id:
        The model identifier to use for decision calls.
    """

    def __init__(self, provider: object, model_id: str) -> None:
        self._provider = provider
        self._model_id = model_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def decide(
        self,
        message: str,
        *,
        has_project: bool,
        chat_history: list[dict] | None = None,
    ) -> DecisionResult:
        """
        First pass: classify intent without project context.

        Args:
            message:      The raw user message.
            has_project:  Whether a projectId exists (existing project).
            chat_history: Optional bounded previous conversation turns.
        """
        messages = build_decision_messages(
            user_message=message,
            has_project=has_project,
            project_context=None,
            chat_history=chat_history,
        )
        return await self._call_llm(messages, pass_label="first")

    async def decide_with_context(
        self,
        message: str,
        *,
        has_project: bool,
        project_context: str,
        chat_history: list[dict] | None = None,
    ) -> DecisionResult:
        """
        Second pass: classify intent after project context has been collected.

        Args:
            message:         The raw user message.
            has_project:     Whether a projectId exists.
            project_context: Collected context string (file tree, file contents, etc.).
            chat_history:    Optional bounded previous conversation turns.
        """
        messages = build_decision_messages(
            user_message=message,
            has_project=has_project,
            project_context=project_context,
            chat_history=chat_history,
        )
        return await self._call_llm(messages, pass_label="second")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        messages: list[dict],
        *,
        pass_label: str = "first",
    ) -> DecisionResult:
        """Stream the LLM response, parse JSON, validate, and return."""
        raw_text = ""
        try:
            from ..providers import is_provider_status_token  # type: ignore

            async for token in self._provider.stream(messages, self._model_id):
                if is_provider_status_token(token):
                    continue
                raw_text += token
        except Exception as exc:
            logger.warning("[decision_layer] LLM call failed (%s pass): %s", pass_label, exc)
            return fallback_decision(f"LLM call failed: {exc}")

        return self._parse_and_log(raw_text, pass_label=pass_label)

    @staticmethod
    def _parse_and_log(raw_text: str, *, pass_label: str = "first") -> DecisionResult:
        """
        Extract a JSON object from the LLM response, validate it, and log
        the structured decision at DEBUG level.

        We deliberately never log `raw_text` to avoid leaking chain-of-thought.
        """
        json_text = _extract_json(raw_text)
        if not json_text:
            logger.warning("[decision_layer] No JSON found in LLM response (%s pass).", pass_label)
            return fallback_decision("LLM did not return valid JSON.")

        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as exc:
            logger.warning("[decision_layer] JSON parse error (%s pass): %s", pass_label, exc)
            return fallback_decision(f"JSON parse error: {exc}")

        try:
            result = validate_decision(parsed)
        except (ValueError, KeyError) as exc:
            logger.warning("[decision_layer] Decision validation failed (%s pass): %s", pass_label, exc)
            return fallback_decision(f"Validation error: {exc}")

        # Structured log — intent, route, confidence, reason only (no CoT)
        logger.debug(
            "[decision_layer] Decision (%s pass): intent=%s route=%s confidence=%.2f reason=%r",
            pass_label,
            result.get("intent"),
            result.get("route"),
            result.get("confidence", 0.0),
            result.get("reason", "")[:100],
        )
        return result


def _extract_json(text: str) -> str:
    """
    Extract the first valid JSON object from an LLM response string.
    Handles responses wrapped in markdown code fences.
    """
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    # Find the first {...} block
    start = text.find("{")
    if start == -1:
        return ""

    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return ""


__all__ = ["DecisionLayerService"]
