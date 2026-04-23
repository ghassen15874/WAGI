from __future__ import annotations

import re

from .planning_service import PlanningService
from ..shared.write_guard import is_safe_generated_path, normalize_generated_path


class PlanRepairService:
    """Maps failures back to plan units and narrows retries to the affected scope."""

    def __init__(self, planning: PlanningService):
        self.planning = planning

    def extract_phase_error_paths(self, errors: list[str], fallback_paths: list[str]) -> list[str]:
        targets: list[str] = []
        seen: set[str] = set()

        for err in errors:
            rel_path = ""
            parts = str(err or "").split(":", 1)
            if len(parts) > 1:
                rel_path = self._coerce_safe_error_path(parts[0])
            if not rel_path:
                for quoted_candidate in re.findall(r"['\"]([^'\"]+)['\"]", str(err or "")):
                    rel_path = self._coerce_safe_error_path(quoted_candidate)
                    if rel_path:
                        break
            if rel_path and rel_path not in seen:
                seen.add(rel_path)
                targets.append(rel_path)

        if targets:
            return targets

        for path in fallback_paths:
            clean = str(path or "").strip().replace("\\", "/")
            if clean and clean not in seen:
                seen.add(clean)
                targets.append(clean)
        return targets

    def _coerce_safe_error_path(self, raw_path: str) -> str:
        candidate = normalize_generated_path(
            str(raw_path or "").strip().lstrip("-* ").strip("`'\" ")
        )
        if candidate and is_safe_generated_path(candidate):
            return candidate
        return ""

    def extract_blueprint_scope_cluster(self, text: str) -> list[str]:
        cluster_paths: list[str] = []
        seen: set[str] = set()

        for line in str(text or "").splitlines():
            match = re.search(
                r"Rewrite the full connected blueprint contract cluster together:\s*(.+)",
                line,
                re.IGNORECASE,
            )
            if not match:
                continue

            for raw_path in match.group(1).split(","):
                normalized = str(raw_path or "").strip().lstrip("-* ").strip().replace("\\", "/")
                if not normalized or not normalized.startswith(("src/", "server/")) or normalized in seen:
                    continue
                seen.add(normalized)
                cluster_paths.append(normalized)

        return cluster_paths

    def determine_retry_batch(self, error_text: str, current_batch: list[str]) -> list[str]:
        normalized_current = [
            str(path or "").strip().replace("\\", "/")
            for path in list(current_batch or [])
            if str(path or "").strip()
        ]
        if not normalized_current:
            return []

        explicit_cluster = self.extract_blueprint_scope_cluster(error_text)
        if explicit_cluster:
            return explicit_cluster

        partial_match = re.search(r"Missing files:\s*(.+)", str(error_text or ""), re.IGNORECASE | re.DOTALL)
        if partial_match:
            raw_missing = partial_match.group(1).splitlines()[0]
            requested = [part.strip().replace("\\", "/") for part in raw_missing.split(",") if part.strip()]
            retry = [path for path in normalized_current if path in requested]
            if retry:
                return retry

        error_lines = [line.strip() for line in str(error_text or "").splitlines() if line.strip()]
        extracted_paths = self.extract_phase_error_paths(error_lines, [])
        if not extracted_paths:
            return normalized_current

        message = str(error_text or "")
        if "BLUEPRINT_NOT_ENFORCED" in message:
            cluster_paths = self.planning.get_cluster_for_paths(extracted_paths)
            cluster_set = {
                str(path or "").strip().replace("\\", "/").lower().lstrip("./")
                for path in list(cluster_paths or [])
                if str(path or "").strip()
            }
            scoped = self.planning.build_scoped_blueprint(extracted_paths)
            current_lookup = {
                str(path or "").strip().replace("\\", "/").lower().lstrip("./"): path
                for path in normalized_current
            }
            adjacency: dict[str, set[str]] = {}
            for relation in list(scoped.get("relationships") or []):
                if not isinstance(relation, dict):
                    continue
                source = str(relation.get("source", "") or "").strip().replace("\\", "/").lower().lstrip("./")
                target = str(relation.get("target", "") or "").strip().replace("\\", "/").lower().lstrip("./")
                if source not in current_lookup or target not in current_lookup:
                    continue
                adjacency.setdefault(source, set()).add(target)
                adjacency.setdefault(target, set()).add(source)

            queue = [
                str(path or "").strip().replace("\\", "/").lower().lstrip("./")
                for path in extracted_paths
                if str(path or "").strip().replace("\\", "/").lower().lstrip("./") in current_lookup
            ]
            seen: set[str] = set()
            focused_norms: set[str] = set()
            while queue:
                node = queue.pop(0)
                if node in seen:
                    continue
                seen.add(node)
                focused_norms.add(node)
                for neighbor in sorted(adjacency.get(node, set())):
                    if neighbor not in seen:
                        queue.append(neighbor)

            focused_retry = [
                path
                for path in normalized_current
                if str(path or "").strip().replace("\\", "/").lower().lstrip("./") in focused_norms
            ]
            seed_norms = {
                str(path or "").strip().replace("\\", "/").lower().lstrip("./")
                for path in extracted_paths
                if str(path or "").strip()
            }
            contract_prefixes = (
                "server/",
                "src/services/",
                "src/hooks/",
                "src/types/",
                "src/context/",
                "src/utils/",
                "src/store/",
            )
            focused_retry = [
                path
                for path in focused_retry
                if (
                    str(path or "").strip().replace("\\", "/").lower().lstrip("./") in seed_norms
                    or str(path or "").strip().replace("\\", "/").lower().lstrip("./").startswith(contract_prefixes)
                )
            ]
            if not focused_retry:
                focused_retry = [
                    path
                    for path in normalized_current
                    if str(path or "").strip().replace("\\", "/").lower().lstrip("./") in cluster_set
                ]
            if focused_retry:
                return focused_retry

        if "BLUEPRINT_SCOPE_FAILURE" in message:
            cluster_paths = self.planning.get_cluster_for_paths(extracted_paths)
            if cluster_paths:
                return cluster_paths

        direct_retry = [path for path in normalized_current if path in extracted_paths]
        if direct_retry:
            return direct_retry

        cluster_paths = self.planning.get_cluster_for_paths(extracted_paths)
        cluster_set = {str(path).strip().replace("\\", "/") for path in cluster_paths if str(path).strip()}
        retry = [path for path in normalized_current if path in cluster_set]
        if retry:
            return retry

        retry = [str(path).strip().replace("\\", "/") for path in extracted_paths if str(path).strip()]
        return retry or normalized_current
