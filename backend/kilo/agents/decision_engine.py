"""
DecisionEngine — AI-Powered Root Cause Decision Engine
======================================================

BUG FIX: Added missing error types to _TYPE_TO_LAYER that were detected
by error_analyzer but not mapped here, causing them to always fall through
to "unknown" and skip targeted fix logic:
  - ROUTE_MIDDLEWARE_MISMATCH → backend / fix_route_middleware
  - MISSING_IMPORT_FILE       → frontend / fix_missing_import
  - MISSING_EXPORT_DEFAULT    → frontend / fix_missing_export
 - JSON_SYNTAX_ERROR         → backend  / fix_json
  - AUTH_INVALID              → integration / fix_auth_connectivity
  - SCHEMA_SYNC_ERROR         → database / fix_schema
  - API_CONTRACT_DRIFT       → integration / fix_api_contract
  - JSX_IN_TS_FILE            → frontend / fix_jsx_extension
"""

import logging
import os
import re
import shlex

logger = logging.getLogger(__name__)

# ── Layer mapping: error_analyzer type → structured decision layer ────────────

_TYPE_TO_LAYER = {
    # Frontend
    "UNSUPPORTED_JSX_STYLE":        ("frontend",     "fix_jsx_style"),
    "MISMATCHED_IMPORT":            ("frontend",     "fix_import"),
    "MISSING_HOOK_IMPORT":          ("frontend",     "fix_import"),
    "IMPORT_SITE_ERROR":            ("frontend",     "fix_import"),
    "MODULE_EXPORT_MISSING":        ("frontend",     "fix_missing_export"),
    "STRICT_MODE_VIOLATION":        ("frontend",     "fix_component"),
    "HARDCODED_COLOR":              ("frontend",     "fix_style"),
    "MISSING_RETURN_JSX":           ("frontend",     "fix_component"),
    "RUNTIME_UI_BLANK_PAGE":        ("frontend",     "fix_blank_page"),
    "RUNTIME_UI_CRASH":             ("frontend",     "fix_component"),
    "API_RESPONSE_ENVELOPE_MISMATCH": ("integration", "fix_api_contract"),
    "BLUEPRINT_NOT_ENFORCED":      ("integration",  "fix_api_contract"),
    "HTTP_CLIENT_MIXED":           ("frontend",     "fix_http_client"),
    "HTTP_CLIENT_CONTRACT_ERROR":  ("frontend",     "fix_http_client"),
    "TAILWIND_RUNTIME_MISSING":     ("frontend",     "fix_style"),
    "STYLESHEET_CLASS_MISSING":     ("frontend",     "fix_style"),
    "STYLESHEET_CLASS_EMPTY":       ("frontend",     "fix_style"),
    "STYLESHEET_CLASS_INCOMPLETE":  ("frontend",     "fix_style"),
    "FRONTEND_DESIGN_QUALITY_MISSING": ("frontend",  "fix_style"),
    "ROOT_PROVIDER_MISSING":        ("frontend",     "fix_provider"),
    "FEATURE_VALIDATION_BRIDGE_ERROR": ("integration", "fix_integration"),
    "MISSING_VITE_TYPE":            ("frontend",     "fix_html"),
    "ENV_VAR_UNPROTECTED":          ("frontend",     "fix_env"),
    "UNOPTIMIZED_FETCH":            ("frontend",     "fix_component"),
    "MISSING_ASSET":                ("frontend",     "fix_asset"),
    "CONNECTED_FEATURE_MISSING":    ("integration",  "fix_integration"),
    "DISCONNECTED_ROUTE":           ("integration",  "fix_integration"),
    "API_BASE_URL_HARDCODED":       ("frontend",     "fix_api_url"),
    "JSX_IN_TS_FILE":               ("frontend",     "fix_jsx_extension"),
    # BUG FIX: These frontend errors were detected but not mapped → fell to unknown
    "MISSING_IMPORT_FILE":          ("frontend",     "fix_missing_import"),
    "MISSING_EXPORT_DEFAULT":       ("frontend",     "fix_missing_export"),

    # Backend
    "CJS_ESM_MIX":                  ("backend",      "fix_cjs_esm"),
    "MISSING_EXPRESS_LISTEN":       ("backend",      "fix_server_entry"),
    "RUNTIME_BACKEND_CRASH":        ("backend",      "fix_runtime"),
    "ROUTE_CALLBACK_ERROR":         ("backend",      "fix_controller"),
    "DATABASE_LOCK":                ("database",     "fix_db_connection"),
    "ROUTE_NOT_FOUND":              ("backend",      "fix_route"),
    "MIDDLEWARE_ORDER":             ("backend",      "fix_middleware"),
    "DATABASE_UNINITIALIZED":       ("database",     "fix_schema"),
    # BUG FIX: ROUTE_MIDDLEWARE_MISMATCH was in error_analyzer but absent here.
    # Routes passing undefined to Express because of wrong require() style
    # (destructured vs direct) now get routed to backend fix with a clear strategy.
    "ROUTE_MIDDLEWARE_MISMATCH":    ("backend",      "fix_route_middleware"),

    # Config
    "MISSING_DEPENDENCY":           ("backend",      "add_dependency"),
    "VITE_TERSER_MISSING":          ("frontend",     "fix_vite_config"),
    "INVALID_PROXY":                ("integration",  "fix_proxy"),
    "SYNTAX_ERROR":                 ("backend",      "fix_syntax"),
    "INVALID_JSON":                 ("backend",      "fix_json"),
    # BUG FIX: JSON_SYNTAX_ERROR was detected but not mapped
    "JSON_SYNTAX_ERROR":            ("backend",      "fix_json"),
    "PORT_COLLISION":               ("backend",      "fix_port"),

    # Integration / auth
    # BUG FIX: AUTH_INVALID and SCHEMA_SYNC_ERROR were never mapped here,
    # so auth connectivity problems always fell to unknown → no targeted fix.
    "AUTH_INVALID":                 ("integration",  "fix_auth_connectivity"),
    "AUTH_RESPONSE_CONTRACT_ERROR": ("integration",  "fix_auth_contract"),
    "SCHEMA_SYNC_ERROR":            ("database",     "fix_schema"),
    "API_CONTRACT_DRIFT":           ("integration",  "fix_api_contract"),
    "STRUCTURAL_DRIFT":             ("system",       "delete_ghost_file"),
}

_SEVERITY_TO_CONFIDENCE = {
    "CRITICAL": "HIGH",
    "HIGH":     "HIGH",
    "MEDIUM":   "MEDIUM",
    "LOW":      "LOW",
}


