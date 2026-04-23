import json
import os
import re

from .project_schema import canonical_entity_fields, resource_specs
from .project_spec import ProjectSpec, EntitySpec, _component_name, _pascal, _singular_slug, _slug

BACKEND_ENTRY_FILES = ["server/index.ts"]

class FeatureValidator:
    """
    Detects backend features and ensures corresponding frontend UI exists and is connected.

    BUG FIXES:
    1. _check_frontend_auth_ui(): "Login.tsx" and "Register.tsx" were duplicated
       in the auth_pages list — removed duplicates.
    2. _check_common_standards(): f.endswith((".tsx", ".tsx")) checked .tsx TWICE
       instead of (".tsx", ".ts"), so .ts files were never checked for missing
       hook imports. Fixed to check both extensions.
    """

    def __init__(
        self,
        sandbox_dir: str,
        project_spec: ProjectSpec | None = None,
        backend_port: int = 3001,
    ):
        self.sandbox_dir = sandbox_dir
        self.project_spec = project_spec
        self.backend_port = int(backend_port)
        self.blueprint_items: list[dict[str, object]] = []

    def set_project_spec(
        self,
        project_spec: ProjectSpec | None,
        blueprint_items: list[dict[str, object]] | None = None,
    ) -> None:
        self.project_spec = project_spec
        self.blueprint_items = [
            dict(item)
            for item in list(blueprint_items or [])
            if isinstance(item, dict)
        ]

    @staticmethod
    def _normalize_rel_path(path: str) -> str:
        return str(path or "").strip().replace("\\", "/").lstrip("./")

    def _dedupe_errors(self, errors: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for error in list(errors or []):
            normalized = str(error or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _read_virtual_file(self, rel_path: str, overlay: dict[str, str]) -> str:
        normalized = self._normalize_rel_path(rel_path)
        if normalized in overlay:
            return str(overlay.get(normalized) or "")
        full_path = os.path.join(self.sandbox_dir, normalized)
        if not os.path.exists(full_path):
            return ""
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def _blueprint_contract(self) -> dict[str, object]:
        blueprint_items = list(self.blueprint_items or [])
        export_contracts: dict[str, dict[str, object]] = {}
        for item in blueprint_items:
            rel_path = self._normalize_rel_path(item.get("path", ""))
            if not rel_path:
                continue
            raw_exports = item.get("exports", None)
            if raw_exports is None:
                # No explicit export metadata for this file in blueprint.
                # Treat as "unspecified" instead of "must export nothing".
                continue
            expected_exports = {
                str(export_name).strip()
                for export_name in list(raw_exports or [])
                if str(export_name).strip()
            }
            if not expected_exports:
                # Empty export list from planner metadata is usually "unknown/unspecified",
                # not a strict "no exports allowed" contract.
                continue
            export_contracts[rel_path] = {
                "default": "default" in expected_exports,
                "named": {name for name in expected_exports if name != "default"},
            }

        schema_map: dict[str, set[str]] = {}
        type_fields: dict[str, set[str]] = {}
        file_to_resource: dict[str, str] = {}

        for item in blueprint_items:
            rel_path = self._normalize_rel_path(item.get("path", ""))
            if not rel_path:
                continue
            endpoint_signatures = list(item.get("api_endpoints_provided", []) or []) + list(item.get("api_endpoints_used", []) or [])
            for signature in endpoint_signatures:
                route_name = self._route_name_from_api_signature(signature)
                if route_name:
                    file_to_resource[rel_path] = route_name
                    break

        if self.project_spec and self.project_spec.auth.enabled:
            user_fields = canonical_entity_fields(self.project_spec, EntitySpec(name="User", fields=[]))
            schema_map["users"] = {
                str(field["db"]).strip()
                for field in user_fields
                if field.get("stored")
            }
            type_fields["User"] = {
                str(field["public"]).strip()
                for field in user_fields
                if field.get("expose")
            }
            type_fields["AuthResponse"] = {"user", "token"}
            type_fields["LoginCredentials"] = {"email", "password"}
            if self.project_spec.auth.allow_registration:
                type_fields["RegisterCredentials"] = {"username", "email", "password"}

        for resource_spec in resource_specs(self.project_spec) if self.project_spec else []:
            table = str(resource_spec.get("table") or "").strip()
            fields = list(resource_spec.get("fields") or [])
            resource = resource_spec.get("resource")
            if table:
                schema_map[table] = {
                    str(field["db"]).strip()
                    for field in fields
                    if field.get("stored")
                }
            interface_name = _pascal(resource_spec["entity"].name or resource_spec.get("singular", "Item"))
            type_fields[interface_name] = {
                str(field["public"]).strip()
                for field in fields
                if field.get("expose")
            }
            if resource:
                controller_path, route_path, service_path, hook_path = self._resource_file_paths(resource)
                route_name = self._route_name_from_api_path(getattr(resource, "route", ""))
                for file_path in (controller_path, route_path, service_path, hook_path):
                    file_to_resource.setdefault(self._normalize_rel_path(file_path), route_name)

        return {
            "exports": export_contracts,
            "schema": schema_map,
            "type_fields": type_fields,
            "file_to_resource": file_to_resource,
        }

    def _resolve_internal_import_candidate(
        self,
        importer_rel: str,
        source: str,
        known_paths: set[str],
    ) -> str | None:
        module_spec = str(source or "").strip()
        if not module_spec.startswith("."):
            return None
        if re.search(r"\.(?:css|scss|sass|less|svg|png|jpe?g|gif|webp)$", module_spec, re.IGNORECASE):
            return None

        importer_dir = os.path.dirname(self._normalize_rel_path(importer_rel))
        base_path = os.path.normpath(os.path.join(importer_dir, module_spec)).replace("\\", "/")
        candidates: list[str] = []
        if re.search(r"\.(?:ts|tsx|js|jsx)$", base_path):
            candidates.append(base_path)
        else:
            for ext in (".ts", ".tsx", ".js", ".jsx"):
                candidates.append(base_path + ext)
            for ext in (".ts", ".tsx", ".js", ".jsx"):
                candidates.append(f"{base_path}/index{ext}")

        for candidate in candidates:
            normalized = self._normalize_rel_path(candidate)
            if normalized.startswith("../") or "/../" in normalized:
                continue
            full_path = os.path.join(self.sandbox_dir, normalized)
            if normalized in known_paths or os.path.exists(full_path):
                return normalized
        return None

    def _collect_server_module_exports(self, content: str) -> dict[str, object]:
        exports: dict[str, object] = {
            "default": False,
            "named": set(),
        }
        normalized = str(content or "")
        named = set(re.findall(r"\bexports\.(\w+)\s*=", normalized))

        object_export = re.search(r"\bmodule\.exports\s*=\s*\{(?P<body>[\s\S]*?)\}", normalized)
        if object_export:
            body = object_export.group("body")
            named.update(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?::|,|$)", body))
        elif re.search(r"\bmodule\.exports\s*=", normalized):
            exports["default"] = True

        exports["named"] = named
        return exports

    def _module_exports_for_path(
        self,
        rel_path: str,
        overlay: dict[str, str],
        blueprint_exports: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        normalized = self._normalize_rel_path(rel_path)
        content = self._read_virtual_file(normalized, overlay)
        if content:
            if normalized.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
                frontend_exports = self._collect_frontend_module_exports(content)
                server_exports = self._collect_server_module_exports(content)
                return {
                    "default": bool(frontend_exports.get("default") or server_exports.get("default")),
                    "named": set(frontend_exports.get("named") or set()) | set(server_exports.get("named") or set()),
                }
            if normalized.startswith("src/"):
                return self._collect_frontend_module_exports(content)
            return self._collect_server_module_exports(content)
        return dict(blueprint_exports.get(normalized, {"default": False, "named": set()}))

    def _extract_sql_blocks_from_content(self, content: str) -> list[str]:
        blocks: list[str] = []
        for match in re.finditer(
            r"`([\s\S]*?)`"
            r"|'([^'\n]*?(?:SELECT|INSERT|UPDATE|DELETE)[^'\n]*?)'"
            r"|\"([^\"\n]*?(?:SELECT|INSERT|UPDATE|DELETE)[^\"\n]*?)\"",
            str(content or ""),
            re.IGNORECASE,
        ):
            sql_block = next((group for group in match.groups() if group), "")
            if sql_block:
                blocks.append(sql_block)
        return blocks

    def _check_blueprint_schema_batch(
        self,
        overlay: dict[str, str],
        schema_map: dict[str, set[str]],
    ) -> list[str]:
        if not schema_map:
            return []

        implicit_cols = {"id", "rowid", "created_at", "updated_at", "published_at"}
        errors: list[str] = []
        for rel_path, content in overlay.items():
            if not rel_path.startswith("server/") or not rel_path.endswith(".ts"):
                continue

            for sql_block in self._extract_sql_blocks_from_content(content):
                alias_map = self._parse_sql_aliases(sql_block)

                for table_name, table_cols in schema_map.items():
                    cols_lower = {column.lower() for column in table_cols} | implicit_cols

                    insert_re = re.compile(
                        rf"INSERT\s+INTO\s+{re.escape(table_name)}\s*\(([^)]+)\)",
                        re.IGNORECASE,
                    )
                    for match in insert_re.finditer(sql_block):
                        for raw_column in match.group(1).split(","):
                            column = raw_column.strip()
                            if not column or self._is_sql_literal_or_expression(column):
                                continue
                            if column.lower() not in cols_lower:
                                errors.append(
                                    f"{rel_path}: BLUEPRINT_NOT_ENFORCED: SCHEMA_SYNC_ERROR: "
                                    f"Column '{column}' is not in the blueprint schema for table '{table_name}'. "
                                    f"Allowed columns: {sorted(table_cols)}"
                                )

                    update_re = re.compile(
                        rf"UPDATE\s+{re.escape(table_name)}\s+SET\s+(.*?)(?:\bWHERE\b|$)",
                        re.IGNORECASE | re.DOTALL,
                    )
                    for match in update_re.finditer(sql_block):
                        assignments = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", match.group(1))
                        for column in assignments:
                            if column.lower() not in cols_lower:
                                errors.append(
                                    f"{rel_path}: BLUEPRINT_NOT_ENFORCED: SCHEMA_SYNC_ERROR: "
                                    f"Column '{column}' is not in the blueprint schema for table '{table_name}'. "
                                    f"Allowed columns: {sorted(table_cols)}"
                                )

                for clause_name, pattern in (
                    ("SELECT", r"\bSELECT\b(.*?)(?:\bFROM\b|$)"),
                    ("WHERE", r"\bWHERE\b(.*?)(?:\bORDER\b|\bGROUP\b|\bLIMIT\b|\bHAVING\b|$)"),
                    ("ORDER BY", r"\bORDER\s+BY\b(.*?)(?:\bLIMIT\b|\bOFFSET\b|$)"),
                    ("GROUP BY", r"\bGROUP\s+BY\b(.*?)(?:\bHAVING\b|\bORDER\b|\bLIMIT\b|$)"),
                ):
                    match = re.search(pattern, sql_block, re.IGNORECASE | re.DOTALL)
                    if not match:
                        continue
                    refs = self._extract_sql_column_refs(match.group(1), alias_map, schema_map)
                    for resolved_table, column, _confidence in refs:
                        allowed = {col.lower() for col in schema_map.get(resolved_table, set())} | implicit_cols
                        if column.lower() in allowed:
                            continue
                        errors.append(
                            f"{rel_path}: BLUEPRINT_NOT_ENFORCED: SCHEMA_SYNC_ERROR: "
                            f"Column '{column}' is not in the blueprint schema for table '{resolved_table}' "
                            f"and cannot be used in {clause_name}."
                        )
        return errors

    def _check_blueprint_api_envelope_batch(
        self,
        overlay: dict[str, str],
        file_to_resource: dict[str, str],
    ) -> list[str]:
        errors: list[str] = []
        wrapped_response_pattern = re.compile(
            r"res(?:\.status\([^)]*\))?\.json\s*\(\s*\{(?=[\s\S]{0,300}?\bsuccess\s*:)(?=[\s\S]{0,300}?\bdata\s*:)",
            re.IGNORECASE,
        )

        for rel_path, content in overlay.items():
            route_name = file_to_resource.get(rel_path, "")
            if rel_path.startswith("server/controllers/") and wrapped_response_pattern.search(content):
                errors.append(
                    f"{rel_path}: BLUEPRINT_NOT_ENFORCED: API_RESPONSE_ENVELOPE_MISMATCH: "
                    f"Blueprint-driven resources must return raw data, not a `{{ success, data }}` envelope"
                    + (f" for route '{route_name}'." if route_name else ".")
                )

            if rel_path.startswith("src/") and ".data.data" in str(content or ""):
                errors.append(
                    f"{rel_path}: BLUEPRINT_NOT_ENFORCED: API_RESPONSE_ENVELOPE_MISMATCH: "
                    "Blueprint-driven frontend code must consume raw `response.data`, not `response.data.data`."
                )

        return errors

    def _check_blueprint_symbol_batch(
        self,
        overlay: dict[str, str],
        blueprint_exports: dict[str, dict[str, object]],
    ) -> list[str]:
        errors: list[str] = []
        known_paths = set(blueprint_exports.keys()) | set(overlay.keys())

        for rel_path, content in overlay.items():
            if rel_path.startswith("src/"):
                for entry in self._parse_internal_src_imports(content):
                    source = str(entry.get("source") or "").strip()
                    target_rel = self._resolve_internal_import_candidate(rel_path, source, known_paths)
                    if not target_rel:
                        errors.append(
                            f"{rel_path}: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                            f"Relative import '{source}' does not resolve to a real blueprint file."
                        )
                        continue
                    target_exports = self._module_exports_for_path(target_rel, overlay, blueprint_exports)
                    default_import = str(entry.get("default") or "").strip()
                    named_imports = list(entry.get("named") or [])

                    if default_import and not bool(target_exports.get("default")):
                        errors.append(
                            f"{rel_path}: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                            f"Default import from {target_rel} is invalid because the symbol does not exist in the blueprint export contract."
                        )
                    for imported_name in named_imports:
                        if imported_name not in set(target_exports.get("named") or set()):
                            errors.append(
                                f"{rel_path}: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                                f"Imported symbol '{imported_name}' from {target_rel} does not exist. "
                                "Do not invent types, hooks, or helpers outside the blueprint contract."
                            )
                continue

            if not rel_path.startswith("server/") or not rel_path.endswith(".ts"):
                continue

            destructured_imports = re.findall(
                r"const\s*\{([^}]+)\}\s*=\s*require\(['\"](?P<source>\.[^'\"]+)['\"]\)",
                content,
            )
            for raw_symbols, source in destructured_imports:
                target_rel = self._resolve_internal_import_candidate(rel_path, source, known_paths)
                if not target_rel:
                    errors.append(
                        f"{rel_path}: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                        f"Relative require '{source}' does not resolve to a real blueprint file."
                    )
                    continue
                target_exports = self._module_exports_for_path(target_rel, overlay, blueprint_exports)
                for raw_symbol in raw_symbols.split(","):
                    imported_name = raw_symbol.strip().split(":", 1)[0].strip()
                    if imported_name and imported_name not in set(target_exports.get("named") or set()):
                        errors.append(
                            f"{rel_path}: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                            f"Required symbol '{imported_name}' from {target_rel} does not exist in the blueprint export contract."
                        )

            namespaced_imports = re.findall(
                r"const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*require\(['\"](?P<source>\.[^'\"]+)['\"]\)",
                content,
            )
            non_import_lines = "\n".join(line for line in content.splitlines() if "require(" not in line)
            for namespace, source in namespaced_imports:
                target_rel = self._resolve_internal_import_candidate(rel_path, source, known_paths)
                if not target_rel:
                    errors.append(
                        f"{rel_path}: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                        f"Relative require '{source}' does not resolve to a real blueprint file."
                    )
                    continue
                target_exports = self._module_exports_for_path(target_rel, overlay, blueprint_exports)
                if bool(target_exports.get("default")) and not set(target_exports.get("named") or set()):
                    continue
                method_refs = set(re.findall(rf"{re.escape(namespace)}\.(\w+)", non_import_lines))
                for method in method_refs:
                    if method not in set(target_exports.get("named") or set()):
                        errors.append(
                            f"{rel_path}: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                            f"{target_rel} does not export '{method}', but this file tries to call {namespace}.{method}."
                        )

        return errors

    def _check_blueprint_export_batch(
        self,
        overlay: dict[str, str],
        blueprint_exports: dict[str, dict[str, object]],
    ) -> list[str]:
        errors: list[str] = []
        for rel_path in overlay:
            expected = blueprint_exports.get(rel_path)
            if not expected:
                continue
            actual = self._module_exports_for_path(rel_path, overlay, blueprint_exports)
            expected_named = set(expected.get("named") or set())
            actual_named = set(actual.get("named") or set())

            has_explicit_contract = bool(expected.get("default")) or bool(expected_named)
            if not has_explicit_contract:
                # Do not enforce export drift for files without explicit export contract.
                continue

            if bool(expected.get("default")) and not bool(actual.get("default")):
                errors.append(
                    f"{rel_path}: BLUEPRINT_NOT_ENFORCED: BLUEPRINT_EXPORT_MISMATCH: "
                    "This file must provide a default export because the blueprint contract requires it."
                )

            for missing_name in sorted(expected_named - actual_named):
                errors.append(
                    f"{rel_path}: BLUEPRINT_NOT_ENFORCED: BLUEPRINT_EXPORT_MISMATCH: "
                    f"Missing required export '{missing_name}' from the blueprint contract."
                )

        return errors

    def _check_blueprint_type_batch(
        self,
        overlay: dict[str, str],
        blueprint_type_fields: dict[str, set[str]],
    ) -> list[str]:
        rel_path = "src/types/index.ts"
        if rel_path not in overlay:
            return []

        content = str(overlay.get(rel_path) or "")
        exported_blocks: dict[str, str] = {}
        for match in re.finditer(r"export\s+interface\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{([\s\S]*?)\n\}", content):
            exported_blocks[match.group(1)] = match.group(2)
        for match in re.finditer(r"export\s+type\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{([\s\S]*?)\n\}", content):
            exported_blocks[match.group(1)] = match.group(2)

        errors: list[str] = []
        property_pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\??\s*:", re.MULTILINE)
        for type_name, body in exported_blocks.items():
            allowed_fields = blueprint_type_fields.get(type_name)
            if not allowed_fields:
                continue
            actual_fields = set(property_pattern.findall(body))
            unexpected_fields = sorted(actual_fields - set(allowed_fields))
            if unexpected_fields:
                errors.append(
                    f"{rel_path}: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                    f"Type '{type_name}' declares fields {unexpected_fields} that are outside the blueprint contract. "
                    f"Allowed fields: {sorted(allowed_fields)}"
                )

        return errors

    def _build_blueprint_not_enforced_summary(
        self,
        errors: list[str],
        fallback_paths: list[str] | None = None,
    ) -> str | None:
        categories: list[str] = []
        if any("SCHEMA_SYNC_ERROR" in error or "DB_CONTRACT_ERROR" in error for error in errors):
            categories.append("schema violations")
        if any("API_RESPONSE_ENVELOPE_MISMATCH" in error or "API_CONTRACT_DRIFT" in error or "AUTH_RESPONSE_CONTRACT_ERROR" in error for error in errors):
            categories.append("API contract drift")
        if any("IMPORT_SITE_ERROR" in error or "BLUEPRINT_EXPORT_MISMATCH" in error for error in errors):
            categories.append("symbol/export drift")
        if any("STRUCTURAL_DRIFT" in error for error in errors):
            categories.append("structural drift")
        if any("CJS_ESM_MIX" in error for error in errors):
            categories.append("syntax purity violations")
        if not categories:
            return None

        affected_paths: list[str] = []
        seen: set[str] = set()
        for error in errors:
            rel_path = ""
            parts = str(error or "").split(":", 1)
            if len(parts) > 1 and "/" in parts[0]:
                rel_path = self._normalize_rel_path(parts[0])
            if rel_path and rel_path not in seen:
                seen.add(rel_path)
                affected_paths.append(rel_path)

        # Only fall back to broad target paths when no concrete error path was extracted.
        # This avoids noisy summaries like "...across env, gitignore, index.html..."
        # when the real violation is in a specific source file.
        if not affected_paths:
            for path in list(fallback_paths or []):
                rel_path = self._normalize_rel_path(path)
                if rel_path and rel_path not in seen:
                    seen.add(rel_path)
                    affected_paths.append(rel_path)

        summary_path = affected_paths[0] if affected_paths else "src/types/index.ts"
        affected_preview = ", ".join(affected_paths[:6]) if affected_paths else summary_path
        return (
            f"{summary_path}: BLUEPRINT_NOT_ENFORCED: "
            f"Blueprint execution failed with {', '.join(categories)} across {affected_preview}. "
            "Regenerate the full connected blueprint contract cluster together and do not apply style-only fixes first."
        )

    def validate_blueprint_execution_batch(
        self,
        files: list[dict[str, str]] | dict[str, str],
        target_paths: list[str] | None = None,
    ) -> list[str]:
        if not self.project_spec:
            return []

        if isinstance(files, dict):
            overlay = {
                self._normalize_rel_path(path): str(content or "")
                for path, content in files.items()
                if self._normalize_rel_path(path)
            }
        else:
            overlay = {
                self._normalize_rel_path(item.get("path", "")): str(item.get("content", "") or "")
                for item in list(files or [])
                if self._normalize_rel_path((item or {}).get("path", ""))
            }

        if not overlay:
            return []

        blueprint = self._blueprint_contract()
        blueprint_exports = dict(blueprint.get("exports") or {})
        schema_map = dict(blueprint.get("schema") or {})
        blueprint_type_fields = dict(blueprint.get("type_fields") or {})
        file_to_resource = dict(blueprint.get("file_to_resource") or {})

        schema_errors = self._check_blueprint_schema_batch(overlay, schema_map)
        api_errors = self._check_blueprint_api_envelope_batch(overlay, file_to_resource)
        import_errors = self._check_blueprint_symbol_batch(overlay, blueprint_exports)
        export_errors = self._check_blueprint_export_batch(overlay, blueprint_exports)
        type_errors = self._check_blueprint_type_batch(overlay, blueprint_type_fields)

        errors = self._dedupe_errors(schema_errors + api_errors + import_errors + export_errors + type_errors)
        summary = self._build_blueprint_not_enforced_summary(
            errors,
            fallback_paths=list(target_paths or overlay.keys()),
        )
        if summary:
            return [summary] + errors
        return errors

    def validate_full_stack(self, project_spec: ProjectSpec | None = None) -> list:
        """
        Returns a list of missing integration errors.
        """
        if project_spec is not None:
            self.project_spec = project_spec

        errors = []
        
        # 1. Detect Backend Features
        has_auth = self._check_backend_auth()
        registered_routes = self._list_registered_routes()
        has_models = self._check_backend_models()
        spec_auth_required = bool(self.project_spec and self.project_spec.auth.enabled)
        auth_required = has_auth or spec_auth_required

        # 1.5. Check direct parity against the planner's ProjectSpec when available.
        errors.extend(self._check_project_spec_parity(registered_routes))
        errors.extend(self._check_frontend_navigation_targets())
        
        # 2. Check Frontend Parity
        if auth_required:
            if not self._check_frontend_auth_ui():
                errors.append(
                    "MISSING_FEATURE: Auth is required by the backend or ProjectSpec, "
                    "but the frontend is missing Login/Register pages or auth navigation links."
                )

        if self.project_spec and self.project_spec.api_resources:
            for resource in self.project_spec.api_resources:
                if resource.frontend:
                    route_name = self._route_name_from_api_path(resource.route)
                    if route_name and not self._check_frontend_api_call(route_name):
                        errors.append(
                            f"PROJECT_SPEC_FRONTEND_DISCONNECTED: ProjectSpec requires frontend usage of '{resource.route}', "
                            "but no frontend service, hook, or page appears to call it."
                        )
        else:
            for route in registered_routes:
                if not self._check_frontend_api_call(route):
                    if any(x in route for x in ["posts", "comments", "users", "products", "orders", "contacts", "items", "auth"]):
                        errors.append(f"DISCONNECTED_FEATURE: Backend has route '{route}' but no frontend component appears to call it.")

        # 3. Check Database Initialization
        if has_models:
             if not self._check_db_initialization():
                 errors.append("DATABASE_UNINITIALIZED: Backend has data models but no database initialization (sqlite/better-sqlite3) found in server entry points.")
        
        # 4. Check Auth API Connectivity
        if auth_required:
            errors.extend(self._check_auth_api_connectivity())
            errors.extend(self._check_auth_link_state_contract())
        auth_contract_errors = self._check_auth_response_contract() if auth_required else []

        # 5. Check Schema-Controller Column Sync
        schema_errors = self._check_schema_controller_column_sync()
        errors.extend(schema_errors)

        # 5.5. Check DB adapter / export consistency across backend files
        db_contract_errors = self._check_backend_db_contract()
        errors.extend(db_contract_errors)

        # 5.55. Check that controllers use getDatabase() instead of calling .prepare() on the module exports object
        errors.extend(self._check_db_access_pattern())

        # 5.6. Check frontend request-client stack consistency
        http_client_errors = self._check_frontend_http_client_contract()
        errors.extend(http_client_errors)

        # 6. Check API/data contract drift
        api_errors = auth_contract_errors + self._check_api_contract_drift() + self._check_api_response_envelope_contract()
        errors.extend(api_errors)

        # 7. Check internal frontend import/export/type contracts before runtime/style work.
        import_errors = self._check_frontend_symbol_contracts()
        errors.extend(import_errors)

        # 7.5. Check structural purity (e.g. no .js in .ts project)
        structural_errors = self._check_structural_purity()
        errors.extend(structural_errors)

        # 7.6. Check module syntax purity (ESM vs CommonJS)
        syntax_errors = self._check_module_syntax_purity()
        errors.extend(syntax_errors)

        blueprint_summary = self._build_blueprint_not_enforced_summary(
            schema_errors + db_contract_errors + http_client_errors + api_errors + import_errors + structural_errors + syntax_errors
        )
        if blueprint_summary:
            errors.insert(0, blueprint_summary)

        # 8. Runtime / integration logic.
        runtime_errors = []
        runtime_errors.extend(self._check_common_standards())
        runtime_errors.extend(self._check_root_provider_wiring())
        runtime_errors.extend(self._check_route_controller_sync())
        runtime_errors.extend(self._check_vite_proxy())
        errors.extend(runtime_errors)

        # 9. Styling and Dependency Health
        if not (schema_errors or db_contract_errors or api_errors or import_errors or runtime_errors):
            errors.extend(self._check_frontend_styling_contract())
            errors.extend(self._check_design_system_tokens())
            errors.extend(self._check_essential_libraries())

        return self._dedupe_errors(errors)

    def _find_component_file(self, component_name: str) -> str | None:
        src_dir = os.path.join(self.sandbox_dir, "src")
        if not os.path.exists(src_dir):
            return None

        expected = f"{component_name}.tsx"
        for root, _, files in os.walk(src_dir):
            for file_name in files:
                if file_name == expected:
                    return os.path.join(root, file_name)
        return None

    def _component_likely_requires_props(self, component_name: str) -> bool:
        component_path = self._find_component_file(component_name)
        if not component_path:
            return True

        try:
            with open(component_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return True

        prop_interface = re.search(
            r'(?:interface|type)\s+\w*Props\s*(?:=\s*)?\{(?P<body>.*?)\}',
            content,
            re.DOTALL
        )
        if prop_interface and re.search(r'\b\w+\s*[?:]\s*', prop_interface.group("body")):
            return True

        if re.search(rf'\b{re.escape(component_name)}\b\s*:\s*React\.FC<[^>]+>', content):
            return True

        if re.search(rf'\bfunction\s+{re.escape(component_name)}\s*\(\s*{{[^}}]+}}\s*:\s*\w*Props', content):
            return True

        if re.search(rf'\bconst\s+{re.escape(component_name)}\s*=\s*\(\s*{{[^}}]+}}\s*:\s*\w*Props', content):
            return True

        return False

    def _check_backend_auth(self) -> bool:
        auth_paths = [
            "server/routes/auth.ts",
            "server/routes/authRoutes.ts",
            "server/controllers/authController.ts",
            "server/middleware/auth.ts",
            "server/middleware/authMiddleware.ts",
        ]
        return any(os.path.exists(os.path.join(self.sandbox_dir, p)) for p in auth_paths)

    def _file_exists(self, rel_path: str) -> bool:
        return os.path.exists(os.path.join(self.sandbox_dir, rel_path.replace("\\", "/")))

    def _route_name_from_api_path(self, route: str) -> str:
        normalized = str(route or "").strip()
        if not normalized:
            return ""
        if normalized.startswith("/api/"):
            normalized = normalized[len("/api/"):]
        return normalized.strip("/").split("/", 1)[0]

    def _route_name_from_api_signature(self, signature: str) -> str:
        normalized = str(signature or "").strip()
        if not normalized:
            return ""
        parts = normalized.split(None, 1)
        route = parts[1] if len(parts) > 1 else parts[0]
        return self._route_name_from_api_path(route)

    def _resource_file_paths(self, resource) -> tuple[str, str, str, str]:
        slug = _slug(resource.name or self._route_name_from_api_path(resource.route))
        singular = _singular_slug(slug)
        controller_path = f"server/controllers/{singular}Controller.ts"
        route_path = f"server/routes/{singular}Routes.ts"
        service_path = f"src/services/{singular}Service.ts"
        hook_path = f"src/hooks/use{_pascal(slug)}.tsx"
        return controller_path, route_path, service_path, hook_path

    def _route_is_registered_in_frontend(self, route: str) -> bool:
        normalized = str(route or "").strip() or "/"
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"

        src_dir = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_dir):
            return False

        path_attr = re.compile(rf'path\s*=\s*["\'`]{re.escape(normalized)}["\'`]')
        path_object = re.compile(rf'path\s*:\s*["\'`]{re.escape(normalized)}["\'`]')

        for root, _, files in os.walk(src_dir):
            for file_name in files:
                if not file_name.endswith((".tsx", ".ts", ".jsx", ".js")):
                    continue
                full_path = os.path.join(root, file_name)
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue
                if path_attr.search(content) or path_object.search(content):
                    return True
        return False

    def _collect_frontend_declared_routes(self) -> set[str]:
        routes: set[str] = set()
        src_dir = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_dir):
            return routes

        path_attr = re.compile(r'path\s*=\s*["\'`]([^"\'`]+)["\'`]')
        path_object = re.compile(r'path\s*:\s*["\'`]([^"\'`]+)["\'`]')
        for root, _, files in os.walk(src_dir):
            for file_name in files:
                if not file_name.endswith((".tsx", ".ts", ".jsx", ".js")):
                    continue
                full_path = os.path.join(root, file_name)
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue
                for raw in path_attr.findall(content) + path_object.findall(content):
                    route = str(raw or "").strip()
                    if not route:
                        continue
                    if route == "*":
                        routes.add("*")
                        continue
                    if not route.startswith("/"):
                        route = f"/{route}"
                    routes.add(route.rstrip("/") or "/")
        return routes

    def _normalize_frontend_route_target(self, target: str) -> str:
        candidate = str(target or "").strip()
        if not candidate:
            return ""
        if candidate.startswith(("http://", "https://", "mailto:", "tel:")):
            return ""
        if candidate.startswith("#"):
            return ""
        if not candidate.startswith("/"):
            return ""
        if candidate.startswith("/api"):
            return ""
        candidate = candidate.split("?", 1)[0].split("#", 1)[0]
        if "${" in candidate:
            prefix = candidate.split("${", 1)[0]
            prefix = prefix.rstrip("/")
            candidate = f"{prefix}/:param" if prefix else "/:param"
        return candidate.rstrip("/") or "/"

    def _route_target_matches_declared_routes(self, target: str, declared_routes: set[str]) -> bool:
        normalized_target = self._normalize_frontend_route_target(target)
        if not normalized_target:
            return True
        if normalized_target in declared_routes:
            return True
        if "*" in declared_routes:
            return True
        for declared in declared_routes:
            if not declared:
                continue
            if ":" in declared:
                prefix = declared.split(":", 1)[0].rstrip("/")
                if not prefix:
                    prefix = "/"
                if normalized_target == prefix or normalized_target.startswith(prefix + "/"):
                    return True
            if declared.endswith("*"):
                wildcard_prefix = declared[:-1].rstrip("/")
                if not wildcard_prefix:
                    wildcard_prefix = "/"
                if normalized_target == wildcard_prefix or normalized_target.startswith(wildcard_prefix + "/"):
                    return True
        return False

    def _check_frontend_navigation_targets(self) -> list[str]:
        src_dir = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_dir):
            return []

        declared_routes = self._collect_frontend_declared_routes()
        if not declared_routes:
            return []

        target_patterns = [
            re.compile(r'<(?:Link|NavLink)\b[^>]*\bto\s*=\s*["\'`]([^"\'`]+)["\'`]', re.IGNORECASE),
            re.compile(r'<(?:Link|NavLink)\b[^>]*\bto\s*=\s*\{\s*["\'`]([^"\'`]+)["\'`]\s*\}', re.IGNORECASE),
            re.compile(r'\bnavigate\s*\(\s*["\'`]([^"\'`]+)["\'`]', re.IGNORECASE),
            re.compile(r'<a\b[^>]*\bhref\s*=\s*["\'`]([^"\'`]+)["\'`]', re.IGNORECASE),
            re.compile(r'<a\b[^>]*\bhref\s*=\s*\{\s*["\'`]([^"\'`]+)["\'`]\s*\}', re.IGNORECASE),
        ]

        errors: list[str] = []
        seen: set[tuple[str, str]] = set()

        for root, _, files in os.walk(src_dir):
            for file_name in files:
                if not file_name.endswith((".tsx", ".ts", ".jsx", ".js")):
                    continue
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, self.sandbox_dir).replace("\\", "/")
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue

                candidates: list[str] = []
                for pattern in target_patterns:
                    candidates.extend(pattern.findall(content))

                for raw_target in candidates:
                    normalized_target = self._normalize_frontend_route_target(raw_target)
                    if not normalized_target:
                        continue
                    key = (rel_path, normalized_target)
                    if key in seen:
                        continue
                    seen.add(key)
                    if self._route_target_matches_declared_routes(normalized_target, declared_routes):
                        continue
                    errors.append(
                        f"{rel_path}: FRONTEND_ROUTE_TARGET_MISSING: Found navigation target '{normalized_target}' "
                        "but no matching route is registered in the frontend router. Add the route to App.tsx (or remove/fix the link)."
                    )

        return errors

    def _check_auth_link_state_contract(self) -> list[str]:
        if not self.project_spec or not self.project_spec.auth.enabled:
            return []

        candidate_files = [
            "src/components/Navbar.tsx",
            "src/pages/Home.tsx",
            "src/components/Hero.tsx",
        ]
        errors: list[str] = []
        for rel_path in candidate_files:
            content = self._read_rel_file(rel_path)
            if not content:
                continue
            lowered = content.lower()
            if "/login" not in lowered and "/register" not in lowered:
                continue
            auth_awareness_markers = (
                "useauth",
                "authcontext",
                "isauthenticated",
                "user ?",
                "if (user",
                "user &&",
            )
            if any(marker in lowered for marker in auth_awareness_markers):
                continue
            errors.append(
                f"{rel_path}: AUTH_UI_STATE_MISSING: Auth links are present but no auth-state conditional was detected. "
                "Hide Login/Register when a user is already authenticated."
            )
        return errors

    def _route_is_mounted_in_backend(self, route: str) -> bool:
        normalized = str(route or "").strip()
        if not normalized:
            return False
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"

        patterns = [
            re.compile(rf"(?:app|router)\.use\(\s*['\"`]{re.escape(normalized)}['\"`]"),
            re.compile(rf"(?:app|router)\.(?:get|post|put|delete|patch)\(\s*['\"`]{re.escape(normalized)}['\"`]"),
            re.compile(rf"mountRouteIfPresent\(\s*['\"`]{re.escape(normalized)}['\"`]"),
        ]
        for rel_path in BACKEND_ENTRY_FILES:
            full_path = os.path.join(self.sandbox_dir, rel_path)
            if not os.path.exists(full_path):
                continue
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue
            if any(pattern.search(content) for pattern in patterns):
                return True
        return False

    def _check_project_spec_parity(self, registered_routes: list[str]) -> list[str]:
        if not self.project_spec:
            return []

        errors: list[str] = []

        for required in self.project_spec.required_files:
            if not self._file_exists(required):
                errors.append(
                    f"PROJECT_SPEC_REQUIRED_FILE_MISSING: ProjectSpec requires '{required}', but that file is missing."
                )

        for page in self.project_spec.pages:
            component_name = _component_name(page.name, page.route)
            expected_path = f"src/pages/{component_name}.tsx"
            if not self._file_exists(expected_path):
                errors.append(
                    f"PROJECT_SPEC_PAGE_MISSING: ProjectSpec requires page '{page.route}' in '{expected_path}', but that file is missing."
                )
            if not self._route_is_registered_in_frontend(page.route):
                errors.append(
                    f"PROJECT_SPEC_ROUTE_MISSING: ProjectSpec requires frontend route '{page.route}', but no React router path for it was found."
                )

        for resource in self.project_spec.api_resources:
            slug = _slug(resource.name or self._route_name_from_api_path(resource.route))
            singular = _singular_slug(slug)
            controller_path = f"server/controllers/{singular}Controller.ts"
            route_path = f"server/routes/{singular}Routes.ts"
            route_name = self._route_name_from_api_path(resource.route)

            if not self._file_exists(controller_path):
                errors.append(
                    f"PROJECT_SPEC_RESOURCE_MISSING: ProjectSpec requires controller '{controller_path}' for '{resource.route}', but it is missing."
                )
            if not self._file_exists(route_path):
                errors.append(
                    f"PROJECT_SPEC_RESOURCE_MISSING: ProjectSpec requires route file '{route_path}' for '{resource.route}', but it is missing."
                )
            if not self._route_is_mounted_in_backend(resource.route):
                fallback_match = route_name and route_name in registered_routes
                if not fallback_match:
                    errors.append(
                        f"PROJECT_SPEC_BACKEND_ROUTE_MISSING: ProjectSpec requires backend route '{resource.route}', but it is not mounted in the server entry point."
                    )

        if self.project_spec.auth.enabled:
            required_auth_files = [
                "server/controllers/authController.ts",
                "server/routes/authRoutes.ts",
                "src/services/authService.ts",
                self.project_spec.auth.state_owner,
            ]
            for rel_path in required_auth_files:
                if not self._file_exists(rel_path):
                    errors.append(
                        f"PROJECT_SPEC_AUTH_MISSING: ProjectSpec enables auth, but required file '{rel_path}' is missing."
                    )
            if not self._route_is_mounted_in_backend("/api/auth"):
                auth_registered = any(route == "auth" for route in registered_routes)
                if not auth_registered:
                    errors.append(
                        "PROJECT_SPEC_AUTH_ROUTE_MISSING: ProjectSpec enables auth, but '/api/auth' is not mounted in the backend entry point."
                    )

        return errors

    def validate_scaffold_phase(
        self,
        project_spec: ProjectSpec | None = None,
        target_paths: list[str] | None = None,
    ) -> list[str]:
        if project_spec is not None:
            self.project_spec = project_spec

        errors: list[str] = []
        normalized_targets = {
            str(path).strip().replace("\\", "/")
            for path in list(target_paths or [])
            if str(path).strip()
        }
        required = [
            "package.json",
            "vite.config.ts",
            "tsconfig.json",
            "tsconfig.node.json",
            "index.html",
            "src/main.tsx",
            "src/App.tsx",
            "src/styles/variables.css",
            "src/styles/global.css",
            "src/services/api.ts",
            "server/index.ts",
        ]
        for rel_path in required:
            if normalized_targets and rel_path not in normalized_targets:
                continue
            if not self._file_exists(rel_path):
                errors.append(f"{rel_path}: SCAFFOLD_MISSING: Deterministic scaffold file is missing.")

        should_check_vite = not normalized_targets or "vite.config.ts" in normalized_targets
        if should_check_vite and self._file_exists("vite.config.ts"):
            for err in self._check_vite_proxy():
                errors.append(f"vite.config.ts: {err}")

        # Check TSConfig Purity
        should_check_tsconfig = not normalized_targets or any(ts in normalized_targets for ts in ["tsconfig.json", "tsconfig.node.json"])
        if should_check_tsconfig:
            errors.extend(self._check_tsconfig_purity())

        return errors

    def validate_backend_phase(self, target_paths: list[str], project_spec: ProjectSpec | None = None) -> list[str]:
        if project_spec is not None:
            self.project_spec = project_spec
        if not self.project_spec:
            return []

        normalized_targets = {
            str(path).strip().replace("\\", "/")
            for path in target_paths
            if str(path).strip()
        }
        errors: list[str] = []

        for resource in self.project_spec.api_resources:
            controller_path, route_path, _service_path, _hook_path = self._resource_file_paths(resource)
            if controller_path not in normalized_targets and route_path not in normalized_targets:
                continue

            route_exists_or_targeted = route_path in normalized_targets or self._file_exists(route_path)
            controller_exists_or_targeted = controller_path in normalized_targets or self._file_exists(controller_path)

            if controller_path in normalized_targets and not self._file_exists(controller_path):
                errors.append(f"{controller_path}: BACKEND_PHASE_MISSING: Expected controller for '{resource.route}' is missing.")
            if route_path in normalized_targets and not controller_exists_or_targeted:
                errors.append(f"{controller_path}: BACKEND_PHASE_MISSING: Expected controller for '{resource.route}' is missing.")
            if controller_path in normalized_targets and route_path in normalized_targets and not self._file_exists(route_path):
                errors.append(f"{route_path}: BACKEND_PHASE_MISSING: Expected route file for '{resource.route}' is missing.")
            if route_exists_or_targeted and self._file_exists(route_path) and not self._route_is_mounted_in_backend(resource.route):
                errors.append(f"server/index.ts: BACKEND_PHASE_ROUTE_MISSING: '{resource.route}' is not mounted in the backend entry point.")

        auth_targets = {
            "server/controllers/authController.ts",
            "server/routes/authRoutes.ts",
            "server/middleware/authMiddleware.ts",
            "server/utils/jwt.ts",
        }
        if self.project_spec.auth.enabled and normalized_targets & auth_targets:
            auth_controller_exists_or_targeted = (
                "server/controllers/authController.ts" in normalized_targets
                or self._file_exists("server/controllers/authController.ts")
            )
            auth_route_exists_or_targeted = (
                "server/routes/authRoutes.ts" in normalized_targets
                or self._file_exists("server/routes/authRoutes.ts")
            )
            if "server/controllers/authController.ts" in normalized_targets and not self._file_exists("server/controllers/authController.ts"):
                errors.append("server/controllers/authController.ts: BACKEND_PHASE_AUTH_MISSING: Auth controller is missing.")
            if "server/routes/authRoutes.ts" in normalized_targets and not auth_controller_exists_or_targeted:
                errors.append("server/controllers/authController.ts: BACKEND_PHASE_AUTH_MISSING: Auth controller is missing.")
            if "server/controllers/authController.ts" in normalized_targets and "server/routes/authRoutes.ts" in normalized_targets and not self._file_exists("server/routes/authRoutes.ts"):
                errors.append("server/routes/authRoutes.ts: BACKEND_PHASE_AUTH_MISSING: Auth route file is missing.")
            if auth_route_exists_or_targeted and self._file_exists("server/routes/authRoutes.ts") and not self._route_is_mounted_in_backend("/api/auth"):
                errors.append("server/index.ts: BACKEND_PHASE_AUTH_ROUTE_MISSING: '/api/auth' is not mounted in the backend entry point.")
            errors.extend(self._check_auth_response_contract())

        sync_errors = self._check_route_controller_sync()
        for err in sync_errors:
            if any(path in err for path in normalized_targets):
                errors.append(err)

        return errors

    def _check_db_access_pattern(self) -> list[str]:
        """Detect controllers that import the db module but call .prepare() on the exports object
        instead of calling getDatabase() first — causing TypeError: db.prepare is not a function."""
        errors: list[str] = []
        controller_paths = []
        server_dir = os.path.join(self.sandbox_dir, "server", "controllers")
        if os.path.isdir(server_dir):
            for fname in os.listdir(server_dir):
                if fname.endswith((".ts", ".js")):
                    controller_paths.append(os.path.join("server", "controllers", fname))

        for rel_path in controller_paths:
            content = self._read_virtual_file(rel_path, {})
            if not content:
                continue
            # Check if the file imports from the database module
            imports_db = re.search(r"require\(['\"]\.\.\/db\/database['\"]|from ['\"]\.\.\/db\/database['\"]", content)
            if not imports_db:
                continue
            # Check if it uses getDatabase() correctly
            uses_get_database = bool(re.search(r"getDatabase\s*\(\s*\)", content))
            # Check if it calls .prepare() directly on a variable bound to require('../db/database')
            # Pattern: const db = require('../db/database') followed by db.prepare without getDatabase
            direct_module_as_db = bool(re.search(
                r"const\s+\w+\s*=\s*require\(['\"]\.\.\/db\/database['\"]|require\(['\"]\.\.\/db\/database['\"]\)",
                content
            ))
            if direct_module_as_db and not uses_get_database:
                errors.append(
                    f"{rel_path}: DB_ACCESS_PATTERN_ERROR: Controller imports `../db/database` but never calls "
                    "`getDatabase()`. The module exports {initDatabase, getDatabase}, NOT the raw db instance. "
                    "Fix: `const { getDatabase } = require('../db/database')` and call `getDatabase()` inside each handler."
                )

        return errors

    def _check_essential_libraries(self) -> list[str]:
        """Verify that UI libs (lucide-react, recharts, etc.) are in package.json if used."""
        errors = []
        pkg_path = os.path.join(self.sandbox_dir, "package.json")
        if not os.path.exists(pkg_path):
            return []

        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg_data = json.load(f)
            deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
        except Exception:
            return []

        essential = ["lucide-react", "recharts", "framer-motion", "clsx", "tailwind-merge"]
        src_dir = os.path.join(self.sandbox_dir, "src")
        
        found_imports = set()
        if os.path.exists(src_dir):
            for root, _, files in os.walk(src_dir):
                for name in files:
                    if name.endswith((".tsx", ".ts")):
                        content = self._read_virtual_file(os.path.relpath(os.path.join(root, name), self.sandbox_dir), {})
                        for lib in essential:
                            if f"from '{lib}'" in content or f'from "{lib}"' in content:
                                found_imports.add(lib)

        for lib in found_imports:
            if lib not in deps:
                errors.append(f"package.json: MISSING_DEPENDENCY: Code uses '{lib}' but it is missing from package.json.")

        return errors

    def _check_design_system_tokens(self) -> list[str]:
        """Verify that mandatory tokens are present in variables.css."""
        errors = []
        vars_path = os.path.join(self.sandbox_dir, "src/styles/variables.css")
        if not os.path.exists(vars_path):
            return []

        try:
            with open(vars_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return []

        mandatory = ["--background", "--foreground", "--card", "--card-foreground", "--border"]
        for token in mandatory:
            if token not in content:
                errors.append(f"src/styles/variables.css: STYLESHEET_CLASS_INCOMPLETE: Missing mandatory design token '{token}'.")

        return errors

    def _check_tsconfig_purity(self) -> list[str]:
        """Detect tsconfig contract drift that commonly breaks TypeScript composite builds."""
        errors = []
        root_path = os.path.join(self.sandbox_dir, "tsconfig.json")
        node_path = os.path.join(self.sandbox_dir, "tsconfig.node.json")

        root_content = ""
        node_content = ""
        try:
            if os.path.exists(root_path):
                with open(root_path, "r", encoding="utf-8") as f:
                    root_content = f.read()
            if os.path.exists(node_path):
                with open(node_path, "r", encoding="utf-8") as f:
                    node_content = f.read()
        except Exception:
            return errors

        def _has_bool_flag(content: str, key: str, expected: bool) -> bool:
            bool_str = "true" if expected else "false"
            pattern = rf'["\']{re.escape(key)}["\']\s*:\s*{bool_str}\b'
            return bool(re.search(pattern, content or "", re.IGNORECASE))

        def _extends_tsconfig_root(content: str) -> bool:
            return bool(
                re.search(
                    r'["\']extends["\']\s*:\s*["\'](?:\./)?tsconfig(?:\.json)?["\']',
                    content or "",
                    re.IGNORECASE,
                )
            )

        if root_content:
            if _has_bool_flag(root_content, "noEmit", True) and _has_bool_flag(root_content, "composite", True):
                errors.append(
                    "tsconfig.json: TSCONFIG_PURITY_ERROR: TSConfig must NOT have 'noEmit: true' "
                    "when 'composite': true is also enabled. Set 'noEmit: false' or remove it entirely."
                )

        if node_content:
            node_has_no_emit_true = _has_bool_flag(node_content, "noEmit", True)
            node_has_no_emit_false = _has_bool_flag(node_content, "noEmit", False)
            node_has_composite_true = _has_bool_flag(node_content, "composite", True)
            node_has_allow_ts_ext_true = _has_bool_flag(node_content, "allowImportingTsExtensions", True)
            node_has_allow_ts_ext_false = _has_bool_flag(node_content, "allowImportingTsExtensions", False)
            node_extends_root = _extends_tsconfig_root(node_content)

            inherited_no_emit_true = (
                node_extends_root
                and not node_has_no_emit_false
                and _has_bool_flag(root_content, "noEmit", True)
            )
            inherited_allow_ts_ext_true = (
                node_extends_root
                and not node_has_allow_ts_ext_false
                and _has_bool_flag(root_content, "allowImportingTsExtensions", True)
            )

            effective_no_emit_true = node_has_no_emit_true or inherited_no_emit_true
            effective_no_emit_false = node_has_no_emit_false
            effective_allow_ts_ext_true = node_has_allow_ts_ext_true or inherited_allow_ts_ext_true

            if node_has_composite_true and effective_no_emit_true:
                if inherited_no_emit_true:
                    errors.append(
                        "tsconfig.node.json: TSCONFIG_PURITY_ERROR: Composite tsconfig.node.json inherits 'noEmit: true' "
                        "from tsconfig.json via extends. Set 'noEmit': false in tsconfig.node.json or make it standalone."
                    )
                else:
                    errors.append(
                        "tsconfig.node.json: TSCONFIG_PURITY_ERROR: TSConfig must NOT have 'noEmit: true' "
                        "when 'composite': true is also enabled. Set 'noEmit: false' or remove it entirely."
                    )

            if effective_allow_ts_ext_true and effective_no_emit_false:
                errors.append(
                    "tsconfig.node.json: TSCONFIG_PURITY_ERROR: 'allowImportingTsExtensions: true' requires "
                    "'noEmit: true' or 'emitDeclarationOnly'. Disable allowImportingTsExtensions for tsconfig.node.json "
                    "or avoid inheriting it from tsconfig.json."
                )
        return errors

    def _extract_classname_tokens(self, content: str) -> str:
        joined: list[str] = []
        pattern = re.compile(
            r'className\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|`([^`]+)`)',
            re.DOTALL,
        )
        for match in pattern.finditer(str(content or "")):
            token = match.group(1) or match.group(2) or match.group(3) or ""
            token = " ".join(str(token).split())
            if token:
                joined.append(token)
        return " ".join(joined)

    def _check_frontend_page_design_quality(self, page_path: str, *, route: str = "") -> list[str]:
        rel_path = str(page_path or "").strip().replace("\\", "/")
        if not rel_path.startswith("src/pages/"):
            return []
        if not self._file_exists(rel_path):
            return []

        content = self._read_virtual_file(rel_path, {})
        if not content.strip():
            return []

        errors: list[str] = []
        class_tokens = self._extract_classname_tokens(content)

        has_responsive = bool(re.search(r"\b(?:sm|md|lg|xl|2xl):", class_tokens))
        if not has_responsive:
            errors.append(
                f"{rel_path}: FRONTEND_DESIGN_QUALITY_RESPONSIVE_MISSING: "
                "Add responsive Tailwind breakpoints (`sm:`/`md:`/`lg:`) so the page adapts across mobile and desktop."
            )

        has_visual_depth = bool(
            re.search(r"\b(?:bg-|from-|to-|via-|shadow|ring-|border-|rounded|backdrop-)", class_tokens)
        )
        if not has_visual_depth:
            errors.append(
                f"{rel_path}: FRONTEND_DESIGN_QUALITY_VISUAL_DEPTH_MISSING: "
                "Add visual hierarchy with surfaces/contrast, borders/rings, shadows, gradients, or layered cards."
            )

        normalized_route = str(route or "").strip() or "/"
        if normalized_route == "/":
            section_count = len(re.findall(r"<section\b", content, flags=re.IGNORECASE))
            if section_count < 2:
                errors.append(
                    f"{rel_path}: FRONTEND_DESIGN_QUALITY_SECTION_RHYTHM_MISSING: "
                    "Home page should include at least 2 distinct `<section>` blocks (hero + supporting content)."
                )

        return errors

    def validate_frontend_phase(self, target_paths: list[str], project_spec: ProjectSpec | None = None) -> list[str]:
        if project_spec is not None:
            self.project_spec = project_spec
        if not self.project_spec:
            return []

        normalized_targets = {
            str(path).strip().replace("\\", "/")
            for path in target_paths
            if str(path).strip()
        }
        errors: list[str] = []

        for page in self.project_spec.pages:
            page_path = f"src/pages/{_component_name(page.name, page.route)}.tsx"
            if page_path not in normalized_targets:
                continue

            if not self._file_exists(page_path):
                errors.append(f"{page_path}: FRONTEND_PHASE_PAGE_MISSING: Expected page file for route '{page.route}' is missing.")
            else:
                errors.extend(self._check_frontend_page_design_quality(page_path, route=page.route))
            if not self._route_is_registered_in_frontend(page.route):
                errors.append(f"src/App.tsx: FRONTEND_PHASE_ROUTE_MISSING: Route '{page.route}' is not registered in the frontend router.")

        for resource in self.project_spec.api_resources:
            _controller_path, _route_path, service_path, hook_path = self._resource_file_paths(resource)
            relevant_paths = {service_path, hook_path}
            if not (normalized_targets & relevant_paths):
                continue

            route_name = self._route_name_from_api_path(resource.route)
            if route_name and not self._check_frontend_api_call(route_name):
                errors.append(f"{service_path}: FRONTEND_PHASE_API_DISCONNECTED: No frontend API call for '{resource.route}' was found.")

        auth_state_owner = self.project_spec.auth.state_owner if self.project_spec else "src/context/AuthContext.tsx"
        auth_api_targets = {
            "src/services/authService.ts",
            auth_state_owner,
            "src/hooks/useAuth.tsx",
        }
        auth_state_targets = {
            auth_state_owner,
            "src/hooks/useAuth.tsx",
        }
        auth_ui_targets = {
            "src/pages/Login.tsx",
            "src/pages/Register.tsx",
            "src/App.tsx",
            "src/components/Navbar.tsx",
        }
        auth_frontend_targets = auth_api_targets | auth_state_targets | auth_ui_targets | {"src/components/AdminRoute.tsx"}
        if self.project_spec.auth.enabled and normalized_targets & auth_frontend_targets:
            if normalized_targets & auth_state_targets:
                if not (
                    self._file_exists(auth_state_owner)
                    or self._file_exists("src/hooks/useAuth.tsx")
                ):
                    errors.append(
                        f"{auth_state_owner}: FRONTEND_PHASE_AUTH_STATE_MISSING: "
                        "Auth projects need a shared auth state layer (context, hook, or equivalent)."
                    )
            if normalized_targets & auth_api_targets and (
                "src/services/authService.ts" in normalized_targets
                or self._file_exists("src/services/authService.ts")
            ):
                for err in self._check_auth_api_connectivity():
                    target = "src/services/authService.ts" if self._file_exists("src/services/authService.ts") else auth_state_owner
                    errors.append(f"{target}: {err}")
            if normalized_targets & auth_ui_targets:
                if not self._check_frontend_auth_ui():
                    errors.append(
                        "src/pages/Login.tsx: FRONTEND_PHASE_AUTH_UI_MISSING: Auth requires Login/Register UI or auth navigation links."
                    )
            errors.extend(self._check_auth_response_contract())

        provider_targets = {
            "src/main.tsx",
            "src/App.tsx",
            "src/components/Navbar.tsx",
            "src/components/Footer.tsx",
            "src/components/AdminRoute.tsx",
        }
        if normalized_targets & provider_targets or any(path.startswith(("src/hooks/", "src/context/")) for path in normalized_targets):
            errors.extend(self._check_root_provider_wiring(target_paths=normalized_targets))

        nav_targets = {
            "src/App.tsx",
            "src/components/Navbar.tsx",
            "src/pages/Home.tsx",
            "src/components/Hero.tsx",
        }
        if normalized_targets & nav_targets:
            errors.extend(self._check_frontend_navigation_targets())
            if self.project_spec and self.project_spec.auth.enabled:
                errors.extend(self._check_auth_link_state_contract())

        return errors

    def _check_backend_models(self) -> bool:
        models_dir = os.path.join(self.sandbox_dir, "server/models")
        return os.path.exists(models_dir) and len(os.listdir(models_dir)) > 0

    def _list_registered_routes(self) -> list:
        routes = []
        for sf in BACKEND_ENTRY_FILES:
            full_path = os.path.join(self.sandbox_dir, sf)
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        matches = re.findall(r"(?:app|router)\.use\(['\"]/api/([\w-]+)['\"]", content)
                        matches.extend(re.findall(r"mountRouteIfPresent\(['\"]/api/([\w-]+)['\"]", content))
                        routes.extend(matches)
                except:
                    pass
        
        # Fallback: Check server/routes directory
        routes_dir = os.path.join(self.sandbox_dir, "server/routes")
        if os.path.exists(routes_dir):
            for f in os.listdir(routes_dir):
                if f.endswith(".ts") or f.endswith(".js"):
                    name = f.replace(".routes.ts", "").replace(".route.ts", "")
                    name = name.replace("Routes.ts", "").replace("Route.ts", "")
                    name = name.replace(".ts", "").replace(".js", "")
                    if name not in routes:
                        routes.append(name)
        
        return list(set(routes))

    def _strip_non_contract_noise(self, text: str) -> str:
        # Ignore SQL/template/message literals so DB column names like
        # category_id in raw SQL do not falsely count as public-contract drift.
        without_strings = re.sub(
            r"""('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|`(?:\\.|[^`\\])*`)""",
            '""',
            text,
            flags=re.DOTALL,
        )
        # Also ignore repair notes / comments such as
        # "createdAt vs created_at" so diagnostics do not create false positives.
        without_block_comments = re.sub(r"/\*.*?\*/", " ", without_strings, flags=re.DOTALL)
        without_line_comments = re.sub(r"(^|[^:])//.*?$", r"\1", without_block_comments, flags=re.MULTILINE)
        
        # NEW: Ignore mapper function internals (e.g. toPublicUser)
        # Find functions starting with `toPublic` and blank out their bodies
        # This prevents intentional name-mapping from triggering drift errors.
        mapper_internals_removed = re.sub(
            r"(function\s+toPublic[A-Za-z0-9_]*\s*\([^)]*\)\s*\{)(.*?)(\})", 
            r"\1 /* MAPPER_INTERNAL_OMITTED */ \3", 
            without_line_comments, 
            flags=re.DOTALL
        )
        return mapper_internals_removed

    def _api_contract_field_pairs(self) -> list[tuple[str, str]]:
        return [
            ("createdAt", "created_at"),
            ("updatedAt", "updated_at"),
            ("categoryId", "category_id"),
            ("categoryName", "category_name"),
            ("authorId", "author_id"),
            ("authorName", "author_name"),
            ("imageUrl", "image_url"),
            ("coverImage", "image_url"),
            ("postId", "post_id"),
            ("userId", "user_id"),
        ]

    def _extract_backend_public_contract_text(self, content: str) -> str:
        normalized = self._strip_non_contract_noise(content)
        parts: list[str] = []

        # Response/object literal keys count as public contract.
        object_keys = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b\s*:", normalized)
        if object_keys:
            parts.append("\n".join(object_keys))

        # Request payload/query/params field names are also public contract.
        destructures = re.findall(
            r"(?:const|let|var)\s*\{([^}]+)\}\s*=\s*req\.(?:body|query|params)\b",
            normalized,
            re.DOTALL,
        )
        for chunk in destructures:
            names: list[str] = []
            for raw in chunk.split(","):
                token = raw.strip()
                if not token:
                    continue
                token = token.split(":", 1)[0].split("=", 1)[0].strip()
                if token:
                    names.append(token)
            if names:
                parts.append("\n".join(names))

        req_accesses = re.findall(
            r"req\.(?:body|query|params)\.([A-Za-z_][A-Za-z0-9_]*)",
            normalized,
        )
        if req_accesses:
            parts.append("\n".join(req_accesses))

        return "\n".join(parts)

    def _extract_contract_presence(self, rel_path: str, content: str) -> dict[tuple[str, str], dict[str, bool]]:
        field_pairs = self._api_contract_field_pairs()
        presence = {
            (camel, snake): {"camel": False, "snake": False}
            for camel, snake in field_pairs
        }

        scan_text = ""
        if rel_path.startswith("src/"):
            scan_text = self._strip_non_contract_noise(content)
        elif rel_path.startswith("server/controllers/"):
            scan_text = self._extract_backend_public_contract_text(content)
        else:
            return presence

        has_mapper = bool(re.search(r"\btoPublic[A-Z][a-zA-Z0-9_]*\b", content))

        for camel, snake in field_pairs:
            if re.search(rf"\b{re.escape(camel)}\b", scan_text):
                presence[(camel, snake)]["camel"] = True
            
            # If the file uses a explicit toPublic... mapper, intentionally blind
            # the validator to snake_case usage so it doesn't trigger false positives.
            if not has_mapper:
                if re.search(rf"\b{re.escape(snake)}\b", scan_text):
                    presence[(camel, snake)]["snake"] = True

        return presence

    def collect_api_contract_drift(self) -> tuple[list[str], dict[str, list[str]]]:
        """
        Return mixed field pairs plus the files that participate in the drift.
        """
        field_pairs = self._api_contract_field_pairs()
        pair_hits = {
            (camel, snake): {"camel": set(), "snake": set()}
            for camel, snake in field_pairs
        }
        file_presence: dict[str, dict[tuple[str, str], dict[str, bool]]] = {}

        for root, _, files in os.walk(self.sandbox_dir):
            if any(x in root for x in ["node_modules", ".git", "dist", "build"]):
                continue
            for file_name in files:
                if not file_name.endswith((".ts", ".tsx", ".js", ".jsx")):
                    continue
                path = os.path.join(root, file_name)
                rel_path = os.path.relpath(path, self.sandbox_dir).replace("\\", "/")
                if rel_path.startswith("server/db/"):
                    continue
                if not (rel_path.startswith("src/") or rel_path.startswith("server/controllers/")):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue

                presence = self._extract_contract_presence(rel_path, content)
                file_presence[rel_path] = presence
                for camel, snake in field_pairs:
                    if presence[(camel, snake)]["camel"]:
                        pair_hits[(camel, snake)]["camel"].add(rel_path)
                    if presence[(camel, snake)]["snake"]:
                        pair_hits[(camel, snake)]["snake"].add(rel_path)

        mixed_pairs: list[str] = []
        offending_files: dict[str, list[str]] = {}
        for camel, snake in field_pairs:
            presence = pair_hits[(camel, snake)]
            if not presence["camel"] or not presence["snake"]:
                continue

            pair_label = f"{camel} vs {snake}"
            mixed_pairs.append(pair_label)
            canonical = "camel"
            shared_types_presence = file_presence.get("src/types/index.ts", {}).get((camel, snake), {"camel": False, "snake": False})
            if shared_types_presence["snake"] and not shared_types_presence["camel"]:
                canonical = "snake"
            elif shared_types_presence["camel"] and not shared_types_presence["snake"]:
                canonical = "camel"
            else:
                camel_score = 0
                snake_score = 0
                for rel_path, rel_presence in file_presence.items():
                    pair_presence = rel_presence.get((camel, snake), {"camel": False, "snake": False})
                    if not pair_presence["camel"] and not pair_presence["snake"]:
                        continue
                    weight = 2 if rel_path.startswith("src/") else 1
                    if pair_presence["camel"] and not pair_presence["snake"]:
                        camel_score += weight
                    elif pair_presence["snake"] and not pair_presence["camel"]:
                        snake_score += weight
                canonical = "camel" if camel_score >= snake_score else "snake"

            for rel_path in sorted(presence["camel"] | presence["snake"]):
                rel_presence = file_presence.get(rel_path, {}).get((camel, snake), {"camel": False, "snake": False})
                uses_camel = rel_presence["camel"]
                uses_snake = rel_presence["snake"]
                if not uses_camel and not uses_snake:
                    continue

                violates_contract = (
                    (canonical == "camel" and uses_snake)
                    or (canonical == "snake" and uses_camel)
                )
                if uses_camel and uses_snake:
                    violates_contract = True
                if not violates_contract:
                    continue

                offending_files.setdefault(rel_path, [])
                if pair_label not in offending_files[rel_path]:
                    offending_files[rel_path].append(pair_label)

        return mixed_pairs, offending_files

    def _check_api_contract_drift(self) -> list:
        """
        Detect mixed naming conventions for the same resource fields.
        This catches cases where the DB, controllers, shared types, and UI
        disagree about the same shape.
        """
        mixed_pairs, offending_files = self.collect_api_contract_drift()

        if not mixed_pairs:
            return []

        if not offending_files:
            return [
                "API_CONTRACT_DRIFT: Mixed field naming detected in the public API/frontend contract "
                f"({', '.join(mixed_pairs)}). Standardize controller request/response shapes, shared types, "
                "hooks, and components to one consistent camelCase contract. If your database uses snake_case, "
                "write a `toPublicModelName(row)` mapper function locally in the controller to bridge the gap."
            ]

        errors = []
        for rel_path in sorted(offending_files):
            pairs = ", ".join(offending_files[rel_path])
            errors.append(
                f"{rel_path}: API_CONTRACT_DRIFT: This file participates in a mixed public API/frontend contract "
                f"({pairs}). Standardize this file to the project's single request/response and shared-type shape. "
                "Use a `toPublic...` mapper if mapping DB fields."
            )
        return errors

    def _project_has_tailwind_runtime(self, overlay: dict[str, str] | None = None) -> bool:
        config_candidates = [
            "tailwind.config.js",
            "tailwind.config.cjs",
            "tailwind.config.ts",
        ]
        if any(self._file_exists(path) for path in config_candidates):
            return True
        if overlay and any(path in overlay for path in config_candidates):
            return True

        package_json_path = os.path.join(self.sandbox_dir, "package.json")
        package_data = {}
        if overlay and "package.json" in overlay:
            try:
                package_data = json.loads(overlay["package.json"])
            except Exception:
                pass
        
        if not package_data and os.path.exists(package_json_path):
            try:
                with open(package_json_path, "r", encoding="utf-8") as f:
                    package_data = json.load(f)
            except Exception:
                pass

        dependencies = dict(package_data.get("dependencies", {}) or {})
        dev_dependencies = dict(package_data.get("devDependencies", {}) or {})
        all_packages = {str(name).strip() for name in list(dependencies) + list(dev_dependencies)}
        return "tailwindcss" in all_packages or "@tailwindcss/vite" in all_packages

    def _extract_classname_literals(self, content: str) -> list[str]:
        patterns = [
            re.compile(r'className\s*=\s*["\'`]([^"\'`]+)["\'`]'),
            re.compile(r'className\s*=\s*\{\s*["\'`]([^"\'`]+)["\'`]\s*\}'),
        ]
        literals: list[str] = []
        for pattern in patterns:
            literals.extend(match.group(1) for match in pattern.finditer(str(content or "")))
        return literals

    def _looks_like_tailwind_utility(self, token: str) -> bool:
        value = str(token or "").strip()
        if not value:
            return False

        utility_patterns = (
            r"^(?:sm|md|lg|xl|2xl):",
            r"^(?:hover|focus|active|disabled|group-hover|dark):",
            r"^(?:min-h-screen|max-w-[A-Za-z0-9_-]+|mx-auto|my-auto|line-clamp-\d+)$",
            r"^(?:p|px|py|pt|pr|pb|pl|m|mx|my|mt|mr|mb|ml|gap)-\d+$",
            r"^(?:grid-cols|col-span|row-span)-\d+$",
            r"^(?:text|bg|border|ring)-(?:[a-z]+(?:-\d+)?|white|black|transparent)(?:/\d+)?$",
            r"^(?:rounded|shadow)(?:-[a-z0-9]+)?$",
            r"^(?:w|h|min-w|min-h|max-w|max-h)-[A-Za-z0-9_-]+$",
            r"^(?:font|tracking|leading)-[A-Za-z0-9_-]+$",
            r"^(?:flex|grid|inline-flex|items-center|justify-center|justify-between|place-items-center)$",
        )
        return any(re.search(pattern, value) for pattern in utility_patterns)

    def _collect_stylesheet_class_definitions(self) -> tuple[set[str], set[str]]:
        stylesheet_contents: dict[str, str] = {}
        declared_classes: set[str] = set()
        implemented_classes: set[str] = set()
        for root, _dirs, files in os.walk(os.path.join(self.sandbox_dir, "src")):
            if any(skip in root for skip in ("node_modules", "dist", "build")):
                continue
            for file_name in files:
                if not file_name.endswith(".css"):
                    continue
                full_path = os.path.join(root, file_name)
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        stylesheet_contents[os.path.relpath(full_path, self.sandbox_dir).replace("\\", "/")] = f.read()
                except Exception:
                    continue
        return self._collect_stylesheet_class_definitions_from_contents(stylesheet_contents)

    def _collect_stylesheet_class_definitions_from_contents(self, stylesheet_contents: dict[str, str]) -> tuple[set[str], set[str]]:
        declared_classes: set[str] = set()
        implemented_classes: set[str] = set()
        for _rel_path, content in sorted((stylesheet_contents or {}).items()):
            for match in re.finditer(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}", str(content or ""), re.DOTALL):
                selectors = str(match.group("selectors") or "")
                body = str(match.group("body") or "")
                class_names = re.findall(r"\.([A-Za-z_-][A-Za-z0-9_-]*)\b", selectors)
                if not class_names:
                    continue
                normalized_body = re.sub(r"/\*[\s\S]*?\*/", "", body).strip()
                has_real_rules = bool(re.search(r"[A-Za-z-]+\s*:", normalized_body))
                for class_name in class_names:
                    declared_classes.add(class_name)
                    if has_real_rules:
                        implemented_classes.add(class_name)
        return declared_classes, implemented_classes

    def _styling_contract_errors_for_ui_files(
        self,
        ui_files: dict[str, str],
        declared_classes: set[str],
        implemented_classes: set[str],
    ) -> list[str]:
        errors: list[str] = []
        for rel_path, content in sorted((ui_files or {}).items()):
            utility_tokens: set[str] = set()
            semantic_tokens: list[str] = []
            for literal in self._extract_classname_literals(content):
                for token in literal.split():
                    if self._looks_like_tailwind_utility(token):
                        utility_tokens.add(token)
                        continue
                    clean = str(token or "").strip()
                    if clean:
                        semantic_tokens.append(clean)

            if len(utility_tokens) < 6:
                missing_semantic = sorted(
                    {
                        token
                        for token in semantic_tokens
                        if token not in declared_classes
                    }
                )
                empty_semantic = sorted(
                    {
                        token
                        for token in semantic_tokens
                        if token in declared_classes and token not in implemented_classes
                    }
                )
                unresolved_semantic = sorted(set(missing_semantic) | set(empty_semantic))
                if len(unresolved_semantic) >= 6:
                    sample = ", ".join(unresolved_semantic[:6])
                    if empty_semantic and not missing_semantic:
                        issue_code = "STYLESHEET_CLASS_EMPTY"
                        guidance = (
                            "These selectors only exist as empty placeholder blocks. "
                            "Regenerate this UI together with src/styles/global.css or the owning stylesheet "
                            "and implement real CSS rules."
                        )
                    elif empty_semantic:
                        issue_code = "STYLESHEET_CLASS_INCOMPLETE"
                        guidance = (
                            "Some selectors are missing and others only exist as empty placeholder blocks. "
                            "Regenerate this UI together with src/styles/global.css or the owning stylesheet."
                        )
                    else:
                        issue_code = "STYLESHEET_CLASS_MISSING"
                        guidance = (
                            "Regenerate this UI together with src/styles/global.css or the owning stylesheet."
                        )
                    errors.append(
                        f"{rel_path}: {issue_code}: This file references semantic CSS classes "
                        f"({sample}) that are not implemented as real project stylesheet rules. "
                        f"{guidance}"
                    )
                continue

            sample = ", ".join(sorted(utility_tokens)[:6])
            errors.append(
                f"{rel_path}: TAILWIND_RUNTIME_MISSING: This file uses Tailwind-style utility classes "
                f"({sample}), but the project does not include Tailwind config/runtime. "
                "Replace them with real CSS classes or inline styles backed by variables.css/global.css, "
                "or explicitly add Tailwind to the scaffold."
            )
        return errors

    def _check_frontend_styling_contract(self) -> list[str]:
        if self._project_has_tailwind_runtime():
            return []

        src_root = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_root):
            return []

        errors: list[str] = []
        declared_classes, implemented_classes = self._collect_stylesheet_class_definitions()
        ui_files: dict[str, str] = {}
        for root, _dirs, files in os.walk(src_root):
            if any(skip in root for skip in ("node_modules", "dist", "build")):
                continue
            for file_name in files:
                if not file_name.endswith((".tsx", ".jsx")):
                    continue
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, self.sandbox_dir).replace("\\", "/")
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        ui_files[rel_path] = f.read()
                except Exception:
                    continue
        errors.extend(self._styling_contract_errors_for_ui_files(ui_files, declared_classes, implemented_classes))
        return errors

    def validate_frontend_style_batch(
        self,
        files: list[dict[str, str]] | dict[str, str],
        target_paths: list[str] | None = None,
    ) -> list[str]:
        if isinstance(files, dict):
            overlay = {
                self._normalize_rel_path(path): str(content or "")
                for path, content in files.items()
                if self._normalize_rel_path(path)
            }
        else:
            overlay = {
                self._normalize_rel_path((item or {}).get("path", "")): str((item or {}).get("content", "") or "")
                for item in list(files or [])
                if self._normalize_rel_path((item or {}).get("path", ""))
            }

        if self._project_has_tailwind_runtime(overlay=overlay):
            return []

        if not overlay and not target_paths:
            return []

        src_root = os.path.join(self.sandbox_dir, "src")
        stylesheet_contents: dict[str, str] = {}
        ui_contents: dict[str, str] = {}

        if os.path.isdir(src_root):
            for root, _dirs, files_in_dir in os.walk(src_root):
                if any(skip in root for skip in ("node_modules", "dist", "build")):
                    continue
                for file_name in files_in_dir:
                    if not file_name.endswith((".css", ".tsx", ".jsx")):
                        continue
                    full_path = os.path.join(root, file_name)
                    rel_path = os.path.relpath(full_path, self.sandbox_dir).replace("\\", "/")
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            content = f.read()
                    except Exception:
                        continue
                    if rel_path.endswith(".css"):
                        stylesheet_contents[rel_path] = content
                    else:
                        ui_contents[rel_path] = content

        for rel_path, content in overlay.items():
            if rel_path.endswith(".css"):
                stylesheet_contents[rel_path] = content
            elif rel_path.endswith((".tsx", ".jsx")):
                ui_contents[rel_path] = content

        inspect_paths = {
            self._normalize_rel_path(path)
            for path in list(target_paths or overlay.keys())
            if self._normalize_rel_path(path)
        }
        ui_targets = {
            rel_path: content
            for rel_path, content in ui_contents.items()
            if rel_path in inspect_paths and rel_path.endswith((".tsx", ".jsx"))
        }
        if not ui_targets:
            return []

        declared_classes, implemented_classes = self._collect_stylesheet_class_definitions_from_contents(stylesheet_contents)
        return self._styling_contract_errors_for_ui_files(ui_targets, declared_classes, implemented_classes)

    def _frontend_file_expects_raw_api_payload(self, rel_path: str, content: str) -> list[dict[str, str]]:
        expectations: list[dict[str, str]] = []
        normalized = str(content or "")

        destructured_pattern = re.compile(
            r"const\s*\{\s*data\s*\}\s*=\s*await\s+api\.\w+<(?P<type>[^>]+)>\(\s*['\"`](?P<path>/[^'\"`]+)['\"`]",
            re.DOTALL,
        )
        direct_pattern = re.compile(
            r"const\s+(?P<var>\w+)\s*=\s*await\s+api\.\w+<(?P<type>[^>]+)>\(\s*['\"`](?P<path>/[^'\"`]+)['\"`]",
            re.DOTALL,
        )

        def _generic_looks_wrapped(type_hint: str) -> bool:
            lowered = str(type_hint or "").lower()
            if "apiresponse" in lowered or "envelope" in lowered:
                return True
            return "{" in lowered and "data" in lowered

        for match in destructured_pattern.finditer(normalized):
            type_hint = match.group("type")
            route_path = match.group("path")
            if _generic_looks_wrapped(type_hint):
                continue
            expectations.append(
                {
                    "file": rel_path,
                    "route_name": self._route_name_from_api_path(route_path),
                    "path": route_path,
                }
            )

        for match in direct_pattern.finditer(normalized):
            type_hint = match.group("type")
            route_path = match.group("path")
            route_name = self._route_name_from_api_path(route_path)
            var_name = match.group("var")
            if _generic_looks_wrapped(type_hint):
                continue
            if re.search(rf"\b{re.escape(var_name)}\.data\.data\b", normalized):
                continue
            if re.search(rf"\b{re.escape(var_name)}\.data\b", normalized):
                expectations.append(
                    {
                        "file": rel_path,
                        "route_name": route_name,
                        "path": route_path,
                    }
                )

        return [item for item in expectations if item.get("route_name")]

    def _controller_wraps_response_envelope(self, rel_path: str) -> bool:
        full_path = os.path.join(self.sandbox_dir, rel_path.replace("\\", "/"))
        if not os.path.exists(full_path):
            return False

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return False

        return bool(
            re.search(
                r"res(?:\.status\([^)]*\))?\.json\(\s*\{[\s\S]{0,240}?\bdata\s*:",
                content,
                re.DOTALL,
            )
        )

    def _collect_api_route_wrappers(self) -> dict[str, dict[str, str]]:
        wrappers: dict[str, dict[str, str]] = {}

        if self.project_spec and self.project_spec.api_resources:
            for resource in self.project_spec.api_resources:
                controller_path, _route_path, _service_path, _hook_path = self._resource_file_paths(resource)
                if self._controller_wraps_response_envelope(controller_path):
                    route_name = self._route_name_from_api_path(resource.route)
                    if route_name:
                        wrappers[route_name] = {
                            "route_name": route_name,
                            "route_path": str(resource.route or "").strip(),
                            "controller": controller_path,
                        }
            return wrappers

        controllers_dir = os.path.join(self.sandbox_dir, "server", "controllers")
        if not os.path.isdir(controllers_dir):
            return wrappers

        for file_name in os.listdir(controllers_dir):
            if not file_name.endswith("Controller.ts"):
                continue
            rel_path = f"server/controllers/{file_name}"
            if not self._controller_wraps_response_envelope(rel_path):
                continue
            resource_name = file_name[:-len("Controller.ts")]
            route_name = _slug(resource_name)
            if route_name:
                wrappers[route_name] = {
                    "route_name": route_name,
                    "route_path": f"/api/{route_name}",
                    "controller": rel_path,
                }

        return wrappers

    def _check_api_response_envelope_contract(self) -> list[str]:
        wrappers = self._collect_api_route_wrappers()
        if not wrappers:
            return []

        src_root = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_root):
            return []

        route_consumers: dict[str, set[str]] = {}
        for root, _dirs, files in os.walk(src_root):
            if any(skip in root for skip in ("node_modules", "dist", "build")):
                continue
            for file_name in files:
                if not file_name.endswith((".ts", ".tsx", ".js", ".jsx")):
                    continue
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, self.sandbox_dir).replace("\\", "/")
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue

                for expectation in self._frontend_file_expects_raw_api_payload(rel_path, content):
                    route_name = expectation.get("route_name", "")
                    if route_name in wrappers:
                        route_consumers.setdefault(route_name, set()).add(rel_path)

        if not route_consumers:
            return []

        errors: list[str] = []
        seen_errors: set[str] = set()
        for route_name, consumers in sorted(route_consumers.items()):
            wrapper = wrappers.get(route_name, {})
            controller_path = wrapper.get("controller", "")
            route_path = wrapper.get("route_path", f"/api/{route_name}")
            consumer_list = ", ".join(sorted(consumers))

            for consumer in sorted(consumers):
                message = (
                    f"{consumer}: API_RESPONSE_ENVELOPE_MISMATCH: route '{route_name}' currently resolves to '{route_path}' "
                    f"and is returned as wrapped JSON (for example {{ success, data }}) by {controller_path}, "
                    "but this frontend code reads raw axios data. Unwrap `response.data.data` in a shared service/helper "
                    "or return raw JSON consistently from the backend."
                )
                if message not in seen_errors:
                    seen_errors.add(message)
                    errors.append(message)

            if controller_path:
                message = (
                    f"{controller_path}: API_RESPONSE_ENVELOPE_MISMATCH: route '{route_name}' currently returns wrapped JSON "
                    f"(for example {{ success, data }}), but frontend consumers such as {consumer_list} expect raw arrays/objects. "
                    "Standardize the controller, services, hooks, pages, and shared types to one response envelope."
                )
                if message not in seen_errors:
                    seen_errors.add(message)
                    errors.append(message)

        return errors

    def _check_db_initialization(self) -> bool:
        server_files = [
            *BACKEND_ENTRY_FILES,
            "server/db.ts", "server/database.ts", "server/db/database.ts"
        ]
        db_keywords = ["sqlite", "better-sqlite3", "mongoose", "sequelize", "knex", "pg", "Pool"]
        for sf in server_files:
            full_path = os.path.join(self.sandbox_dir, sf)
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if any(kw in content.lower() for kw in db_keywords):
                            return True
                except:
                    pass
        return False

    def _check_frontend_auth_ui(self) -> bool:
        pages_dir = os.path.join(self.sandbox_dir, "src/pages")
        if not os.path.exists(pages_dir):
            return False

        if self.project_spec and self.project_spec.auth.enabled:
            required_routes = ["/login"]
            if self.project_spec.auth.allow_registration:
                required_routes.append("/register")

            auth_pages = [
                page for page in self.project_spec.pages
                if page.route in required_routes
                or any(term in " ".join([page.name.lower(), page.route.lower(), page.purpose.lower()]) for term in ("login", "sign", "auth", "register", "otp", "verify"))
            ]
            if auth_pages:
                for page in auth_pages:
                    component_name = _component_name(page.name, page.route)
                    if os.path.exists(os.path.join(pages_dir, f"{component_name}.tsx")):
                        return True

        fallback_pages = ["Login.tsx", "Auth.tsx"]
        if not self.project_spec or self.project_spec.auth.allow_registration:
            fallback_pages.append("Register.tsx")
        for file_name in fallback_pages:
            if os.path.exists(os.path.join(pages_dir, file_name)):
                return True
        return False

    def _check_frontend_api_call(self, route_name: str) -> bool:
        src_dir = os.path.join(self.sandbox_dir, "src")
        if not os.path.exists(src_dir):
            return False

        for root, _, files in os.walk(src_dir):
            for f in files:
                if f.endswith((".tsx", ".ts")):
                    try:
                        with open(os.path.join(root, f), 'r', encoding='utf-8') as file:
                            content = file.read()
                            if f"/api/{route_name}" in content: return True
                            if f"api.post('/{route_name}" in content: return True
                            if f"api.get('/{route_name}" in content: return True
                            if f"api.put('/{route_name}" in content: return True
                            if f"api.delete('/{route_name}" in content: return True
                            if f"api.patch('/{route_name}" in content: return True
                            if f'api.post("/{route_name}' in content: return True
                            if f'api.get("/{route_name}' in content: return True
                            if f'api.put("/{route_name}' in content: return True
                            if f'api.delete("/{route_name}' in content: return True
                            if f'api.patch("/{route_name}' in content: return True
                            if f"/{route_name}" in content and ("api." in content or "fetch(" in content): return True
                    except:
                        continue
        return False

    def _read_rel_file(self, rel_path: str) -> str:
        full_path = os.path.join(self.sandbox_dir, rel_path)
        if not os.path.exists(full_path):
            return ""
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def _find_symbol_candidates(self, symbol: str, *, folders: tuple[str, ...] = ("src",)) -> list[str]:
        clean_symbol = str(symbol or "").strip()
        if not clean_symbol:
            return []

        matches: list[str] = []
        for folder in folders:
            full_folder = os.path.join(self.sandbox_dir, folder)
            if not os.path.isdir(full_folder):
                continue
            for root, _dirs, files in os.walk(full_folder):
                if any(skip in root for skip in ("node_modules", "dist", "build")):
                    continue
                for name in files:
                    if not name.endswith((".ts", ".tsx", ".js", ".jsx")):
                        continue
                    full_path = os.path.join(root, name)
                    rel_path = os.path.relpath(full_path, self.sandbox_dir).replace("\\", "/")
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            content = f.read()
                    except Exception:
                        continue
                    if re.search(rf"\b{re.escape(clean_symbol)}\b", content):
                        matches.append(rel_path)
        deduped: list[str] = []
        seen: set[str] = set()
        for path in matches:
            if path not in seen:
                seen.add(path)
                deduped.append(path)
        return deduped

    def _check_root_provider_wiring(self, target_paths: set[str] | None = None) -> list[str]:
        main_rel = "src/main.tsx"
        app_rel = "src/App.tsx"
        main_content = self._read_rel_file(main_rel)
        app_content = self._read_rel_file(app_rel)
        if not main_content and not app_content:
            return []

        src_root = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_root):
            return []

        root_mount_content = "\n".join([main_content, app_content])
        filtered_targets = {str(path).strip() for path in (target_paths or set()) if str(path).strip()}
        global_shell_paths = {
            "src/App.tsx",
            "src/main.tsx",
            "src/components/Navbar.tsx",
            "src/components/Footer.tsx",
            "src/components/AdminRoute.tsx",
        }
        errors: list[str] = []
        seen_errors: set[str] = set()

        provider_guard_pattern = re.compile(
            r"throw new Error\(['\"][^'\"]*\b(use[A-Z]\w+)\b\s+must be used within (?:an?\s+)?([A-Z]\w*Provider)\b[^'\"]*['\"]\)",
            re.IGNORECASE,
        )

        for root, _dirs, files in os.walk(src_root):
            if any(skip in root for skip in ("node_modules", "dist", "build")):
                continue
            for name in files:
                if not name.endswith((".ts", ".tsx", ".js", ".jsx")):
                    continue
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, self.sandbox_dir).replace("\\", "/")
                content = self._read_rel_file(rel_path)
                if not content:
                    continue

                for hook_name, provider_name in provider_guard_pattern.findall(content):
                    consumer_paths: list[str] = []
                    for scan_root, _scan_dirs, scan_files in os.walk(src_root):
                        if any(skip in scan_root for skip in ("node_modules", "dist", "build")):
                            continue
                        for scan_name in scan_files:
                            if not scan_name.endswith((".ts", ".tsx", ".js", ".jsx")):
                                continue
                            scan_full = os.path.join(scan_root, scan_name)
                            scan_rel = os.path.relpath(scan_full, self.sandbox_dir).replace("\\", "/")
                            if scan_rel == rel_path:
                                continue
                            scan_content = self._read_rel_file(scan_rel)
                            if not scan_content:
                                continue
                            if re.search(rf"\b{re.escape(hook_name)}\s*\(", scan_content) or re.search(rf"\b{re.escape(hook_name)}\b", scan_content):
                                consumer_paths.append(scan_rel)

                    deduped_consumers: list[str] = []
                    seen_consumers: set[str] = set()
                    for consumer in consumer_paths:
                        if consumer not in seen_consumers:
                            seen_consumers.add(consumer)
                            deduped_consumers.append(consumer)

                    global_consumers = [path for path in deduped_consumers if path in global_shell_paths]
                    is_app_wide = bool(global_consumers) or len(deduped_consumers) >= 2
                    if not is_app_wide:
                        continue

                    if filtered_targets:
                        related_targets = {rel_path, main_rel, app_rel, *deduped_consumers}
                        if not (filtered_targets & related_targets):
                            continue

                    provider_mounted = bool(re.search(rf"<\s*{re.escape(provider_name)}\b", root_mount_content))
                    if provider_mounted:
                        continue

                    consumer_hint = ", ".join(global_consumers[:2] or deduped_consumers[:2] or [rel_path])
                    error = (
                        f"{main_rel}: ROOT_PROVIDER_MISSING: Global hook '{hook_name}' is used by {consumer_hint}, "
                        f"but '{provider_name}' is not mounted in src/main.tsx or src/App.tsx."
                    )
                    if error not in seen_errors:
                        seen_errors.add(error)
                        errors.append(error)

        return errors

    def validate_backend_runtime(self, port=None) -> tuple:
        """Checks if the backend is listening on the specified port."""
        import socket
        if port is None:
            port = self.backend_port
        try:
            with socket.create_connection(('localhost', port), timeout=3.0):
                return True, ""
        except:
            pass
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=3.0):
                return True, ""
        except:
            pass
        error_log = self.get_backend_logs()
        return False, error_log

    def get_backend_logs(self, log_path="/tmp/sandbox_server.log") -> str:
        candidate_logs = [
            log_path,
            "/tmp/sandbox_server.log",
            "/tmp/sandbox_direct.log",
            "/tmp/sandbox_dev.log",
        ]

        for candidate in candidate_logs:
            if not candidate or not os.path.exists(candidate):
                continue
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.splitlines()
                    tail_excerpt = "\n".join(lines[-80:])
                    error_lines = []
                    in_error = False
                    for line in reversed(lines[-100:]):
                        if "Error:" in line or "Exception" in line or "ERR!" in line:
                            in_error = True
                        if in_error:
                            error_lines.insert(0, line)
                    error_excerpt = "\n".join(error_lines) if error_lines else "\n".join(lines[-20:])
                    has_project_path = bool(
                        re.search(r"(?:server|src)/[^\s:()]+?\.(?:ts|tsx|js|jsx)", error_excerpt)
                    )
                    is_low_signal_bootstrap = (
                        ("triggerUncaughtException" in error_excerpt or "node:internal/modules/" in error_excerpt)
                        and not has_project_path
                    )
                    return tail_excerpt if is_low_signal_bootstrap else error_excerpt
            except:
                return "Failed to read backend logs."

        return "No backend log file found."

    def _check_common_standards(self) -> list:
        """
        Runs project-wide checks for common patterns.

        BUG FIX: f.endswith((".tsx", ".tsx")) was checking .tsx TWICE — .ts files
        were never checked for missing useState/useEffect imports.
        Fixed to: f.endswith((".tsx", ".ts"))
        """
        errors = []
        for root, _, files in os.walk(self.sandbox_dir):
            if any(x in root for x in ["node_modules", ".git", "dist", "build"]):
                continue
            for f in files:
                if not f.endswith((".tsx", ".ts", ".css", ".html")):
                    continue
                path = os.path.join(root, f)
                rel_path = os.path.relpath(path, self.sandbox_dir)
                try:
                    with open(path, 'r', encoding='utf-8') as file:
                        c = file.read()
                        
                        # BUG FIX: Was (".tsx", ".tsx") — now correctly checks both .tsx and .ts
                        if f.endswith((".tsx", ".ts")):
                            if "useState" in c and "import" in c:
                                if 'from "react"' not in c and "from 'react'" not in c:
                                    errors.append(f"{rel_path}: 'useState' used but 'react' not imported.")
                            if "useEffect" in c and "import" in c:
                                if 'from "react"' not in c and "from 'react'" not in c:
                                    errors.append(f"{rel_path}: 'useEffect' used but 'react' not imported.")

                        # Hardcoded Localhost
                        if "http://localhost:5000" in c or f"http://localhost:{self.backend_port}" in c:
                             if "vite.config" not in rel_path:
                                 errors.append(f"{rel_path}: Hardcoded localhost URL found. Use relative paths for Vite proxy.")

                        # Unsupported JSX Style
                        if "<style jsx>" in c:
                             errors.append(f"{rel_path}: <style jsx> detected. Use standard <style> or CSS modules for Vite.")
                             
                        # Legacy CJS enforcement rule removed.

                        if rel_path.startswith(("src/pages/", "src/components/")) and f.endswith(".tsx"):
                            if f[0].islower():
                                errors.append(f"{rel_path}: NAMING_CONVENTION_ERROR: React component files MUST use PascalCase (e.g. Dashboard.tsx). Rename this file.")

                        # Case-sensitive import matching check (Linux Parity)
                        imports = re.findall(r"from\s+['\"](\.\.?/[^'\"]+)['\"]", c)
                        for imp in imports:
                            importer_dir = os.path.dirname(rel_path)
                            # Basic resolution
                            resolved = self._resolve_internal_src_import(rel_path, imp)
                            if not resolved and imp.startswith("."):
                                # If it didn't resolve, check for case mismatch
                                base_path = os.path.normpath(os.path.join(importer_dir, imp)).replace("\\", "/")
                                for ext in ("", ".ts", ".tsx", ".js", ".jsx"):
                                    full_path = os.path.join(self.sandbox_dir, base_path + ext)
                                    match = self._find_case_insensitive_match(full_path)
                                    if match and match != os.path.basename(full_path):
                                        errors.append(f"{rel_path}: IMPORT_CASE_MISMATCH_ERROR: Import '{imp}' path case does NOT match disk file '{match}'. Fix the import casing.")
                                        break

                        # Component Prop Safety (Detection of empty page crashes)
                        # Check for <Posts />, <Items />, <ProductList />, <PostGrid /> etc. (missing data props)
                        suspicious_components = re.findall(r"<([A-Z]\w*(?:List|Grid|Gallery|Carousel|Table|Collection|Items|Posts|Products|Articles))\s*/>", c)
                        for component in suspicious_components:
                             if f"{component}.tsx" not in rel_path and self._component_likely_requires_props(component):
                                 errors.append(f"{rel_path}: <{component} /> is likely missing mandatory data props. This often causes frontend crashes.")


                except:
                    continue
        return errors

    def _find_case_insensitive_match(self, full_path: str) -> str | None:
        directory = os.path.dirname(full_path)
        if not os.path.isdir(directory):
            return None
        target = os.path.basename(full_path).lower()
        try:
            for f in os.listdir(directory):
                if f.lower() == target:
                    return f
        except:
            pass
        return None

    def _resolve_internal_src_import(self, importer_rel: str, source: str) -> str | None:
        module_spec = str(source or "").strip()
        if not module_spec.startswith("."):
            return None

        importer_dir = os.path.dirname(importer_rel)
        base_path = os.path.normpath(os.path.join(importer_dir, module_spec)).replace("\\", "/")
        candidates = []
        if re.search(r"\.(?:ts|tsx|js|jsx)$", base_path):
            candidates.append(base_path)
        else:
            for ext in (".ts", ".tsx", ".js", ".jsx"):
                candidates.append(base_path + ext)
            for ext in (".ts", ".tsx", ".js", ".jsx"):
                candidates.append(f"{base_path}/index{ext}")

        for candidate in candidates:
            if candidate.startswith("../") or "/../" in candidate:
                continue
            full_path = os.path.join(self.sandbox_dir, candidate)
            if os.path.exists(full_path):
                return candidate
        return None

    def _collect_frontend_module_exports(self, content: str) -> dict[str, object]:
        exports: dict[str, object] = {
            "default": False,
            "named": set(),
        }
        normalized = str(content or "")
        if re.search(r"\bexport\s+default\b", normalized):
            exports["default"] = True

        named = set(re.findall(
            r"\bexport\s+(?:(?:async\s+)?function|const|class|interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
            normalized,
        ))

        for match in re.finditer(r"\bexport\s*\{([^}]+)\}", normalized, re.DOTALL):
            for raw in match.group(1).split(","):
                token = raw.strip()
                if not token:
                    continue
                if " as " in token:
                    exported_name = token.split(" as ", 1)[1].strip()
                else:
                    exported_name = token
                if exported_name:
                    if exported_name == "default":
                        exports["default"] = True
                    else:
                        named.add(exported_name)

        exports["named"] = named
        return exports

    def _parse_internal_src_imports(self, content: str) -> list[dict[str, object]]:
        imports: list[dict[str, object]] = []
        import_pattern = re.compile(
            r"(?ms)^\s*import\s+(?:type\s+)?(?P<clause>.+?)\s+from\s+['\"](?P<source>[^'\"]+)['\"]\s*;?\s*$",
        )
        for match in import_pattern.finditer(str(content or "")):
            clause = str(match.group("clause") or "").strip()
            source = str(match.group("source") or "").strip()
            if not source.startswith("."):
                continue
            default_import = ""
            named_imports: list[str] = []

            if clause.startswith("{"):
                named_block = clause
            elif clause.startswith("*"):
                named_block = ""
            elif "," in clause:
                first, remainder = clause.split(",", 1)
                default_import = first.strip()
                named_block = remainder.strip()
            else:
                default_import = clause.strip()
                named_block = ""

            if named_block.startswith("{") and "}" in named_block:
                inner = named_block[1:named_block.index("}")]
                for raw in inner.split(","):
                    token = raw.strip()
                    if not token:
                        continue
                    token = re.sub(r"^type\s+", "", token).strip()
                    imported_name = token.split(" as ", 1)[0].strip()
                    if imported_name:
                        named_imports.append(imported_name)

            imports.append(
                {
                    "source": source,
                    "default": default_import,
                    "named": named_imports,
                }
            )
        return imports

    def _check_module_syntax_purity(self) -> list[str]:
        """
        Detects legacy CommonJS syntax (require, module.exports, exports.)
        in files that are supposedly TypeScript/ESM.
        """
        errors = []
        is_typescript = os.path.exists(os.path.join(self.sandbox_dir, "tsconfig.json"))
        if not is_typescript:
            return []

        # Keywords that indicate CommonJS drift in a TS project
        cjs_patterns = {
            r"\brequire\s*\(": "require()",
            r"\bmodule\.exports\b": "module.exports",
            r"\bexports\.[a-zA-Z0-9_]+\s*=": "exports.prop =",
        }

        # print(f"[DEBUG] Scanning for CJS purity in {self.sandbox_dir} (is_ts={is_typescript})")
        for root, dirs, files in os.walk(self.sandbox_dir):
            relative_root = os.path.relpath(root, self.sandbox_dir).replace("\\", "/")
            if any(skip in relative_root.split("/") for skip in ("node_modules", "dist", "build", ".lovable", ".git")):
                continue
            for f in files:
                if not f.endswith(".ts") and not f.endswith(".tsx"):
                    continue
                
                rel_path = os.path.join(relative_root, f).replace("\\", "/").lstrip("./")
                if not rel_path.startswith(("src/", "server/")):
                    continue

                # Skip root config files that might legit use require
                if f in {"vite.config.ts", "postcss.config.js"}:
                    continue

                # Trace file scanning
                # print(f"[DEBUG] Checking {rel_path}")
                
                content = self._read_virtual_file(rel_path, {})
                if not content:
                    continue

                for pattern, label in cjs_patterns.items():
                    if re.search(pattern, content):
                        err_msg = (
                            f"{rel_path}: CJS_ESM_MIX: CRITICAL: Found legacy CommonJS syntax ({label}) in a TypeScript project. "
                            "You MUST rewrite this file to use 100% ESM. "
                            "1. REPLACE all `require()` calls with `import` statements. "
                            "2. REPLACE all `module.exports` or `exports.prop` with `export` or `export default`. "
                            "Failure to use ESM will cause immediate validation rejection."
                        )
                        errors.append(err_msg)
                        # Intentionally not breaking, to catch all violations in this test phase
        return errors

    def _check_structural_purity(self) -> list[str]:
        """
        Ensures the project doesn't contain redundant or invalid file extensions
        given the project's primary language (e.g. no .js in a TypeScript project).
        """
        errors = []
        is_typescript = os.path.exists(os.path.join(self.sandbox_dir, "tsconfig.json"))
        
        if is_typescript:
            forbidden_extensions = {".js", ".jsx"}
            for root, dirs, files in os.walk(self.sandbox_dir):
                if any(skip in root for skip in ("node_modules", "dist", "build", ".lovable", ".git")):
                    continue
                for f in files:
                    if any(f.endswith(ext) for ext in forbidden_extensions):
                        # Some root config files are allowed to be JS
                        if f in {"postcss.config.js", "tailwind.config.js"}:
                            continue
                        rel_path = os.path.relpath(os.path.join(root, f), self.sandbox_dir).replace("\\", "/")
                        
                        # Only check src and server for purity
                        if rel_path.startswith(("src/", "server/")):
                            errors.append(
                                f"{rel_path}: STRUCTURAL_DRIFT: Found JavaScript file in a TypeScript project. "
                                f"Delete {rel_path} and ensure logic is in its .ts/.tsx counterpart."
                            )
        return errors

    def _check_frontend_symbol_contracts(self) -> list:
        src_root = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_root):
            return []

        file_contents: dict[str, str] = {}
        module_exports: dict[str, dict[str, object]] = {}
        for root, _dirs, files in os.walk(src_root):
            if any(skip in root for skip in ("node_modules", "dist", "build")):
                continue
            for file_name in files:
                if not file_name.endswith((".ts", ".tsx", ".js", ".jsx")):
                    continue
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, self.sandbox_dir).replace("\\", "/")
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue
                file_contents[rel_path] = content
                module_exports[rel_path] = self._collect_frontend_module_exports(content)

        errors: list[str] = []
        seen_errors: set[str] = set()
        for importer_rel, content in file_contents.items():
            for entry in self._parse_internal_src_imports(content):
                target_rel = self._resolve_internal_src_import(importer_rel, str(entry.get("source") or ""))
                if not target_rel or not target_rel.startswith("src/"):
                    continue
                target_exports = module_exports.get(target_rel)
                if not target_exports:
                    continue

                default_import = str(entry.get("default") or "").strip()
                if default_import and not bool(target_exports.get("default")):
                    error = (
                        f"{importer_rel}: IMPORT_SITE_ERROR: Missing export default in {target_rel}. "
                        f"Imported as default by {importer_rel}, but {target_rel} has no default export. "
                        "Rewrite this import statement to use named imports if applicable."
                    )
                    if error not in seen_errors:
                        seen_errors.add(error)
                        errors.append(error)

                for imported_name in entry.get("named", []) or []:
                    if imported_name not in set(target_exports.get("named") or set()):
                        error = (
                            f"{importer_rel}: IMPORT_SITE_ERROR: "
                            f"Imported symbol '{imported_name}' from {target_rel} does not exist. "
                            f"{target_rel} has no exported member '{imported_name}'. "
                            "Do not invent fake exports. Remove this import or find the correct source."
                        )
                        if error not in seen_errors:
                            seen_errors.add(error)
                            errors.append(error)

        return errors

    def _check_route_controller_sync(self) -> list:
        """
        Deep scan of routes/ and controllers/ to ensure all methods exist and
        imports are correct. Prevents 'Route.get() requires a callback' errors.
        """
        errors = []
        routes_dir = os.path.join(self.sandbox_dir, "server/routes")
        controllers_dir = os.path.join(self.sandbox_dir, "server/controllers")

        if not os.path.exists(routes_dir) or not os.path.exists(controllers_dir):
            return []

        def _get_exported_methods(ctrl_path: str) -> set:
            try:
                with open(ctrl_path, 'r', encoding='utf-8') as f:
                    c = f.read()
            except Exception:
                return set()

            exported = set()
            exported.update(re.findall(r'exports\.(\w+)\s*=', c))
            obj_match = re.search(r'module\.exports\s*=\s*\{([^}]+)\}', c, re.DOTALL)
            if obj_match:
                obj_body = obj_match.group(1)
                # Capture all word characters that appear to be keys or shorthand exports
                exported.update(re.findall(r'(\w+)', obj_body))
            return exported

        for f in os.listdir(routes_dir):
            if not f.endswith(".ts"):
                continue
            route_path = os.path.join(routes_dir, f)
            try:
                with open(route_path, 'r', encoding='utf-8') as file:
                    content = file.read()

                # Pattern A: const controller = require('../controllers/name')
                namespaced_imports = re.findall(
                    r"const\s+(\w+)\s*=\s*require\(['\"]\.{1,2}/controllers/([^'\"]+)['\"]\)",
                    content
                )
                for var_name, ctrl_filename in namespaced_imports:
                    ctrl_filename = re.sub(r'\.ts$', '', ctrl_filename)
                    ctrl_path = os.path.join(controllers_dir, f"{ctrl_filename}.ts")
                    if not os.path.exists(ctrl_path):
                        errors.append(
                            f"server/routes/{f}: References missing controller "
                            f"'server/controllers/{ctrl_filename}.ts'"
                        )
                        continue

                    exported_methods = _get_exported_methods(ctrl_path)
                    non_import_lines = "\n".join(
                        line for line in content.splitlines()
                        if "require(" not in line
                    )
                    method_refs = set(re.findall(
                        rf'{re.escape(var_name)}\.(\w+)',
                        non_import_lines
                    ))
                    for method in method_refs:
                        if method not in exported_methods:
                            errors.append(
                                f"ROUTE_SYNC_ERROR: server/routes/{f} calls "
                                f"'{var_name}.{method}' but 'server/controllers/{ctrl_filename}.ts' "
                                f"does not export '{method}'. "
                                f"Add: exports.{method} = async (req, res) => {{ ... }}"
                            )

                # Pattern B: const { login, register } = require('../controllers/name')
                destructured_imports = re.findall(
                    r"const\s*\{([^}]+)\}\s*=\s*require\(['\"]\.{1,2}/controllers/([^'\"]+)['\"]\)",
                    content
                )
                for names_str, ctrl_filename in destructured_imports:
                    ctrl_filename = re.sub(r'\.ts$', '', ctrl_filename)
                    ctrl_path = os.path.join(controllers_dir, f"{ctrl_filename}.ts")
                    if not os.path.exists(ctrl_path):
                        errors.append(
                            f"server/routes/{f}: References missing controller "
                            f"'server/controllers/{ctrl_filename}.ts'"
                        )
                        continue
                    exported_methods = _get_exported_methods(ctrl_path)
                    imported_names = [n.strip() for n in names_str.split(',') if n.strip()]
                    for name in imported_names:
                        if name and name not in exported_methods:
                            errors.append(
                                f"ROUTE_SYNC_ERROR: server/routes/{f} destructures "
                                f"'{name}' from 'server/controllers/{ctrl_filename}.ts' "
                                f"but that method is not exported. "
                                f"Add: exports.{name} = async (req, res) => {{ ... }}"
                            )

                # Middleware import style mismatch check
                mw_imports = re.findall(
                    r"const\s+(\w+)\s*=\s*require\(['\"]\.{1,2}/middleware/([^'\"]+)['\"]\)",
                    content
                )
                for mw_var, mw_filename in mw_imports:
                    mw_filename = re.sub(r'\.ts$', '', mw_filename)
                    mw_path = os.path.join(self.sandbox_dir, "server", "middleware", f"{mw_filename}.ts")
                    if not os.path.exists(mw_path):
                        continue
                    try:
                        with open(mw_path, 'r', encoding='utf-8') as mf:
                            mw_content = mf.read()
                        exports_direct = bool(re.search(
                            r'module\.exports\s*=\s*(?:function|async function|\()',
                            mw_content
                        )) or (bool(re.search(r'module\.exports\s*=\s*\w+\s*;', mw_content))
                               and 'exports.' not in mw_content)
                        exports_named_property = bool(re.search(r'exports\.\w+\s*=', mw_content)) or \
                                                 bool(re.search(r'module\.exports\s*=\s*\{', mw_content))

                        if exports_direct and f"const {{ {mw_var} }}" in content:
                            errors.append(
                                f"server/routes/{f}: '{mw_filename}.ts' exports a direct function. "
                                f"Use 'const {mw_var} = require(...)' (without destructuring)."
                            )
                        elif exports_named_property:
                            is_destructured = bool(re.search(
                                rf"const\s+{{\s*[^}}]*\b{re.escape(mw_var)}\b[^}}]*\s*}}\s*=\s*require",
                                content
                            ))
                            is_used_with_dot = bool(re.search(rf"{re.escape(mw_var)}\.\w+", content))
                            if not is_destructured and not is_used_with_dot:
                                errors.append(
                                    f"server/routes/{f}: '{mw_filename}.ts' exports an object of functions. "
                                    f"You imported it as '{mw_var}' but used it directly as a function. "
                                    f"Use destructuring: 'const {{ {mw_var} }} = require(...)' or use '{mw_var}.methodName'."
                                )
                    except Exception:
                        pass

            except Exception as e:
                print(f"Sync check error on {f}: {e}")
                continue

        # Check server/index.ts for errorMiddleware destructuring
        server_index = os.path.join(self.sandbox_dir, "server/index.ts")
        if os.path.exists(server_index):
            try:
                with open(server_index, 'r', encoding='utf-8') as file:
                    content = file.read()
                    error_mw_destructured = [
                        "const { errorMiddleware } = require('./middleware/errorMiddleware')",
                        "const { errorHandler } = require('./middleware/errorHandler')",
                        "const { errorMiddleware } = require('./middleware/errorHandler')",
                        "const { errorHandler } = require('./middleware/errorMiddleware')"
                    ]
                    for pattern in error_mw_destructured:
                        if pattern in content:
                            errors.append(
                                f"server/index.ts: Incorrect error middleware import ('{pattern}'). "
                                "Use 'const errorMiddleware = require(...)' (direct import) if the file uses module.exports = handler."
                            )
            except Exception:
                pass

        return errors

    def _check_auth_api_connectivity(self) -> list:
        errors = []
        src_root = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_root):
            return []

        try:
            candidate_files = []
            for root, _dirs, files in os.walk(src_root):
                for fname in files:
                    if fname.endswith((".ts", ".tsx", ".js", ".jsx")):
                        candidate_files.append(os.path.join(root, fname))

            combined = []
            for full_path in candidate_files:
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        combined.append(f.read())
                except Exception:
                    continue

            content = "\n".join(combined)
            auth_spec = self.project_spec.auth if self.project_spec else None
            login_route = str(getattr(auth_spec, "login_route", "/api/auth/login") or "/api/auth/login").strip()
            register_route = str(getattr(auth_spec, "register_route", "/api/auth/register") or "/api/auth/register").strip()
            allow_registration = bool(getattr(auth_spec, "allow_registration", True)) if auth_spec else True
            login_relative = login_route.replace("/api", "", 1) if login_route.startswith("/api/") else login_route
            register_relative = register_route.replace("/api", "", 1) if register_route.startswith("/api/") else register_route

            login_pattern = rf'^\s*(?!\/\/|\/\*|\*).*?api\.post(<[^>]+>)?\([\'"`]{re.escape(login_relative)}[\'"`]'
            register_pattern = rf'^\s*(?!\/\/|\/\*|\*).*?api\.post(<[^>]+>)?\([\'"`]{re.escape(register_relative)}[\'"`]'

            has_login_api = bool(re.search(login_pattern, content, re.MULTILINE))
            has_register_api = bool(re.search(register_pattern, content, re.MULTILINE))

            if not has_login_api:
                errors.append(
                    "AUTH_INVALID: The frontend auth layer does not appear to call "
                    f"'api.post(\"{login_relative}\", ...)'. Fix: Use the unified api service to perform "
                    "a real login request from the auth service, hook, context, or equivalent auth state layer."
                )
            if allow_registration and not has_register_api:
                errors.append(
                    "AUTH_INVALID: The frontend auth layer does not appear to call "
                    f"'api.post(\"{register_relative}\", ...)'. Fix: Implement a register flow that "
                    "connects to the backend from the auth service, hook, context, or equivalent auth state layer."
                )
        except Exception:
            pass
        return errors

    def _check_auth_response_contract(self) -> list:
        if not self.project_spec or not self.project_spec.auth.enabled:
            return []

        controller_path = "server/controllers/authController.ts"
        auth_service_path = "src/services/authService.ts"
        auth_state_owner = self.project_spec.auth.state_owner or "src/context/AuthContext.tsx"

        controller_content = self._read_rel_file(controller_path)
        if not controller_content:
            return []

        frontend_auth_content = "\n".join(
            filter(
                None,
                [
                    self._read_rel_file(auth_service_path),
                    self._read_rel_file(auth_state_owner),
                    self._read_rel_file("src/pages/Login.tsx"),
                    self._read_rel_file("src/pages/Register.tsx"),
                ],
            )
        )
        if not frontend_auth_content:
            return []

        expects_token = bool(
            re.search(r"\.\s*token\b", frontend_auth_content)
            or re.search(r"\{\s*token\s*(?:,|\})", frontend_auth_content)
            or "localStorage.setItem('token'" in frontend_auth_content
            or 'localStorage.setItem("token"' in frontend_auth_content
        )
        expects_user = bool(
            re.search(r"\.\s*user\b", frontend_auth_content)
            or re.search(r"\{\s*[^}]*\buser\b[^}]*\}", frontend_auth_content)
            or re.search(r"\bsetUser\s*\(", frontend_auth_content)
        )
        if not expects_token and not expects_user:
            return []

        errors: list[str] = []
        if expects_token and not re.search(r"\btoken\b", controller_content):
            errors.append(
                "server/controllers/authController.ts: AUTH_RESPONSE_CONTRACT_ERROR: "
                "The authentication controller does not appear to return a `token`. Ensure login and register success paths return { token, user }."
            )
        if expects_user and not re.search(r"\buser\b", controller_content):
            errors.append(
                "server/controllers/authController.ts: AUTH_RESPONSE_CONTRACT_ERROR: "
                "The authentication controller does not appear to return a `user` object. Ensure login and register success paths return { token, user }."
            )

        # Real-auth integrity checks: prevent fake/demo auth flows that only look wired.
        controller_lower = controller_content.lower()
        frontend_lower = frontend_auth_content.lower()

        has_literal_token = bool(re.search(r"\btoken\s*:\s*['\"`][^'\"`]+['\"`]", controller_content))
        has_fake_markers = any(
            marker in controller_lower or marker in frontend_lower
            for marker in (
                "mock token",
                "fake token",
                "demo token",
                "sample token",
                "token123",
                "dummy user",
                "mock user",
                "fake user",
            )
        )
        if has_literal_token or has_fake_markers:
            errors.append(
                "server/controllers/authController.ts: AUTH_INVALID: "
                "Detected hardcoded/mock authentication payloads. Login/register must use real backend auth logic, not demo tokens or fake users."
            )

        mode = str(getattr(self.project_spec.auth, "mode", "token") or "token").strip().lower()
        token_based_mode = mode in {"token", "jwt", "bearer", ""}
        if token_based_mode and expects_token:
            has_token_generation = bool(
                re.search(r"\bgenerateToken\s*\(", controller_content)
                or re.search(r"\bjwt\.(sign|encode)\s*\(", controller_content)
                or re.search(r"\bsign(Token)?\s*\(", controller_content)
            )
            if not has_token_generation:
                errors.append(
                    "server/controllers/authController.ts: AUTH_INVALID: "
                    "Token-based auth is enabled but no token generation logic was found. Generate and return a real token from backend login/register."
                )

        has_password_field = "password" in frontend_lower or "password" in controller_lower
        if has_password_field:
            has_secure_password_verify = bool(
                re.search(r"\bbcrypt\.(compare|compareSync|hash|hashSync)\s*\(", controller_content)
                or re.search(r"\bargon2\.(verify|hash)\s*\(", controller_content)
                or re.search(r"\bverifyPassword\s*\(", controller_content)
                or re.search(r"\bcheckPassword\s*\(", controller_content)
            )
            has_insecure_compare = bool(re.search(r"\bpassword\s*={2,3}\s*", controller_content))
            if has_insecure_compare:
                errors.append(
                    "server/controllers/authController.ts: AUTH_INVALID: "
                    "Insecure direct password comparison detected. Use hashed password verification (bcrypt/argon2) instead."
                )
            elif not has_secure_password_verify:
                errors.append(
                    "server/controllers/authController.ts: AUTH_INVALID: "
                    "Password-based auth appears enabled but secure password hash/verify logic was not found."
                )

        has_user_lookup = bool(
            re.search(r"from\s+users\b", controller_content, re.IGNORECASE)
            or re.search(r"\bprisma\.user\.", controller_content)
            or re.search(r"\buser\.find(one|unique|first)\b", controller_content, re.IGNORECASE)
            or re.search(r"\bfind(one|unique|first)\s*\(\s*\{[^}]*email", controller_content, re.IGNORECASE)
            or re.search(r"knex\s*\(\s*['\"]users['\"]\s*\)", controller_content)
            or re.search(r"db\.prepare\s*\([^)]*users", controller_content, re.IGNORECASE)
        )
        if not has_user_lookup:
            errors.append(
                "server/controllers/authController.ts: AUTH_INVALID: "
                "No real user lookup was found for login/session flows. Query real users from the database (or ORM) before issuing auth success responses."
            )

        if bool(getattr(self.project_spec.auth, "allow_registration", True)):
            has_user_create = bool(
                re.search(r"insert\s+into\s+users\b", controller_content, re.IGNORECASE)
                or re.search(r"\bprisma\.user\.create\s*\(", controller_content)
                or re.search(r"\buser\.create\s*\(", controller_content, re.IGNORECASE)
                or re.search(r"knex\s*\(\s*['\"]users['\"]\s*\)\.insert\s*\(", controller_content)
                or re.search(r"db\.prepare\s*\([^)]*insert\s+into\s+users", controller_content, re.IGNORECASE)
            )
            if not has_user_create:
                errors.append(
                    "server/controllers/authController.ts: AUTH_INVALID: "
                    "Registration is enabled but no real user-create persistence was found. Register must write a user record to storage."
                )
        return errors

    def _check_vite_proxy(self) -> list:
        errors = []
        expected_port = str(self.backend_port)
        vite_cfg_path = os.path.join(self.sandbox_dir, "vite.config.ts")
        if not os.path.exists(vite_cfg_path):
            return ["MISSING_CONFIG: vite.config.ts not found."]
        
        try:
            with open(vite_cfg_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Match both object format { target: '...' } and shorthand string format '/api': '...'
            server_match = re.search(
                r"server\s*:\s*\{[\s\S]*?proxy\s*:\s*\{[\s\S]*?['\"]/api['\"][\s\S]*?(?:target\s*:\s*)?['\"]http://localhost:\d+['\"]",
                content,
                re.DOTALL
            )
            preview_match = re.search(
                r"preview\s*:\s*\{[\s\S]*?proxy\s*:\s*\{[\s\S]*?['\"]/api['\"][\s\S]*?(?:target\s*:\s*)?['\"]http://localhost:\d+['\"]",
                content,
                re.DOTALL
            )
            server_port_match = re.search(
                r"server\s*:\s*\{[\s\S]*?proxy\s*:\s*\{[\s\S]*?['\"]/api['\"][\s\S]*?(?:target\s*:\s*)?['\"]http://localhost:(\d+)['\"]",
                content,
                re.DOTALL
            )
            preview_port_match = re.search(
                r"preview\s*:\s*\{[\s\S]*?proxy\s*:\s*\{[\s\S]*?['\"]/api['\"][\s\S]*?(?:target\s*:\s*)?['\"]http://localhost:(\d+)['\"]",
                content,
                re.DOTALL
            )

            if not server_match:
                errors.append(
                    "MISSING_PROXY: vite.config.ts is missing the mandatory 'server.proxy' configuration for '/api'. "
                    f"Ensure it proxies to the backend server at http://localhost:{expected_port}."
                )
            if not preview_match:
                # If server.proxy exists but preview.proxy is missing, we still flag it but it's less critical.
                # However, for 100% parity, we want both.
                errors.append(
                    "INVALID_PROXY: vite.config.ts is missing a matching 'preview.proxy' target for '/api'."
                )
            if server_port_match and server_port_match.group(1) != expected_port:
                errors.append(
                    "INVALID_PROXY_PORT: vite.config.ts server.proxy target uses the wrong port. "
                    f"Backend runs on {expected_port}. Use 'http://localhost:{expected_port}' as the proxy target."
                )
            if preview_port_match and preview_port_match.group(1) != expected_port:
                errors.append(
                    "INVALID_PROXY_PORT: vite.config.ts preview.proxy target uses the wrong port. "
                    f"Backend runs on {expected_port}. Use 'http://localhost:{expected_port}' as the proxy target."
                )
            if "proxy" in content and "localhost:3000" in content and not any("INVALID_PROXY_PORT" in e for e in errors):
                errors.append(
                    "INVALID_PROXY_PORT: vite.config.ts proxy target uses port 3000. "
                    f"Backend runs on {expected_port}. Use 'http://localhost:{expected_port}' as the proxy target."
                )
        except Exception:
            pass
        return errors

    def _check_backend_db_contract(self) -> list:
        errors = []
        db_path = os.path.join(self.sandbox_dir, "server/db/database.ts")
        if not os.path.exists(db_path):
            return []

        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                db_content = f.read()
        except Exception:
            return []

        exports_direct_db = bool(
            re.search(r"module\.exports\s*=\s*db\b", db_content)
        )
        uses_sqlite3 = bool(re.search(r"(?:require\(['\"]sqlite3['\"]\)|(?:from|import)\s+['\"]sqlite3['\"])", db_content))
        uses_better_sqlite = bool(re.search(r"(?:require\(['\"]better-sqlite3['\"]\)|(?:from|import)\s+['\"]better-sqlite3['\"])", db_content))
        if uses_sqlite3 and uses_better_sqlite:
            errors.append(
                "DB_CONTRACT_ERROR: server/db/database.ts mixes `sqlite3` and `better-sqlite3`. "
                "Use `better-sqlite3` only in this pipeline."
            )
        elif uses_sqlite3:
            errors.append(
                "DB_CONTRACT_ERROR: server/db/database.ts uses `sqlite3`, but this pipeline standardizes on "
                "`better-sqlite3`. Rewrite the database module and all DB consumers to use synchronous "
                "`db.prepare(...).get/all/run()`."
            )
        elif not uses_better_sqlite:
            errors.append(
                "DB_CONTRACT_ERROR: server/db/database.ts does not clearly use `better-sqlite3`. "
                "This pipeline expects a single SQLite driver: `better-sqlite3`."
            )

        backend_consumer_files: list[tuple[str, str]] = []
        for rel_dir in ("server/controllers", "server/middleware"):
            full_dir = os.path.join(self.sandbox_dir, rel_dir)
            if not os.path.isdir(full_dir):
                continue
            for name in os.listdir(full_dir):
                if not name.endswith(".ts"):
                    continue
                rel_path = f"{rel_dir}/{name}"
                backend_consumer_files.append((rel_path, os.path.join(full_dir, name)))

        callback_db_pattern = re.compile(
            r"db\.(?:all|get|run)\([^)]*,\s*(?:function|\([^)]*\)\s*=>)",
            re.DOTALL,
        )
        for rel_path, full_path in backend_consumer_files:
            base_name = os.path.basename(rel_path)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    ctrl_content = f.read()
            except Exception:
                continue

            if exports_direct_db and re.search(
                r"const\s*\{\s*db\s*\}\s*=\s*require\(['\"]\.\./db/database['\"]\)",
                ctrl_content,
            ):
                errors.append(
                    f"DB_CONTRACT_ERROR: {base_name} destructures '{{ db }}' from server/db/database.ts, "
                    "but that module exports the database object directly. Use `const db = require('../db/database')`."
                )

            has_callback_style = bool(callback_db_pattern.search(ctrl_content))
            if uses_better_sqlite and has_callback_style:
                errors.append(
                    f"DB_CONTRACT_ERROR: {base_name} uses sqlite-style callbacks with `db.all/get/run`, "
                    "but server/db/database.ts uses better-sqlite3. Remove callbacks and use synchronous `.get()/.all()/.run()` results."
                )
            elif uses_better_sqlite and ".prepare(" not in ctrl_content and re.search(r"\bdb\.(?:all|get|run)\(", ctrl_content):
                errors.append(
                    f"DB_CONTRACT_ERROR: {base_name} uses direct `db.get/all/run` calls, "
                    "but server/db/database.ts uses better-sqlite3. Use `db.prepare(...).get/all/run()` consistently."
                )

        return errors

    def _check_frontend_http_client_contract(self) -> list[str]:
        errors: list[str] = []
        src_root = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_root):
            return errors

        api_client_path = os.path.join(src_root, "services", "api.ts")
        api_client_exists = os.path.exists(api_client_path)
        api_client_uses_axios = False
        if api_client_exists:
            try:
                with open(api_client_path, "r", encoding="utf-8") as handle:
                    api_client_content = handle.read()
                api_client_uses_axios = bool(
                    re.search(r"import\s+.+?\s+from\s+['\"]axios['\"]", api_client_content)
                    or re.search(r"require\(['\"]axios['\"]\)", api_client_content)
                )
            except Exception:
                api_client_uses_axios = False

        fetch_files: list[str] = []
        direct_axios_files: list[str] = []
        for root, _dirs, files in os.walk(src_root):
            if any(skip in root for skip in ("node_modules", "dist", "build")):
                continue
            for file_name in files:
                if not file_name.endswith((".ts", ".tsx", ".js", ".jsx")):
                    continue
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, self.sandbox_dir).replace("\\", "/")
                try:
                    with open(full_path, "r", encoding="utf-8") as handle:
                        content = handle.read()
                except Exception:
                    continue

                if rel_path == "src/services/api.ts":
                    continue
                if self._has_raw_fetch_call(content):
                    fetch_files.append(rel_path)
                if re.search(r"import\s+.+?\s+from\s+['\"]axios['\"]", content) or re.search(r"require\(['\"]axios['\"]\)", content):
                    direct_axios_files.append(rel_path)

        if api_client_exists and not api_client_uses_axios:
            errors.append(
                "src/services/api.ts: HTTP_CLIENT_CONTRACT_ERROR: The shared API client must use axios directly. "
                "This pipeline standardizes on axios via src/services/api.ts."
            )

        for rel_path in sorted(fetch_files):
            errors.append(
                f"{rel_path}: HTTP_CLIENT_CONTRACT_ERROR: Direct fetch() is not allowed in the generated frontend. "
                "Use the shared axios client from src/services/api.ts instead."
            )

        for rel_path in sorted(direct_axios_files):
            errors.append(
                f"{rel_path}: HTTP_CLIENT_CONTRACT_ERROR: Direct axios imports are not allowed outside src/services/api.ts. "
                "Import the shared `api` client or a service built on top of it instead."
            )

        if (fetch_files and api_client_exists) or (fetch_files and direct_axios_files):
            errors.append(
                "HTTP_CLIENT_MIXED: Frontend code mixes raw fetch() and the axios-based shared client. "
                "Use a single HTTP stack: axios only via src/services/api.ts."
            )

        return errors

    @staticmethod
    def _has_raw_fetch_call(content: str) -> bool:
        src = str(content or "")
        if not src:
            return False

        if re.search(r"\b(?:window|globalThis)\.fetch\s*\(", src):
            return True

        local_fetch_declared = bool(
            re.search(r"\b(?:const|let|var|function)\s+fetch\b", src)
            or re.search(r"\bimport\s+fetch\s+from\b", src)
            or re.search(r"\bimport\s*\{\s*fetch(?:\s+as\s+\w+)?\s*\}\s*from\b", src)
            or re.search(r"\b(?:const|let|var)\s*\{\s*fetch(?:\s*:\s*\w+)?\s*\}\s*=", src)
        )

        if re.search(r"\b(?:await|return)\s+fetch\s*\(", src) and not local_fetch_declared:
            return True

        if re.search(r"(?<![\w$.])fetch\s*\(", src) and not local_fetch_declared:
            return True

        return False

    # ── SQL-Aware Validation Helpers ─────────────────────────────────────────

    _SQL_SAFE_EXPRESSIONS = frozenset({
        "true", "false", "null", "not", "and", "or", "is", "in",
        "like", "between", "exists", "case", "when", "then", "else",
        "end", "as", "on", "asc", "desc", "limit", "offset",
        "count", "sum", "avg", "min", "max", "group", "having",
        "distinct", "coalesce", "ifnull", "nullif", "cast",
        "inner", "left", "right", "outer", "cross", "join",
        "select", "from", "where", "order", "by", "insert",
        "into", "update", "set", "delete", "values",
    })

    @staticmethod
    def _parse_sql_aliases(sql_block: str) -> dict:
        """Parse FROM/JOIN clauses to build alias → table_name map."""
        alias_map: dict[str, str] = {}
        # Match:  FROM table_name alias  |  JOIN table_name alias ON ...
        for m in re.finditer(
            r"(?:FROM|JOIN)\s+(\w+)\s+(?:AS\s+)?(\w+)",
            sql_block,
            re.IGNORECASE,
        ):
            table, alias = m.group(1), m.group(2)
            low_alias = alias.lower()
            # Skip SQL keywords that look like aliases
            if low_alias in ("on", "where", "set", "inner", "left", "right",
                             "outer", "cross", "join", "order", "group",
                             "having", "limit", "as", "values", "select"):
                continue
            alias_map[low_alias] = table.lower()
        # Also register each table as its own "alias" for unqualified refs
        for m in re.finditer(r"(?:FROM|JOIN)\s+(\w+)", sql_block, re.IGNORECASE):
            table = m.group(1).lower()
            if table not in alias_map:
                alias_map[table] = table
        return alias_map

    @staticmethod
    def _is_sql_literal_or_expression(token: str) -> bool:
        """Return True if token is a SQL literal, placeholder, number, or safe keyword."""
        t = token.strip()
        if not t:
            return True
        # Numeric literals (1, 0, 42, 3.14)
        if re.fullmatch(r"\d+(\.\d+)?", t):
            return True
        # Parameterized placeholders (?, $1, :param, @param)
        if t.startswith(("?", "$", ":", "@")):
            return True
        # String literals
        if (t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"')):
            return True
        # Template expressions like ${...}
        if "${" in t:
            return True
        # SQL keywords / functions
        if t.lower() in FeatureValidator._SQL_SAFE_EXPRESSIONS:
            return True
        # Function calls like COUNT(...), LOWER(...)
        if re.fullmatch(r"\w+\s*\(", t) or "(" in t:
            return True
        return False

    def _extract_sql_column_refs(
        self, clause: str, alias_map: dict, schema_map: dict
    ) -> list[tuple[str, str, str]]:
        """
        Extract (resolved_table, column, confidence) tuples from a SQL clause.
        Handles qualified (alias.col) and unqualified (col) references.
        Returns only refs where the table could be resolved.
        """
        refs = []
        select_aliases = {
            match.group(1)
            for match in re.finditer(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)", clause, re.IGNORECASE)
        }
        # Qualified refs: alias.column
        for m in re.finditer(r"(\w+)\.(\w+)", clause):
            qualifier, col = m.group(1).lower(), m.group(2)
            if self._is_sql_literal_or_expression(col):
                continue
            if qualifier in alias_map:
                resolved_table = alias_map[qualifier]
                refs.append((resolved_table, col, "HIGH"))

        # Unqualified refs after WHERE/ORDER BY/GROUP BY keywords
        # These are harder — only flag with MEDIUM confidence if they
        # appear alone (not part of a qualified ref)
        qualified_cols = {col for _, col, _ in refs}
        known_table_or_alias_identifiers = {
            str(key or "").lower()
            for key in (alias_map or {}).keys()
            if str(key or "").strip()
        } | {
            str(value or "").lower()
            for value in (alias_map or {}).values()
            if str(value or "").strip()
        }
        for m in re.finditer(r"(?<![.\w])(\w+)(?![.\w(])", clause):
            col = m.group(1)
            if col in qualified_cols:
                continue
            if col in select_aliases:
                continue
            if col.lower() in known_table_or_alias_identifiers:
                continue
            if self._is_sql_literal_or_expression(col):
                continue
            # Try to find which table this belongs to
            # If only one table in context has this column, it's clear
            matching_tables = [
                tname for tname, tcols in schema_map.items()
                if col.lower() in [c.lower() for c in tcols]
                and tname.lower() in [v for v in alias_map.values()]
            ]
            if len(matching_tables) == 1:
                continue  # Column exists in a known table — no error
            # If column doesn't exist in ANY table in context, flag it
            all_tables_in_context = set(alias_map.values())
            in_any_table = any(
                col.lower() in [c.lower() for c in schema_map.get(t, set())]
                for t in all_tables_in_context
                if t in schema_map
            )
            if not in_any_table and all_tables_in_context:
                # Attribute to the primary table (first FROM)
                primary = next(iter(alias_map.values()), None)
                if primary and primary in schema_map:
                    refs.append((primary, col, "MEDIUM"))

        return refs

    # ── Schema-Controller Column Sync (SQL-aware) ─────────────────────────

    def _extract_create_table_blocks(self, schema_content: str) -> list[tuple[str, str]]:
        tables: list[tuple[str, str]] = []
        pattern = re.compile(
            r"CREATE TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)\s*\(",
            re.IGNORECASE,
        )

        for match in pattern.finditer(str(schema_content or "")):
            table_name = match.group(1)
            body_start = match.end()
            index = body_start
            depth = 1
            quote_char = ""

            while index < len(schema_content):
                char = schema_content[index]
                prev_char = schema_content[index - 1] if index > 0 else ""

                if quote_char:
                    if char == quote_char and prev_char != "\\":
                        quote_char = ""
                    index += 1
                    continue

                if char in {"'", '"', "`"}:
                    quote_char = char
                    index += 1
                    continue

                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        tables.append((table_name, schema_content[body_start:index]))
                        break
                index += 1

        return tables

    def _check_schema_controller_column_sync(self) -> list:
        errors = []
        schema_path = ""
        for candidate in (
            "server/db/schema.ts",
            "server/db/database.ts",
            "server/database.ts",
            "server/db.ts",
        ):
            full_candidate = os.path.join(self.sandbox_dir, candidate)
            if os.path.exists(full_candidate):
                schema_path = full_candidate
                break
        controllers_dir = os.path.join(self.sandbox_dir, "server/controllers")

        if not schema_path or not os.path.exists(controllers_dir):
            return []

        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_content = f.read()

            tables = self._extract_create_table_blocks(schema_content)
            schema_map: dict[str, set[str]] = {}
            for table_name, body in tables:
                cols = re.findall(r"^\s*(\w+)\s+", body, re.MULTILINE)
                # Filter out SQL keywords that aren't columns
                cols = [c for c in cols if c.upper() not in (
                    "PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT",
                    "INDEX", "REFERENCES", "DEFAULT", "NOT", "NULL",
                )]
                schema_map[table_name.lower()] = set(cols)

            # Always-valid implicit columns
            implicit_cols = {"id", "rowid", "created_at", "updated_at", "published_at"}

            for ctrl_file in os.listdir(controllers_dir):
                if not ctrl_file.endswith(".ts"):
                    continue
                ctrl_path = os.path.join(controllers_dir, ctrl_file)
                with open(ctrl_path, 'r', encoding='utf-8') as f:
                    ctrl_content = f.read()

                # Extract SQL blocks from template literals and string literals
                sql_blocks = []
                for match in re.finditer(
                    r"`([\s\S]*?)`"
                    r"|'([^'\n]*?(?:SELECT|INSERT|UPDATE|DELETE)[^'\n]*?)'"
                    r"|\"([^\"\n]*?(?:SELECT|INSERT|UPDATE|DELETE)[^\"\n]*?)\"",
                    ctrl_content, re.IGNORECASE,
                ):
                    sql_block = next((g for g in match.groups() if g), "")
                    if sql_block:
                        sql_blocks.append(sql_block)

                for sql_block in sql_blocks:
                    alias_map = self._parse_sql_aliases(sql_block)

                    # ── INSERT column validation ──
                    for table_name_lower, table_cols in schema_map.items():
                        insert_re = re.compile(
                            rf"INSERT\s+INTO\s+{re.escape(table_name_lower)}\s*\(([^)]+)\)",
                            re.IGNORECASE,
                        )
                        for m in insert_re.finditer(sql_block):
                            col_list = [c.strip() for c in m.group(1).split(",")]
                            cols_lower = {c.lower() for c in table_cols} | implicit_cols
                            for c in col_list:
                                if not c or self._is_sql_literal_or_expression(c):
                                    continue
                                if c.lower() not in cols_lower:
                                    errors.append(
                                        f"SCHEMA_SYNC_ERROR: {ctrl_file} attempts to insert "
                                        f"into non-existent '{table_name_lower}' column '{c}'. "
                                        f"Schema uses: {sorted(table_cols)}"
                                    )

                    # ── WHERE clause validation ──
                    where_match = re.search(
                        r"\bWHERE\b(.*?)(?:\bORDER\b|\bGROUP\b|\bLIMIT\b|\bHAVING\b|$)",
                        sql_block, re.IGNORECASE | re.DOTALL,
                    )
                    if where_match:
                        where_clause = where_match.group(1)
                        col_refs = self._extract_sql_column_refs(
                            where_clause, alias_map, schema_map,
                        )
                        for resolved_table, col, _confidence in col_refs:
                            if resolved_table not in schema_map:
                                continue
                            table_cols = schema_map[resolved_table]
                            cols_lower = {c.lower() for c in table_cols} | implicit_cols
                            if col.lower() not in cols_lower:
                                errors.append(
                                    f"SCHEMA_SYNC_ERROR: {ctrl_file} query references "
                                    f"non-existent '{resolved_table}' column '{col}' "
                                    f"in WHERE clause."
                                )

                    # ── ORDER BY clause validation ──
                    order_match = re.search(
                        r"\bORDER\s+BY\b(.*?)(?:\bLIMIT\b|\bOFFSET\b|$)",
                        sql_block, re.IGNORECASE | re.DOTALL,
                    )
                    if order_match:
                        order_clause = order_match.group(1)
                        col_refs = self._extract_sql_column_refs(
                            order_clause, alias_map, schema_map,
                        )
                        for resolved_table, col, _confidence in col_refs:
                            if resolved_table not in schema_map:
                                continue
                            table_cols = schema_map[resolved_table]
                            cols_lower = {c.lower() for c in table_cols} | implicit_cols
                            if col.lower() not in cols_lower:
                                errors.append(
                                    f"SCHEMA_SYNC_ERROR: {ctrl_file} query references "
                                    f"non-existent '{resolved_table}' column '{col}' "
                                    f"in ORDER BY clause."
                                )

                    # ── GROUP BY clause validation ──
                    group_match = re.search(
                        r"\bGROUP\s+BY\b(.*?)(?:\bHAVING\b|\bORDER\b|\bLIMIT\b|$)",
                        sql_block, re.IGNORECASE | re.DOTALL,
                    )
                    if group_match:
                        group_clause = group_match.group(1)
                        col_refs = self._extract_sql_column_refs(
                            group_clause, alias_map, schema_map,
                        )
                        for resolved_table, col, _confidence in col_refs:
                            if resolved_table not in schema_map:
                                continue
                            table_cols = schema_map[resolved_table]
                            cols_lower = {c.lower() for c in table_cols} | implicit_cols
                            if col.lower() not in cols_lower:
                                errors.append(
                                    f"SCHEMA_SYNC_ERROR: {ctrl_file} query references "
                                    f"non-existent '{resolved_table}' column '{col}' "
                                    f"in GROUP BY clause."
                                )

        except Exception:
            pass
        return errors
