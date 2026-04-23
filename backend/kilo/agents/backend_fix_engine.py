"""
BackendFixEngine
================
Generates fix actions for backend-layer root causes.

Each action:
    {"type": "create|update", "file": "<relative path>", "content": "<code>"}

Supported fix_strategy values:
    fix_route       → patch server/index.ts route registration
    fix_controller  → patch controller export
    add_dependency  → add missing package to package.json
    fix_syntax      → flag file for AI re-generation (no blind overwrite)
    fix_runtime     → flag file for AI re-generation
    fix_port        → patch server/index.ts to use process.env.PORT
    unknown         → no-op (returns empty list)

Never raises — all methods wrapped in try/except.
"""

import os
import re
import json
import logging

logger = logging.getLogger(__name__)


# ── Templates ──────────────────────────────────────────────────────────────────

_ROUTE_STUB_TEMPLATE = """\
// {route_file} — auto-generated stub by BackendFixEngine
// TODO: Replace with real route logic
const express = require('express');
const router  = express.Router();

router.get('/', (req, res) => res.json({{ message: 'OK' }}));

module.exports = router;
"""

_CONTROLLER_STUB_TEMPLATE = """\
// {controller_file} — auto-generated stub by BackendFixEngine
// TODO: Replace with real controller logic

exports.getAll = async (req, res) => {{
  try {{
    res.json([]);
  }} catch (err) {{
    res.status(500).json({{ error: err.message }});
  }}
}};

exports.create = async (req, res) => {{
  try {{
    res.status(201).json({{ message: 'created' }});
  }} catch (err) {{
    res.status(500).json({{ error: err.message }});
  }}
}};
"""


class BackendFixEngine:
    """
    Generates backend fix actions from a root-cause dict.

    Usage:
        engine = BackendFixEngine(sandbox_dir)
        actions = engine.generate_backend_fix(root_cause, context)
    """

    def __init__(self, sandbox_dir: str):
        self.sandbox_dir = sandbox_dir

    def generate_backend_fix(self, root_cause: dict, context: dict) -> list:
        """
        Main entry point.

        Args:
            root_cause: Structured decision/fix payload from the active triage pipeline
            context:    Output of ContextCollector.collect()

        Returns:
            List of action dicts.
        """
        strategy = root_cause.get("fix_strategy", "unknown")
        raw_errors = root_cause.get("raw_errors", [])
        combined_error = " ".join(raw_errors)

        try:
            if strategy == "fix_route":
                return self._fix_route(combined_error, context)
            elif strategy == "fix_controller":
                return self._fix_controller(combined_error, context)
            elif strategy == "add_dependency":
                return self._add_dependency(combined_error, context)
            elif strategy in ("fix_syntax", "fix_runtime"):
                return self._flag_for_ai_fix(combined_error, context)
            elif strategy == "fix_port":
                return self._fix_port(context)
            else:
                logger.info(f"[BackendFixEngine] No action for strategy='{strategy}', delegating to AI fallback")
                targets = root_cause.get("target_files", [])
                target_file = targets[0] if targets else "server/index.ts"
                return [{
                    "type":         "ai_fix_required",
                    "file":         target_file,
                    "content":      "",
                    "error_detail": combined_error[:500],
                }]
        except Exception as exc:
            logger.error(f"[BackendFixEngine] generate_backend_fix raised: {exc}")
            return []

    # ── Strategies ─────────────────────────────────────────────────────────────

    def _fix_route(self, error: str, context: dict) -> list:
        """
        If a route stub is missing, create it and note that server/index.ts may
        need a registration line. We do NOT overwrite server/index.ts blindly.
        """
        actions = []
        # Try to extract the missing endpoint from the error
        m = re.search(r"Cannot GET (/api/[\w/]+)", error, re.IGNORECASE)
        if m:
            endpoint = m.group(1)          # e.g. /api/posts
            resource = endpoint.split("/")[-1]  # e.g. posts
            route_file = f"server/routes/{resource}Routes.ts"
            full = os.path.join(self.sandbox_dir, route_file)
            if not os.path.exists(full):
                actions.append({
                    "type":    "create",
                    "file":    route_file,
                    "content": _ROUTE_STUB_TEMPLATE.format(route_file=route_file),
                    "note":    f"Register in server/index.ts: app.use('/api/{resource}', require('./routes/{resource}Routes'))",
                })
        return actions

    def _fix_controller(self, error: str, context: dict) -> list:
        """
        Create a stub controller for any controller file referenced in the error
        that is missing or has undefined exports.
        """
        actions = []
        # Match e.g. "server/controllers/postController.ts"
        for m in re.finditer(r"server/controllers/([\w]+\.ts)", error, re.IGNORECASE):
            ctrl_file = f"server/controllers/{m.group(1)}"
            full = os.path.join(self.sandbox_dir, ctrl_file)
            if not os.path.exists(full):
                actions.append({
                    "type":    "create",
                    "file":    ctrl_file,
                    "content": _CONTROLLER_STUB_TEMPLATE.format(controller_file=ctrl_file),
                })
        return actions

    def _add_dependency(self, error: str, context: dict) -> list:
        """
        Add a missing package to package.json dependencies.
        Only safe to do if we can identify the package name from the error.
        """
        actions = []
        pkg_json_path = os.path.join(self.sandbox_dir, "package.json")
        if not os.path.exists(pkg_json_path):
            return []

        # Extract package name from "Cannot find module 'X'" or "Can't resolve 'X'"
        m = re.search(r"Cannot find module '([^'./][^']*)'|Can't resolve '([^'./][^']*)'", error)
        if not m:
            return []
        pkg_name = (m.group(1) or m.group(2)).split("/")[0]  # handle scoped @scope/pkg

        try:
            with open(pkg_json_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        deps = pkg.get("dependencies", {})
        dev_deps = pkg.get("devDependencies", {})
        if pkg_name in deps or pkg_name in dev_deps:
            logger.info(f"[BackendFixEngine] {pkg_name} already in package.json — skipping")
            return []

        deps[pkg_name] = "latest"
        pkg["dependencies"] = deps
        actions.append({
            "type":    "update",
            "file":    "package.json",
            "content": json.dumps(pkg, indent=2),
            "note":    f"Added '{pkg_name}' to dependencies. Run npm install.",
        })
        return actions

    def _fix_port(self, context: dict) -> list:
        """
        Patch server/index.ts to use process.env.PORT || 5000 instead of a hardcoded port.
        """
        index_path = os.path.join(self.sandbox_dir, "server", "index.ts")
        if not os.path.exists(index_path):
            return []
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Replace app.listen(...) → app.listen(process.env.PORT || 3001, ...)
            patched = re.sub(
                r"app\.listen\(\d+,",
                "app.listen(process.env.PORT || 3001,",
                content,
                count=1,
            )
            if patched == content:
                return []  # no change needed
            return [{
                "type":    "update",
                "file":    "server/index.ts",
                "content": patched,
                "note":    "Patched app.listen() to use process.env.PORT",
            }]
        except Exception as exc:
            logger.warning(f"[BackendFixEngine] _fix_port failed: {exc}")
            return []

    def _flag_for_ai_fix(self, error: str, context: dict) -> list:
        """
        For syntax/runtime errors we cannot safely auto-patch, return an informational
        action with type='ai_fix_required' so the orchestrator can route to the AI.
        """
        # Extract the most likely broken file from the error
        m = re.search(r"(server/[\w/]+\.ts)", error)
        broken_file = m.group(1) if m else "server/index.ts"
        return [{
            "type":         "ai_fix_required",
            "file":         broken_file,
            "content":      "",
            "error_detail": error[:500],
        }]
