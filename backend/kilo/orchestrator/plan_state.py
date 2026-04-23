from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .plan_paths import compiled_core_paths
from .planner import ExecutionPlanner, ExecutionStatus, ExecutionTask
from .project_spec import ProjectSpec


def _normalize_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


class PlanUnitStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


def _title_from_unit(unit_id: str) -> str:
    text = str(unit_id or "batch_core").strip() or "batch_core"
    return text.replace("batch_", "").replace("_", " ").title() or "Core"


def _unit_stage(paths: list[str], project_spec: ProjectSpec | None) -> str:
    normalized = [_normalize_path(path) for path in paths if _normalize_path(path)]
    if not normalized:
        return "architecture"

    managed = {_normalize_path(path) for path in compiled_core_paths(project_spec)}
    if all(path in managed for path in normalized):
        return "scaffold"

    backend_count = sum(1 for path in normalized if path.startswith("server/"))
    frontend_count = sum(1 for path in normalized if path.startswith("src/"))

    if backend_count and not frontend_count:
        return "backend"
    if frontend_count and not backend_count:
        return "frontend"
    return "architecture"


@dataclass
class PlanUnit:
    id: str
    unit_id: str
    name: str
    stage: str
    paths: list[str] = field(default_factory=list)
    depends_on_units: list[str] = field(default_factory=list)
    api_endpoints_used: list[str] = field(default_factory=list)
    api_endpoints_provided: list[str] = field(default_factory=list)
    status: PlanUnitStatus = PlanUnitStatus.PENDING
    retry_count: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "unit_id": self.unit_id,
            "name": self.name,
            "stage": self.stage,
            "paths": list(self.paths),
            "depends_on_units": list(self.depends_on_units),
            "api_endpoints_used": list(self.api_endpoints_used),
            "api_endpoints_provided": list(self.api_endpoints_provided),
            "status": self.status.value,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanUnit":
        return cls(
            id=str(data.get("id", "") or ""),
            unit_id=str(data.get("unit_id", data.get("batch_name", "")) or ""),
            name=str(data.get("name", "") or ""),
            stage=str(data.get("stage", "architecture") or "architecture"),
            paths=[_normalize_path(path) for path in list(data.get("paths", []) or []) if _normalize_path(path)],
            depends_on_units=[
                str(unit_id).strip()
                for unit_id in list(data.get("depends_on_units", []) or [])
                if str(unit_id).strip()
            ],
            api_endpoints_used=[
                str(item).strip()
                for item in list(data.get("api_endpoints_used", []) or [])
                if str(item).strip()
            ],
            api_endpoints_provided=[
                str(item).strip()
                for item in list(data.get("api_endpoints_provided", []) or [])
                if str(item).strip()
            ],
            status=PlanUnitStatus(str(data.get("status", PlanUnitStatus.PENDING.value) or PlanUnitStatus.PENDING.value)),
            retry_count=max(0, int(data.get("retry_count", 0) or 0)),
            last_error=str(data.get("last_error", "") or ""),
        )


