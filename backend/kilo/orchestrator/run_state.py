from __future__ import annotations

import json
import os
from typing import Any


class GenerationRunStateStore:
    """Persists mutable execution state separately from the build plan."""

    def __init__(self, sandbox_dir: str):
        self.sandbox_dir = sandbox_dir

    def _lovable_dir(self) -> str:
        return os.path.join(self.sandbox_dir, ".lovable")

    def path(self) -> str:
        return os.path.join(self._lovable_dir(), "run_state.json")

    def load(self) -> dict[str, Any]:
        candidate = self.path()
        if not os.path.exists(candidate):
            return {}
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def save(self, payload: dict[str, Any]) -> None:
        os.makedirs(self._lovable_dir(), exist_ok=True)
        filtered = {
            key: value
            for key, value in dict(payload or {}).items()
            if key != "planner"
        }
        filtered.setdefault("plan_path", ".lovable/plan.json")
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump(filtered, handle, indent=2)

    def clear(self) -> None:
        candidate = self.path()
        if os.path.exists(candidate):
            try:
                os.remove(candidate)
            except Exception:
                pass
