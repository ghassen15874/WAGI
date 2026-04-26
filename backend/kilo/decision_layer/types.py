"""
Decision Layer — Type Definitions

Defines the structured output that the Decision Layer LLM must return.
These types are used throughout the decision_layer package.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


# ---------------------------------------------------------------------------
# Intent taxonomy
# ---------------------------------------------------------------------------
IntentType = Literal[
    "new_generation",
    "normal_chat",
    "modify_project",
    "add_feature",
    "delete_file",
    "rename_file",
    "explain_file",
    "ask_about_project",
    "generate_project_summary",
    "inspect_project",
    "needs_more_context",
    "unknown",
]

# Route tells the router which handler to invoke
RouteType = Literal[
    "existing_generation_path",
    "normal_chat_path",
    "project_context_builder",
    "project_modification_path",
    "project_explanation_path",
    "project_summary_path",
    "delete_file_path",
    "rename_file_path",
    "inspect_project_path",
    "clarification_path",
]

# Context request types
ContextRequestType = Literal[
    "file_tree",
    "read_file",
    "search",
    "ast",
    "dependency_graph",
    "memory",
    "command",
]


class ContextRequest(TypedDict, total=False):
    """A single context collection request from the Decision Layer."""
    type: ContextRequestType        # required
    query: str                       # what to inspect or search for
    target: str                      # optional: file path or search term


class DecisionResult(TypedDict, total=False):
    """
    Structured result returned by the Decision Layer LLM.

    All fields are present in a valid result; `total=False` allows
    partial construction during parsing/validation.
    """
    intent: IntentType              # required
    confidence: float               # 0.0 – 1.0
    reason: str                     # short explanation (never chain-of-thought)
    requires_project_context: bool  # True → run context builder first
    context_requests: list[ContextRequest]
    target_files: list[str]         # files the action targets
    proposed_action: str            # one-line description of the next step
    route: RouteType                # required


# ---------------------------------------------------------------------------
# Default / fallback result
# ---------------------------------------------------------------------------
def fallback_decision(reason: str = "Could not parse decision.") -> DecisionResult:
    """Return a safe clarification decision when the LLM output is unparseable."""
    return DecisionResult(
        intent="unknown",
        confidence=0.0,
        reason=reason,
        requires_project_context=False,
        context_requests=[],
        target_files=[],
        proposed_action="Ask the user to clarify their request.",
        route="clarification_path",
    )


def validate_decision(raw: Any) -> DecisionResult:
    """
    Validate and coerce a raw parsed dict into a DecisionResult.
    Fills in missing optional fields with safe defaults.
    Raises ValueError if required fields are missing or invalid.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"Decision must be a JSON object, got: {type(raw).__name__}")

    intent = raw.get("intent", "unknown")
    route = raw.get("route", "clarification_path")

    valid_intents = {
        "new_generation", "normal_chat", "modify_project", "add_feature",
        "delete_file", "rename_file", "explain_file", "ask_about_project",
        "generate_project_summary", "inspect_project", "needs_more_context", "unknown",
    }
    valid_routes = {
        "existing_generation_path", "normal_chat_path", "project_context_builder",
        "project_modification_path", "project_explanation_path", "project_summary_path",
        "delete_file_path", "rename_file_path", "inspect_project_path", "clarification_path",
    }

    if intent not in valid_intents:
        intent = "unknown"
    if route not in valid_routes:
        route = "clarification_path"

    context_requests: list[ContextRequest] = []
    for req in raw.get("context_requests", []):
        if isinstance(req, dict) and req.get("type"):
            context_requests.append(ContextRequest(
                type=req.get("type", "file_tree"),
                query=str(req.get("query", "")),
                target=str(req.get("target", "")),
            ))

    return DecisionResult(
        intent=intent,
        confidence=float(raw.get("confidence", 0.5)),
        reason=str(raw.get("reason", ""))[:500],  # never expose long CoT
        requires_project_context=bool(raw.get("requires_project_context", False)),
        context_requests=context_requests,
        target_files=[str(f) for f in raw.get("target_files", [])],
        proposed_action=str(raw.get("proposed_action", ""))[:300],
        route=route,
    )


__all__ = [
    "IntentType",
    "RouteType",
    "ContextRequestType",
    "ContextRequest",
    "DecisionResult",
    "fallback_decision",
    "validate_decision",
]