class DecisionEngine:
    """
    AI-powered triage engine.  Call await engine.decide(...) from
    unified_self_healing or the active orchestrator loop to get a structured decision
    before choosing a fix path.
    """

    def __init__(self, error_analyzer, provider=None, model_id: str = "", backend_port: int = 3001):
        self.error_analyzer = error_analyzer
        self.provider       = provider
        self.model_id       = model_id
        self.backend_port   = backend_port

    # ── Public entry point ────────────────────────────────────────────────────

    async def decide(
        self,
        error_log:     str,
        ast_summary:   str = "",
        graph_summary: str = "",
        sandbox_dir:   str = "",
        query_context: str = "",
        allow_query_commands: bool = True,
        force_ai: bool = False,
        project_spec: dict | None = None,
        phase_context: str = "",
        target_file_hint: str = "",
    ) -> dict:
        """
        Run Step 1 (rule) then Step 2 (AI) if needed.
        Always returns a fully-populated decision dict.
        """
        # ── Step 1: rule-based classification via error_analyzer ──────────────
        if not force_ai:
            rule_result = self._rule_classify(error_log, sandbox_dir=sandbox_dir)
            if rule_result["layer"] != "unknown":
                rule_result = self._apply_target_hints(
                    rule_result,
                    project_spec=project_spec,
                    phase_context=phase_context,
                    target_file_hint=target_file_hint,
                )
                logger.info(
                    f"[DecisionEngine] Rule matched: layer={rule_result['layer']}, "
                    f"strategy={rule_result['strategy']}, confidence={rule_result['confidence']}"
                )
                return rule_result

            logger.info("[DecisionEngine] Rule classification returned unknown — escalating to AI.")
        else:
            logger.info("[DecisionEngine] force_ai=True — skipping rule classification and calling AI directly.")

        # ── Step 2: AI classification ─────────────────────────────────────────
        if self.provider is None:
            logger.warning("[DecisionEngine] No LLM provider — cannot run AI classification.")
            return _unknown_decision("No LLM provider available for AI classification.")

        try:
            return await self._ai_classify(
                error_log,
                ast_summary,
                graph_summary,
                sandbox_dir,
                query_context=query_context,
                allow_query_commands=allow_query_commands,
                project_spec=project_spec,
                phase_context=phase_context,
                target_file_hint=target_file_hint,
            )
        except Exception as exc:
            logger.error(f"[DecisionEngine] AI classification failed: {exc}")
            return _unknown_decision(f"AI classification error: {exc}")

    # ── Step 1: rule-based ────────────────────────────────────────────────────

        # ── Step 1: rule-based classification via error_analyzer ──────────────
    def _rule_classify(self, error_log: str, sandbox_dir: str = "") -> dict:
        """
        Use error_analyzer.analyze() to identify known patterns instantly.
        Maps the error_type to a structured layer+strategy decision.
        """
        lowered_error = error_log.lower()

        if any(
            marker in lowered_error
            for marker in (
                "missing 'server' script",
                'remove "type": "module"',
                "better-sqlite3 must be pinned",
            )
        ):
            return self._normalize_decision({
                "layer":        "backend",
                "confidence":   "HIGH",
                "strategy":     "fix_package_runtime_contract",
                "target_files": ["package.json", "server/index.ts", "server/db/database.ts"],
                "root_cause":   (
                    "package.json and the backend runtime contract drifted away from the canonical pipeline requirements."
                ),
                "fix_hint":     (
                    "Rewrite package.json to use the exact backend script `node --import tsx server/index.ts`, ADD "
                    "`type: module`, keep axios in dependencies, and pin `better-sqlite3` to `^12.2.0`. "
                    "Keep backend server files 100% ESM."
                ),
                "command":      None,
                "command_kind": "none",
                "return_query_result": "no",
                "write_files":  "yes",
                "source":       "rule",
            })

        if any(
            marker in lowered_error
            for marker in (
                "ts6310",
                "tsconfig_purity_error",
                "allowimportingtsextensions",
                "referenced project",
                "may not disable emit",
                "tsconfig.node.json",
            )
        ) and ("tsconfig" in lowered_error or "noemit" in lowered_error or "composite" in lowered_error):
            return self._normalize_decision({
                "layer":        "frontend",
                "confidence":   "HIGH",
                "strategy":     "fix_tsconfig_contract",
                "target_files": ["tsconfig.json", "tsconfig.node.json"],
                "root_cause":   (
                    "TypeScript config contract drift: composite tsconfig.node.json and emitted/noEmit/extension "
                    "settings are incompatible."
                ),
                "fix_hint":     (
                    "Repair tsconfig.json and tsconfig.node.json as a pair. Keep tsconfig include to ['src']. "
                    "Use a standalone tsconfig.node.json for vite.config.ts with composite=true and noEmit=false. "
                    "Do not inherit frontend-only allowImportingTsExtensions into tsconfig.node.json."
                ),
                "command":      None,
                "command_kind": "none",
                "return_query_result": "no",
                "write_files":  "yes",
                "source":       "rule",
            })

        # Special case: Backend is missing or not starting
        if "npm run dev" in lowered_error and ("error" in lowered_error or "not found" in lowered_error):
            return self._normalize_decision({
                "layer":        "backend",
                "confidence":   "HIGH",
                "strategy":     "FIX_PACKAGE_JSON",
                "target_files": ["package.json", "server/index.ts"],
                "root_cause":   "Frontend dev script was used where a backend server command is required",
                "fix_hint":     "Use the dedicated backend start path. Ensure package.json has a 'server' script pointing to 'node --import tsx server/index.ts' instead of relying on 'npm run dev' to boot the backend.",
                "command":      "cat package.json",
                "source":       "rule",
                "issue_class":  "GENERATION_ERROR",
            })

        runtime_api_match = re.search(rf"http (404|500) http://localhost:{self.backend_port}/api/([a-z0-9_-]+)", lowered_error)
        if runtime_api_match:
            status_code = runtime_api_match.group(1)
            endpoint = runtime_api_match.group(2)
            targets = _guess_runtime_api_targets(endpoint)
            return self._normalize_decision({
                "layer":        "integration",
                "confidence":   "HIGH",
                "strategy":     "fix_route" if status_code == "404" else "fix_integration",
                "target_files": targets,
                "root_cause":   (
                    f"The frontend runtime requested '/api/{endpoint}' but received HTTP {status_code}. "
                    "The backend route is missing, mounted under a different path, or returning the wrong response shape."
                ),
                "fix_hint":     (
                    f"Ensure the backend mounts the exact '/api/{endpoint}' route in server/index.ts and that the matching "
                    f"route/controller file exports working handlers. Also ensure the frontend uses the same resource name and "
                    "does not call placeholder or stub data once the API exists."
                ),
                "source":       "rule",
            })

        if (
            ("axioserror" in lowered_error or "http 404" in lowered_error or "status code 404" in lowered_error)
            and "/api/" in lowered_error
        ):
            is_auth_404 = "/api/auth" in lowered_error
            return self._normalize_decision({
                "layer":        "integration",
                "confidence":   "HIGH",
                "strategy":     "fix_auth_connectivity" if is_auth_404 else "fix_proxy",
                "target_files": (
                    ["vite.config.ts", "server/index.ts", "src/services/api.ts", "src/context/AuthContext.tsx"]
                    if is_auth_404 else
                    ["vite.config.ts", "src/services/api.ts"]
                ),
                "root_cause":   (
                    "Frontend API requests are returning HTTP 404 during runtime validation. "
                    "This usually means preview/dev proxy wiring is wrong or the backend route is not mounted."
                ),
                "fix_hint":     (
                    f"Keep the frontend on port 3000 and the backend on port {self.backend_port}. "
                    "Ensure vite.config.ts defines BOTH server.proxy and preview.proxy for '/api' targeting "
                    f"'http://localhost:{self.backend_port}'. Ensure src/services/api.ts uses baseURL '/api'. "
                    "If the failing URL is /api/auth/*, verify server/index.ts mounts app.use('/api/auth', authRoutes). "
                    "Do NOT change the backend port to 3000 or 5000."
                ),
                "source":       "rule",
            })

        if "/api/api/" in lowered_error:
            return self._normalize_decision({
                "layer":        "frontend",
                "confidence":   "HIGH",
                "strategy":     "fix_api_url",
                "target_files": ["src/services/api.ts"],
                "root_cause":   "Frontend requests contain a duplicated /api prefix.",
                "fix_hint":     (
                    "The axios client already uses baseURL '/api', so application code must call endpoints like "
                    "'/users', '/products', '/dashboard/stats', or other resource paths without adding another '/api'. "
                    "Keep exactly one /api prefix in the final request URL."
                ),
                "source":       "rule",
            })

        undefined_route_match = re.search(r"/([a-z0-9_-]+)/undefined(?:[\"'/?#<\s]|$)", lowered_error)
        if undefined_route_match and undefined_route_match.group(1) not in {"api", "assets", "static"}:
            route_segment = undefined_route_match.group(1)
            return self._normalize_decision({
                "layer":        "frontend",
                "confidence":   "HIGH",
                "strategy":     "fix_component_props_with_types",
                "target_files": _guess_dynamic_param_targets(route_segment),
                "root_cause":   f"Rendered links for '{route_segment}' contain an undefined dynamic parameter, which usually means the frontend is reading the wrong field names or using placeholder data instead of the real API contract.",
                "fix_hint":     (
                    "Align the frontend list/detail components, shared types, and API service with the actual backend payload. "
                    "Use the real identifier field returned by the API for links and detail routes, and remove placeholder stub data once live API data is available."
                ),
                "source":       "rule",
            })

        if (
            ("triggeruncaughtexception" in lowered_error or "node:internal/modules/run_main" in lowered_error)
            and not _extract_error_paths(error_log, limit=1)
        ):
            return self._normalize_decision({
                "layer":        "backend",
                "confidence":   "HIGH",
                "strategy":     "inspect_backend_boot_log",
                "target_files": ["server/index.ts", "server/db/database.ts"],
                "root_cause":   (
                    "Node crashed during backend bootstrap, but the current log excerpt does not identify the actual app file yet."
                ),
                "fix_hint":     (
                    "Inspect the real backend boot log before editing files. Ensure the project is 100% ESM before making changes; "
                    "server files must use 'import' and 'export', and package.json must have 'type': 'module'."
                ),
                "command":      "tail -120 /tmp/sandbox_server.log || cat /tmp/sandbox_server.log || cat server/index.ts",
                "command_kind": "query",
                "return_query_result": "yes",
                "write_files":  "no",
                "source":       "rule",
            })

        result = self.error_analyzer.analyze(error_log)
        error_type = result.get("type", "UNKNOWN")
        severity   = result.get("severity", "MEDIUM")
        fix_hint   = result.get("fix", "")

        if error_type == "API_CONTRACT_DRIFT":
            return self._normalize_decision({
                "layer":        "integration",
                "confidence":   "HIGH",
                "strategy":     "fix_api_contract",
                "target_files": _guess_api_contract_targets(error_log, sandbox_dir),
                "root_cause":   (
                    "The project is using mixed field names for the same resource across backend, shared types, hooks, and UI, "
                    "so isolated component fixes will keep failing until the contract is standardized."
                ),
                "fix_hint":     (
                    "Standardize the PUBLIC contract to camelCase outside raw SQL/schema files. Keep database column names "
                    "snake_case if needed, but alias them in controller SQL/results and use camelCase in shared types, hooks, "
                    "request bodies, and React components."
                ),
                "command":      None,
                "command_kind": "none",
                "return_query_result": "no",
                "write_files":  "yes",
                "source":       "rule",
            })

        if "enospc" in lowered_error and "file watchers" in lowered_error:
            return self._normalize_decision({
                "layer":        "frontend",
                "confidence":   "HIGH",
                "strategy":     "WATCHER_LIMIT_ERROR",
                "target_files": ["vite.config.ts"],
                "root_cause":   "System file watcher limit reached (ENOSPC)",
                "fix_hint":     "Add 'server: { watch: { usePolling: true } }' to vite.config.ts as a workaround instead of attempting sudo commands.",
                "source":       "rule",
            })

        if "STRUCTURAL_DRIFT" in error_log:
            # Parse the path from "path/to/file: STRUCTURAL_DRIFT: ..." or similar
            # Look for any sequence before ": STRUCTURAL_DRIFT"
            path_match = re.search(r"([^\s:]+):\s*STRUCTURAL_DRIFT", error_log)
            target_path = path_match.group(1).strip() if path_match else None
            return self._normalize_decision({
                "layer":        "system",
                "confidence":   "HIGH",
                "strategy":     "delete_ghost_file",
                "target_files": [target_path] if target_path else [],
                "root_cause":   f"Structural drift detected: {target_path} violates project language spec (e.g. .js in .ts project).",
                "fix_hint":     f"Delete the redundant file {target_path} to maintain project structural purity.",
                "command":      f"rm -f {shlex.quote(target_path)}" if target_path else None,
                "command_kind": "mutation",
                "write_files":  "no",
                "source":       "rule",
            })

        if error_type == "UNKNOWN" or error_type == "RECURSIVE_FAILURE":
            return _unknown_decision("No rule matched the error log.")

        layer, strategy = _TYPE_TO_LAYER.get(error_type, ("unknown", error_type.lower()))
        confidence = _SEVERITY_TO_CONFIDENCE.get(severity, "MEDIUM")

        return self._normalize_decision({
            "layer":        layer,
            "confidence":   confidence,
            "strategy":     strategy,
            "target_files": _guess_target_files(error_log, layer),
            "root_cause":   f"{error_type}: {fix_hint[:120]}",
            "fix_hint":     fix_hint,
            "command":      self._extract_command(error_log, error_type),
            "source":       "rule",
            "issue_class":  "GENERATION_ERROR",
        })

    def _extract_command(self, error_log: str, error_type: str) -> str:
        """
        If the error is a missing dependency, extract one or more bare package names
        and return a single npm install command.
        """
        if error_type != "MISSING_DEPENDENCY":
            return None

        packages = []
        patterns = (
            r"Cannot find module ['\"]([^'\"]+)['\"](?: or its corresponding type declarations)?",
            r"Can't resolve ['\"]([^'\"]+)['\"]",
            r"Failed to resolve import ['\"]([^'\"]+)['\"]",
        )

        for pattern in patterns:
            for match in re.finditer(pattern, error_log):
                package_name = self._normalize_package_name(match.group(1))
                if package_name and package_name not in packages:
                    packages.append(package_name)

        if packages:
            return f"npm install --save {' '.join(packages)}"
        return None

    def _normalize_package_name(self, specifier: str | None) -> str | None:
        if not specifier:
            return None

        value = specifier.strip()
        if not value or value.startswith((".", "/", "~")):
            return None

        if value.startswith("@"):
            parts = value.split("/")
            if len(parts) >= 2 and parts[0] and parts[1]:
                return "/".join(parts[:2])
            return None

        return value.split("/")[0]

    # ── Step 2: AI classification ─────────────────────────────────────────────

    async def _ai_classify(
        self,
        error_log:     str,
        ast_summary:   str,
        graph_summary: str,
        sandbox_dir:   str,
        *,
        query_context: str = "",
        allow_query_commands: bool = True,
        project_spec: dict | None = None,
        phase_context: str = "",
        target_file_hint: str = "",
    ) -> dict:
        """
        Send a structured prompt to the LLM and parse the response with
        ResponseParser.parse_decision().
        """
        from .codegen.parser import ResponseParser

        prompt = self._build_prompt(
            error_log,
            ast_summary,
            graph_summary,
            sandbox_dir,
            query_context=query_context,
            allow_query_commands=allow_query_commands,
            project_spec=project_spec,
            phase_context=phase_context,
            target_file_hint=target_file_hint,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a senior full-stack debugger. Your job is to triage errors in a "
                    "React + Express + SQLite project and return a structured JSON diagnosis.\n"
                    "PLATFORM: The environment is LINUX (Kali/Ubuntu/Debian).\n"
                    "STRICT: ONLY use Linux/Unix terminal commands (lsof, fuser, netstat -tunlp, ls, cat).\n"
                    "NEVER use Windows-only commands like 'findstr', 'tasklist', or 'netstat -ano'.\n"
                    "You MUST respond with ONLY a single JSON object — no prose, no markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        raw_response = ""
        from ..providers import is_provider_status_token
        async for token in self.provider.stream(messages, self.model_id):
            if is_provider_status_token(token):
                continue
            raw_response += token

        decision = ResponseParser.parse_decision(raw_response)
        decision["source"] = "ai"
        
        # If AI didn't provide a command but it's clearly a missing dependency,
        # we can try to backfill it from the error log
        if not decision.get("command") and ("dependency" in decision["strategy"].lower() or "install" in decision["strategy"].lower()):
             decision["command"] = self._extract_command(error_log, "MISSING_DEPENDENCY")

        decision = self._normalize_decision(decision, allow_query_commands=allow_query_commands)
        decision = self._apply_target_hints(
            decision,
            project_spec=project_spec,
            phase_context=phase_context,
            target_file_hint=target_file_hint,
        )

        logger.info(
            f"[DecisionEngine] AI decision: layer={decision['layer']}, "
            f"confidence={decision['confidence']}, strategy={decision['strategy']}, "
            f"targets={decision['target_files']}"
        )
        return decision

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        error_log:     str,
        ast_summary:   str,
        graph_summary: str,
        sandbox_dir:   str,
        *,
        query_context: str = "",
        allow_query_commands: bool = True,
        project_spec: dict | None = None,
        phase_context: str = "",
        target_file_hint: str = "",
    ) -> str:
        """
        Build the AI triage prompt with all available context.
        """
        error_excerpt = error_log[:5000] if len(error_log) > 5000 else error_log

        file_listing = ""
        if sandbox_dir and os.path.isdir(sandbox_dir):
            try:
                listing_lines = []
                for root, dirs, files in os.walk(sandbox_dir):
                    dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__", "dist")]
                    for fname in files:
                        rel = os.path.relpath(os.path.join(root, fname), sandbox_dir)
                        listing_lines.append(rel)
                        if len(listing_lines) >= 100:
                            listing_lines.append("... (truncated)")
                            break
                    if len(listing_lines) >= 100:
                        break
                file_listing = "\n".join(listing_lines)
            except Exception:
                file_listing = "(could not read file listing)"

        sections = [
            "## ERROR LOG",
            error_excerpt,
            "## ESTABLISHED NETWORK PORTS",
            f"- Backend Server (API): PORT {self.backend_port} (Always use http://localhost:{self.backend_port} for triage probes)",
            "- Frontend Dev/Preview Server: PORT 3000",
        ]
        if ast_summary:
            sections += ["## AST SUMMARY", ast_summary[:1500]]
        if graph_summary:
            sections += ["## DEPENDENCY GRAPH", graph_summary[:1000]]
        if file_listing:
            sections += ["## PROJECT FILE LISTING", file_listing]
        if project_spec:
            sections += ["## PROJECT SPEC", _summarize_project_spec(project_spec)]
        if phase_context:
            sections += ["## PHASE CONTEXT", str(phase_context).strip()[:3000]]
        if target_file_hint:
            sections += ["## TARGET FILE HINT", target_file_hint]
        if query_context:
            sections += ["## QUERY CONTEXT", query_context[:4000]]
        if not allow_query_commands:
            sections += [
                "## QUERY MODE",
                (
                    "Read-only query commands are disabled for this pass. Use the provided query context and decide whether file writes are needed. "
                    "Do NOT ask for another inspection command. If the query context already reveals a likely code fix, set write_files to 'yes' and target the file(s) to change. "
                    "Set write_files to 'no' only if there is truly nothing to modify."
                ),
            ]

        sections += [
            "## TASK",
            (
                "Diagnose the error above and return a single JSON object with these exact keys:\n"
                "{\n"
                '  "layer":        "frontend | backend | database | integration | unknown",\n'
                '  "confidence":   "HIGH | MEDIUM | LOW",\n'
                '  "strategy":     "<short snake_case strategy key, e.g. fix_api_response_parsing>",\n'
                '  "target_files": ["<relative path to the most likely broken file(s)>"],\n'
                '  "root_cause":   "<one sentence: what is broken and why>",\n'
                '  "fix_hint":     "<what specifically to change to fix it>",\n'
                '  "command":      "<OPTIONAL: terminal command to run>",\n'
                '  "command_kind": "query | dependency_install | runtime_probe | source_edit | none",\n'
                '  "probe_path":   "<optional .lovable/triage/*.py path when command_kind=runtime_probe>",\n'
                '  "probe_content":"<optional python probe file contents when command_kind=runtime_probe>",\n'
                '  "return_query_result": "yes | no",\n'
                '  "write_files":  "yes | no"\n'
                "}\n\n"
                "CRITICAL RULES:\n"
                "- Avoid 'unknown' layer if you have ANY likely lead. Pick the most probable layer.\n"
                '- If you pick "unknown", provide a detailed "root_cause" explaining why it is ambiguous.\n'
                "- target_files SHOULD be non-empty if you see ANY project files in the error log.\n"
                "- If PROJECT SPEC or PHASE CONTEXT identifies owner files, prefer those files over generic catch-all files like src/App.tsx.\n"
                "- When auth fails, prefer auth service/context/route/controller files. When an API resource fails, prefer its route/controller/service/hook owners.\n"
                "- Use target_file_hint when it clearly points at the contract owner file.\n"
                "- If the command is ONLY for inspection (cat, ls, grep, find, sed -n, lsof, netstat, head, tail), set return_query_result to 'yes' and write_files to 'no'.\n"
                "- NEVER return a read-only query command together with write_files='yes' in the same decision. A query/probe decision is diagnosis-only; a source_edit/write decision is repair.\n"
                "- Use command_kind='runtime_probe' only when a read-only shell query is not enough and a temporary Python probe file under .lovable/triage/ would materially improve diagnosis.\n"
                "- If command_kind='runtime_probe', provide BOTH probe_path and probe_content and make the command execute that probe file.\n"
                "- Use command_kind='source_edit' only for small, surgical source changes where a shell command is simpler than rewriting the whole file, such as inserting an import, replacing one field name, or changing one config line.\n"
                "- CRITICAL STYLE POLICY: If Tailwind runtime is present or intended for this project, keep styling in Tailwind utility classes and repair the Tailwind scaffold/config when needed. Only fall back to semantic CSS classes when the project truly does not include Tailwind.\n"
                "- If you already know the exact one-line or one-replacement fix from the error log, fix_hint, or query context, skip cat/rg and emit a source_edit command directly.\n"
                "- If command_kind='source_edit', the command may use sed -i, perl -pi, python -c, or similar file-editing commands, and you should normally set write_files to 'no'.\n"
                "- Do NOT combine source_edit with a full file rewrite for the same fix unless the shell edit fails and you explicitly decide a rewrite is still needed.\n"
                "- Set write_files to 'yes' ONLY when creating or modifying files is actually needed.\n"
                "- CRITICAL: NO TRIVIAL TRIAGE. If the error log already contains the likely broken code block or missing dependency name, DO NOT request a query command (cat, ls, grep, find). Skip directly to a fix turn: set write_files to 'yes' and provide the target files. Trivial cat/grep turns waste time.\n"
                "- If you need to run a dependency install command, the strategy should clearly indicate dependency repair.\n"
                "- ONE PASS POLICY: If you are fixing a build or runtime error, aim to fix ALL related issues in the target files in one go. Do not fix one field and then wait for the next error.\n"
                "- ESM ONLY: files under server/ MUST be 100% ESM.\n"
                f"- ESTABLISHED PORTS: Backend is at PORT {self.backend_port}. Frontend is at PORT 3000.\n"
                "- NEVER rewrite backend listen defaults to 5000 in this pipeline.\n"
            ),
        ]

        return "\n\n".join(sections)

    def _apply_target_hints(
        self,
        decision: dict,
        *,
        project_spec: dict | None = None,
        phase_context: str = "",
        target_file_hint: str = "",
    ) -> dict:
        hinted_targets = _collect_hinted_targets(phase_context, target_file_hint)
        existing_targets = [
            str(path).strip()
            for path in (decision.get("target_files") or [])
            if str(path).strip()
        ]

        if not existing_targets and hinted_targets:
            decision["target_files"] = hinted_targets
            return decision

        if hinted_targets and existing_targets:
            generic_targets = {"src/App.tsx", "server/index.ts", "package.json", "vite.config.ts"}
            if all(path in generic_targets for path in existing_targets) and any(path not in generic_targets for path in hinted_targets):
                decision["target_files"] = _unique_paths(hinted_targets + existing_targets)
            else:
                decision["target_files"] = _unique_paths(existing_targets + hinted_targets)

        if not decision.get("target_files") and project_spec:
            fallback_targets = _project_spec_fallback_targets(project_spec)
            if fallback_targets:
                decision["target_files"] = fallback_targets

        return decision

    def _normalize_decision(self, decision: dict, *, allow_query_commands: bool = True) -> dict:
        # Ensure issue_class is always present
        if "issue_class" not in decision:
            decision["issue_class"] = "GENERATION_ERROR"

        command = decision.get("command")
        command_kind = str(decision.get("command_kind", "")).strip().lower()
        return_query_result = str(decision.get("return_query_result", "")).strip().lower()
        write_files = str(decision.get("write_files", "")).strip().lower()
        probe_path = str(decision.get("probe_path", "") or "").strip()
        probe_content = str(decision.get("probe_content", "") or "")

        if command_kind not in {"query", "dependency_install", "runtime_probe", "source_edit", "mutation", "none"}:
            if self._is_query_command(command):
                command_kind = "query"
            elif self._is_dependency_command(command):
                command_kind = "dependency_install"
            elif self._is_source_mutating_command(command):
                command_kind = "source_edit"
            else:
                command_kind = "none"

        promoted_command = self._build_source_edit_command_from_fix_hint(decision)
        if promoted_command:
            decision["command"] = promoted_command
            command = promoted_command
            command_kind = "source_edit"
            return_query_result = "no"
            write_files = "no"

        if return_query_result not in {"yes", "no"}:
            return_query_result = "yes" if command_kind in {"query", "runtime_probe"} else "no"

        if write_files not in {"yes", "no"}:
            if command_kind in {"query", "runtime_probe", "source_edit"}:
                write_files = "no"
            elif command and self._is_mutating_command(command):
                write_files = "no"
            else:
                write_files = "yes"

        if command_kind == "query":
            return_query_result = "yes"
            write_files = "no"
        elif command_kind == "runtime_probe":
            return_query_result = "yes"
            write_files = "no"
        elif command_kind in {"dependency_install", "source_edit", "mutation"}:
            return_query_result = "no"
            write_files = "no"

        if command_kind == "runtime_probe":
            if not probe_path.startswith(".lovable/triage/") or not probe_path.endswith(".py") or not probe_content.strip():
                command_kind = "none"
                decision["command"] = None
                command = None
                return_query_result = "no"
                if write_files == "no":
                    write_files = "yes"

        if not allow_query_commands and self._is_query_command(command):
            decision["command"] = None
            return_query_result = "no"
            command_kind = "none"

        target_files = [
            str(path).strip()
            for path in (decision.get("target_files") or [])
            if str(path).strip()
        ]
        primary_target = target_files[0] if target_files else ""
        if command_kind == "source_edit" and self._looks_like_broken_source_edit_command(command, primary_target):
            decision["command"] = None
            decision["command_kind"] = "none"
            decision["return_query_result"] = "no"
            decision["write_files"] = "yes"
            existing_hint = str(decision.get("fix_hint", "") or "").strip()
            guard_hint = (
                "The previous shell-edit command was malformed or incomplete. "
                "Use a coherent file rewrite instead of an inline patch shell command."
            )
            decision["fix_hint"] = f"{existing_hint} {guard_hint}".strip()
            command = None
            command_kind = "none"
            return_query_result = "no"
            write_files = "yes"

        decision["command_kind"] = command_kind
        decision["probe_path"] = probe_path
        decision["probe_content"] = probe_content
        decision["return_query_result"] = return_query_result
        decision["write_files"] = write_files

        if self._violates_server_esm_policy(decision):
            decision["command"] = None
            decision["command_kind"] = "none"
            decision["return_query_result"] = "no"
            decision["write_files"] = "yes"
            existing_hint = str(decision.get("fix_hint", "") or "").strip()
            guard_hint = (
                "Server files must use 100% ESM in this pipeline. "
                "Do not convert import/export to require/module.exports. "
                "Ensure package.json has 'type': 'module'."
            )
            decision["fix_hint"] = f"{existing_hint} {guard_hint}".strip()

        if self._violates_api_contract_rewrite_policy(decision):
            decision["command"] = None
            decision["command_kind"] = "none"
            decision["return_query_result"] = "no"
            decision["write_files"] = "yes"
            existing_hint = str(decision.get("fix_hint", "") or "").strip()
            guard_hint = (
                "API contract drift must be fixed with coordinated file rewrites, not one-line shell edits. "
                "Standardize the shared types and all participating request/response files in one consistent pass."
            )
            decision["fix_hint"] = f"{existing_hint} {guard_hint}".strip()
        if self._violates_backend_contract_rewrite_policy(decision):
            decision["command"] = None
            decision["command_kind"] = "none"
            decision["return_query_result"] = "no"
            decision["write_files"] = "yes"
            existing_hint = str(decision.get("fix_hint", "") or "").strip()
            guard_hint = (
                "Backend and shared contract-owner files should be repaired with coherent file rewrites, "
                "not shell-level search/replace edits. Keep database adapters, middleware, controller exports, routes, "
                "shared types, and auth state/service wiring aligned in one pass."
            )
            decision["fix_hint"] = f"{existing_hint} {guard_hint}".strip()
        if self._violates_frontend_root_rewrite_policy(decision):
            decision["command"] = None
            decision["command_kind"] = "none"
            decision["return_query_result"] = "no"
            decision["write_files"] = "yes"
            existing_hint = str(decision.get("fix_hint", "") or "").strip()
            guard_hint = (
                "Root app wiring files should be repaired with coherent rewrites, not shell-level edits. "
                "Keep src/main.tsx, src/App.tsx, and any required provider/context files aligned in one pass."
            )
            decision["fix_hint"] = f"{existing_hint} {guard_hint}".strip()
        if self._violates_http_client_rewrite_policy(decision):
            decision["command"] = None
            decision["command_kind"] = "none"
            decision["return_query_result"] = "no"
            decision["write_files"] = "yes"
            existing_hint = str(decision.get("fix_hint", "") or "").strip()
            guard_hint = (
                "HTTP client contract failures must be fixed with coordinated rewrites of src/services/api.ts and affected consumers. "
                "Do not patch fetch/axios drift with shell-level edits."
            )
            decision["fix_hint"] = f"{existing_hint} {guard_hint}".strip()
        if self._violates_stylesheet_contract_rewrite_policy(decision):
            decision["command"] = None
            decision["command_kind"] = "none"
            decision["return_query_result"] = "no"
            decision["write_files"] = "yes"
            existing_hint = str(decision.get("fix_hint", "") or "").strip()
            guard_hint = (
                "Stylesheet contract failures must be fixed with coordinated component/page plus stylesheet rewrites. "
                "Do not append empty CSS selector stubs or patch semantic classes with shell commands."
            )
            decision["fix_hint"] = f"{existing_hint} {guard_hint}".strip()
        return decision

    def _violates_server_esm_policy(self, decision: dict) -> bool:
        target_files = [str(path).strip() for path in (decision.get("target_files") or []) if str(path).strip()]
        if not any(path.startswith("server/") for path in target_files):
            return False

        command = str(decision.get("command", "") or "")
        command_kind = str(decision.get("command_kind", "")).strip().lower()
        if command_kind != "source_edit" and not self._is_source_mutating_command(command):
            return False

        lowered_command = command.lower()
        cjs_mutation_markers = (
            "module.exports",
            "exports.",
            "require(",
            "require ('",
            'require ("',
        )
        return any(marker in lowered_command for marker in cjs_mutation_markers)

    def _violates_api_contract_rewrite_policy(self, decision: dict) -> bool:
        strategy = str(decision.get("strategy", "") or "").strip().lower()
        command = str(decision.get("command", "") or "")
        command_kind = str(decision.get("command_kind", "")).strip().lower()
        if strategy != "fix_api_contract":
            return False
        return command_kind == "source_edit" or self._is_source_mutating_command(command)

    def _violates_backend_contract_rewrite_policy(self, decision: dict) -> bool:
        command = str(decision.get("command", "") or "")
        command_kind = str(decision.get("command_kind", "")).strip().lower()
        strategy = str(decision.get("strategy", "") or "").strip().lower()
        target_files = [str(path).strip().lower() for path in (decision.get("target_files") or []) if str(path).strip()]
        protected_prefixes = (
            "server/db/",
            "server/controllers/",
            "server/routes/",
            "server/middleware/",
            "src/types/",
        )
        protected_exact = {
            "package.json",
            "server/index.ts",
            "src/services/api.ts",
            "src/services/authservice.ts",
            "src/context/authcontext.tsx",
            "src/hooks/useauth.ts",
            "src/hooks/useauth.tsx",
        }
        if strategy in {"fix_cjs_esm", "fix_package_runtime_contract", "fix_schema"} and any(
            path.startswith("server/") or path == "package.json"
            for path in target_files
        ):
            return command_kind == "source_edit" or self._is_source_mutating_command(command)
        if not any(
            path.startswith(protected_prefixes) or path in protected_exact
            for path in target_files
        ):
            return False
        return command_kind == "source_edit" or self._is_source_mutating_command(command)

    def _violates_frontend_root_rewrite_policy(self, decision: dict) -> bool:
        command = str(decision.get("command", "") or "")
        command_kind = str(decision.get("command_kind", "")).strip().lower()
        strategy = str(decision.get("strategy", "") or "").strip().lower()
        target_files = [str(path).strip().lower() for path in (decision.get("target_files") or []) if str(path).strip()]
        protected_exact = {
            "src/main.tsx",
            "src/app.tsx",
            "src/context/authcontext.tsx",
        }
        if strategy not in {"fix_blank_page", "fix_provider", "fix_auth_contract", "fix_auth_connectivity"} and not any(
            path in protected_exact for path in target_files
        ):
            return False
        return command_kind == "source_edit" or self._is_source_mutating_command(command)

    def _violates_http_client_rewrite_policy(self, decision: dict) -> bool:
        command = str(decision.get("command", "") or "")
        command_kind = str(decision.get("command_kind", "")).strip().lower()
        strategy = str(decision.get("strategy", "") or "").strip().lower()
        target_files = [str(path).strip().lower() for path in (decision.get("target_files") or []) if str(path).strip()]
        protected_prefixes = (
            "src/services/",
            "src/hooks/",
            "src/pages/",
            "src/components/",
        )
        protected_exact = {
            "src/types/index.ts",
            "src/app.tsx",
        }
        if strategy != "fix_http_client" and not any(path == "src/services/api.ts" for path in target_files):
            return False
        if not any(path.startswith(protected_prefixes) or path in protected_exact for path in target_files):
            return False
        return command_kind == "source_edit" or self._is_source_mutating_command(command)

    def _violates_stylesheet_contract_rewrite_policy(self, decision: dict) -> bool:
        command = str(decision.get("command", "") or "")
        command_kind = str(decision.get("command_kind", "")).strip().lower()
        strategy = str(decision.get("strategy", "") or "").strip().lower()
        fix_hint = str(decision.get("fix_hint", "") or "").strip().lower()
        root_cause = str(decision.get("root_cause", "") or "").strip().lower()
        target_files = [str(path).strip().lower() for path in (decision.get("target_files") or []) if str(path).strip()]

        style_markers = (
            "stylesheet_class_missing",
            "tailwind_runtime_missing",
            "semantic css",
            "stylesheet",
            "tailwind",
            "css classes",
        )
        is_style_contract_issue = (
            strategy == "fix_style"
            or any(marker in fix_hint for marker in style_markers)
            or any(marker in root_cause for marker in style_markers)
        )
        if not is_style_contract_issue:
            return False

        protected_prefixes = (
            "src/components/",
            "src/pages/",
            "src/styles/",
        )
        protected_exact = {
            "src/app.tsx",
        }
        if not any(
            path.startswith(protected_prefixes) or path in protected_exact
            for path in target_files
        ):
            return False
        return command_kind == "source_edit" or self._is_source_mutating_command(command)

    def _build_source_edit_command_from_fix_hint(self, decision: dict) -> str | None:
        if str(decision.get("strategy", "") or "").strip().lower() in {"fix_api_contract", "fix_style"}:
            return None
        command_kind = str(decision.get("command_kind", "")).strip().lower()
        command = str(decision.get("command", "") or "").strip()

        target_files = decision.get("target_files") or []
        if not isinstance(target_files, list) or len(target_files) != 1:
            return None

        target_file = str(target_files[0]).strip()
        if not target_file:
            return None

        if (
            (command_kind == "source_edit" or self._is_source_mutating_command(command))
            and not self._looks_like_broken_source_edit_command(command, target_file)
        ):
            return None

        fix_hint = str(decision.get("fix_hint", "") or "").strip()
        if not fix_hint:
            return None

        add_first_line_match = re.search(
            r"""add\s+(["'`])(?P<text>.+?)\1\s+as\s+the\s+first\s+line(?:\s+of\s+.+?)?(?:[.\n]|$)""",
            fix_hint,
            re.IGNORECASE | re.DOTALL,
        )
        if add_first_line_match:
            line_text = add_first_line_match.group("text")
            return self._build_prepend_line_command(target_file, line_text)

        replace_match = re.search(
            r"""replace\s+(["'`])(?P<old>.+?)\1\s+with\s+(["'`])(?P<new>.+?)\3(?:\s+in\s+.+?)?(?:[.\n]|$)""",
            fix_hint,
            re.IGNORECASE | re.DOTALL,
        )
        if replace_match:
            old_text = replace_match.group("old")
            new_text = replace_match.group("new")
            return self._build_replace_text_command(target_file, old_text, new_text)

        return None

    def _looks_like_broken_source_edit_command(self, command: str | None, target_file: str = "") -> bool:
        lowered = str(command or "").strip().lower()
        if not lowered:
            return True

        if "apply_patch" in lowered or "<<" in lowered:
            return True

        if target_file and target_file not in str(command):
            return True

        stripped = lowered.strip()
        if stripped in {"sed -i", "python -c", "python3 -c", "perl -pi"}:
            return True

        if str(command).count("'") % 2 == 1 or str(command).count('"') % 2 == 1:
            return True

        return False

    def _build_prepend_line_command(self, path: str, line_text: str) -> str:
        snippet = (
            "from pathlib import Path; "
            f"p=Path({path!r}); "
            "text=p.read_text(encoding='utf-8') if p.exists() else ''; "
            f"line={line_text!r}; "
            "new_text=text if text == line or text.startswith(line + '\\n') else line + ('\\n' + text if text else ''); "
            "p.write_text(new_text, encoding='utf-8')"
        )
        return f"python3 -c {shlex.quote(snippet)}"

    def _build_replace_text_command(self, path: str, old_text: str, new_text: str) -> str:
        snippet = (
            "from pathlib import Path; "
            f"p=Path({path!r}); "
            "text=p.read_text(encoding='utf-8'); "
            f"old={old_text!r}; "
            f"new={new_text!r}; "
            "p.write_text(text.replace(old, new), encoding='utf-8')"
        )
        return f"python3 -c {shlex.quote(snippet)}"

    def _is_query_command(self, command: str | None) -> bool:
        if not command:
            return False

        lowered = command.strip().lower()
        if self._is_mutating_command(lowered):
            return False

        segments = [seg.strip() for seg in re.split(r"\|\||&&|;|\|", lowered) if seg.strip()]
        if not segments:
            return False

        query_prefixes = (
            "cat ",
            "sed ",
            "grep ",
            "find ",
            "ls",
            "lsof",
            "netstat",
            "head ",
            "tail ",
            "wc ",
            "stat ",
            "readlink ",
            "pwd",
            "tree ",
            "awk ",
            "rg ",
        )
        return all(seg.startswith(query_prefixes) for seg in segments)

    def _is_mutating_command(self, command: str | None) -> bool:
        if not command:
            return False

        lowered = command.strip().lower()
        mutating_fragments = (
            "npm install",
            "npm uninstall",
            "npm rebuild",
            "npm update",
            "pnpm add",
            "yarn add",
            "rm ",
            "mv ",
            "cp ",
            "touch ",
            "sed -i",
            "fuser -k",
            " kill ",
            "pkill ",
            "chmod ",
            "chown ",
            "echo ",
        )
        return any(fragment in f" {lowered} " for fragment in mutating_fragments)

    def _is_dependency_command(self, command: str | None) -> bool:
        if not command:
            return False
        lowered = command.strip().lower()
        dependency_fragments = (
            "npm install",
            "npm uninstall",
            "npm rebuild",
            "npm update",
            "pnpm add",
            "pnpm install",
            "yarn add",
            "yarn install",
            "pip install",
        )
        return any(fragment in lowered for fragment in dependency_fragments)

    def _is_source_mutating_command(self, command: str | None) -> bool:
        if not command:
            return False
        lowered = command.strip().lower()
        source_edit_fragments = (
            "sed -i",
            "perl -pi",
            "python -c",
            "python3 -c",
            "echo ",
            "tee ",
            "cat >",
            "cat >>",
        )
        if self._is_dependency_command(lowered):
            return False
        return any(fragment in lowered for fragment in source_edit_fragments)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _unknown_decision(reason: str = "") -> dict:
    return {
        "layer":        "unknown",
        "confidence":   "LOW",
        "strategy":     "unknown",
        "target_files": [],
        "root_cause":   reason or "Could not determine root cause",
        "fix_hint":     "Inspect the error log manually and fix the most likely culprit file.",
        "command":      None,
        "command_kind": "none",
        "probe_path":   "",
        "probe_content": "",
        "return_query_result": "no",
        "write_files":  "yes",
        "source":       "fallback",
    }


def _extract_error_paths(error_log: str, limit: int = 8) -> list[str]:
    found = []
    for m in re.finditer(r'(?:server|src)/[^\s:()"\',<>]+\.(?:tsx|ts|jsx|js)', error_log):
        p = m.group(0)
        if "node_modules" not in p and p not in found:
            found.append(p)
        if len(found) >= limit:
            break
    return found


def _guess_target_files(error_log: str, layer: str) -> list:
    """
    Extract file paths mentioned in the error log as likely fix targets.
    Falls back to canonical entry-point files per layer.
    """
    found = _extract_error_paths(error_log, limit=4)

    if not found:
        defaults = {
            "frontend":    ["src/App.tsx", "vite.config.ts"],
            "backend":     ["server/index.ts", "server/db/database.ts", "package.json"],
            "database":    ["server/db/database.ts", "server/db/schema.ts", "package.json"],
            "integration": ["src/App.tsx", "server/index.ts", "package.json"],
            "unknown":     [],
        }
        return defaults.get(layer, [])

    return found


def _guess_api_contract_targets(error_log: str, sandbox_dir: str = "") -> list[str]:
    explicit_targets = _extract_error_paths(error_log, limit=8)
    if explicit_targets:
        augmented_targets = list(explicit_targets)
        if "src/types/index.ts" not in augmented_targets:
            augmented_targets.insert(0, "src/types/index.ts")
        return _unique_paths(augmented_targets)

    if sandbox_dir and os.path.isdir(sandbox_dir):
        try:
            from .feature_validator import FeatureValidator

            _mixed_pairs, offending_files = FeatureValidator(sandbox_dir).collect_api_contract_drift()
            if offending_files:
                return _unique_paths(sorted(offending_files.keys()))
        except Exception:
            pass

    candidates = []
    if sandbox_dir and os.path.isdir(sandbox_dir):
        for path in (
            "src/types/index.ts",
            "src/services/api.ts",
            "src/App.tsx",
            "server/index.ts",
        ):
            if os.path.exists(os.path.join(sandbox_dir, path)):
                candidates.append(path)

    if candidates:
        return _unique_paths(candidates)

    return _guess_target_files(error_log, "integration")


def _singularize_resource_name(name: str) -> str:
    if name.endswith("ies") and len(name) > 3:
        return name[:-3] + "y"
    if name.endswith("sses") and len(name) > 4:
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss") and len(name) > 3:
        return name[:-1]
    return name


def _pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[-_/]+", value) if part)


def _unique_paths(paths: list[str], limit: int = 8) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = path.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
        if len(unique) >= limit:
            break
    return unique


def _collect_hinted_targets(phase_context: str, target_file_hint: str) -> list[str]:
    hinted: list[str] = []
    if target_file_hint:
        hinted.append(str(target_file_hint).strip())

    for line in str(phase_context or "").splitlines():
        stripped = line.strip().lstrip("-").strip()
        if stripped.startswith(("src/", "server/")) and stripped not in hinted:
            hinted.append(stripped)

    quoted_paths = re.findall(r"'((?:src|server)/[^']+)'", str(phase_context or ""))
    for path in quoted_paths:
        clean = path.strip()
        if clean and clean not in hinted:
            hinted.append(clean)

    return _unique_paths(hinted)


def _summarize_project_spec(project_spec: dict | None) -> str:
    data = dict(project_spec or {})
    lines = [
        f"Product Type: {data.get('product_type', '')}",
        f"App Kind: {data.get('app_kind', '')}",
    ]
    summary = str(data.get("summary", "") or "").strip()
    if summary:
        lines.append(f"Summary: {summary}")

    features = [str(item).strip() for item in (data.get("features") or []) if str(item).strip()]
    if features:
        lines.append("Features: " + ", ".join(features[:8]))

    pages = []
    for item in (data.get("pages") or [])[:8]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        route = str(item.get("route", "") or "").strip()
        if name or route:
            pages.append(f"{name or 'Page'} ({route or '/'})")
    if pages:
        lines.append("Pages: " + ", ".join(pages))

    resources = []
    for item in (data.get("api_resources") or [])[:8]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        route = str(item.get("route", "") or "").strip()
        if name or route:
            resources.append(f"{name or 'resource'} ({route})")
    if resources:
        lines.append("API Resources: " + ", ".join(resources))

    auth = data.get("auth")
    if isinstance(auth, dict) and auth.get("enabled"):
        roles = [str(item).strip() for item in (auth.get("roles") or []) if str(item).strip()]
        lines.append("Auth: enabled" + (f" [{', '.join(roles)}]" if roles else ""))

    checks = [str(item).strip() for item in (data.get("acceptance_checks") or []) if str(item).strip()]
    if checks:
        lines.append("Acceptance Checks: " + "; ".join(checks[:6]))

    return "\n".join(line for line in lines if line.strip())


def _project_spec_fallback_targets(project_spec: dict | None) -> list[str]:
    data = dict(project_spec or {})
    targets: list[str] = []

    auth = data.get("auth")
    if isinstance(auth, dict) and auth.get("enabled"):
        targets.extend([
            "src/services/authService.ts",
            "src/context/AuthContext.tsx",
            "server/routes/authRoutes.ts",
            "server/controllers/authController.ts",
        ])

    for item in (data.get("api_resources") or [])[:2]:
        if not isinstance(item, dict):
            continue
        route = str(item.get("route", "") or "").strip()
        name = str(item.get("name", "") or "").strip()
        token = route.split("/api/")[-1].strip("/").split("/", 1)[0] if "/api/" in route else name
        token = token.strip().lower()
        if not token:
            continue
        singular = _singularize_resource_name(token)
        pascal = _pascal_case(token)
        targets.extend([
            f"server/routes/{singular}Routes.ts",
            f"server/controllers/{singular}Controller.ts",
            f"src/services/{singular}Service.ts",
            f"src/hooks/use{pascal}.tsx",
        ])

    for item in (data.get("pages") or [])[:2]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        route = str(item.get("route", "") or "").strip()
        component = "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", name or route or "Home") if part and not part.startswith(":")) or "Home"
        targets.append(f"src/pages/{component}.tsx")

    return _unique_paths(targets)


def _guess_runtime_api_targets(endpoint: str) -> list[str]:
    normalized = endpoint.strip().lower().strip("/")
    token_variants: list[str] = []
    for token in re.split(r"[-_/]+", normalized):
        token = token.strip()
        if not token:
            continue
        if token not in token_variants:
            token_variants.append(token)
        singular = _singularize_resource_name(token)
        if singular not in token_variants:
            token_variants.append(singular)

    candidates = [
        "src/services/api.ts",
        "src/services/api.js",
        "src/types/index.ts",
        "server/index.ts",
        "package.json",
    ]

    for token in token_variants:
        pascal = _pascal_case(token)
        candidates.extend([
            f"server/routes/{token}Routes.ts",
            f"server/routes/{token}Routes.js",
            f"server/routes/{token}.ts",
            f"server/routes/{token}.js",
            f"server/controllers/{token}Controller.ts",
            f"server/controllers/{token}Controller.js",
            f"server/controllers/{token}.ts",
            f"server/controllers/{token}.js",
            f"server/models/{token}.ts",
            f"server/models/{token}.js",
            f"src/hooks/use{pascal}.tsx",
            f"src/hooks/use{pascal}.ts",
            f"src/components/{pascal}.tsx",
            f"src/components/{pascal}List.tsx",
            f"src/components/{pascal}Card.tsx",
            f"src/pages/{pascal}.tsx",
            f"src/pages/{pascal}Detail.tsx",
            f"src/pages/{pascal}List.tsx",
        ])

    return _unique_paths(candidates)


def _guess_dynamic_param_targets(route_segment: str) -> list[str]:
    normalized = route_segment.strip().lower().strip("/")
    token_variants = [normalized]
    singular = _singularize_resource_name(normalized)
    if singular not in token_variants:
        token_variants.append(singular)

    candidates = [
        "src/types/index.ts",
        "src/services/api.ts",
        "src/App.tsx",
    ]

    for token in token_variants:
        pascal = _pascal_case(token)
        candidates.extend([
            f"src/components/{pascal}.tsx",
            f"src/components/{pascal}Card.tsx",
            f"src/components/{pascal}List.tsx",
            f"src/components/{pascal}Table.tsx",
            f"src/pages/{pascal}.tsx",
            f"src/pages/{pascal}Detail.tsx",
            f"src/pages/{pascal}View.tsx",
            f"src/pages/{pascal}Editor.tsx",
            f"src/hooks/use{pascal}.tsx",
            f"src/hooks/use{pascal}.ts",
        ])

    return _unique_paths(candidates)
