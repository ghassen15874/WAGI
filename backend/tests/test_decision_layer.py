"""
Tests for the Decision Layer.

All tests use a MockProvider that returns a fixed JSON string — no real LLM
calls are made.  The tests validate routing decisions, type validation,
and context-builder utilities.

Run:
    cd /home/kali/Desktop/v6/lovable-clone/backend
    source venv/bin/activate
    python -m pytest tests/test_decision_layer.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

class MockProvider:
    """
    Fake LLM provider that yields a pre-set JSON response as a single token.
    Injected into DecisionLayerService so no real API calls are made.
    """

    def __init__(self, response: dict) -> None:
        self._response = json.dumps(response)

    async def stream(self, messages, model_id):
        yield self._response


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Helper — build a service with a fixed response
# ---------------------------------------------------------------------------

def _service_with(response: dict):
    from kilo.decision_layer.service import DecisionLayerService
    provider = MockProvider(response)
    return DecisionLayerService(provider, model_id="test-model")


# ---------------------------------------------------------------------------
# 1. New generation intent (no project)
# ---------------------------------------------------------------------------

def test_new_generation_intent():
    """'Build me a SaaS landing page' → new_generation / existing_generation_path"""
    svc = _service_with({
        "intent": "new_generation",
        "confidence": 0.99,
        "reason": "Clear new project request.",
        "requires_project_context": False,
        "context_requests": [],
        "target_files": [],
        "proposed_action": "Start generation.",
        "route": "existing_generation_path",
    })
    result = _run(svc.decide("Build me a SaaS landing page with pricing", has_project=False))
    assert result["intent"] == "new_generation"
    assert result["route"] == "existing_generation_path"
    assert result["requires_project_context"] is False
    assert result["confidence"] >= 0.9


# ---------------------------------------------------------------------------
# 2. Normal chat intent (no project)
# ---------------------------------------------------------------------------

def test_normal_chat_intent():
    """'hello, what can you do?' (no project) → normal_chat / normal_chat_path"""
    svc = _service_with({
        "intent": "normal_chat",
        "confidence": 0.99,
        "reason": "Greeting, no project.",
        "requires_project_context": False,
        "context_requests": [],
        "target_files": [],
        "proposed_action": "Answer conversationally.",
        "route": "normal_chat_path",
    })
    result = _run(svc.decide("hello, what can you do?", has_project=False))
    assert result["intent"] == "normal_chat"
    assert result["route"] == "normal_chat_path"
    assert result["requires_project_context"] is False


# ---------------------------------------------------------------------------
# 3. Add feature intent (existing project)
# ---------------------------------------------------------------------------

def test_add_feature_intent():
    """'Add dark mode to the dashboard' → add_feature, requires_project_context=True"""
    svc = _service_with({
        "intent": "add_feature",
        "confidence": 0.9,
        "reason": "Feature addition to existing project.",
        "requires_project_context": True,
        "context_requests": [
            {"type": "file_tree", "query": "project structure"},
            {"type": "search", "query": "dashboard", "target": "dashboard"},
        ],
        "target_files": [],
        "proposed_action": "Inspect project then apply dark mode.",
        "route": "project_context_builder",
    })
    result = _run(svc.decide("Add dark mode to the dashboard", has_project=True))
    assert result["intent"] == "add_feature"
    assert result["requires_project_context"] is True
    assert len(result["context_requests"]) >= 1
    assert result["context_requests"][0]["type"] == "file_tree"


# ---------------------------------------------------------------------------
# 4. Explain file intent
# ---------------------------------------------------------------------------

def test_explain_file_intent():
    """'Explain this file: src/components/Header.tsx' → explain_file, read_file context"""
    svc = _service_with({
        "intent": "explain_file",
        "confidence": 0.99,
        "reason": "Explicit file explanation request.",
        "requires_project_context": True,
        "context_requests": [
            {"type": "read_file", "query": "read file", "target": "src/components/Header.tsx"},
        ],
        "target_files": ["src/components/Header.tsx"],
        "proposed_action": "Read and explain Header.tsx.",
        "route": "project_context_builder",
    })
    result = _run(svc.decide("Explain this file: src/components/Header.tsx", has_project=True))
    assert result["intent"] == "explain_file"
    assert result["requires_project_context"] is True
    assert any(r["type"] == "read_file" for r in result["context_requests"])
    assert "src/components/Header.tsx" in result["target_files"]


# ---------------------------------------------------------------------------
# 5. Delete file intent
# ---------------------------------------------------------------------------

def test_delete_file_intent():
    """'Delete the old Navbar file' → delete_file, requires_project_context=True"""
    svc = _service_with({
        "intent": "delete_file",
        "confidence": 0.95,
        "reason": "Explicit delete request.",
        "requires_project_context": True,
        "context_requests": [
            {"type": "file_tree", "query": "find Navbar file"},
            {"type": "search", "query": "Navbar", "target": "Navbar"},
        ],
        "target_files": [],
        "proposed_action": "Find and delete Navbar file.",
        "route": "project_context_builder",
    })
    result = _run(svc.decide("Delete the old Navbar file", has_project=True))
    assert result["intent"] == "delete_file"
    assert result["requires_project_context"] is True


# ---------------------------------------------------------------------------
# 6. Fallback on bad JSON
# ---------------------------------------------------------------------------

def test_fallback_on_bad_json():
    """LLM returns malformed JSON → route=clarification_path, no exception raised"""
    from kilo.decision_layer.service import DecisionLayerService

    class BadProvider:
        async def stream(self, messages, model_id):
            yield "this is not json at all!!!"

    svc = DecisionLayerService(BadProvider(), model_id="test-model")
    result = _run(svc.decide("hello", has_project=False))
    assert result["route"] == "clarification_path"
    assert result["intent"] == "unknown"
    assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# 7. validate_decision — all required fields
# ---------------------------------------------------------------------------

def test_decision_result_type():
    """validate_decision coerces a complete dict into a valid DecisionResult."""
    from kilo.decision_layer.types import validate_decision

    raw = {
        "intent": "new_generation",
        "confidence": 0.95,
        "reason": "Test",
        "requires_project_context": False,
        "context_requests": [],
        "target_files": [],
        "proposed_action": "Start.",
        "route": "existing_generation_path",
    }
    result = validate_decision(raw)
    assert result["intent"] == "new_generation"
    assert result["route"] == "existing_generation_path"
    assert isinstance(result["confidence"], float)
    assert isinstance(result["context_requests"], list)
    assert isinstance(result["target_files"], list)


def test_validate_decision_coerces_invalid_intent():
    """Invalid intent is coerced to 'unknown'."""
    from kilo.decision_layer.types import validate_decision

    raw = {
        "intent": "totally_made_up",
        "confidence": 0.5,
        "reason": "?",
        "requires_project_context": False,
        "context_requests": [],
        "target_files": [],
        "proposed_action": "?",
        "route": "also_made_up",
    }
    result = validate_decision(raw)
    assert result["intent"] == "unknown"
    assert result["route"] == "clarification_path"


# ---------------------------------------------------------------------------
# 8. ProjectContextBuilder — file tree
# ---------------------------------------------------------------------------

def test_context_builder_file_tree():
    """get_file_tree returns a non-empty tree for a real temp directory."""
    from kilo.decision_layer.context_builder import ProjectContextBuilder

    with tempfile.TemporaryDirectory() as tmp:
        # Create a couple of files
        os.makedirs(os.path.join(tmp, "src"))
        with open(os.path.join(tmp, "src", "App.tsx"), "w") as f:
            f.write("export default function App() {}")
        with open(os.path.join(tmp, "index.html"), "w") as f:
            f.write("<!DOCTYPE html>")

        builder = ProjectContextBuilder(tmp)
        tree = builder.get_file_tree()

    assert "App.tsx" in tree
    assert "index.html" in tree
    assert "File Tree" in tree


# ---------------------------------------------------------------------------
# 9. ProjectContextBuilder — read file
# ---------------------------------------------------------------------------

def test_context_builder_read_file():
    """read_file returns correct content for an existing file."""
    from kilo.decision_layer.context_builder import ProjectContextBuilder

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        fpath = os.path.join(src, "main.ts")
        with open(fpath, "w") as f:
            f.write("console.log('hello');\n")

        builder = ProjectContextBuilder(tmp)
        content = builder.read_file("src/main.ts")

    assert "console.log" in content
    assert "main.ts" in content


def test_context_builder_read_file_not_found():
    """read_file returns a graceful error for missing files."""
    from kilo.decision_layer.context_builder import ProjectContextBuilder

    with tempfile.TemporaryDirectory() as tmp:
        builder = ProjectContextBuilder(tmp)
        result = builder.read_file("nonexistent/file.tsx")

    assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# 10. ProjectContextBuilder — search
# ---------------------------------------------------------------------------

def test_context_builder_search():
    """search_files finds content matching the query."""
    from kilo.decision_layer.context_builder import ProjectContextBuilder

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "src"))
        with open(os.path.join(tmp, "src", "AuthPage.tsx"), "w") as f:
            f.write("export function AuthPage() { return <div>Login</div>; }")

        builder = ProjectContextBuilder(tmp)
        result = builder.search_files("auth")

    assert "AuthPage" in result or "auth" in result.lower()


# ---------------------------------------------------------------------------
# 11. Second-pass decision with context
# ---------------------------------------------------------------------------

def test_second_pass_decision_with_context():
    """decide_with_context works correctly and passes context to the prompt."""
    svc = _service_with({
        "intent": "modify_project",
        "confidence": 0.92,
        "reason": "Modify after reading context.",
        "requires_project_context": False,
        "context_requests": [],
        "target_files": ["src/Button.tsx"],
        "proposed_action": "Add loading state to Button.tsx.",
        "route": "project_modification_path",
    })
    result = _run(
        svc.decide_with_context(
            "Make the submit button use loading state",
            has_project=True,
            project_context="### File Tree\nsrc/Button.tsx\nsrc/Form.tsx",
        )
    )
    assert result["intent"] == "modify_project"
    assert result["route"] == "project_modification_path"


# ---------------------------------------------------------------------------
# 12. _extract_json helper
# ---------------------------------------------------------------------------

def test_extract_json_from_markdown_fence():
    """_extract_json correctly strips markdown code fences."""
    from kilo.decision_layer.service import _extract_json

    fenced = '```json\n{"intent": "normal_chat", "route": "normal_chat_path"}\n```'
    result = _extract_json(fenced)
    assert result == '{"intent": "normal_chat", "route": "normal_chat_path"}'


def test_extract_json_returns_empty_for_no_brace():
    from kilo.decision_layer.service import _extract_json
    assert _extract_json("no braces here") == ""
