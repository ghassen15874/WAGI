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
            line = str(err or "")
            candidates: list[str] = []

            parts = line.split(":", 1)
            if len(parts) > 1:
                candidates.append(parts[0])

            # Capture every quoted path reference (not only the first one).
            candidates.extend(re.findall(r"['\"]([^'\"]+)['\"]", line))

            # Capture unquoted path-like tokens in messages such as:
            # "... across a.ts, b.ts, c.ts"
            candidates.extend(
                re.findall(r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)", line)
            )

            for candidate in candidates:
                rel_path = self._coerce_safe_error_path(candidate)
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
        def _dedupe(paths: list[str]) -> list[str]:
            result: list[str] = []
            seen_local: set[str] = set()
            for raw_path in list(paths or []):
                candidate = str(raw_path or "").strip().replace("\\", "/")
                if not candidate:
                    continue
                if candidate in seen_local:
                    continue
                seen_local.add(candidate)
                result.append(candidate)
            return result

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
        lowered_message = message.lower()
        is_style_contract_failure = (
            "styling contract validation failed" in lowered_message
            or "stylesheet_class_" in lowered_message
            or "tailwind_runtime_missing" in lowered_message
        )

        if is_style_contract_failure:
            seed_paths = extracted_paths or normalized_current
            retry_candidates: list[str] = []
            retry_candidates.extend(seed_paths)
            retry_candidates.extend(self.planning.get_cluster_for_paths(seed_paths))

            style_owners = [
                "src/styles/global.css",
                "src/styles/variables.css",
                "src/styles/globals.css",
            ]
            if "tailwind_runtime_missing" in lowered_message:
                style_owners.extend(
                    [
                        "package.json",
                        "tailwind.config.js",
                        "tailwind.config.cjs",
                        "tailwind.config.ts",
                        "postcss.config.js",
                        "postcss.config.cjs",
                    ]
                )
            for owner in style_owners:
                retry_candidates.extend(self.planning.get_cluster_for_paths([owner]))
                retry_candidates.append(owner)

            resolved = _dedupe(retry_candidates)
            if resolved:
                return resolved

        if "BLUEPRINT_NOT_ENFORCED" in message:
            seed_paths = extracted_paths or normalized_current
            retry_candidates: list[str] = []
            retry_candidates.extend(seed_paths)
            retry_candidates.extend(self.planning.get_cluster_for_paths(seed_paths))

            scoped = self.planning.build_scoped_blueprint(seed_paths)
            for relation in list(scoped.get("relationships") or []):
                if not isinstance(relation, dict):
                    continue
                source = self._coerce_safe_error_path(str(relation.get("source", "") or ""))
                target = self._coerce_safe_error_path(str(relation.get("target", "") or ""))
                if source:
                    retry_candidates.append(source)
                if target:
                    retry_candidates.append(target)

            if any(
                marker in lowered_message
                for marker in (
                    "import_site_error",
                    "blueprint_export_mismatch",
                    "schema_sync_error",
                    "symbol/export drift",
                    "api_contract_drift",
                    "api_response_envelope_mismatch",
                )
            ):
                retry_candidates.extend(
                    [
                        "src/types/index.ts",
                        "src/services/api.ts",
                        "src/context/AuthContext.tsx",
                        "server/db/database.ts",
                    ]
                )

            resolved = _dedupe(retry_candidates)
            if resolved:
                return resolved

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
