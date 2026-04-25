# Thin adapter — delegates to FilesystemBackend and ShellTool for command execution.
import os
import shutil
import json
import re
import shlex
from pathlib import PurePosixPath

try:
    from .filesystem import FilesystemBackend as _RealFilesystemBackend
except Exception:
    _RealFilesystemBackend = None

from .shell_tools import ShellTool
from ..shared.write_guard import is_safe_generated_path, normalize_generated_file_content


class ToolRegistry:
    """
    Tool registry that delegates file operations to the real
    FilesystemBackend pattern from filesystem_ref.py (735 lines).

    Provides the execute(tool_name, params) API that loop.py depends on.
    """

    # Re-export real class for introspection
    _RealBackend = _RealFilesystemBackend

    def __init__(self, base_dir: str = None, file_tool=None):
        """
        Args:
            base_dir: Sandbox directory for file operations.
            file_tool: Legacy FileTool instance (ignored, kept for compat).
        """
        if base_dir is None and file_tool is not None:
            base_dir = str(getattr(file_tool, 'sandbox_dir', '.'))
        self.base_dir = base_dir or '.'
        os.makedirs(self.base_dir, exist_ok=True)

        self._shell = ShellTool(self.base_dir)

    def _normalize_safe_relative_path(self, path: str) -> str:
        normalized = str(path or "").strip().replace("\\", "/")
        if not normalized or normalized in {"unknown.txt", "."}:
            return ""
        if os.path.isabs(normalized):
            return ""

        parts = PurePosixPath(normalized).parts
        if any(part == ".." for part in parts):
            return ""
        return normalized

    def _is_safe_relative_path(self, path: str) -> bool:
        return bool(self._normalize_safe_relative_path(path))

    def _targets_reserved_ports_for_kill(self, command: str) -> bool:
        """
        Guardrail: never allow commands that attempt to terminate services
        on system-reserved ports 8080 or 5173.
        """
        cmd = str(command or "")
        lowered = cmd.lower()

        kill_like = any(token in lowered for token in ("fuser -k", "kill ", "pkill", "killall"))
        if not kill_like:
            return False

        reserved_patterns = (
            r"(?<!\d)8080(?!\d)",
            r"(?<!\d)5173(?!\d)",
            r":8080\b",
            r":5173\b",
            r"8080/tcp\b",
            r"5173/tcp\b",
        )
        return any(re.search(pattern, lowered) for pattern in reserved_patterns)

    def _validate_batch_entries(self, files: list[dict], allowed_paths: list[str] | None = None) -> tuple[list[dict], list[str]]:
        errors: list[str] = []
        normalized_files: list[dict] = []
        seen_paths: set[str] = set()
        allowed_set = {
            normalized
            for raw_path in list(allowed_paths or [])
            if (normalized := self._normalize_safe_relative_path(raw_path))
        }

        for item in files:
            path = self._normalize_safe_relative_path((item or {}).get("path", ""))
            content = str((item or {}).get("content", "") or "")

            if not path:
                errors.append(f"Invalid or implicit file path: '{path}'")
                continue
            if not is_safe_generated_path(path):
                errors.append(f"Unsafe or malformed generated file path: {path}")
                continue
            if allowed_set and path not in allowed_set:
                errors.append(f"Unexpected file outside current batch: {path}")
                continue
            if path in seen_paths:
                errors.append(f"Duplicate file path in batch: {path}")
                continue

            seen_paths.add(path)
            normalized_content, _notes = normalize_generated_file_content(path, content)
            normalized_files.append({"path": path, "content": normalized_content})

        return normalized_files, errors

    async def execute(self, tool_name: str, params: dict) -> str:
        if tool_name == "write_file":
            path = params.get("path", "")
            content = params.get("content", "")
            full = os.path.join(self.base_dir, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"✓ wrote {path} ({len(content)} chars)"

        elif tool_name == "write_batch":
            files = list(params.get("files", []) or [])
            allowed_paths = list(params.get("allowed_paths", []) or [])
            normalized_files, errors = self._validate_batch_entries(files, allowed_paths=allowed_paths)
            if errors:
                return "Error: write_batch validation failed\n" + "\n".join(f"- {err}" for err in errors[:20])

            written = []
            for item in normalized_files:
                path = item["path"]
                content = item["content"]
                full = os.path.join(self.base_dir, path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(content)
                written.append(path)

            return json.dumps({"status": "ok", "written": written})

        elif tool_name == "read_file":
            path = params.get("path", "")
            full = os.path.join(self.base_dir, path)
            if not os.path.exists(full):
                return f"Error: {path} not found"
            with open(full, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

        elif tool_name in ("ls", "list_files"):
            path = params.get("path", ".")
            full = os.path.join(self.base_dir, path)
            if not os.path.isdir(full):
                return f"Error: {path} is not a directory"
            entries = sorted(os.listdir(full))
            return "\n".join(entries) if entries else "(empty)"

        elif tool_name == "grep":
            import re as _re
            pattern = params.get("pattern", "")
            path = params.get("path", ".")
            full = os.path.join(self.base_dir, path)
            results = []
            for root, _dirs, files in os.walk(full):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                if pattern in line:
                                    rel = os.path.relpath(fpath, self.base_dir)
                                    results.append(f"{rel}:{i}: {line.rstrip()}")
                    except (IsADirectoryError, PermissionError):
                        continue
            return "\n".join(results[:50]) if results else "(no matches)"

        elif tool_name in ("execute_command", "shell"):
            command = params.get("command", "")
            if self._targets_reserved_ports_for_kill(command):
                return (
                    "Error: Command blocked by safety policy. "
                    "Killing processes on reserved ports 8080 and 5173 is not allowed."
                )
            return await self._shell.execute(
                command,
                params.get("timeout", 30)
            )

        elif tool_name == "clear_sandbox":
            def _sync_clear():
                if not os.path.exists(self.base_dir):
                    os.makedirs(self.base_dir, exist_ok=True)
                    return
                
                for item in os.listdir(self.base_dir):
                    if item == ".lovable":
                        # Preserve logs but clear other things in .lovable if needed?
                        # For now, just keep the whole .lovable dir
                        continue
                        
                    item_path = os.path.join(self.base_dir, item)
                    try:
                        if os.path.isfile(item_path) or os.path.islink(item_path):
                            os.unlink(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                    except Exception as e:
                        print(f"Error clearing {item_path}: {e}")
                        
            import asyncio
            await asyncio.to_thread(_sync_clear)
            return "sandbox cleared (logs preserved)"

        elif tool_name == "backend_validator":
            script_path = os.path.join(os.path.dirname(__file__), "backend_validator.js")
            # Run the backend validator against the sandbox directory
            return await self._shell.execute(f"node '{script_path}' '{self.base_dir}'", timeout=90)

        elif tool_name == "browser_check":
            script_path = os.path.join(os.path.dirname(__file__), "browser_check.js")
            frontend_port = int(params.get("frontend_port", 3000) or 3000)
            required_routes = list(params.get("required_routes", []) or [])
            required_api = list(params.get("required_api", []) or [])
            require_theme_toggle = bool(params.get("require_theme_toggle", False))
            theme_storage_key = str(params.get("theme_storage_key", "theme") or "theme").strip() or "theme"

            env_exports = [
                f"FRONTEND_PREVIEW_PORT={frontend_port}",
                f"REQUIRED_ROUTES_JSON={shlex.quote(json.dumps(required_routes))}",
                f"REQUIRED_API_JSON={shlex.quote(json.dumps(required_api))}",
                f"REQUIRE_THEME_TOGGLE={'1' if require_theme_toggle else '0'}",
                f"THEME_STORAGE_KEY={shlex.quote(theme_storage_key)}",
            ]
            # Run the frontend browser check
            return await self._shell.execute(
                f"{' '.join(env_exports)} node '{script_path}'",
                timeout=45,
            )

        else:
            return f"Unknown tool: {tool_name}"

    def get_descriptions(self) -> str:
        return """Available tools:
  write_file(path, content) — write file to sandbox
  write_batch(files) — atomically validate and write a batch of files
  read_file(path) — read file from sandbox
  ls(path) — list directory contents
  grep(pattern, path) — search in files
  execute_command(command, timeout) — run shell command
  clear_sandbox() — clear all generated files
  backend_validator() — validate backend runtime and db seeding
  browser_check() — validate frontend UI locally"""
