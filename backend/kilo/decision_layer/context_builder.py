"""
Decision Layer — Project Context Builder

Collects various types of project context for the Decision Layer's second pass.
All methods operate on the project's sandbox directory and are safe (read-only).

Wraps existing codebase systems:
  - ast_extractor  (orchestrator/ast_extractor.py)
  - ProjectMapManager (orchestrator/project_map.py)

Memory is loaded from .lovable/memory.json if it exists.
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger("decision_layer.context_builder")

# Maximum sizes to avoid flooding the LLM context window
MAX_FILE_CONTENT_CHARS = 8_000
MAX_SEARCH_RESULTS = 10
MAX_TREE_LINES = 200


class ProjectContextBuilder:
    """
    Collects and returns project context strings for the Decision Layer.

    Parameters
    ----------
    sandbox_dir:
        Absolute path to the project's sandbox directory.
    """

    def __init__(self, sandbox_dir: str) -> None:
        self.sandbox_dir = sandbox_dir

    # ------------------------------------------------------------------
    # Individual context collectors
    # ------------------------------------------------------------------

    def get_file_tree(self) -> str:
        """Return a text representation of the project file tree."""
        if not os.path.isdir(self.sandbox_dir):
            return "Project directory not found."

        lines: list[str] = []
        skip_dirs = {"node_modules", ".git", "dist", "__pycache__", ".lovable", "venv", ".pytest_cache"}

        for root, dirs, files in os.walk(self.sandbox_dir):
            dirs[:] = sorted(d for d in dirs if d not in skip_dirs and not d.startswith("."))
            rel_root = os.path.relpath(root, self.sandbox_dir)
            depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
            indent = "  " * depth
            folder_name = os.path.basename(root) if rel_root != "." else "."
            if rel_root != ".":
                lines.append(f"{indent}{folder_name}/")

            for fname in sorted(files):
                lines.append(f"{'  ' * (depth + 1)}{fname}")

            if len(lines) >= MAX_TREE_LINES:
                lines.append("  ... (truncated)")
                break

        return "### File Tree\n" + "\n".join(lines)

    def read_file(self, relative_path: str) -> str:
        """Read and return a single project file's content."""
        # Sanitize path — no directory traversal
        clean = os.path.normpath(relative_path).lstrip(os.sep)
        full_path = os.path.join(self.sandbox_dir, clean)

        if not full_path.startswith(os.path.realpath(self.sandbox_dir)):
            return f"Error: path traversal not allowed: {relative_path}"

        if not os.path.isfile(full_path):
            return f"File not found: {relative_path}"

        try:
            with open(full_path, encoding="utf-8", errors="ignore") as handle:
                content = handle.read(MAX_FILE_CONTENT_CHARS)
            truncated = os.path.getsize(full_path) > MAX_FILE_CONTENT_CHARS
            suffix = "\n... (truncated)" if truncated else ""
            return f"### {relative_path}\n```\n{content}{suffix}\n```"
        except Exception as exc:
            return f"Error reading {relative_path}: {exc}"

    def search_files(self, query: str, target: str = "") -> str:
        """
        Search for files whose name or content matches *query* or *target*.
        Returns a summary of matching files (paths + first matching line).
        """
        term = (target or query).lower().strip()
        if not term:
            return "No search term provided."

        results: list[str] = []
        skip_dirs = {"node_modules", ".git", "dist", "__pycache__", ".lovable", "venv"}

        for root, dirs, files in os.walk(self.sandbox_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for fname in files:
                if len(results) >= MAX_SEARCH_RESULTS:
                    break
                rel_path = os.path.relpath(os.path.join(root, fname), self.sandbox_dir)
                # Match on filename
                if term in fname.lower():
                    results.append(f"- {rel_path}  [filename match]")
                    continue
                # Match on content (read first 4 KB only)
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as handle:
                        snippet = handle.read(4096)
                    if term in snippet.lower():
                        # Find first matching line
                        for line in snippet.splitlines():
                            if term in line.lower():
                                preview = line.strip()[:120]
                                results.append(f"- {rel_path}: `{preview}`")
                                break
                except Exception:
                    continue

        if not results:
            return f"No files found matching: {term!r}"

        return f"### Search Results for {term!r}\n" + "\n".join(results)

    def get_ast_summary(self) -> str:
        """Return the AST architecture summary using the existing ast_extractor."""
        try:
            from ..orchestrator.ast_extractor import ast_extractor  # type: ignore
            from ..orchestrator.ai_context_builder import AIContextBuilder  # type: ignore
            from ..orchestrator.project_map import ProjectMapManager  # type: ignore

            project_map = ProjectMapManager(self.sandbox_dir)
            builder = AIContextBuilder(project_map)
            context = builder.build_context(compact=True)
            return f"### AST / Dependency Summary\n{context}" if context.strip() else "No AST data available."
        except Exception as exc:
            logger.debug("[context_builder] AST summary unavailable: %s", exc)
            return "AST summary not available."

    def get_dependency_graph(self) -> str:
        """Return the dependency graph from ProjectMapManager."""
        try:
            from ..orchestrator.project_map import ProjectMapManager  # type: ignore

            project_map = ProjectMapManager(self.sandbox_dir)
            summary = project_map.get_summary_for_ai()
            return f"### Dependency Graph\n{summary}"
        except Exception as exc:
            logger.debug("[context_builder] Dependency graph unavailable: %s", exc)
            return "Dependency graph not available."

    def get_memory(self) -> str:
        """
        Load project memory/notes from .lovable/memory.json if it exists.
        Returns a formatted string or a 'not available' message.
        """
        memory_path = os.path.join(self.sandbox_dir, ".lovable", "memory.json")
        if not os.path.isfile(memory_path):
            return "Project memory: not available."
        try:
            with open(memory_path, encoding="utf-8") as handle:
                data = json.load(handle)
            # Present as a readable text block (max 2000 chars)
            text = json.dumps(data, indent=2)[:2000]
            return f"### Project Memory\n```json\n{text}\n```"
        except Exception as exc:
            return f"Project memory: could not read ({exc})."

    # ------------------------------------------------------------------
    # Bulk fulfillment
    # ------------------------------------------------------------------

    def fulfill_context_requests(self, requests: list[dict]) -> str:
        """
        Fulfill a list of ContextRequest dicts and return a combined context string.

        This is the main entry point called by the Decision Router.
        """
        parts: list[str] = []

        for req in requests:
            req_type = str(req.get("type", "")).lower()
            query = str(req.get("query", ""))
            target = str(req.get("target", ""))

            if req_type == "file_tree":
                parts.append(self.get_file_tree())

            elif req_type == "read_file":
                path = target or query
                if path:
                    parts.append(self.read_file(path))
                else:
                    parts.append("read_file: no target path specified.")

            elif req_type == "search":
                parts.append(self.search_files(query=query, target=target))

            elif req_type == "ast":
                parts.append(self.get_ast_summary())

            elif req_type == "dependency_graph":
                parts.append(self.get_dependency_graph())

            elif req_type == "memory":
                parts.append(self.get_memory())

            elif req_type == "command":
                # Commands (e.g. grep) are not executed for safety; return a note.
                parts.append(f"[command not executed for safety: {query}]")

            else:
                parts.append(f"[unknown context request type: {req_type}]")

        return "\n\n".join(filter(None, parts))


__all__ = ["ProjectContextBuilder"]
