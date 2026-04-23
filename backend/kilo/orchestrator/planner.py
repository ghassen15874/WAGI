from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .project_spec import (
    ProjectSpec,
    compile_file_blueprint,
    infer_project_spec,
    parse_project_spec_response,
)
from .plan_graph import ExecutionPlanGraph


async def _collect_provider_text(provider, messages, model_id: str, status_hook=None) -> str:
    """Collect only model text while routing provider status tokens elsewhere."""
    from ..providers import is_provider_status_token

    chunks: list[str] = []
    async for token in provider.stream(messages, model_id):
        if is_provider_status_token(token):
            if status_hook:
                result = status_hook(token)
                if inspect.isawaitable(result):
                    await result
            continue
        chunks.append(token)
    return "".join(chunks)


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass
class ExecutionTask:
    id: int
    path: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    unit_id: str = "batch_core"
    imports: list[dict[str, Any]] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    api_endpoints_used: list[str] = field(default_factory=list)
    api_endpoints_provided: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path = self._normalize_builder_path(self.path)

    @staticmethod
    def _normalize_builder_path(path: str) -> str:
        raw_path = str(path or "").strip().replace("\\", "/")
        lower_path = raw_path.lower()
        if any(prefix in lower_path for prefix in ("src/components", "src/pages", "src/context", "src/hooks", "src/layouts")):
            return re.sub(r"\.(ts|jsx|js)$", ".tsx", raw_path, flags=re.IGNORECASE)
        if any(prefix in lower_path for prefix in ("src/services", "src/utils", "src/store", "src/types")):
            return re.sub(r"\.(tsx|jsx|js)$", ".ts", raw_path, flags=re.IGNORECASE)
        if lower_path.startswith("server/"):
            return re.sub(r"\.(js|tsx|jsx)$", ".ts", raw_path, flags=re.IGNORECASE)
        if lower_path == "vite.config.js":
            return "vite.config.ts"
        return raw_path

    @property
    def is_done(self) -> bool:
        return self.status == ExecutionStatus.DONE

    def mark_done(self) -> None:
        self.status = ExecutionStatus.DONE

    def mark_in_progress(self) -> None:
        self.status = ExecutionStatus.IN_PROGRESS

    def mark_pending(self) -> None:
        self.status = ExecutionStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "status": self.status.value,
            "unit_id": self.unit_id,
            "imports": list(self.imports),
            "exports": list(self.exports),
            "functions": list(self.functions),
            "variables": list(self.variables),
            "api_endpoints_used": list(self.api_endpoints_used),
            "api_endpoints_provided": list(self.api_endpoints_provided),
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionTask":
        return cls(
            id=max(1, int(data.get("id", 1) or 1)),
            path=str(data.get("path", data.get("task", "")) or ""),
            status=ExecutionStatus(str(data.get("status", ExecutionStatus.PENDING.value) or ExecutionStatus.PENDING.value)),
            unit_id=str(data.get("unit_id", data.get("batch_name", "batch_core")) or "batch_core"),
            imports=[dict(item) for item in list(data.get("imports", []) or []) if isinstance(item, dict)],
            exports=[str(item) for item in list(data.get("exports", []) or []) if str(item).strip()],
            functions=[str(item) for item in list(data.get("functions", []) or []) if str(item).strip()],
            variables=[str(item) for item in list(data.get("variables", []) or []) if str(item).strip()],
            api_endpoints_used=[str(item) for item in list(data.get("api_endpoints_used", []) or []) if str(item).strip()],
            api_endpoints_provided=[str(item) for item in list(data.get("api_endpoints_provided", []) or []) if str(item).strip()],
            depends_on=[str(item) for item in list(data.get("depends_on", []) or []) if str(item).strip()],
        )