@dataclass
class BuildPlanState:
    prompt: str = ""
    summary: str = ""
    created_at: int = 0
    project_spec: ProjectSpec | None = None
    tasks: list[dict[str, Any]] = field(default_factory=list)
    units: list[PlanUnit] = field(default_factory=list)
    acceptance_checks: list[str] = field(default_factory=list)

    @classmethod
    def from_planner(
        cls,
        planner: ExecutionPlanner,
        *,
        prompt: str = "",
        previous: "BuildPlanState" | None = None,
    ) -> "BuildPlanState":
        previous_units = {
            str(unit.id).strip(): unit
            for unit in (previous.units if previous else [])
            if str(unit.id).strip()
        }

        units = cls._units_from_planner(planner, previous_units=previous_units)
        project_spec = planner.project_spec
        summary = ""
        acceptance_checks: list[str] = []
        if project_spec:
            summary = str(project_spec.summary or "").strip()
            acceptance_checks = list(project_spec.acceptance_checks or [])

        return cls(
            prompt=str(prompt or (previous.prompt if previous else "") or ""),
            summary=summary,
            created_at=int(previous.created_at if previous and previous.created_at else time.time()),
            project_spec=project_spec,
            tasks=[task.to_dict() for task in planner.tasks],
            units=units,
            acceptance_checks=acceptance_checks,
        )

    @staticmethod
    def _unit_status(tasks: list[ExecutionTask]) -> PlanUnitStatus:
        statuses = {task.status for task in tasks}
        if statuses and statuses <= {ExecutionStatus.DONE}:
            return PlanUnitStatus.DONE
        if ExecutionStatus.IN_PROGRESS in statuses:
            return PlanUnitStatus.IN_PROGRESS
        return PlanUnitStatus.PENDING

    @classmethod
    def _units_from_planner(
        cls,
        planner: ExecutionPlanner,
        *,
        previous_units: dict[str, PlanUnit] | None = None,
    ) -> list[PlanUnit]:
        previous_units = previous_units or {}
        task_by_path = {
            ExecutionPlanner._normalize_task_path(task.path): task
            for task in planner.tasks
        }

        grouped: dict[str, list[ExecutionTask]] = {}
        for task in planner.tasks:
            grouped.setdefault(str(task.unit_id or "batch_core"), []).append(task)

        units: list[PlanUnit] = []
        for unit_id, tasks in sorted(grouped.items(), key=lambda pair: min(task.id for task in pair[1])):
            previous = previous_units.get(unit_id)
            depends_on_units: list[str] = []
            seen_dep_units: set[str] = set()
            used_apis: list[str] = []
            provided_apis: list[str] = []
            seen_used_apis: set[str] = set()
            seen_provided_apis: set[str] = set()

            for task in tasks:
                for raw_dep in list(task.depends_on or []):
                    dep_task = task_by_path.get(ExecutionPlanner._normalize_task_path(raw_dep))
                    dep_unit = str(dep_task.unit_id or "") if dep_task else ""
                    if dep_task and dep_unit and dep_unit != unit_id and dep_unit not in seen_dep_units:
                        seen_dep_units.add(dep_unit)
                        depends_on_units.append(dep_unit)
                for api in list(task.api_endpoints_used or []):
                    clean_api = str(api).strip()
                    if clean_api and clean_api not in seen_used_apis:
                        seen_used_apis.add(clean_api)
                        used_apis.append(clean_api)
                for api in list(task.api_endpoints_provided or []):
                    clean_api = str(api).strip()
                    if clean_api and clean_api not in seen_provided_apis:
                        seen_provided_apis.add(clean_api)
                        provided_apis.append(clean_api)

            status = cls._unit_status(tasks)
            if previous and previous.status == PlanUnitStatus.BLOCKED and status != PlanUnitStatus.DONE:
                status = PlanUnitStatus.BLOCKED

            units.append(
                PlanUnit(
                    id=unit_id,
                    unit_id=unit_id,
                    name=_title_from_unit(unit_id),
                    stage=_unit_stage([task.path for task in tasks], planner.project_spec),
                    paths=[_normalize_path(task.path) for task in sorted(tasks, key=lambda entry: entry.id)],
                    depends_on_units=depends_on_units,
                    api_endpoints_used=used_apis,
                    api_endpoints_provided=provided_apis,
                    status=status,
                    retry_count=int(previous.retry_count if previous else 0),
                    last_error=str(previous.last_error if previous else ""),
                )
            )

        return units

    def sync_with_planner(self, planner: ExecutionPlanner, *, prompt: str | None = None) -> None:
        refreshed = BuildPlanState.from_planner(planner, prompt=prompt if prompt is not None else self.prompt, previous=self)
        self.prompt = refreshed.prompt
        self.summary = refreshed.summary
        self.created_at = refreshed.created_at
        self.project_spec = refreshed.project_spec
        self.tasks = refreshed.tasks
        self.units = refreshed.units
        self.acceptance_checks = refreshed.acceptance_checks

    def planner_payload(self) -> dict[str, Any]:
        return {
            "project_spec": self.project_spec.to_dict() if self.project_spec else None,
            "tasks": [dict(task) for task in self.tasks],
        }

    def record_retry(self, paths: list[str], error_text: str) -> None:
        normalized_paths = {
            _normalize_path(path)
            for path in list(paths or [])
            if _normalize_path(path)
        }
        if not normalized_paths:
            return

        error_preview = "\n".join(
            line.strip()
            for line in str(error_text or "").splitlines()
            if line.strip()
        )[:2000]

        for unit in self.units:
            if normalized_paths & set(unit.paths):
                unit.retry_count += 1
                unit.last_error = error_preview
                if unit.status != PlanUnitStatus.DONE:
                    unit.status = PlanUnitStatus.BLOCKED

    def unit_paths_for(self, paths: list[str]) -> list[str]:
        normalized_paths = {
            _normalize_path(path)
            for path in list(paths or [])
            if _normalize_path(path)
        }
        result: list[str] = []
        seen: set[str] = set()
        for unit in self.units:
            if not normalized_paths & set(unit.paths):
                continue
            for path in unit.paths:
                if path not in seen:
                    seen.add(path)
                    result.append(path)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "summary": self.summary,
            "created_at": self.created_at,
            "project_spec": self.project_spec.to_dict() if self.project_spec else None,
            "tasks": [dict(task) for task in self.tasks],
            "units": [unit.to_dict() for unit in self.units],
            "acceptance_checks": list(self.acceptance_checks),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuildPlanState":
        raw_spec = data.get("project_spec")
        raw_tasks = data.get("tasks")

        planner = ExecutionPlanner()
        planner.load_state(
            {
                "project_spec": raw_spec if isinstance(raw_spec, dict) else None,
                "tasks": raw_tasks if isinstance(raw_tasks, list) else [],
            }
        )

        raw_units = data.get("units")
        units = [
            PlanUnit.from_dict(item)
            for item in list(raw_units or [])
            if isinstance(item, dict)
        ]
        if not units:
            units = cls._units_from_planner(planner)

        return cls(
            prompt=str(data.get("prompt", "") or ""),
            summary=str(data.get("summary", "") or ""),
            created_at=max(0, int(data.get("created_at", 0) or 0)),
            project_spec=planner.project_spec,
            tasks=[task.to_dict() for task in planner.tasks],
            units=units,
            acceptance_checks=[
                str(item).strip()
                for item in list(data.get("acceptance_checks", []) or [])
                if str(item).strip()
            ],
        )

    def to_console_report(self) -> str:
        total_files = sum(len(unit.paths) for unit in self.units)
        done_files = sum(len(unit.paths) for unit in self.units if unit.status == PlanUnitStatus.DONE)

        lines = [
            f"EXECUTION PLAN STATUS ({done_files}/{total_files} files complete, {len(self.units)} units)"
        ]
        if self.project_spec:
            lines.append(f"Product Type: {self.project_spec.product_type}")
            lines.append(f"App Kind: {self.project_spec.app_kind}")
        overview = self.summary or (self.project_spec.summary if self.project_spec else "")
        if overview:
            lines.append(f"Summary: {overview}")
        if self.project_spec and self.project_spec.features:
            lines.append("Features: " + ", ".join(self.project_spec.features))
        if self.project_spec and self.project_spec.pages:
            lines.append("Pages: " + ", ".join(f"{page.name} ({page.route})" for page in self.project_spec.pages))
        if self.project_spec and self.project_spec.api_resources:
            lines.append(
                "API Resources: "
                + ", ".join(f"{resource.name} ({resource.route})" for resource in self.project_spec.api_resources)
            )
        if self.acceptance_checks:
            lines.append("Acceptance Checks: " + "; ".join(self.acceptance_checks[:5]))

        lines.append("UNITS")
        for unit in self.units:
            line = f"{unit.status.value.upper()} {unit.id} [{unit.stage}]"
            if unit.paths:
                line += f" :: {', '.join(unit.paths)}"
            lines.append(line)
            if unit.depends_on_units:
                lines.append("depends_on: " + ", ".join(unit.depends_on_units))
            if unit.retry_count:
                lines.append(f"retries: {unit.retry_count}")
            if unit.last_error:
                preview = unit.last_error.splitlines()[0][:160]
                lines.append(f"last_error: {preview}")

        return "\n".join(lines).strip()

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
