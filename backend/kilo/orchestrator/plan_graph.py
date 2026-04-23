from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .plan_paths import compiled_core_paths
from .project_spec import ProjectSpec


def _normalize_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("./").lower()


def _is_shared_hub_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return normalized in {
        "package.json",
        "vite.config.ts",
        "tsconfig.json",
        "tsconfig.node.json",
        "index.html",
        ".env",
        ".gitignore",
        "src/main.tsx",
        "src/app.tsx",
        "src/styles/variables.css",
        "src/styles/global.css",
        "src/services/api.ts",
        "src/types/index.ts",
        "server/index.ts",
        "server/db/database.ts",
    }


def _is_frontend_leaf_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return normalized.startswith(
        (
            "src/pages/",
            "src/components/",
            "src/hooks/",
            "src/services/",
            "src/context/",
        )
    )


def _is_backend_leaf_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return normalized.startswith(
        (
            "server/controllers/",
            "server/routes/",
            "server/middleware/",
            "server/utils/",
            "server/lib/",
        )
    )


class ExecutionPlanGraph:
    """Relationship graph derived from the execution contract."""

    def __init__(self, tasks: list[Any], project_spec: ProjectSpec | None):
        self.tasks = sorted(list(tasks or []), key=lambda task: (int(getattr(task, "id", 0) or 0), str(getattr(task, "path", "") or "")))
        self.project_spec = project_spec
        self._task_by_path: dict[str, Any] = {}
        self._tasks_by_unit: dict[str, list[Any]] = defaultdict(list)
        self._reverse_dependencies: dict[str, list[Any]] = defaultdict(list)
        self._api_providers: dict[str, list[Any]] = defaultdict(list)
        self._api_consumers: dict[str, list[Any]] = defaultdict(list)

        for task in self.tasks:
            normalized = _normalize_path(getattr(task, "path", ""))
            if not normalized:
                continue
            self._task_by_path[normalized] = task
            self._tasks_by_unit[str(getattr(task, "unit_id", "batch_core") or "batch_core")].append(task)
            for api in list(getattr(task, "api_endpoints_provided", []) or []):
                clean_api = str(api or "").strip()
                if clean_api:
                    self._api_providers[clean_api].append(task)
            for api in list(getattr(task, "api_endpoints_used", []) or []):
                clean_api = str(api or "").strip()
                if clean_api:
                    self._api_consumers[clean_api].append(task)

        for task in self.tasks:
            for raw_dep in list(getattr(task, "depends_on", []) or []):
                normalized_dep = _normalize_path(raw_dep)
                if normalized_dep in self._task_by_path:
                    self._reverse_dependencies[normalized_dep].append(task)

    def _task_contract(self, task: Any) -> dict[str, Any]:
        return {
            "path": str(getattr(task, "path", "") or ""),
            "unit_id": str(getattr(task, "unit_id", "batch_core") or "batch_core"),
            "imports": list(getattr(task, "imports", []) or []),
            "exports": list(getattr(task, "exports", []) or []),
            "functions": list(getattr(task, "functions", []) or []),
            "variables": list(getattr(task, "variables", []) or []),
            "api_endpoints_used": list(getattr(task, "api_endpoints_used", []) or []),
            "api_endpoints_provided": list(getattr(task, "api_endpoints_provided", []) or []),
            "depends_on": list(getattr(task, "depends_on", []) or []),
        }

    def _include_shared_context(self, included: set[str]) -> None:
        if not included:
            return

        include_frontend = any(path.startswith("src/") for path in included)
        include_backend = any(path.startswith("server/") for path in included)
        include_ui_shell = any(
            path.startswith(("src/pages/", "src/components/", "src/hooks/", "src/context/", "src/services/"))
            for path in included
        )

        if include_frontend:
            for path in ("src/types/index.ts", "src/services/api.ts"):
                normalized = _normalize_path(path)
                if normalized in self._task_by_path:
                    included.add(normalized)

        if include_ui_shell:
            for path in ("src/app.tsx", "src/main.tsx", "src/styles/variables.css", "src/styles/global.css"):
                normalized = _normalize_path(path)
                if normalized in self._task_by_path:
                    included.add(normalized)

        if include_backend:
            for path in ("server/index.ts", "server/db/database.ts"):
                normalized = _normalize_path(path)
                if normalized in self._task_by_path:
                    included.add(normalized)

    def connected_paths(
        self,
        seed_paths: list[str],
        *,
        include_unit: bool = True,
        include_dependencies: bool = True,
        include_dependents: bool = True,
        include_api: bool = True,
    ) -> list[str]:
        queue: deque[str] = deque()
        seen_seed: set[str] = set()

        for raw_path in list(seed_paths or []):
            normalized = _normalize_path(raw_path)
            if normalized and normalized in self._task_by_path and normalized not in seen_seed:
                seen_seed.add(normalized)
                queue.append(normalized)

        included: set[str] = set()
        while queue:
            normalized = queue.popleft()
            if normalized in included:
                continue
            task = self._task_by_path.get(normalized)
            if task is None:
                continue

            included.add(normalized)
            unit_id = str(getattr(task, "unit_id", "batch_core") or "batch_core")

            if include_unit:
                for peer in self._tasks_by_unit.get(unit_id, []):
                    peer_normalized = _normalize_path(getattr(peer, "path", ""))
                    if peer_normalized and peer_normalized not in included:
                        queue.append(peer_normalized)

            if include_dependencies:
                for raw_dep in list(getattr(task, "depends_on", []) or []):
                    dep_normalized = _normalize_path(raw_dep)
                    if dep_normalized in self._task_by_path and dep_normalized not in included:
                        queue.append(dep_normalized)

            if _is_shared_hub_path(normalized):
                continue

            if include_dependents:
                for dependent in self._reverse_dependencies.get(normalized, []):
                    dependent_normalized = _normalize_path(getattr(dependent, "path", ""))
                    if dependent_normalized and dependent_normalized not in included:
                        queue.append(dependent_normalized)

            if include_api:
                related_apis = set(
                    str(api or "").strip()
                    for api in (
                        list(getattr(task, "api_endpoints_used", []) or [])
                        + list(getattr(task, "api_endpoints_provided", []) or [])
                    )
                    if str(api or "").strip()
                )
                for api in related_apis:
                    for related in self._api_providers.get(api, []) + self._api_consumers.get(api, []):
                        related_normalized = _normalize_path(getattr(related, "path", ""))
                        if related_normalized and related_normalized not in included:
                            queue.append(related_normalized)

        self._include_shared_context(included)
        return [
            str(getattr(task, "path", "") or "")
            for task in self.tasks
            if _normalize_path(getattr(task, "path", "")) in included
        ]

    def _unit_stage(self, paths: list[str]) -> str:
        normalized = [_normalize_path(path) for path in paths if _normalize_path(path)]
        if not normalized:
            return "architecture"

        managed = {_normalize_path(path) for path in compiled_core_paths(self.project_spec)}
        if all(path in managed for path in normalized):
            return "scaffold"

        frontend_count = sum(1 for path in normalized if path.startswith("src/"))
        backend_count = sum(1 for path in normalized if path.startswith("server/"))
        if backend_count and not frontend_count:
            return "backend"
        if frontend_count and not backend_count:
            return "frontend"
        return "architecture"

    def _unit_contract(self, unit_id: str, included: set[str]) -> dict[str, Any] | None:
        tasks = [
            task
            for task in self._tasks_by_unit.get(unit_id, [])
            if _normalize_path(getattr(task, "path", "")) in included
        ]
        if not tasks:
            return None

        depends_on_units: list[str] = []
        seen_units: set[str] = set()
        used_apis: list[str] = []
        provided_apis: list[str] = []

        for task in tasks:
            for raw_dep in list(getattr(task, "depends_on", []) or []):
                dep_task = self._task_by_path.get(_normalize_path(raw_dep))
                dep_unit = str(getattr(dep_task, "unit_id", "") or "")
                if dep_task and dep_unit and dep_unit != unit_id and dep_unit not in seen_units:
                    seen_units.add(dep_unit)
                    depends_on_units.append(dep_unit)
            for api in list(getattr(task, "api_endpoints_used", []) or []):
                clean_api = str(api or "").strip()
                if clean_api and clean_api not in used_apis:
                    used_apis.append(clean_api)
            for api in list(getattr(task, "api_endpoints_provided", []) or []):
                clean_api = str(api or "").strip()
                if clean_api and clean_api not in provided_apis:
                    provided_apis.append(clean_api)

        return {
            "id": unit_id,
            "name": unit_id.replace("batch_", "").replace("_", " ").title() or "Core",
            "stage": self._unit_stage([str(getattr(task, "path", "") or "") for task in tasks]),
            "paths": [str(getattr(task, "path", "") or "") for task in tasks],
            "depends_on_units": depends_on_units,
            "api_endpoints_used": used_apis,
            "api_endpoints_provided": provided_apis,
        }

    def _relationships_for_paths(self, paths: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        included = {_normalize_path(path) for path in list(paths or []) if _normalize_path(path)}
        relationships: list[dict[str, Any]] = []
        external_relationships: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()

        def add_edge(target_list: list[dict[str, Any]], source: str, target: str, kind: str, detail: str = "") -> None:
            key = (_normalize_path(source), _normalize_path(target), kind, detail)
            if not key[0] or not key[1] or key in seen:
                return
            seen.add(key)
            payload = {"source": source, "target": target, "type": kind}
            if detail:
                payload["detail"] = detail
            target_list.append(payload)

        for task in self.tasks:
            source_path = str(getattr(task, "path", "") or "")
            source_normalized = _normalize_path(source_path)
            if source_normalized not in included:
                continue

            for raw_dep in list(getattr(task, "depends_on", []) or []):
                dep_task = self._task_by_path.get(_normalize_path(raw_dep))
                target_path = str(getattr(dep_task, "path", raw_dep) or raw_dep)
                target_list = relationships if _normalize_path(target_path) in included else external_relationships
                add_edge(target_list, source_path, target_path, "depends_on")

            for item in list(getattr(task, "imports", []) or []):
                if not isinstance(item, dict):
                    continue
                target_path = str(item.get("target", "") or "").strip()
                if not target_path:
                    continue
                detail = str(item.get("role", "") or item.get("mode", "") or "").strip()
                target_list = relationships if _normalize_path(target_path) in included else external_relationships
                add_edge(target_list, source_path, target_path, "imports", detail=detail)

            for api in list(getattr(task, "api_endpoints_used", []) or []):
                clean_api = str(api or "").strip()
                if not clean_api:
                    continue
                for provider in self._api_providers.get(clean_api, []):
                    target_path = str(getattr(provider, "path", "") or "")
                    if not target_path:
                        continue
                    target_list = relationships if _normalize_path(target_path) in included else external_relationships
                    add_edge(target_list, source_path, target_path, "uses_api", detail=clean_api)

        return relationships, external_relationships

    def slice_for_paths(self, paths: list[str], *, current_paths: list[str] | None = None) -> dict[str, Any]:
        connected_paths = self.connected_paths(paths)
        included = {_normalize_path(path) for path in connected_paths if _normalize_path(path)}
        current = [
            str(path or "").strip().replace("\\", "/")
            for path in list(current_paths or paths or [])
            if str(path or "").strip()
        ]
        relationships, external_relationships = self._relationships_for_paths(connected_paths)

        blueprint = [
            self._task_contract(task)
            for task in self.tasks
            if _normalize_path(getattr(task, "path", "")) in included
        ]
        unit_ids: list[str] = []
        seen_units: set[str] = set()
        for task in self.tasks:
            normalized = _normalize_path(getattr(task, "path", ""))
            unit_id = str(getattr(task, "unit_id", "batch_core") or "batch_core")
            if normalized in included and unit_id not in seen_units:
                seen_units.add(unit_id)
                unit_ids.append(unit_id)

        units = [
            unit
            for unit in (self._unit_contract(unit_id, included) for unit_id in unit_ids)
            if unit is not None
        ]

        api_contracts: list[dict[str, str]] = []
        seen_api_contracts: set[tuple[str, str]] = set()
        for relationship in relationships:
            if relationship.get("type") != "uses_api":
                continue
            endpoint = str(relationship.get("detail", "") or "").strip()
            provider_path = str(relationship.get("target", "") or "").strip()
            key = (endpoint, provider_path)
            if endpoint and provider_path and key not in seen_api_contracts:
                seen_api_contracts.add(key)
                api_contracts.append({"endpoint": endpoint, "provided_by": provider_path})

        related_types = [
            {
                "path": str(getattr(task, "path", "") or ""),
                "exports": list(getattr(task, "exports", []) or []),
            }
            for task in self.tasks
            if _normalize_path(getattr(task, "path", "")).startswith("src/types/")
            and _normalize_path(getattr(task, "path", "")) in included
        ]

        shared_files = [
            str(getattr(task, "path", "") or "")
            for task in self.tasks
            if _normalize_path(getattr(task, "path", "")) in included
            and _is_shared_hub_path(getattr(task, "path", ""))
        ]

        return {
            "current_files": [path for path in current if _normalize_path(path) in included],
            "blueprint": blueprint,
            "units": units,
            "relationships": relationships,
            "external_relationships": external_relationships,
            "shared_files": shared_files,
            "api_contracts": api_contracts,
            "related_types": related_types,
            "project_spec": self.project_spec.to_dict() if self.project_spec else {},
        }

    def editable_context_files(self, paths: list[str]) -> list[str]:
        seed = [
            str(path or "").strip().replace("\\", "/")
            for path in list(paths or [])
            if str(path or "").strip()
        ]
        if not seed:
            return []

        normalized_seed = {_normalize_path(path) for path in seed}
        if not any(path and not _is_shared_hub_path(path) for path in normalized_seed):
            return []

        connected = self.connected_paths(seed)
        connected_set = {_normalize_path(path) for path in connected if _normalize_path(path)}

        has_frontend_leaf = any(_is_frontend_leaf_path(path) for path in normalized_seed)
        has_backend_leaf = any(_is_backend_leaf_path(path) for path in normalized_seed)
        has_page = any(_normalize_path(path).startswith("src/pages/") for path in seed)
        has_ui_surface = any(
            _normalize_path(path).startswith(("src/pages/", "src/components/"))
            for path in seed
        )

        desired: list[str] = []
        if has_frontend_leaf:
            desired.extend(
                [
                    "src/types/index.ts",
                    "src/services/api.ts",
                ]
            )
        if has_ui_surface:
            desired.extend(
                [
                    "src/styles/variables.css",
                    "src/styles/global.css",
                ]
            )
        if has_page:
            desired.extend(
                [
                    "src/App.tsx",
                    "src/main.tsx",
                ]
            )
        if has_backend_leaf:
            desired.extend(
                [
                    "server/index.ts",
                    "server/db/database.ts",
                ]
            )
        if has_backend_leaf and has_frontend_leaf:
            desired.extend(
                [
                    "src/types/index.ts",
                    "src/services/api.ts",
                ]
            )

        extras: list[str] = []
        seen: set[str] = set()
        desired_set = {_normalize_path(path) for path in desired}
        for task in self.tasks:
            path = str(getattr(task, "path", "") or "")
            normalized = _normalize_path(path)
            if (
                normalized
                and normalized in desired_set
                and normalized in connected_set
                and normalized not in normalized_seed
                and normalized not in seen
            ):
                seen.add(normalized)
                extras.append(path)
        return extras