class ExecutionPlanner:
    """Single execution-plan owner for planning, batching, and scoped retries."""

    DEFAULT_PLANNING_TIMEOUT_SECONDS = 30.0
    REASONING_MODEL_PLANNING_TIMEOUT_SECONDS = 45.0

    def __init__(self) -> None:
        self.project_spec: ProjectSpec | None = None
        self._tasks: list[ExecutionTask] = []
        self._next_id = 1
        self._graph: ExecutionPlanGraph | None = None

    @staticmethod
    def _normalize_task_path(path: str) -> str:
        return str(path or "").strip().lower().lstrip("./").replace("\\", "/")

    @staticmethod
    def _design_summary(design) -> dict[str, str]:
        return {
            "category": str(getattr(design, "category", "") or "").strip(),
            "style": str(getattr(getattr(design, "style", None), "name", "") or "").strip(),
            "pattern": str(getattr(getattr(design, "pattern", None), "name", "") or "").strip(),
        }

    def to_state(self) -> dict[str, Any]:
        return {
            "project_spec": self.project_spec.to_dict() if self.project_spec else None,
            "tasks": [task.to_dict() for task in self._tasks],
        }

    def load_state(self, data: dict[str, Any]) -> None:
        raw_spec = data.get("project_spec") or data.get("contract")
        raw_tasks = data.get("tasks") or data.get("execution_tasks")

        if not isinstance(raw_tasks, list):
            raw_tasks = data.get("files")

        if not isinstance(raw_tasks, list):
            raw_tasks = []
            for feature in list(data.get("features", []) or []):
                if not isinstance(feature, dict):
                    continue
                for item in list(feature.get("files", []) or []):
                    if isinstance(item, dict):
                        raw_tasks.append(item)

        self.project_spec = ProjectSpec.from_dict(raw_spec) if isinstance(raw_spec, dict) else None
        self._tasks = [ExecutionTask.from_dict(item) for item in raw_tasks if isinstance(item, dict)]
        self._next_id = max((task.id for task in self._tasks), default=0) + 1
        self._graph = None

    def load_contract(
        self,
        project_spec: ProjectSpec,
        contract_items: list[dict[str, Any]] | None = None,
    ) -> None:
        self.project_spec = project_spec
        self._tasks = []
        self._next_id = 1
        self._graph = None

        items = [
            dict(item)
            for item in list(contract_items or compile_file_blueprint(project_spec))
            if isinstance(item, dict) and str(item.get("path", "") or "").strip()
        ]

        for item in items:
            unit_id = str(item.get("unit_id", item.get("batch_name", "batch_core")) or "batch_core").strip() or "batch_core"
            self._tasks.append(
                ExecutionTask(
                    id=self._next_id,
                    path=str(item.get("path", "") or "").strip(),
                    unit_id=unit_id,
                    imports=[dict(entry) for entry in list(item.get("imports", []) or []) if isinstance(entry, dict)],
                    exports=[str(entry) for entry in list(item.get("exports", []) or []) if str(entry).strip()],
                    functions=[str(entry) for entry in list(item.get("functions", []) or []) if str(entry).strip()],
                    variables=[str(entry) for entry in list(item.get("variables", []) or []) if str(entry).strip()],
                    api_endpoints_used=[str(entry) for entry in list(item.get("api_endpoints_used", []) or []) if str(entry).strip()],
                    api_endpoints_provided=[str(entry) for entry in list(item.get("api_endpoints_provided", []) or []) if str(entry).strip()],
                    depends_on=[str(entry) for entry in list(item.get("depends_on", []) or []) if str(entry).strip()],
                )
            )
            self._next_id += 1

    def _plan_graph(self) -> ExecutionPlanGraph:
        if self._graph is None:
            self._graph = ExecutionPlanGraph(self._tasks, self.project_spec)
        return self._graph

    async def _create_project_spec(
        self,
        prompt: str,
        design,
        provider,
        model_id: str,
        *,
        existing_files_summary: str = "",
        status_hook=None,
    ) -> ProjectSpec:
        design_summary = self._design_summary(design)
        design_summary["summary"] = " ".join(
            part for part in (design_summary["category"], design_summary["style"], design_summary["pattern"]) if part
        ).strip()

        existing_block = ""
        if str(existing_files_summary or "").strip():
            existing_block = f"EXISTING REPO FILES:\n{existing_files_summary}\n\n"

        spec_prompt = (
            "You are planning a full-stack React + Vite + Express + SQLite builder run.\n"
            "Return ONLY valid JSON wrapped in ```json```.\n"
            "Describe the minimum complete product contract needed to satisfy the request.\n"
            "Do not invent optional dashboards, auth flows, or filler pages.\n\n"
            f"USER REQUEST:\n{prompt}\n\n"
            f"{existing_block}"
            "DESIGN SIGNALS:\n"
            f"- Category: {design_summary['category']}\n"
            f"- Style: {design_summary['style']}\n"
            f"- Pattern: {design_summary['pattern']}\n\n"
            "JSON schema:\n"
            "{\n"
            '  "product_type": "blog | ecommerce | dashboard | portfolio | landing_page | marketplace | website | custom",\n'
            '  "app_kind": "website | web_app | dashboard | landing_page | blog | ecommerce | marketplace | portfolio",\n'
            '  "summary": "short architecture summary",\n'
            '  "features": ["Blog", "Categories"],\n'
            '  "entities": [\n'
            '    { "name": "Post", "fields": [ { "name": "title", "type": "string", "required": true } ] }\n'
            "  ],\n"
            '  "api_resources": [\n'
            '    { "name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": true, "auth": "public" }\n'
            "  ],\n"
            '  "pages": [\n'
            '    { "name": "Home", "route": "/", "purpose": "primary experience", "auth": "public" }\n'
            "  ],\n"
            '  "auth": { "enabled": false, "mode": "token", "roles": [], "identifiers": ["email"], "allow_registration": true, "login_route": "/api/auth/login", "register_route": "/api/auth/register", "session_route": "/api/auth/me", "state_owner": "src/context/AuthContext.tsx" },\n'
            '  "required_files": [],\n'
            '  "acceptance_checks": ["home page renders", "api route exists"]\n'
            "}\n"
        )

        response = await _collect_provider_text(
            provider,
            [{"role": "user", "content": spec_prompt}],
            model_id,
            status_hook=status_hook,
        )
        return parse_project_spec_response(
            response,
            prompt=prompt,
            feature_lines=[],
            design_summary=design_summary,
        )

    async def create_plan(
        self,
        prompt: str,
        design,
        provider,
        model_id: str = "",
        existing_files_summary: str = "",
        status_hook=None,
        planning_timeout_seconds: float | None = None,
    ) -> None:
        design_summary = self._design_summary(design)
        project_spec: ProjectSpec
        timeout_seconds = planning_timeout_seconds
        if timeout_seconds is None:
            normalized_model = str(model_id or "").strip().lower()
            timeout_seconds = (
                self.REASONING_MODEL_PLANNING_TIMEOUT_SECONDS
                if any(token in normalized_model for token in ("reason", "r1"))
                else self.DEFAULT_PLANNING_TIMEOUT_SECONDS
            )

        try:
            project_spec = await asyncio.wait_for(
                self._create_project_spec(
                    prompt,
                    design,
                    provider,
                    model_id,
                    existing_files_summary=existing_files_summary,
                    status_hook=status_hook,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            if status_hook:
                result = status_hook(
                    f"⚠️ Planning provider timed out after {timeout_seconds:.1f}s. "
                    "Building a deterministic execution contract instead..."
                )
                if inspect.isawaitable(result):
                    await result
            project_spec = infer_project_spec(prompt, [], design_summary=design_summary)
        except Exception as exc:
            if status_hook:
                result = status_hook(
                    f"⚠️ Planning provider failed: {exc}. Building a deterministic execution contract instead..."
                )
                if inspect.isawaitable(result):
                    await result
            project_spec = infer_project_spec(prompt, [], design_summary=design_summary)

        contract_items = compile_file_blueprint(project_spec)
        if not contract_items:
            raise ValueError("execution contract compilation produced no tasks")
        self.load_contract(project_spec, contract_items)

    @property
    def tasks(self) -> list[ExecutionTask]:
        return list(self._tasks)

    @property
    def done_count(self) -> int:
        return sum(1 for task in self._tasks if task.is_done)

    @property
    def total_count(self) -> int:
        return len(self._tasks)

    def mark_done(self, item_id_or_path: int | str) -> None:
        normalized_path = None if isinstance(item_id_or_path, int) else self._normalize_task_path(item_id_or_path)
        for task in self._tasks:
            if isinstance(item_id_or_path, int):
                if task.id == item_id_or_path:
                    task.mark_done()
                    return
            elif self._normalize_task_path(task.path) == normalized_path:
                task.mark_done()
                return

    def mark_pending(self, item_id_or_path: int | str) -> None:
        normalized_path = None if isinstance(item_id_or_path, int) else self._normalize_task_path(item_id_or_path)
        for task in self._tasks:
            if isinstance(item_id_or_path, int):
                if task.id == item_id_or_path:
                    task.mark_pending()
                    return
            elif self._normalize_task_path(task.path) == normalized_path:
                task.mark_pending()
                return

    def all_done(self, feature_errors: list[str] | None = None) -> bool:
        return bool(self._tasks) and all(task.is_done for task in self._tasks) and not feature_errors

    def get_blueprint_files(self) -> list[dict[str, Any]]:
        return [
            {
                "path": task.path,
                "unit_id": task.unit_id,
                "batch_name": task.unit_id,
                "imports": list(task.imports),
                "exports": list(task.exports),
                "functions": list(task.functions),
                "variables": list(task.variables),
                "api_endpoints_used": list(task.api_endpoints_used),
                "api_endpoints_provided": list(task.api_endpoints_provided),
                "depends_on": list(task.depends_on),
            }
            for task in self._tasks
        ]

    def _dependencies_ready(
        self,
        task: ExecutionTask,
        task_by_path: dict[str, ExecutionTask],
        done_paths: set[str],
        current_batch_set: set[str],
    ) -> bool:
        for raw_dep in task.depends_on:
            normalized_dep = self._normalize_task_path(raw_dep)
            if normalized_dep in done_paths or normalized_dep in current_batch_set:
                continue
            if normalized_dep in task_by_path:
                return False
        return True

    @staticmethod
    def _is_shared_hub_path(path: str) -> bool:
        normalized = ExecutionPlanner._normalize_task_path(path)
        return normalized in {
            "src/services/api.ts",
            "src/types/index.ts",
            "server/db/database.ts",
            "server/index.ts",
        }

    def _should_traverse_cluster_edge(self, seed: ExecutionTask, source: ExecutionTask, target: ExecutionTask) -> bool:
        source_path = self._normalize_task_path(source.path)
        target_path = self._normalize_task_path(target.path)
        if source.unit_id == target.unit_id:
            return True
        if source.unit_id == seed.unit_id or target.unit_id == seed.unit_id:
            return True
        if self._is_shared_hub_path(source_path) or self._is_shared_hub_path(target_path):
            return False
        return True

    def _pending_cluster_for_seed(
        self,
        seed: ExecutionTask,
        pending_by_path: dict[str, ExecutionTask],
        pending_by_unit: dict[str, list[ExecutionTask]],
        reverse_dependencies: dict[str, list[ExecutionTask]],
    ) -> list[ExecutionTask]:
        queue: list[ExecutionTask] = [seed]
        visited: set[str] = set()
        cluster: dict[str, ExecutionTask] = {}

        while queue:
            task = queue.pop(0)
            normalized = self._normalize_task_path(task.path)
            if normalized in visited:
                continue
            visited.add(normalized)

            pending_task = pending_by_path.get(normalized)
            if pending_task:
                cluster[normalized] = pending_task

            for peer in pending_by_unit.get(task.unit_id, []):
                peer_normalized = self._normalize_task_path(peer.path)
                if peer_normalized not in visited:
                    queue.append(peer)

            for raw_dep in task.depends_on:
                dep_task = pending_by_path.get(self._normalize_task_path(raw_dep))
                if dep_task is not None and self._should_traverse_cluster_edge(seed, task, dep_task):
                    queue.append(dep_task)

            for dependent in reverse_dependencies.get(normalized, []):
                dependent_pending = pending_by_path.get(self._normalize_task_path(dependent.path))
                if dependent_pending is not None and self._should_traverse_cluster_edge(seed, task, dependent_pending):
                    queue.append(dependent_pending)

        return sorted(cluster.values(), key=lambda task: (task.id, task.unit_id, task.path))

    def get_smart_batch(self, batch_cap: int | None = None) -> list[str]:
        pending_tasks = [task for task in self._tasks if not task.is_done]
        if not pending_tasks:
            return []

        pending_tasks = sorted(pending_tasks, key=lambda task: task.id)
        pending_by_path = {
            self._normalize_task_path(task.path): task
            for task in pending_tasks
        }
        pending_by_unit: dict[str, list[ExecutionTask]] = {}
        for task in pending_tasks:
            pending_by_unit.setdefault(task.unit_id, []).append(task)
        reverse_dependencies: dict[str, list[ExecutionTask]] = {}
        for task in pending_tasks:
            for raw_dep in task.depends_on:
                dep_normalized = self._normalize_task_path(raw_dep)
                if dep_normalized not in pending_by_path:
                    continue
                reverse_dependencies.setdefault(dep_normalized, []).append(task)

        done_paths = {
            self._normalize_task_path(task.path)
            for task in self._tasks
            if task.is_done
        }

        candidate_clusters: list[list[ExecutionTask]] = []
        visited_seed_paths: set[str] = set()
        for seed in pending_tasks:
            seed_normalized = self._normalize_task_path(seed.path)
            if seed_normalized in visited_seed_paths:
                continue
            if not self._dependencies_ready(seed, pending_by_path, done_paths, set()):
                continue
            cluster = self._pending_cluster_for_seed(
                seed,
                pending_by_path,
                pending_by_unit,
                reverse_dependencies,
            )
            if not cluster:
                continue
            candidate_clusters.append(cluster)
            for item in cluster:
                visited_seed_paths.add(self._normalize_task_path(item.path))

        if not candidate_clusters:
            candidate_clusters = [[pending_tasks[0]]]

        def _cluster_score(cluster: list[ExecutionTask]) -> tuple[int, int, int, int]:
            paths = [self._normalize_task_path(task.path) for task in cluster]
            frontend_count = sum(1 for path in paths if path.startswith("src/"))
            backend_count = sum(1 for path in paths if path.startswith("server/"))
            cross_layer = 1 if frontend_count and backend_count else 0
            non_shared = sum(1 for path in paths if not self._is_shared_hub_path(path))
            size = len(cluster)
            earliest_id = -min((int(task.id) for task in cluster), default=0)
            return (cross_layer, non_shared, size, earliest_id)

        selected_cluster = max(candidate_clusters, key=_cluster_score)
        selected_cluster = sorted(selected_cluster, key=lambda task: task.id)
        batch_paths = [task.path for task in selected_cluster]

        if batch_cap and int(batch_cap) > 0 and len(batch_paths) > int(batch_cap):
            batch_paths = batch_paths[: int(batch_cap)]

        # Re-open shared context files when continuing a run, so UI/route owners stay coherent.
        if self.done_count > 0 and batch_paths:
            extras = self._plan_graph().editable_context_files(batch_paths)
            seen_paths = {self._normalize_task_path(path) for path in batch_paths}
            for extra in extras:
                normalized_extra = self._normalize_task_path(extra)
                if normalized_extra and normalized_extra not in seen_paths:
                    seen_paths.add(normalized_extra)
                    batch_paths.append(extra)

        return batch_paths

    def build_scoped_blueprint(self, batch_paths: list[str], depth: int = 1) -> dict[str, Any]:
        return self._plan_graph().slice_for_paths(batch_paths, current_paths=batch_paths)

    def get_cluster_for_file(self, path: str) -> list[str]:
        cluster_paths = self._plan_graph().connected_paths([path])
        return cluster_paths or [path]

    def get_cluster_for_paths(self, paths: list[str]) -> list[str]:
        cluster: list[str] = []
        seen: set[str] = set()
        for raw_path in list(paths or []):
            for path in self.get_cluster_for_file(raw_path):
                normalized = self._normalize_task_path(path)
                if normalized in seen:
                    continue
                seen.add(normalized)
                cluster.append(path)
        return cluster
