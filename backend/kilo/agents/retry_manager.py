"""
retry_manager.py — Sandbox-scoped retry state

BUG FIX: The original implementation stored retry_attempts.json next to the
module file (a global path). This meant retry counts from one project bled
into another: if project A exhausted retries for 'server/index.ts', project B
would immediately skip healing that file.

Fix: All functions now accept an optional sandbox_dir parameter. When
provided, the attempts file is stored inside the sandbox. When not provided
(for backward compatibility) it falls back to a temp-dir-scoped file based
on the module path, but this should always be called with sandbox_dir.
"""

import json
import os
from typing import List


def _attempts_path(sandbox_dir: str = None) -> str:
    """
    Return the path for the retry_attempts.json file.
    Sandbox-scoped when sandbox_dir is provided; falls back to module-level
    location for backward compatibility (but this mixes projects — avoid it).
    """
    if sandbox_dir:
        return os.path.join(sandbox_dir, ".lovable", "retry_attempts.json")
    # Legacy fallback: stored next to this module (NOT recommended — mixes projects)
    return os.path.join(os.path.dirname(__file__), "retry_attempts.json")


def _load_attempts(sandbox_dir: str = None) -> dict:
    path = _attempts_path(sandbox_dir)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_attempts(data: dict, sandbox_dir: str = None) -> None:
    path = _attempts_path(sandbox_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def record_attempt(file_path: str, strategy: str, sandbox_dir: str = None) -> None:
    data = _load_attempts(sandbox_dir)
    if file_path not in data:
        data[file_path] = []
    data[file_path].append(strategy)
    _save_attempts(data, sandbox_dir)


def get_attempts(file_path: str, sandbox_dir: str = None) -> List[str]:
    data = _load_attempts(sandbox_dir)
    return data.get(file_path, [])


def should_skip(strategy: str, attempts: List[str]) -> bool:
    if len(attempts) >= 3:
        return True
    if strategy in attempts:
        return True
    return False


def reset_attempts(sandbox_dir: str = None) -> None:
    """Clear all retry state for a sandbox. Call at the start of a new generation."""
    path = _attempts_path(sandbox_dir)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass