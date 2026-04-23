from __future__ import annotations

import json
import os
from typing import Any

from .plan_state import BuildPlanState
from .planner import ExecutionPlanner


class PlanningService:
    """Owns the persisted execution plan and the live planner instance."""

    def __init__(self, sandbox_dir: str, *, planner: ExecutionPlanner | None = None):
        self.sandbox_dir = sandbox_dir
        self.planner = planner or ExecutionPlanner()
        self.state = BuildPlanState()

    def _lovable_dir(self) -> str:
        return os.path.join(self.sandbox_dir, ".lovable")

    def plan_json_path(self) -> str:
        return os.path.join(self._lovable_dir(), "plan.json")

    def clear(self) -> None:
        self.state = BuildPlanState()
        plan_path = self.plan_json_path()
        if os.path.exists(plan_path):
            try:
                os.remove(plan_path)
            except Exception:
                pass

    def persist(self, *, prompt: str | None = None) -> None:
        self.state.sync_with_planner(self.planner, prompt=prompt)
        os.makedirs(self._lovable_dir(), exist_ok=True)
        with open(self.plan_json_path(), "w", encoding="utf-8") as handle:
            handle.write(self.state.dumps())

    def restore(self, *, prompt: str | None = None) -> bool:
        plan_path = self.plan_json_path()
        if not os.path.exists(plan_path):
            return False

        try:
            with open(plan_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                return False
            self.state = BuildPlanState.from_dict(raw)
            self.planner.load_state(self.state.planner_payload())
            if prompt is not None:
                self.state.prompt = str(prompt or "").strip()
            self.persist(prompt=prompt if prompt is not None else self.state.prompt)
            return self.planner.total_count > 0
        except Exception:
            return False

    async def create_plan(
        self,
        prompt: str,
        design,
        provider,
        model_id: str = "",
        *,
        existing_files_summary: str = "",
        status_hook=None,
        planning_timeout_seconds: float | None = None,
    ) -> None:
        await self.planner.create_plan(
            prompt,
            design,
            provider,
            model_id,
            existing_files_summary=existing_files_summary,
            status_hook=status_hook,
            planning_timeout_seconds=planning_timeout_seconds,
        )
        self.persist(prompt=prompt)

    def mark_pending(self, item_id_or_path: int | str) -> None:
        self.planner.mark_pending(item_id_or_path)
        self.persist()

    def mark_done(self, item_id_or_path: int | str) -> None:
        self.planner.mark_done(item_id_or_path)
        self.persist()

    def record_retry(self, paths: list[str], error_text: str) -> None:
        self.state.sync_with_planner(self.planner)
        self.state.record_retry(paths, error_text)
        os.makedirs(self._lovable_dir(), exist_ok=True)
        with open(self.plan_json_path(), "w", encoding="utf-8") as handle:
            handle.write(self.state.dumps())

    @property
    def prompt(self) -> str:
        return self.state.prompt

    @property
    def project_spec(self):
        return self.planner.project_spec

    @property
    def tasks(self):
        return self.planner.tasks

    @property
    def done_count(self) -> int:
        return self.planner.done_count

    @property
    def total_count(self) -> int:
        return self.planner.total_count

    def all_done(self, feature_errors: list[str] | None = None) -> bool:
        return self.planner.all_done(feature_errors=feature_errors)

    def to_state(self) -> dict[str, Any]:
        return self.planner.to_state()

    def get_blueprint_files(self) -> list[dict[str, Any]]:
        return self.planner.get_blueprint_files()

    def get_smart_batch(self, batch_cap: int | None = None) -> list[str]:
        return self.planner.get_smart_batch(batch_cap=batch_cap)

    def build_scoped_blueprint(self, batch_paths: list[str], depth: int = 1) -> dict[str, Any]:
        return self.planner.build_scoped_blueprint(batch_paths, depth=depth)

    def get_cluster_for_file(self, path: str) -> list[str]:
        return self.planner.get_cluster_for_file(path)

    def get_cluster_for_paths(self, paths: list[str]) -> list[str]:
        return self.planner.get_cluster_for_paths(paths)

    def render_console_report(self) -> str:
        self.state.sync_with_planner(self.planner)
        return self.state.to_console_report()
