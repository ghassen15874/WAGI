"""
ContextCollector
================
Scans a sandbox directory and returns a structured project context dict:

    {
        "backend": {
            "routes":      [relative paths],
            "controllers": [relative paths],
            "models":      [relative paths],
        },
        "database": {
            "schema":      [relative paths],
            "migrations":  [relative paths],
            "seed":        [relative paths],
        },
        "frontend": {
            "pages":       [relative paths],
            "components":  [relative paths],
            "router":      [relative paths],   # App.tsx, router files
        },
        "api_base": "/api",                    # detected from vite.config.ts
        "sandbox_dir": "...",
    }

Pure read-only — no writes, no side-effects, never raises.
"""

import os
import re
import logging

logger = logging.getLogger(__name__)


class ContextCollector:
    """
    Collects project-structure context from a sandbox directory.

    Usage:
        ctx = ContextCollector(sandbox_dir).collect()
    """

    def __init__(self, sandbox_dir: str):
        self.sandbox_dir = sandbox_dir

    def collect(self) -> dict:
        """Return the full structured context dict."""
        try:
            return {
                "backend":     self._collect_backend(),
                "database":    self._collect_database(),
                "frontend":    self._collect_frontend(),
                "api_base":    self._detect_api_base(),
                "sandbox_dir": self.sandbox_dir,
            }
        except Exception as exc:
            logger.error(f"[ContextCollector] collect() failed: {exc}")
            return {
                "backend":     {"routes": [], "controllers": [], "models": []},
                "database":    {"schema": [], "migrations": [], "seed": []},
                "frontend":    {"pages": [], "components": [], "router": []},
                "api_base":    "/api",
                "sandbox_dir": self.sandbox_dir,
            }

    # ── Backend ───────────────────────────────────────────────────────────────

    def _collect_backend(self) -> dict:
        return {
            "routes":      self._list_files("server/routes",      ".ts"),
            "controllers": self._list_files("server/controllers", ".ts"),
            "models":      self._list_files("server/models",      ".ts"),
        }

    # ── Database ──────────────────────────────────────────────────────────────

    def _collect_database(self) -> dict:
        schema_files = (
            self._list_files("server/db",   ".ts")
            + self._list_files("server/db", ".sql")
            + self._list_files("server",    ".ts", name_filter="database")
        )
        return {
            "schema":     schema_files,
            "migrations": self._list_files("server/migrations", ".ts") + self._list_files("server/migrations", ".sql"),
            "seed":       self._list_files("server/db", ".ts", name_filter="seed")
                          + self._list_files("server",  ".ts", name_filter="seed"),
        }

    # ── Frontend ──────────────────────────────────────────────────────────────

    def _collect_frontend(self) -> dict:
        # BUG FIX: Each _list_files call was duplicated (called twice and concatenated),
        # producing doubled lists. Each call should appear exactly once.
        return {
            "pages":      self._list_files("src/pages",      ".tsx"),
            "components": self._list_files("src/components", ".tsx"),
            "router":     (
                self._list_files("src", ".tsx", name_filter="app")
                + self._list_files("src", ".tsx", name_filter="router")
            ),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _list_files(self, rel_dir: str, ext: str, name_filter: str = None) -> list:
        """
        Return relative paths (from sandbox_dir) of all files matching ext
        inside rel_dir. If name_filter is set, only include files whose
        lowercase name contains the filter string.
        """
        full_dir = os.path.join(self.sandbox_dir, rel_dir)
        if not os.path.isdir(full_dir):
            return []
        result = []
        try:
            for fname in sorted(os.listdir(full_dir)):
                if not fname.endswith(ext):
                    continue
                if name_filter and name_filter.lower() not in fname.lower():
                    continue
                result.append(os.path.join(rel_dir, fname))
        except PermissionError:
            pass
        return result

    def _detect_api_base(self) -> str:
        """Detect API base URL from vite.config.ts proxy target, defaults to /api."""
        vite_cfg = os.path.join(self.sandbox_dir, "vite.config.ts")
        if not os.path.exists(vite_cfg):
            return "/api"
        try:
            with open(vite_cfg, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            m = re.search(r"target:\s*['\"]http[s]?://[^'\"]+:(\d+)['\"]", content)
            if m:
                return f"http://localhost:{m.group(1)}/api"
        except Exception:
            pass
        return "/api"

    def get_schema_content(self) -> str:
        """
        Return the concatenated content of detected schema/database files.
        Used by db_fix_engine to understand current schema.
        """
        ctx = self._collect_database()
        parts = []
        for rel_path in ctx["schema"] + ctx["migrations"]:
            full = os.path.join(self.sandbox_dir, rel_path)
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    parts.append(f"// === {rel_path} ===\n" + f.read())
            except Exception:
                pass
        return "\n\n".join(parts)

    def get_route_names(self) -> list:
        """Return lowercase route keywords (e.g. ['auth', 'comment', 'post'])."""
        keywords = []
        for rel_path in self._collect_backend()["routes"]:
            stem = os.path.basename(rel_path).lower()
            stem = re.sub(r"routes?\.ts$", "", stem).strip()
            if stem:
                keywords.append(stem)
        return keywords