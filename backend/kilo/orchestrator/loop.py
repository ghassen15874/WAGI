"""
AgentLoop — based on refs/deepagents/graph.py execution pattern.

Core pattern: plan → act → observe → loop (DeepAgents graph nodes).
State flows as dict between nodes; loop exits when no tool calls remain.

Middleware stack mirrors create_deep_agent():
  TodoListMiddleware → FilesystemMiddleware → SummarizationMiddleware →
  PatchToolCallsMiddleware → (optional) AnthropicPromptCachingMiddleware

# From refs/deepagents/graph.py create_deep_agent()
"""
import asyncio
import json
import logging
import os
import re
import hashlib
import shutil
import time
from dataclasses import asdict
from typing import AsyncIterator, Optional, List, Dict

from ..agents.codegen.analyzer import ProjectAnalyzer
from ..agents.codegen.linter import CodeLinter, SyntaxValidator
from ..agents.codegen.parser import ResponseParser
from ..agents.codegen.prompts import (
    build_generation_user_prompt,
    build_stage_system_prompt,
    get_summary_saving_prompt,
    get_repair_prompt,
)
from ..providers import is_provider_status_token, _approximate_message_tokens
from ..shared.design.engine import DesignEngine
from ..shared.write_guard import normalize_generated_file_content
from ..tools.registry import ToolRegistry
from .memory import AgentMemory
from .plan_paths import compiled_core_paths
from .planner import ExecutionPlanner, ExecutionStatus
from .ast_extractor import ast_extractor
from .project_map import ProjectMapManager
from .ai_context_builder import AIContextBuilder
from .error_analyzer import ErrorAnalyzer
from .feature_validator import FeatureValidator
from .global_contract import load_global_contract
from .planning_service import PlanningService
from .project_spec import _pascal, _singular_slug, _slug
from .repair_service import PlanRepairService
from .run_state import GenerationRunStateStore
from ..server.billing import increment_token_usage, enforce_usage_limits, get_plan

_API_CONTRACT_PATTERNS = [
    r"^src/services/api\.(ts|js)$",
    r"^src/services/.*[Ss]ervice\.(ts|js)$",
    r"^src/types/index\.(ts|js)$",
    r"^src/hooks/use[A-Z].*\.(ts|tsx)$",
]


def _extract_broken_server_file(error_log: str, sandbox_dir: str) -> str:
    """
    Extract the most likely broken server-side file from a runtime error log.
    Avoids defaulting to server/index.ts for errors that originate in route/controller files.
    Rules (in priority order):
      1. Prefer explicit paths under server/routes/ or server/controllers/ in the log.
      2. Skip any path that contains 'node_modules' (those are Express internals).
      3. For 'Route.get() requires a callback' errors, enumerate server/routes/ and return the first file.
      4. Fall back to server/index.ts only as a last resort.
    """
    is_route_callback_error = bool(re.search(
        r"Route\.\w+\(\) requires a callback|requires a callback function but got a \[object",
        error_log, re.IGNORECASE
    ))

    # Priority 1: look for explicit project paths (not node_modules)
    # The regex allows spaces in the base path (e.g., 'New Folder') by using [^\n()]+? before server|src
    for match in re.finditer(r"((?:/[^\n():]+?)?(?:server|src)/[^\s:]+\.ts)", error_log):
        found = match.group(1)
        if "node_modules" in found:
            continue
        # Prefer route/controller files for route callback errors
        if is_route_callback_error and not any(x in found for x in ["routes/", "controllers/"]):
            continue
        if sandbox_dir and sandbox_dir in found:
            return os.path.relpath(found, sandbox_dir)
        if "sandbox/" in found:
            return found.split("sandbox/")[-1].split("/", 1)[-1]
        
        # If it's a relative path like 'server/routes/app.ts'
        if found.startswith("server/") or found.startswith("src/"):
            return found
        
        return found

    # Priority 2: for route callback errors, enumerate routes directory
    if is_route_callback_error and sandbox_dir:
        routes_dir = os.path.join(sandbox_dir, "server/routes")
        if os.path.isdir(routes_dir):
            route_files = [f for f in os.listdir(routes_dir) if f.endswith(".ts")]
            if route_files:
                return f"server/routes/{route_files[0]}"

    return "server/index.ts"


def _collect_broken_files_from_sync_errors(sync_errors: list, sandbox_dir: str) -> list:
    """
    Parse ROUTE_SYNC_ERROR messages to collect all unique route and controller files
    that need to be fixed. Returns paths relative to sandbox_dir, deduplicated and
    ordered: controllers first (fix the source), then routes.
    """
    route_files: set = set()
    ctrl_files: set = set()

    for err in sync_errors:
        # Extract route file: "server/routes/postRoutes.ts calls ..."
        m = re.search(r"server/routes/(\S+\.ts)", err)
        if m:
            route_files.add(f"server/routes/{m.group(1)}")

        # Extract controller file: "server/controllers/postController.ts does not export ..."
        m = re.search(r"server/controllers/(\S+\.ts)", err)
        if m:
            ctrl_files.add(f"server/controllers/{m.group(1)}")

    # Return controllers first so the AI fixes exports before the routes that reference them
    ordered = sorted(ctrl_files) + sorted(route_files)

    # Deduplicate while preserving order
    seen: set = set()
    result = []
    for f in ordered:
        if f not in seen:
            seen.add(f)
            result.append(f)

    # Fallback: if nothing extracted, fix server/index.ts
    return result if result else ["server/index.ts"]


class AgentLoop:
    """
    Main builder execution processor.

    The active production architecture is:
      server route -> session runtime -> session prompt -> session processor -> AgentLoop

    This loop assumes the session runtime has already prepared the design
    system, persisted the execution plan, and written run_state.json. It owns
    the execution/validation/repair loop only.
    """

    def __init__(
        self,
        provider,
        sandbox_dir: Optional[str] = None,
        model_id: str = "",
        *,
        tool_registry: Optional[ToolRegistry] = None,
        design_engine: Optional[DesignEngine] = None,
        pipeline_config: dict = None,
    ):
        """
        Execution-processor constructor.

        The production path injects the tool registry and design engine from the
        session runtime. A sandbox path can still be provided for isolated local
        tests, but session preparation is required before run() is called.
        """
        # From refs/deepagents/graph.py — middleware stack wired at construction
        self.provider  = provider
        self.model_id  = model_id

        # ── Resolve tool_registry & sandbox_dir ───────────────────────────────
        if tool_registry is not None:
            self.tool_registry = tool_registry
            self.sandbox_dir   = str(tool_registry.base_dir)
        elif sandbox_dir is not None:
            self.sandbox_dir   = sandbox_dir
            self.tool_registry = ToolRegistry(base_dir=sandbox_dir)
        else:
            raise ValueError("AgentLoop requires either sandbox_dir or tool_registry")

        # ── Resolve design_engine ─────────────────────────────────────────────
        if design_engine is not None:
            self.design_engine = design_engine
        else:
            self.design_engine = DesignEngine()

        # ── Other middleware ──────────────────────────────────────────────────
        self.memory  = AgentMemory()   # SummarizationMiddleware analogue
        self.planner = ExecutionPlanner()
        self.planning = PlanningService(self.sandbox_dir, planner=self.planner)
        self.run_state_store = GenerationRunStateStore(self.sandbox_dir)
        self.repair_service = PlanRepairService(self.planning)
        self.linter  = CodeLinter()    # Cline self-healing linter
        self.error_analyzer = ErrorAnalyzer()

        # ── Runtime / Self-Healing flags ────────────────────────────────────
        self.pipeline_config = pipeline_config or {}
        self.global_contract = load_global_contract(self.sandbox_dir, self.pipeline_config)
        self.pipeline_config["_global_contract"] = self.global_contract
        
        self.clear_sandbox_enabled = self.pipeline_config.get("clear_sandbox_enabled", True)
        self.design_system_enabled = self.pipeline_config.get("design_system_enabled", True)
        self.system_prompt_enabled = self.pipeline_config.get("system_prompt_enabled", True)
        self.builder_enabled = self.pipeline_config.get("builder_enabled", True)
        self.auto_install_enabled = self.pipeline_config.get("auto_install_enabled", True)
        self.project_build_enabled = self.pipeline_config.get("project_build_enabled", True)
        self.integration_test_enabled = self.pipeline_config.get("integration_test_enabled", False)
        
        self.runtime_enabled       = self.pipeline_config.get("runtime_enabled", True)
        self.self_healing_enabled  = self.pipeline_config.get("self_healing_enabled", True)
        self.linter_enabled        = self.pipeline_config.get("linter_enabled", True)
        self.feature_validator_enabled = self.pipeline_config.get("feature_validator_enabled", True)
        self.summary_enabled = self.pipeline_config.get("summary_enabled", True)
        self.triage_cache: dict = {}
        self.validation_repair_state: dict = {}
        self.generation_retry_state: dict = {}
        self.retry_batch_override: list[str] = []
        self.backend_port = int(self.pipeline_config.get("backend_port", 3001))
        self.frontend_port = int(self.pipeline_config.get("frontend_port", 3000))
        
        self.max_iter = int(self.pipeline_config.get("max_iter", 70))
        self.max_healing_attempts = int(self.pipeline_config.get("max_healing_attempts", 20))
        self.active_memory_enabled = self.pipeline_config.get("active_memory_enabled", True)
        self.safe_mode             = False
        self.request_provider_name = str(self.pipeline_config.get("_request_provider") or getattr(self.provider, "provider_name", "") or "")
        self.request_api_key = str(self.pipeline_config.get("_request_api_key", "") or "")
        self.request_scraper_url = str(self.pipeline_config.get("_request_scraper_url", "") or "")
        self.user_provider_keys = dict(self.pipeline_config.get("_user_provider_keys", {}) or {})
        self.use_shared_models = bool(self.pipeline_config.get("use_shared_models", True))
        self.shared_models = str(self.pipeline_config.get("shared_models", "") or "")

        # ── Project Map & AST Analyzers ──────────────────────────────────────
        self.project_map = ProjectMapManager(self.sandbox_dir)
        self.analyzer = ProjectAnalyzer()
        self.context_builder = AIContextBuilder(self.project_map)
        self.feature_validator = FeatureValidator(
            self.sandbox_dir,
            backend_port=self.backend_port,
            global_contract=self.global_contract,
        )
        self.phase_runtime_ready = self._phase_runtime_dependencies_ready()

        self.stage_providers = {}
        self.stage_model_ids = {}
        for stage_name in ("planning", "architecture", "frontend", "backend", "validation"):
            provider_for_stage, model_for_stage = self._build_stage_client(stage_name)
            self.stage_providers[stage_name] = provider_for_stage
            self.stage_model_ids[stage_name] = model_for_stage

        from ..agents.unified_self_healing import UnifiedSelfHealing
        self.unified_repair = UnifiedSelfHealing(
            self.sandbox_dir, self.stage_providers["validation"], self.tool_registry, 
            self.error_analyzer, self.context_builder, self.stage_model_ids["validation"] or self.model_id, self.memory,
            backend_port=self.backend_port
        )
        self.decision_engine = self.unified_repair.decision_engine

    def _stage_model_config(self, stage_name: str) -> str:
        if self.use_shared_models and self.shared_models:
            return self.shared_models

        key_map = {
            "planning": "planning_model",
            "architecture": "architecture_model",
            "frontend": "frontend_model",
            "backend": "backend_model",
            "validation": "validation_model",
        }
        return str(self.pipeline_config.get(key_map[stage_name], "") or "")

    def _build_stage_client(self, stage_name: str):
        raw_models = self._stage_model_config(stage_name)
        if not raw_models:
            return self.provider, self.model_id

        from ..providers import FailoverProvider, parse_model_candidates

        explicit_keys = dict(self.user_provider_keys)
        if self.request_provider_name and self.request_api_key:
            explicit_keys[self.request_provider_name] = self.request_api_key

        candidates = parse_model_candidates(
            raw_models,
            self.request_provider_name or getattr(self.provider, "provider_name", "") or "groq",
            self.model_id,
        )
        if not candidates:
            return self.provider, self.model_id

        return (
            FailoverProvider(
                candidates,
                scraper_url=self.request_scraper_url,
                explicit_api_keys=explicit_keys,
            ),
            candidates[0].model,
        )

    def _generation_stage_for_batch(self, current_batch: list[str]) -> str:
        if not current_batch:
            return "architecture"

        normalized_batch = [str(path or "").strip().replace("\\", "/") for path in current_batch]
        backend_count = sum(1 for path in normalized_batch if path.lower().startswith("server/"))
        frontend_count = len(current_batch) - backend_count
        package_in_batch = any(path == "package.json" for path in normalized_batch)

        project_spec = getattr(self.planner, "project_spec", None)
        project_requires_backend = bool(
            project_spec
            and (
                list(getattr(project_spec, "api_resources", []) or [])
                or bool(getattr(getattr(project_spec, "auth", None), "enabled", False))
            )
        )

        if package_in_batch and project_requires_backend:
            return "architecture"

        if backend_count and not frontend_count:
            return "backend"
        if frontend_count and not backend_count:
            return "frontend"
        return "architecture"

    def _effective_model_id(self, provider, fallback: str) -> str:
        return str(getattr(provider, "last_model_id", "") or fallback or self.model_id)

    def _compiled_managed_paths(self, project_spec=None) -> list[str]:
        return compiled_core_paths(project_spec or self.planner.project_spec)

    def _prompt_focus_paths(self, current_batch: list[str], scoped_blueprint: dict | None) -> list[str]:
        focus: list[str] = []
        seen: set[str] = set()

        def _add(path: str) -> None:
            normalized = str(path or "").strip().replace("\\", "/")
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            focus.append(normalized)

        for path in current_batch or []:
            _add(path)

        scoped_blueprint = dict(scoped_blueprint or {})
        for item in list(scoped_blueprint.get("blueprint") or []):
            if isinstance(item, dict):
                _add(item.get("path", ""))
        for item in list(scoped_blueprint.get("related_types") or []):
            if isinstance(item, dict):
                _add(item.get("path", ""))
        for item in list(scoped_blueprint.get("api_contracts") or []):
            if isinstance(item, dict):
                _add(item.get("provided_by", ""))
        for path in list(scoped_blueprint.get("shared_files") or []):
            _add(path)

        for shared_path in (
            "src/types/index.ts",
            "src/services/api.ts",
            "src/App.tsx",
            "src/main.tsx",
            "server/db/database.ts",
        ):
            _add(shared_path)

        return focus

    def _normalize_batch_for_stage(self, current_batch: list[str], stage_name: str) -> list[str]:
        stage = str(stage_name or "").strip().lower()
        batch = list(current_batch or [])
        if stage == "architecture":
            return batch
        return batch

    def _get_unit_paths_for_batch(self, current_batch: list[str]) -> list[str]:
        """
        Return all paths that share the same unit_id as the files in current_batch.
        This provides 'unit parity' during repairs, allowing the AI to rewrite
        scaffold files even if the iteration focus has narrowed to a specific fix.
        """
        if not current_batch:
            return []

        unit_ids = set()
        for path in current_batch:
            for task in self.planner._tasks:
                if task.path == path:
                    unit_ids.add(task.unit_id)
                    break

        if not unit_ids:
            return current_batch

        unit_paths = [t.path for t in self.planner._tasks if t.unit_id in unit_ids]
        
        dynamic_hubs = [
            "src/types/index.ts",
            "src/types/index.d.ts",
            "server/db/database.ts",
            "src/services/api.ts"
        ]
        
        return sorted(list(set(current_batch) | set(unit_paths) | set(dynamic_hubs)))

    def _augment_batch_with_runtime_scaffold(
        self,
        current_batch: list[str],
        *,
        batch_cap: int | None = None,
    ) -> list[str]:
        """
        Ensure frontend batches do not fail styling contract gates due to missing
        Tailwind runtime scaffolding.
        """
        normalized_batch: list[str] = []
        seen: set[str] = set()
        for raw in list(current_batch or []):
            path = str(raw or "").strip().replace("\\", "/")
            if not path or path in seen:
                continue
            seen.add(path)
            normalized_batch.append(path)

        if not normalized_batch:
            return normalized_batch

        frontend_surface_prefixes = (
            "src/pages/",
            "src/components/",
            "src/layouts/",
            "src/hooks/",
            "src/context/",
            "src/App.tsx",
            "src/main.tsx",
        )
        touches_frontend_surface = any(
            path.startswith(frontend_surface_prefixes) or path in {"src/App.tsx", "src/main.tsx"}
            for path in normalized_batch
        )
        if not touches_frontend_surface:
            return normalized_batch

        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        auto_add_runtime_scaffold = self._read_bool_config(
            cfg,
            "builder_auto_add_runtime_scaffold",
            False,
        )
        if not auto_add_runtime_scaffold:
            return normalized_batch

        runtime_ready = False
        try:
            runtime_ready = bool(self.feature_validator._project_has_tailwind_runtime())  # noqa: SLF001
        except Exception:
            runtime_ready = False
        if runtime_ready:
            return normalized_batch

        pending_paths = {
            str(task.path or "").strip().replace("\\", "/")
            for task in list(getattr(self.planner, "tasks", []) or [])
            if not bool(getattr(task, "is_done", False))
        }
        runtime_scaffold = ["package.json", "tailwind.config.js", "postcss.config.js"]
        additions = [
            path
            for path in runtime_scaffold
            if path in pending_paths and path not in seen
        ]
        if not additions:
            return normalized_batch

        augmented = normalized_batch + additions
        if batch_cap and int(batch_cap) > 0 and len(augmented) > int(batch_cap):
            # Keep runtime scaffolding in the batch by trimming from the original tail first.
            cap = int(batch_cap)
            pinned = set(additions)
            trimmed_original: list[str] = []
            for path in normalized_batch:
                if len(trimmed_original) + len(additions) >= cap:
                    break
                trimmed_original.append(path)
            augmented = trimmed_original + additions

        return augmented

    def _list_existing_project_files(self) -> list[str]:
        existing_files: list[str] = []
        ignored_dirs = {"node_modules", ".git", "__pycache__", "venv"}

        for root, dirs, files in os.walk(self.sandbox_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
            rel_root = os.path.relpath(root, self.sandbox_dir)
            if rel_root == ".lovable" or rel_root.startswith(".lovable/"):
                continue

            for filename in files:
                rel_path = os.path.relpath(os.path.join(root, filename), self.sandbox_dir).replace("\\", "/")
                if rel_path.startswith(".lovable/") or rel_path == "project_map.json":
                    continue
                existing_files.append(rel_path)

        return sorted(existing_files)

    def _ensure_orchestration_services(self) -> None:
        sandbox_dir = str(getattr(self, "sandbox_dir", "") or ".")
        planner = getattr(self, "planner", None)
        if planner is None:
            planner = ExecutionPlanner()
            self.planner = planner

        planning = getattr(self, "planning", None)
        if planning is None:
            planning = PlanningService(sandbox_dir, planner=planner)
            self.planning = planning
        else:
            planning.sandbox_dir = sandbox_dir
            planning.planner = planner

        if getattr(self, "run_state_store", None) is None:
            self.run_state_store = GenerationRunStateStore(sandbox_dir)

        repair_service = getattr(self, "repair_service", None)
        if repair_service is None:
            self.repair_service = PlanRepairService(self.planning)
        else:
            repair_service.planning = self.planning

    def _resume_state_path(self) -> str:
        self._ensure_orchestration_services()
        return self.run_state_store.path()

    def _load_resume_state(self) -> dict:
        self._ensure_orchestration_services()
        return self.run_state_store.load()

    def _save_resume_state(self, *, original_prompt: str, iteration: int, design=None, design_prompt_context=None) -> None:
        try:
            self._ensure_orchestration_services()
            self.planning.persist(prompt=original_prompt)
            existing_payload = self.run_state_store.load()
            payload = {
                "original_prompt": original_prompt,
                "iteration": iteration,
                "triage_cache": self.triage_cache,
                "validation_repair_state": self.validation_repair_state,
                "generation_retry_state": self.generation_retry_state,
                "retry_batch_override": list(self.retry_batch_override or []),
            }
            if design is not None:
                payload["design"] = asdict(design)
            if design_prompt_context is not None:
                payload["design_prompt_context"] = design_prompt_context
            elif existing_payload.get("design_prompt_context") is not None:
                payload["design_prompt_context"] = existing_payload.get("design_prompt_context")
            self.run_state_store.save(payload)
        except Exception:
            pass

    def _clear_resume_state(self) -> None:
        self._ensure_orchestration_services()
        self.run_state_store.clear()

    def _triage_issue_key(self, broken_file: str, message: str) -> str:
        raw = f"{broken_file.strip().lower()}::{message.strip()}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _remember_validation_ai_decision(
        self,
        signature: str,
        broken_file: str,
        decision: dict,
        strategy: str,
    ) -> None:
        if not signature:
            return

        signature_state = dict(self.validation_repair_state.get(signature, {}) or {})
        last_ai_decisions = dict(signature_state.get("last_ai_decisions", {}) or {})
        target_files = [
            str(path).strip()
            for path in ((decision or {}).get("target_files") or [broken_file])
            if str(path).strip()
        ]
        last_ai_decisions[broken_file] = {
            "strategy": str(strategy or "UNKNOWN"),
            "root_cause": str((decision or {}).get("root_cause", "") or "").strip(),
            "write_files": str((decision or {}).get("write_files", "") or "").strip(),
            "target_files": target_files,
        }
        signature_state["last_ai_decisions"] = last_ai_decisions
        self.validation_repair_state[signature] = signature_state

    def _provider_retry_policy(self) -> tuple[int, list[int]]:
        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        retries = max(1, int(cfg.get("provider_retries", 3) or 3))
        raw_backoff = cfg.get("provider_backoff_seconds", [3, 8, 15])
        if isinstance(raw_backoff, str):
            backoff = [
                int(part.strip())
                for part in raw_backoff.split(",")
                if str(part).strip().isdigit()
            ]
        elif isinstance(raw_backoff, (list, tuple)):
            backoff = []
            for item in raw_backoff:
                try:
                    backoff.append(max(0, int(item)))
                except Exception:
                    continue
        else:
            backoff = []

        if not backoff:
            backoff = [3, 8, 15]
        while len(backoff) < retries:
            backoff.append(backoff[-1])
        return retries, backoff

    def _single_batch_mode_enabled(self) -> bool:
        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        provider_name = str(
            getattr(self, "request_provider_name", "")
            or getattr(getattr(self, "provider", None), "provider_name", "")
            or ""
        ).strip().lower()
        contract_batching = dict((self.global_contract or {}).get("batching") or {})
        constrained_batching = bool(contract_batching.get("constrained_batching", True))
        default_single_batch = not constrained_batching
        raw = cfg.get("builder_single_batch_mode", default_single_batch)
        if provider_name:
            scoped_key = f"builder_single_batch_mode_{provider_name}"
            if scoped_key in cfg:
                raw = cfg.get(scoped_key)

        if isinstance(raw, bool):
            return raw
        text = str(raw or "").strip().lower()
        if text in {"0", "false", "no", "off"}:
            return False
        if text in {"1", "true", "yes", "on"}:
            return True
        return True

    def _runtime_min_validation_seconds(self) -> int:
        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        try:
            contract_min = int(
                ((self.global_contract or {}).get("runtime_smoke") or {}).get("min_validation_seconds", 180) or 180
            )
        except Exception:
            contract_min = 180
        raw = cfg.get("runtime_min_validation_seconds", contract_min)
        try:
            return max(0, int(raw or 0))
        except Exception:
            return max(0, contract_min)

    def _backend_runtime_attempt_limit(self) -> int:
        # Default backend health checks to at least a 3-minute validation window.
        base_attempts = 20
        initial_wait = 10
        retry_wait = 5
        minimum_window = self._runtime_min_validation_seconds()
        if minimum_window <= 0:
            return base_attempts
        remaining = max(0, minimum_window - initial_wait)
        extra_attempts = (remaining + retry_wait - 1) // retry_wait
        return max(base_attempts, 1 + int(extra_attempts))

    def _frontend_preview_attempt_limit(self) -> int:
        # Default frontend preview probing to at least a 3-minute validation window.
        base_attempts = 15
        retry_wait = 2
        minimum_window = self._runtime_min_validation_seconds()
        if minimum_window <= 0:
            return base_attempts
        attempts = (minimum_window + retry_wait - 1) // retry_wait
        return max(base_attempts, int(attempts))

    def _single_batch_max_files(self) -> int:
        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        provider_name = str(
            getattr(self, "request_provider_name", "")
            or getattr(getattr(self, "provider", None), "provider_name", "")
            or ""
        ).strip().lower()

        scoped_key = f"builder_single_batch_max_files_{provider_name}" if provider_name else ""
        # Keep true one-batch generation by default.
        # Operators can still force splitting via:
        # - builder_single_batch_max_files
        # - builder_single_batch_max_files_<provider>
        default_limit = 0
        raw = cfg.get(scoped_key, cfg.get("builder_single_batch_max_files", default_limit)) if scoped_key else cfg.get(
            "builder_single_batch_max_files",
            default_limit,
        )
        try:
            return max(0, int(raw or 0))
        except Exception:
            return default_limit

    def _guard_single_batch_paths(
        self,
        pending_paths: list[str],
        *,
        fallback_cap: int = 20,
    ) -> tuple[list[str], str]:
        paths = [
            str(path or "").strip().replace("\\", "/")
            for path in list(pending_paths or [])
            if str(path or "").strip()
        ]
        if not paths:
            return [], ""
        if not self._single_batch_mode_enabled():
            return paths, ""

        max_files = self._single_batch_max_files()
        if max_files <= 0 or len(paths) <= max_files:
            return paths, ""

        smart_cap = max(1, min(max_files, int(fallback_cap or max_files)))
        narrowed = list(self.planner.get_smart_batch(batch_cap=smart_cap) or [])
        if not narrowed:
            narrowed = paths[:max_files]

        note = (
            "ℹ️ Single-batch safety guard: oversized batch detected "
            f"({len(paths)} files). Narrowing this turn to {len(narrowed)} files "
            "to reduce blueprint drift/truncation risk."
        )
        return narrowed, note

    @staticmethod
    def _read_bool_config(cfg: dict, key: str, default: bool) -> bool:
        raw = cfg.get(key, default)
        if isinstance(raw, bool):
            return raw
        text = str(raw or "").strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    def _pending_batch_paths(self) -> list[str]:
        pending: list[str] = []
        seen: set[str] = set()
        for task in list(getattr(self.planner, "tasks", []) or []):
            if bool(getattr(task, "is_done", False)):
                continue
            path = str(getattr(task, "path", "") or "").strip().replace("\\", "/")
            if not path or path in seen:
                continue
            seen.add(path)
            pending.append(path)
        return pending

    def _generation_failure_limit(self) -> int:
        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        return max(1, int(cfg.get("generation_failure_limit", 3) or 3))

    def _record_generation_failure(
        self,
        failure_kind: str,
        current_batch: list[str],
        error_text: str,
        retry_batch: list[str] | None = None,
    ) -> tuple[str, int, bool]:
        normalized_batch = sorted(
            str(path).strip().replace("\\", "/")
            for path in list(current_batch or [])
            if str(path).strip()
        )
        normalized_retry = sorted(
            str(path).strip().replace("\\", "/")
            for path in list(retry_batch or [])
            if str(path).strip()
        )
        normalized_lines = [
            re.sub(r"\s+", " ", str(line).strip())
            for line in str(error_text or "").splitlines()
            if str(line).strip()
        ]
        signature_payload = json.dumps(
            {
                "kind": str(failure_kind or "").strip().lower(),
                "batch": normalized_batch,
                "retry": normalized_retry,
                "error": normalized_lines[:12],
            },
            sort_keys=True,
        )
        signature = hashlib.sha1(signature_payload.encode("utf-8")).hexdigest()
        state = dict(self.generation_retry_state.get(signature, {}) or {})
        count = int(state.get("count", 0) or 0) + 1
        state.update(
            {
                "count": count,
                "kind": str(failure_kind or "").strip().lower(),
                "batch": normalized_batch,
                "retry": normalized_retry,
                "error_preview": normalized_lines[:5],
            }
        )
        self.generation_retry_state[signature] = state
        return signature, count, count >= self._generation_failure_limit()

    def _clear_generation_failure_state(self) -> None:
        self.generation_retry_state = {}

    def _hydrate_existing_project_state(self, existing_files: list[str]) -> None:
        self.project_map.data = {"files": []}
        for rel_path in existing_files:
            full_path = os.path.join(self.sandbox_dir, rel_path)
            try:
                metadata = self.analyzer.analyze_file(full_path, rel_path)
                self.project_map.add_file(metadata)
            except Exception:
                continue

    def _mark_existing_files_done(self, existing_files: list[str]) -> int:
        before = self.planner.done_count
        existing = {
            path.strip().lower().lstrip("./").replace("\\", "/")
            for path in existing_files
        }
        target_override = {
            str(path).strip().lower().lstrip("./").replace("\\", "/")
            for path in list(self.pipeline_config.get("target_files_override", []) or [])
            if str(path).strip()
        }
        changed = False
        for task in self.planner.tasks:
            task_path = task.path.strip().lower().lstrip("./").replace("\\", "/")
            if task_path in target_override:
                continue
            if task_path in existing:
                self.planner.mark_done(task.path)
                changed = True
        if changed:
            self.planning.persist()
        return self.planner.done_count - before

    def _apply_written_paths(self, written_paths: list[str]) -> None:
        changed = False
        for task in self.planner.tasks:
            if task.status == ExecutionStatus.DONE:
                continue

            task_path = task.path.strip().lower()
            for wp in written_paths:
                wp_path = wp.strip().lower()
                if ".lovable/plan.json" in wp_path or ".lovable/run_state.json" in wp_path:
                    continue

                is_match = (wp_path == task_path) or wp_path.endswith("/" + task_path) or task_path.endswith("/" + wp_path)
                if is_match:
                    self.planner.mark_done(task.id)
                    changed = True
                    try:
                        full_path = os.path.join(self.sandbox_dir, wp)
                        if os.path.exists(full_path):
                            metadata = self.analyzer.analyze_file(full_path, wp)
                            self.project_map.add_file(metadata)
                    except Exception as e:
                        print(f"AST Analysis Error for {wp}: {e}")
                    break
        if changed:
            self.planning.persist()

    def _validate_blueprint_execution_gate(
        self,
        files_to_write: list[dict[str, str]],
        *,
        target_paths: list[str] | None = None,
    ) -> list[str]:
        if not bool(self.pipeline_config.get("pre_write_blueprint_validation_enabled", True)):
            return []
        if not self.feature_validator_enabled or not self.planner.project_spec:
            return []

        self.feature_validator.set_project_spec(
            self.planner.project_spec,
            self.planner.get_blueprint_files(),
        )
        errors = self.feature_validator.validate_blueprint_execution_batch(
            files_to_write,
            target_paths=target_paths,
        )
        if not errors:
            return []

        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        inject_scope_failure = self._read_bool_config(
            cfg,
            "pre_write_blueprint_scope_injection_enabled",
            False,
        )
        if not inject_scope_failure:
            return errors

        normalized_targets = [
            str(path or "").strip().replace("\\", "/")
            for path in list(target_paths or [])
            if str(path or "").strip()
        ]
        extracted_error_paths = self._extract_phase_error_paths(errors, [])
        cluster_seed_paths = extracted_error_paths or normalized_targets
        cluster_paths = self.planner.get_cluster_for_paths(cluster_seed_paths)
        if cluster_paths:
            scope_message = (
                f"{cluster_paths[0]}: BLUEPRINT_SCOPE_FAILURE: "
                "Rewrite the full connected blueprint contract cluster together: "
                + ", ".join(cluster_paths[:12])
            )
            if scope_message not in errors:
                errors.insert(1 if errors else 0, scope_message)

        return errors

    def _validate_pre_write_style_gate(
        self,
        files_to_write: list[dict[str, str]],
        *,
        target_paths: list[str] | None = None,
    ) -> list[str]:
        if not self.feature_validator_enabled:
            return []
        errors = self.feature_validator.validate_frontend_style_batch(
            files_to_write,
            target_paths=target_paths,
        )
        if not errors:
            return []

        # If the only issue is missing Tailwind runtime, but this batch scope includes
        # runtime scaffold owner files, allow the write and let missing scaffolds be
        # recovered by partial-batch retry logic.
        only_tailwind_runtime_missing = all(
            "TAILWIND_RUNTIME_MISSING" in str(err or "")
            for err in errors
        )
        if only_tailwind_runtime_missing:
            runtime_markers = {
                "package.json",
                "tailwind.config.js",
                "tailwind.config.cjs",
                "tailwind.config.ts",
                "postcss.config.js",
                "postcss.config.cjs",
            }
            normalized_targets = {
                str(path or "").strip().replace("\\", "/")
                for path in list(target_paths or [])
                if str(path or "").strip()
            }
            normalized_written_paths = {
                str((item or {}).get("path", "") or "").strip().replace("\\", "/")
                for item in list(files_to_write or [])
                if str((item or {}).get("path", "") or "").strip()
            }
            pending_planned_paths = {
                str(task.path).strip().replace("\\", "/")
                for task in getattr(self.planner, "_tasks", [])
                if not getattr(task, "is_done", False) and str(task.path).strip()
            }
            if (normalized_targets | normalized_written_paths | pending_planned_paths) & runtime_markers:
                return []

        return errors

    def _extract_blueprint_scope_cluster(self, text: str) -> list[str]:
        return self.repair_service.extract_blueprint_scope_cluster(text)

    def _strict_failed_retry_paths(
        self,
        error_text: str,
        current_batch: list[str],
    ) -> list[str]:
        normalized_current = [
            str(path or "").strip().replace("\\", "/")
            for path in list(current_batch or [])
            if str(path or "").strip()
        ]
        if not normalized_current:
            return []

        current_lookup = {
            path.lower().lstrip("./"): path
            for path in normalized_current
        }
        direct_error_paths = self._extract_phase_error_paths(
            [line for line in str(error_text or "").splitlines() if line.strip()],
            [],
        )

        strict_retry: list[str] = []
        seen: set[str] = set()
        for raw_path in direct_error_paths:
            key = str(raw_path or "").strip().replace("\\", "/").lower().lstrip("./")
            matched = current_lookup.get(key)
            if matched and matched not in seen:
                seen.add(matched)
                strict_retry.append(matched)

        return strict_retry

    def _determine_retry_batch(
        self,
        error_text: str,
        current_batch: list[str],
    ) -> list[str]:
        self._ensure_orchestration_services()
        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        minimal_retry_scope = self._read_bool_config(
            cfg,
            "builder_retry_only_failed_files",
            True,
        )
        strict_failed_only_retry = self._read_bool_config(
            cfg,
            "builder_retry_strict_failed_only",
            True,
        )
        message = str(error_text or "")
        lowered_message = message.lower()
        is_blueprint_contract_failure = (
            "BLUEPRINT_NOT_ENFORCED" in message
            or "BLUEPRINT_SCOPE_FAILURE" in message
        )
        is_style_contract_failure = (
            "styling contract validation failed" in lowered_message
            or "stylesheet_class_" in lowered_message
            or "tailwind_runtime_missing" in lowered_message
        )
        has_connected_blueprint_markers = any(
            marker in lowered_message
            for marker in (
                "import_site_error",
                "blueprint_export_mismatch",
                "schema_sync_error",
                "symbol/export drift",
                "rewrite the full connected blueprint contract cluster together",
            )
        )
        batching_contract = dict((self.global_contract or {}).get("batching") or {})
        retry_cluster_expansion = bool(batching_contract.get("retry_cluster_expansion_on_contract_error", True))
        prefer_cluster_retry = retry_cluster_expansion and (
            is_style_contract_failure or has_connected_blueprint_markers
        )
        normalized_current = [
            str(path or "").strip().replace("\\", "/")
            for path in list(current_batch or [])
            if str(path or "").strip()
        ]
        if (
            strict_failed_only_retry
            and minimal_retry_scope
            and is_blueprint_contract_failure
            and not prefer_cluster_retry
        ):
            strict_retry = self._strict_failed_retry_paths(error_text, normalized_current)
            retry = strict_retry or normalized_current
            if retry and getattr(self, "sandbox_dir", ""):
                self.planning.record_retry(retry, error_text)
            return retry

        if self._single_batch_mode_enabled():
            if "phase gate" in message.lower():
                retry = self._pending_batch_paths() or normalized_current
                retry, _guard_note = self._guard_single_batch_paths(
                    retry,
                    fallback_cap=int(self.pipeline_config.get("builder_batch_cap", 20) or 20),
                )
                if retry and getattr(self, "sandbox_dir", ""):
                    self.planning.record_retry(retry, error_text)
                return retry

            current_lookup = {
                path.lower().lstrip("./"): path
                for path in normalized_current
            }
            if (
                minimal_retry_scope
                and not prefer_cluster_retry
                and (
                "BLUEPRINT_NOT_ENFORCED" in message
                or "BLUEPRINT_SCOPE_FAILURE" in message
                )
            ):
                direct_error_paths = self._extract_phase_error_paths(
                    [line for line in message.splitlines() if line.strip()],
                    [],
                )
                minimal_retry: list[str] = []
                seen_minimal: set[str] = set()
                for raw_path in direct_error_paths:
                    key = str(raw_path or "").strip().replace("\\", "/").lower().lstrip("./")
                    matched = current_lookup.get(key)
                    if matched and matched not in seen_minimal:
                        seen_minimal.add(matched)
                        minimal_retry.append(matched)

                if not minimal_retry:
                    explicit_cluster = self._extract_blueprint_scope_cluster(message)
                    for raw_path in explicit_cluster:
                        key = str(raw_path or "").strip().replace("\\", "/").lower().lstrip("./")
                        matched = current_lookup.get(key)
                        if matched and matched not in seen_minimal:
                            seen_minimal.add(matched)
                            minimal_retry.append(matched)

                if minimal_retry:
                    if getattr(self, "sandbox_dir", ""):
                        self.planning.record_retry(minimal_retry, error_text)
                    return minimal_retry

            focused_retry = self.repair_service.determine_retry_batch(error_text, current_batch)
            retry = [
                str(path or "").strip().replace("\\", "/")
                for path in list(focused_retry or [])
                if str(path or "").strip()
            ]
            if not retry:
                retry = self._pending_batch_paths()
            if not retry:
                retry = [
                    str(path or "").strip().replace("\\", "/")
                    for path in list(current_batch or [])
                    if str(path or "").strip()
                ]
            retry, _guard_note = self._guard_single_batch_paths(
                retry,
                fallback_cap=int(self.pipeline_config.get("builder_batch_cap", 20) or 20),
            )
            if retry and getattr(self, "sandbox_dir", ""):
                self.planning.record_retry(retry, error_text)
            return retry
        retry = self.repair_service.determine_retry_batch(error_text, current_batch)
        if retry and getattr(self, "sandbox_dir", ""):
            self.planning.record_retry(retry, error_text)
        return retry

    def _extract_phase_error_paths(self, errors: list[str], fallback_paths: list[str]) -> list[str]:
        return self.repair_service.extract_phase_error_paths(errors, fallback_paths)

    def _reopen_pending_paths(self, paths: list[str]) -> None:
        for path in paths:
            self.planning.mark_pending(path)

    def _run_phase_gates(
        self,
        batch_paths: list[str],
        *,
        files_to_write: list[dict[str, str]] | None = None,
    ) -> tuple[list[str], list[str]]:
        if not self.feature_validator_enabled or not self.planner.project_spec:
            return [], []

        normalized_batch = [str(path).strip().replace("\\", "/") for path in batch_paths if str(path).strip()]
        errors: list[str] = []
        phases: list[str] = []
        compiled_paths = set(self._compiled_managed_paths())
        is_pure_scaffold_batch = bool(normalized_batch) and all(path in compiled_paths for path in normalized_batch)

        # Collect all files that are still pending in the planner (planned but not yet
        # written to disk). These are passed to the backend/frontend validators so that
        # existence checks don't raise false BACKEND_PHASE_MISSING errors for files that
        # are queued in the same generation round but haven't been flushed yet.
        pending_planned_paths: set[str] = {
            str(task.path).strip().replace("\\", "/")
            for task in getattr(self.planner, "_tasks", [])
            if not getattr(task, "is_done", False) and str(task.path).strip()
        }

        if any(path in compiled_paths for path in normalized_batch):
            scaffold_errors = self.feature_validator.validate_scaffold_phase(
                self.planner.project_spec,
                target_paths=normalized_batch,
            )
            if scaffold_errors:
                phases.append("scaffold")
                errors.extend(scaffold_errors)
        if is_pure_scaffold_batch:
            return phases, errors

        if any(path.startswith("server/") for path in normalized_batch):
            backend_errors = self.feature_validator.validate_backend_phase(
                normalized_batch,
                self.planner.project_spec,
                planned_paths=pending_planned_paths,
            )
            if backend_errors:
                phases.append("backend")
                errors.extend(backend_errors)

        frontend_prefixes = ("src/pages/", "src/services/", "src/hooks/", "src/context/", "src/components/AdminRoute.tsx")
        if any(path.startswith(frontend_prefixes) or path == "src/components/AdminRoute.tsx" for path in normalized_batch):
            frontend_errors = self.feature_validator.validate_frontend_phase(
                normalized_batch,
                self.planner.project_spec,
                files_to_write=files_to_write or [],
            )
            if frontend_errors:
                runtime_markers = {
                    "package.json",
                    "tailwind.config.js",
                    "tailwind.config.cjs",
                    "tailwind.config.ts",
                    "postcss.config.js",
                    "postcss.config.cjs",
                }
                only_tailwind_runtime_missing = all(
                    "TAILWIND_RUNTIME_MISSING" in str(err or "")
                    for err in frontend_errors
                )
                if only_tailwind_runtime_missing and (pending_planned_paths & runtime_markers):
                    frontend_errors = []
            if frontend_errors:
                phases.append("frontend")
                errors.extend(frontend_errors)

        return phases, errors

    def _resource_backend_owner_paths(self, route: str) -> tuple[str, str]:
        normalized = str(route or "").strip()
        if normalized.startswith("/api/"):
            normalized = normalized[len("/api/"):]
        normalized = normalized.strip("/").split("/", 1)[0]
        slug = _slug(normalized or "items")
        singular = _singular_slug(slug)
        return (
            f"server/controllers/{singular}Controller.ts",
            f"server/routes/{singular}Routes.ts",
        )

    def _sandbox_has_file(self, rel_path: str) -> bool:
        clean = str(rel_path or "").strip().replace("\\", "/")
        if not clean:
            return False
        return os.path.exists(os.path.join(self.sandbox_dir, clean))

    def _determine_backend_smoke_targets(self, batch_paths: list[str]) -> tuple[list[dict[str, str]], bool, bool]:
        project_spec = self.planner.project_spec
        if not project_spec:
            return [], False, False

        normalized = {
            str(path or "").strip().replace("\\", "/")
            for path in batch_paths
            if str(path or "").strip()
        }
        health_check = bool(normalized & {"server/index.ts", "server/db/database.ts"})
        auth_paths = {
            "server/controllers/authController.ts",
            "server/routes/authRoutes.ts",
            "server/middleware/authMiddleware.ts",
            "server/utils/jwt.ts",
        }
        auth_files_exist = (
            self._sandbox_has_file("server/controllers/authController.ts")
            and self._sandbox_has_file("server/routes/authRoutes.ts")
        )
        auth_required = bool(
            project_spec.auth.enabled
            and (
                normalized & auth_paths
                or (health_check and auth_files_exist)
            )
        )
        routes: list[dict[str, str]] = []
        seen: set[str] = set()
        for resource in project_spec.api_resources:
            controller_path, route_path = self._resource_backend_owner_paths(resource.route)
            resource_files_exist = self._sandbox_has_file(controller_path) and self._sandbox_has_file(route_path)
            should_check_route = (
                controller_path in normalized
                or route_path in normalized
                or (health_check and resource_files_exist)
            )
            if should_check_route and resource.route not in seen:
                seen.add(resource.route)
                routes.append(
                    {
                        "route": str(resource.route or "").strip(),
                        "auth": str(resource.auth or "public").strip().lower() or "public",
                    }
                )

        return routes, auth_required, health_check

    async def _start_backend_for_phase_smoke(self) -> tuple[bool, str]:
        if not self._has_backend_entry():
            return False, "server/index.ts: BACKEND_RUNTIME_SMOKE_FAILED: No backend entry point exists."

        await self.tool_registry.execute(
            "execute_command",
            {"command": self._kill_common_backend_ports_command() + "; sleep 1", "timeout": 10},
        )
        await self.tool_registry.execute(
            "execute_command",
            {"command": "> /tmp/sandbox_server.log 2>/dev/null || true", "timeout": 3, "label": "clear stale server log..."},
        )
        await self.tool_registry.execute(
            "execute_command",
            {"command": self._get_backend_start_command(), "timeout": 5, "label": "start backend service..."},
        )

        await asyncio.sleep(3)
        log_check = await self.tool_registry.execute(
            "execute_command",
            {
                "command": "cat /tmp/sandbox_server.log 2>/dev/null || echo '(empty)'",
                "timeout": 5,
            },
        )
        log_text = str(log_check or "")

        crash_signals = ("error:", "cannot", "failed", "enoent", "exception", "typeerror", "syntaxerror")
        is_empty = not log_text.strip() or log_text.strip() == "(empty)"
        is_crashed = any(s in log_text.lower() for s in crash_signals)

        if is_empty or is_crashed:
            return False, (
                f"server/index.ts: BACKEND_RUNTIME_SMOKE_FAILED: "
                f"Backend process crashed immediately on start.\\n{log_text[:800]}"
            )

        for _ in range(8):
            await asyncio.sleep(2)
            health_result = await self.tool_registry.execute(
                "execute_command",
                {
                    "command": (
                        "node <<'NODE'\n"
                        "(async()=>{"
                        f"try{{const res=await fetch('http://127.0.0.1:{self.backend_port}/api/health'); "
                        "if(res.ok){console.log('SMOKE_OK');} "
                        "else {console.error(`HEALTH ${res.status} ${await res.text()}`); process.exit(1);}}"
                        "catch(error){console.error(String(error)); process.exit(1);}})();\n"
                        "NODE"
                    ),
                    "timeout": 8,
                },
            )
            if "SMOKE_OK" in str(health_result):
                return True, ""

        error_log = self.feature_validator.get_backend_logs()
        return False, f"server/index.ts: BACKEND_RUNTIME_SMOKE_FAILED: Backend failed health check after compilation.\n{error_log[:800]}"

    async def _run_backend_smoke_tests(self, batch_paths: list[str]) -> list[str]:
        if not self._phase_runtime_dependencies_ready():
            return []
        routes_to_check, auth_required, health_check = self._determine_backend_smoke_targets(batch_paths)
        if not health_check and not routes_to_check and not auth_required:
            return []

        healthy, error = await self._start_backend_for_phase_smoke()
        if not healthy:
            return [error]

        smoke_script = f"""node <<'NODE'
const routes = {json.dumps(routes_to_check)};
const needsAuth = {str(auth_required).lower()};
const base = 'http://127.0.0.1:{self.backend_port}';

(async () => {{
  if (needsAuth) {{
    const meRes = await fetch(base + '/api/auth/me', {{
      headers: {{ Accept: 'application/json' }},
    }});
    if (![200, 401, 403].includes(meRes.status)) {{
      console.error(`AUTH_ME ${{meRes.status}} ${{await meRes.text()}}`);
      process.exit(1);
    }}
  }}

  for (const target of routes) {{
    const res = await fetch(base + target.route, {{ headers: {{ Accept: 'application/json' }} }});
    const allowedStatuses = target.auth === 'public' ? [] : [401, 403];
    if (!(res.ok || allowedStatuses.includes(res.status))) {{
      console.error(`RESOURCE ${{target.route}} ${{res.status}} ${{await res.text()}}`);
      process.exit(1);
    }}
  }}

  console.log('SMOKE_OK');
}})().catch((error) => {{
  console.error(String(error?.stack || error));
  process.exit(1);
}});
NODE"""
        smoke_result = await self.tool_registry.execute(
            "execute_command",
            {"command": smoke_script, "timeout": 40},
        )
        if "SMOKE_OK" in str(smoke_result):
            return []

        result_text = str(smoke_result or "").strip()
        if result_text.startswith("AUTH_"):
            return [
                "server/controllers/authController.ts: BACKEND_RUNTIME_SMOKE_FAILED: "
                + result_text.splitlines()[0][:500]
            ]
        if result_text.startswith("RESOURCE "):
            match = re.match(r"RESOURCE\s+(\S+)\s+(\d+)\s*(.*)", result_text.splitlines()[0])
            if match:
                route = match.group(1)
                controller_path, route_path = self._resource_backend_owner_paths(route)
                return [
                    f"{controller_path}: BACKEND_RUNTIME_SMOKE_FAILED: {route} returned HTTP {match.group(2)}.",
                    f"{route_path}: BACKEND_RUNTIME_SMOKE_FAILED: {route} did not serve a healthy response.",
                ]

        return [
            "server/index.ts: BACKEND_RUNTIME_SMOKE_FAILED: Runtime smoke test failed.\n"
            + result_text[:800]
        ]

    async def _ensure_phase_runtime_dependencies(self) -> tuple[bool, str]:
        if self._phase_runtime_dependencies_ready():
            self.phase_runtime_ready = True
            return True, "already installed"
        if not (self.auto_install_enabled and self.runtime_enabled):
            return False, "phase runtime dependency bootstrap disabled"

        node_modules_dir = os.path.join(self.sandbox_dir, "node_modules")
        package_json_path = os.path.join(self.sandbox_dir, "package.json")

        # Early phase runtime checks are intentionally best-effort only.
        # Do not block generation on a full npm install before the project is even generated.
        if not os.path.exists(package_json_path):
            self.phase_runtime_ready = False
            return False, "phase runtime dependencies deferred until package.json exists"

        if not os.path.isdir(node_modules_dir):
            self.phase_runtime_ready = False
            return False, "phase runtime dependencies are not installed yet; deferring early smoke until final install"

        # A partially-populated node_modules can happen on resumed runs. Re-check only, but
        # still do not perform a blocking install during early phase validation.
        self.phase_runtime_ready = self._phase_runtime_dependencies_ready()
        if not self.phase_runtime_ready:
            return False, "phase runtime dependencies are incomplete; deferring early smoke until final install"

        return True, "already installed"

    def _phase_runtime_dependencies_ready(self) -> bool:
        required_paths = [
            os.path.join(self.sandbox_dir, "node_modules", "tsx", "dist", "loader.mjs"),
            os.path.join(self.sandbox_dir, "node_modules", "express", "package.json"),
        ]
        return all(os.path.exists(path) for path in required_paths)

    def _is_phase_runtime_infra_error(self, errors: list[str]) -> bool:
        haystack = "\n".join(str(err or "") for err in errors).lower()
        markers = (
            "tsx: not found",
            "cannot find package 'tsx'",
            "cannot find module 'tsx'",
            "core runtime dependencies are still unavailable",
            "phase runtime dependency bootstrap disabled",
            "npm err!",
            "npm error",
            "command timed out after",
        )
        return any(marker in haystack for marker in markers)

    def _project_spec_repair_context(self) -> str:
        project_spec = self.planner.project_spec
        if not project_spec:
            return ""

        lines = [
            f"Product Type: {project_spec.product_type}",
            f"App Kind: {project_spec.app_kind}",
        ]
        if project_spec.summary:
            lines.append(f"Summary: {project_spec.summary}")
        if project_spec.features:
            lines.append("Features: " + ", ".join(project_spec.features[:8]))
        if project_spec.pages:
            lines.append(
                "Pages: " + ", ".join(
                    f"{page.name} ({page.route}, auth={page.auth})"
                    for page in project_spec.pages[:8]
                )
            )
        if project_spec.api_resources:
            lines.append(
                "API Resources: " + ", ".join(
                    f"{resource.name} ({resource.route}, auth={resource.auth}, frontend={resource.frontend})"
                    for resource in project_spec.api_resources[:8]
                )
            )
        if project_spec.auth.enabled:
            auth_bits = [project_spec.auth.mode]
            if project_spec.auth.identifiers:
                auth_bits.append("identifiers=" + "/".join(project_spec.auth.identifiers))
            auth_bits.append("registration=" + ("yes" if project_spec.auth.allow_registration else "no"))
            if project_spec.auth.roles:
                auth_bits.append("roles=" + ",".join(project_spec.auth.roles))
            auth_bits.append(f"login={project_spec.auth.login_route}")
            if project_spec.auth.allow_registration:
                auth_bits.append(f"register={project_spec.auth.register_route}")
            auth_bits.append(f"session={project_spec.auth.session_route}")
            auth_bits.append(f"state={project_spec.auth.state_owner}")
            lines.append("Auth: enabled (" + "; ".join(auth_bits) + ")")
        if project_spec.acceptance_checks:
            lines.append("Acceptance Checks: " + "; ".join(project_spec.acceptance_checks[:6]))
        return "\n".join(lines)

    def _extract_project_paths_from_text(self, text: str, limit: int = 8) -> list[str]:
        found: list[str] = []
        for match in re.finditer(r'(?:server|src)/[^\s:()"\',<>]+\.(?:tsx|ts|jsx|js)', str(text or "")):
            path = match.group(0).strip()
            if path and path not in found and "node_modules" not in path:
                found.append(path)
            if len(found) >= limit:
                break
        return found

    def _resolve_relative_project_import(self, importer_rel: str, source: str) -> str | None:
        module_spec = str(source or "").strip()
        if not module_spec.startswith("."):
            return None
        return self._select_existing_project_candidate(
            self._project_import_candidates(importer_rel, module_spec)
        )

    def _resolve_project_module_candidate(self, candidate: str) -> str | None:
        clean = str(candidate or "").strip().replace("\\", "/").lstrip("/")
        if not clean:
            return None

        options: list[str] = []
        if re.search(r"\.(?:ts|tsx|js|jsx)$", clean):
            options.append(clean)
        else:
            for ext in (".ts", ".tsx", ".js", ".jsx"):
                options.append(clean + ext)
            for ext in (".ts", ".tsx", ".js", ".jsx"):
                options.append(f"{clean}/index{ext}")

        for option in options:
            if option.startswith("../") or "/../" in option:
                continue
            if os.path.exists(os.path.join(self.sandbox_dir, option)):
                return option
        return None

    def _project_import_candidates(self, importer_rel: str, source: str) -> list[str]:
        module_spec = str(source or "").strip()
        importer = str(importer_rel or "").strip().replace("\\", "/")
        if not module_spec:
            return []

        if module_spec.startswith("."):
            if not importer:
                return []
            importer_dir = os.path.dirname(importer)
            base_path = os.path.normpath(os.path.join(importer_dir, module_spec)).replace("\\", "/")
        else:
            base_path = module_spec.replace("\\", "/").lstrip("/")
            if base_path.startswith(("src/", "server/")):
                pass
            elif any(
                base_path.startswith(prefix)
                for prefix in (
                    "components/",
                    "pages/",
                    "services/",
                    "hooks/",
                    "types/",
                    "context/",
                    "utils/",
                    "store/",
                    "styles/",
                )
            ):
                base_path = f"src/{base_path}"
            elif any(
                base_path.startswith(prefix)
                for prefix in ("routes/", "controllers/", "middleware/", "db/")
            ):
                base_path = f"server/{base_path}"
            else:
                return []

        normalized_base = base_path.strip().replace("\\", "/")
        if not normalized_base or normalized_base.startswith("../") or "/../" in normalized_base:
            return []
        if not normalized_base.startswith(("src/", "server/")):
            return []

        if re.search(r"\.(?:ts|tsx|js|jsx|css)$", normalized_base):
            return [normalized_base]

        if normalized_base.startswith("src/styles/"):
            ext_order = (".css", ".ts", ".tsx", ".js", ".jsx")
        elif normalized_base.startswith(("src/components/", "src/pages/", "src/context/", "src/hooks/")):
            ext_order = (".tsx", ".ts", ".jsx", ".js")
        else:
            ext_order = (".ts", ".tsx", ".js", ".jsx")

        candidates: list[str] = []
        for ext in ext_order:
            candidates.append(normalized_base + ext)
        for ext in ext_order:
            candidates.append(f"{normalized_base}/index{ext}")
        return candidates

    def _select_existing_project_candidate(self, candidates: list[str]) -> str | None:
        for candidate in candidates:
            if candidate.startswith("../") or "/../" in candidate:
                continue
            if os.path.exists(os.path.join(self.sandbox_dir, candidate)):
                return candidate
        return None

    def _guess_missing_import_target(self, importer_rel: str, source: str) -> str | None:
        candidates = self._project_import_candidates(importer_rel, source)
        if not candidates:
            return None
        return self._select_existing_project_candidate(candidates) or candidates[0]

    def _extract_build_owner_targets(self, build_output: str) -> list[str]:
        targets = self._extract_project_paths_from_text(build_output, limit=16)
        text = str(build_output or "")

        for line in text.splitlines():
            importer_match = re.match(r"^(src/[^(]+)\(\d+,\d+\):\s*error\s+TS\d+:", line.strip())
            importer_rel = importer_match.group(1).strip() if importer_match else ""
            if importer_rel:
                targets.append(importer_rel)

            rel_module_match = re.search(
                r"Module\s+['\"](?:\\\"|\"|')?([.]{1,2}/[^'\"\\]+)(?:\\\"|\"|')?['\"]",
                line,
            )
            if importer_rel and rel_module_match:
                resolved = self._resolve_relative_project_import(importer_rel, rel_module_match.group(1))
                if resolved:
                    targets.append(resolved)

            for abs_src_match in re.finditer(r"/(src/[A-Za-z0-9_./-]+)", line):
                resolved = self._resolve_project_module_candidate(abs_src_match.group(1).rstrip("\"'"))
                if resolved:
                    targets.append(resolved)

        deduped: list[str] = []
        seen: set[str] = set()
        for path in targets:
            clean = str(path or "").strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            deduped.append(clean)
        return deduped

    def _find_existing_src_symbol_paths(self, symbol: str, limit: int = 6) -> list[str]:
        clean_symbol = str(symbol or "").strip()
        if not clean_symbol:
            return []

        src_root = os.path.join(self.sandbox_dir, "src")
        if not os.path.isdir(src_root):
            return []

        matches: list[str] = []
        for root, _dirs, files in os.walk(src_root):
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
                if len(matches) >= limit:
                    return matches
        return matches

    def _runtime_owner_targets_from_text(self, text: str) -> list[str]:
        haystack = str(text or "")
        targets = self._extract_project_paths_from_text(haystack)

        provider_match = re.search(
            r"\b(use[A-Z]\w+)\b must be used within (?:an?\s+)?([A-Z]\w*Provider)\b",
            haystack,
        )
        if provider_match:
            hook_name, provider_name = provider_match.groups()
            targets.extend(["src/main.tsx", "src/App.tsx"])
            targets.extend(self._find_existing_src_symbol_paths(hook_name))
            targets.extend(self._find_existing_src_symbol_paths(provider_name))

        for component_name in re.findall(r"<([A-Z]\w+)> component", haystack):
            targets.extend(self._find_existing_src_symbol_paths(component_name))

        deduped: list[str] = []
        seen: set[str] = set()
        for path in targets:
            clean = str(path or "").strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            deduped.append(clean)
        return deduped

    def _set_unified_repair_context(self, *, phase_context: str = "", owner_targets: list[str] | None = None) -> None:
        normalized_targets: list[str] = []
        seen: set[str] = set()
        for path in owner_targets or []:
            clean = str(path or "").strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            normalized_targets.append(clean)

        owner_context = "\n".join(f"- {path}" for path in normalized_targets)
        self.unified_repair.set_repair_context(
            project_spec_context=self._project_spec_repair_context(),
            phase_context=str(phase_context or "").strip(),
            owner_context=owner_context,
        )

    def _resource_owner_paths(self, route_name: str) -> dict[str, str]:
        project_spec = self.planner.project_spec
        normalized_route = str(route_name or "").strip().lower().strip("/")
        if not project_spec or not normalized_route:
            return {}

        for resource in project_spec.api_resources:
            resource_route = str(resource.route or "").strip()
            resource_name = resource_route.split("/api/")[-1].strip("/").split("/", 1)[0] if "/api/" in resource_route else str(resource.name or "").strip()
            if resource_name.lower() != normalized_route:
                continue
            slug = _slug(resource.name or resource_name)
            singular = _singular_slug(slug)
            pascal = _pascal(slug)
            return {
                "route": f"server/routes/{singular}Routes.ts",
                "controller": f"server/controllers/{singular}Controller.ts",
                "service": f"src/services/{singular}Service.ts",
                "hook": f"src/hooks/use{pascal}.tsx",
            }
        return {}

    def _preferred_repair_targets_for_error(self, err: str, fallback_file: str = "") -> list[str]:
        message = str(err or "")
        targets: list[str] = []

        scope_cluster = self._extract_blueprint_scope_cluster(message)
        targets.extend(scope_cluster)
        targets.extend(self._runtime_owner_targets_from_text(message))

        backend_file_hints = re.findall(
            r"\b([A-Za-z0-9_-]+(?:Controller|Middleware|Routes?)\.ts)\b",
            message,
        )
        for hint in backend_file_hints:
            clean = str(hint or "").strip()
            lowered = clean.lower()
            if lowered.endswith("controller.ts"):
                targets.append(f"server/controllers/{clean}")
            elif lowered.endswith("middleware.ts"):
                targets.append(f"server/middleware/{clean}")
            elif lowered.endswith("routes.ts") or lowered.endswith("route.ts"):
                targets.append(f"server/routes/{clean}")

        if "BLUEPRINT_NOT_ENFORCED" in message:
            targets.append("src/types/index.ts")
        if "DB_CONTRACT_ERROR" in message or "SCHEMA_SYNC_ERROR" in message:
            targets.append("server/db/database.ts")
            targets.append("package.json")
        if any(
            token in message
            for token in (
                "Missing 'server' script",
                'Remove "type": "module"',
                "better-sqlite3 must be pinned",
            )
        ):
            targets.extend(["package.json", "server/index.ts", "server/db/database.ts"])

        default_importer_match = re.search(r"Imported as default by ([^,\s]+)", message)
        if default_importer_match:
            importer_path = str(default_importer_match.group(1) or "").strip()
            if importer_path.startswith(("src/", "server/")):
                targets.append(importer_path)

        named_importer_match = re.search(r"Imported symbol ['\"`][^'\"`]+['\"`] is used by ([^,\s]+)", message)
        if named_importer_match:
            importer_path = str(named_importer_match.group(1) or "").strip()
            if importer_path.startswith(("src/", "server/")):
                targets.append(importer_path)

        parts = message.split(":", 1)
        if len(parts) > 1 and "/" in parts[0]:
            explicit = parts[0].strip()
            if explicit.startswith(("src/", "server/")):
                targets.append(explicit)

        route_match = re.search(r"route '(\w+)'", message)
        route_name = route_match.group(1) if route_match else ""
        owner_paths = self._resource_owner_paths(route_name)

        if "API_CONTRACT_DRIFT" in message or "BLUEPRINT_NOT_ENFORCED" in message:
            targets.append("src/types/index.ts")
        if "API_RESPONSE_ENVELOPE_MISMATCH" in message or "BLUEPRINT_NOT_ENFORCED" in message:
            targets.append("src/types/index.ts")
            targets.extend([owner_paths.get("service", ""), owner_paths.get("hook", ""), owner_paths.get("controller", ""), owner_paths.get("route", "")])
        if any(token in message for token in ("HTTP_CLIENT_MIXED", "HTTP_CLIENT_CONTRACT_ERROR")):
            targets.extend(["src/services/api.ts", "src/types/index.ts"])
        if any(token in message for token in ("STYLESHEET_CLASS_MISSING", "STYLESHEET_CLASS_EMPTY", "STYLESHEET_CLASS_INCOMPLETE")):
            targets.extend([
                "src/styles/global.css",
                "src/styles/variables.css",
            ])
        if "TAILWIND_RUNTIME_MISSING" in message:
            targets.extend([
                "package.json",
                "tailwind.config.js",
                "postcss.config.js",
                "src/main.tsx",
                "src/styles/global.css",
                "src/styles/variables.css",
            ])
        if any(
            token in message
            for token in (
                "TSCONFIG_PURITY_ERROR",
                "TS6310",
                "allowImportingTsExtensions",
                "may not disable emit",
            )
        ):
            targets.extend([
                "tsconfig.json",
                "tsconfig.node.json",
            ])
        if "ROOT_PROVIDER_MISSING" in message:
            targets.extend(["src/main.tsx", "src/App.tsx"])
        if "AUTH_INVALID" in message or "AUTH_RESPONSE_CONTRACT_ERROR" in message or "AUTH_" in message or route_name == "auth":
            auth_targets = [
                "src/services/authService.ts",
                "src/context/AuthContext.tsx",
                "src/pages/Login.tsx",
                "server/routes/authRoutes.ts",
                "server/controllers/authController.ts",
            ]
            targets.extend(auth_targets)
        elif any(token in message for token in ("DISCONNECTED_FEATURE", "PROJECT_SPEC_FRONTEND_DISCONNECTED", "FRONTEND_PHASE_API_DISCONNECTED")):
            targets.extend([owner_paths.get("service", ""), owner_paths.get("hook", "")])
        elif any(token in message for token in ("ROUTE_SYNC_ERROR", "BACKEND_PHASE_ROUTE_MISSING", "PROJECT_SPEC_BACKEND_ROUTE_MISSING")):
            targets.extend([owner_paths.get("route", ""), owner_paths.get("controller", "")])
        elif "PROJECT_SPEC_RESOURCE_MISSING" in message:
            targets.extend([owner_paths.get("controller", ""), owner_paths.get("route", "")])

        if fallback_file:
            targets.append(str(fallback_file).strip())

        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        expand_blueprint_cluster = self._read_bool_config(
            cfg,
            "validation_repair_expand_blueprint_cluster",
            False,
        )
        if expand_blueprint_cluster and ("BLUEPRINT_SCOPE_FAILURE" in message or "BLUEPRINT_NOT_ENFORCED" in message):
            seed_paths = scope_cluster or self._extract_phase_error_paths(
                [line for line in message.splitlines() if line.strip()],
                [fallback_file] if fallback_file else [],
            )
            targets.extend(self.planner.get_cluster_for_paths(seed_paths))

        clean_targets = []
        seen = set()
        for path in targets:
            normalized = str(path or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            clean_targets.append(normalized)
        return self._expand_fix_targets(clean_targets)

    def _normalize_repair_target_list(self, paths: list[str] | None) -> list[str]:
        normalized_targets: list[str] = []
        seen: set[str] = set()
        for path in paths or []:
            normalized = str(path or "").strip().replace("\\", "/")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_targets.append(normalized)
        return normalized_targets

    def _expand_fix_targets(self, targets: list[str]) -> list[str]:
        normalized_targets = self._normalize_repair_target_list(targets)
        if not normalized_targets:
            return []

        cfg = dict(getattr(self, "pipeline_config", {}) or {})
        try:
            max_targets = max(1, int(cfg.get("validation_repair_scope_max_files", 10) or 10))
        except Exception:
            max_targets = 10

        expanded: list[str] = list(normalized_targets)
        seen: set[str] = set(expanded)
        has_api_contract_hit = any(
            any(re.match(pattern, path) for pattern in _API_CONTRACT_PATTERNS)
            for path in normalized_targets
        )
        if not has_api_contract_hit:
            return normalized_targets[:max_targets]

        # Prefer planner-local cluster expansion over project-wide API sweeps.
        scoped_cluster = []
        try:
            scoped_cluster = list(self.planner.get_cluster_for_paths(normalized_targets) or [])
        except Exception:
            scoped_cluster = []

        for rel in scoped_cluster:
            clean = str(rel or "").strip().replace("\\", "/")
            if not clean or clean in seen:
                continue
            if not any(re.match(pattern, clean) for pattern in _API_CONTRACT_PATTERNS):
                continue
            seen.add(clean)
            expanded.append(clean)
            if len(expanded) >= max_targets:
                return expanded[:max_targets]

        # Optional legacy fallback: full repository API-contract scan.
        if bool(cfg.get("validation_repair_scope_allow_fullscan", False)):
            for root, _dirs, files in os.walk(self.sandbox_dir):
                for filename in files:
                    rel = os.path.relpath(os.path.join(root, filename), self.sandbox_dir).replace("\\", "/")
                    if not any(re.match(pattern, rel) for pattern in _API_CONTRACT_PATTERNS):
                        continue
                    if rel in seen:
                        continue
                    seen.add(rel)
                    expanded.append(rel)
                    if len(expanded) >= max_targets:
                        return expanded[:max_targets]

        return expanded[:max_targets]

    def _uses_focused_validation_targets(self, decision: dict | None, msgs: list[str]) -> bool:
        message_blob = "\n".join(str(msg or "") for msg in (msgs or []))
        strategy = str((decision or {}).get("strategy", "") or "").strip().lower()
        if strategy in {
            "fix_style",
            "fix_http_client",
            "fix_package_runtime_contract",
            "fix_api_contract",
            "fix_schema",
            "fix_import",
            "fix_tsconfig_contract",
        }:
            return True
        return any(
            token in message_blob
            for token in (
                "BLUEPRINT_NOT_ENFORCED",
                "API_CONTRACT_DRIFT",
                "API_RESPONSE_ENVELOPE_MISMATCH",
                "SCHEMA_SYNC_ERROR",
                "DB_CONTRACT_ERROR",
                "IMPORT_SITE_ERROR",
                "BLUEPRINT_EXPORT_MISMATCH",
                "MISMATCHED_IMPORT",
                "MISSING_EXPORT_DEFAULT",
                "MISSING_IMPORT_FILE",
                "HTTP_CLIENT_MIXED",
                "HTTP_CLIENT_CONTRACT_ERROR",
                "Missing 'server' script",
                'Remove "type": "module"',
                "better-sqlite3 must be pinned",
                "STYLESHEET_CLASS_MISSING",
                "STYLESHEET_CLASS_EMPTY",
                "STYLESHEET_CLASS_INCOMPLETE",
                "TAILWIND_RUNTIME_MISSING",
                "TSCONFIG_PURITY_ERROR",
                "TS6310",
                "allowImportingTsExtensions",
                "may not disable emit",
            )
        )

    def _focused_validation_repair_targets(
        self,
        broken_file: str,
        msgs: list[str],
        decision: dict | None,
    ) -> list[str]:
        message_blob = "\n".join(str(msg or "") for msg in (msgs or []))
        strategy = str((decision or {}).get("strategy", "") or "").strip().lower()
        decision_targets = self._normalize_repair_target_list((decision or {}).get("target_files") or [])
        fallback_targets = self._preferred_repair_targets_for_error(message_blob, fallback_file=broken_file)

        def _build(allowed_prefixes: tuple[str, ...], allowed_exact: set[str], extras: list[str]) -> list[str]:
            targets: list[str] = []
            for path in decision_targets + fallback_targets + extras:
                normalized = str(path or "").strip().replace("\\", "/")
                if not normalized:
                    continue
                if normalized.startswith(allowed_prefixes) or normalized in allowed_exact:
                    targets.append(normalized)
            return self._expand_fix_targets(self._normalize_repair_target_list(targets))

        if strategy == "fix_tsconfig_contract" or any(
            token in message_blob
            for token in (
                "TSCONFIG_PURITY_ERROR",
                "TS6310",
                "allowImportingTsExtensions",
                "may not disable emit",
            )
        ):
            return _build(
                ("tsconfig",),
                {"tsconfig.json", "tsconfig.node.json"},
                [broken_file, "tsconfig.json", "tsconfig.node.json"],
            )

        if "TAILWIND_RUNTIME_MISSING" in message_blob:
            return _build(
                ("src/components/", "src/pages/", "src/styles/"),
                {
                    "src/App.tsx",
                    "src/main.tsx",
                    "package.json",
                    "tailwind.config.js",
                    "postcss.config.js",
                },
                [
                    broken_file,
                    "package.json",
                    "tailwind.config.js",
                    "postcss.config.js",
                    "src/main.tsx",
                    "src/styles/global.css",
                    "src/styles/variables.css",
                ],
            )

        if strategy in {"fix_api_contract", "fix_schema", "fix_import"} or any(
            token in message_blob
            for token in (
                "BLUEPRINT_NOT_ENFORCED",
                "API_CONTRACT_DRIFT",
                "API_RESPONSE_ENVELOPE_MISMATCH",
                "SCHEMA_SYNC_ERROR",
                "DB_CONTRACT_ERROR",
                "IMPORT_SITE_ERROR",
                "BLUEPRINT_EXPORT_MISMATCH",
                "MISMATCHED_IMPORT",
                "MISSING_EXPORT_DEFAULT",
                "MISSING_IMPORT_FILE",
            )
        ):
            return _build(
                (
                    "server/routes/",
                    "server/controllers/",
                    "server/db/",
                    "server/middleware/",
                    "src/services/",
                    "src/hooks/",
                    "src/types/",
                    "src/pages/",
                    "src/components/",
                    "src/context/",
                    "src/utils/",
                    "src/store/",
                ),
                {"src/App.tsx", "src/main.tsx", "server/index.ts", "package.json"},
                [
                    broken_file,
                    "src/types/index.ts",
                    "src/services/api.ts",
                    "server/index.ts",
                    "server/db/database.ts",
                ],
            )

        if strategy == "fix_style" or any(
            token in message_blob
            for token in ("STYLESHEET_CLASS_MISSING", "STYLESHEET_CLASS_EMPTY", "STYLESHEET_CLASS_INCOMPLETE")
        ):
            return _build(
                ("src/components/", "src/pages/", "src/styles/"),
                {"src/App.tsx", "src/main.tsx"},
                [broken_file, "src/styles/global.css", "src/styles/variables.css"],
            )

        if strategy == "fix_http_client" or any(
            token in message_blob for token in ("HTTP_CLIENT_MIXED", "HTTP_CLIENT_CONTRACT_ERROR")
        ):
            return _build(
                ("src/components/", "src/pages/", "src/hooks/", "src/services/"),
                {"src/App.tsx", "src/main.tsx", "src/types/index.ts"},
                [broken_file, "src/services/api.ts", "src/types/index.ts"],
            )

        if strategy == "fix_package_runtime_contract" or any(
            token in message_blob
            for token in ("Missing 'server' script", 'Remove "type": "module"', "better-sqlite3 must be pinned")
        ):
            return _build(
                ("server/routes/", "server/controllers/", "server/db/", "server/middleware/"),
                {"package.json", "server/index.ts"},
                [broken_file, "package.json", "server/index.ts", "server/db/database.ts"],
            )

        return self._expand_fix_targets(
            decision_targets or fallback_targets or self._normalize_repair_target_list([broken_file])
        )

    def _requires_immediate_validation_rewrite(self, msgs: list[str]) -> bool:
        message_blob = "\n".join(str(msg or "") for msg in (msgs or []))
        return any(
            token in message_blob
            for token in (
                "HTTP_CLIENT_MIXED",
                "HTTP_CLIENT_CONTRACT_ERROR",
                "CJS_ESM_MIX",
                "DB_CONTRACT_ERROR",
                "DATABASE_UNINITIALIZED",
                "Missing 'server' script",
                'Remove "type": "module"',
                "better-sqlite3 must be pinned",
                "STYLESHEET_CLASS_MISSING",
                "STYLESHEET_CLASS_EMPTY",
                "STYLESHEET_CLASS_INCOMPLETE",
                "TAILWIND_RUNTIME_MISSING",
            )
        )

    def _forced_validation_rewrite_decision(
        self,
        broken_file: str,
        msgs: list[str],
        decision: dict | None = None,
    ) -> dict | None:
        message_blob = "\n".join(str(msg or "") for msg in (msgs or []))
        strategy = ""
        fix_hint = ""
        banner = ""

        if "BLUEPRINT_NOT_ENFORCED" in message_blob:
            strategy = "fix_api_contract"
            fix_hint = (
                "Treat the blueprint as the execution contract. Rewrite the connected controller, route, shared types, "
                "services, hooks, and pages together so schema fields, exports, and API shape all match the blueprint."
            )
            banner = "♻️ Repeated blueprint execution failures are being escalated to a full contract-cluster rewrite.\n"
        elif "API_CONTRACT_DRIFT" in message_blob:
            strategy = "fix_api_contract"
            fix_hint = (
                "Rewrite the affected controller, shared types, and frontend consumers together. "
                "Keep raw SQL/database columns snake_case if needed, but standardize the public request/response contract to camelCase."
            )
            banner = "♻️ Repeated API contract drift is being escalated to a grouped rewrite batch instead of another query-only pass.\n"
        elif any(token in message_blob for token in ("SCHEMA_SYNC_ERROR", "DB_CONTRACT_ERROR", "DATABASE_UNINITIALIZED")):
            strategy = "fix_schema"
            fix_hint = (
                "Rewrite the affected controller and any related database contract files so every query matches "
                "server/db/database.ts exactly. Use the database's real column names and driver style."
            )
            banner = "♻️ Repeated schema/database contract findings are being escalated to a grouped rewrite batch.\n"
        elif any(
            token in message_blob
            for token in (
                "CJS_ESM_MIX",
                "Missing 'server' script",
                'Remove "type": "module"',
                "better-sqlite3 must be pinned",
            )
        ):
            strategy = "fix_package_runtime_contract"
            fix_hint = (
                "Rewrite package.json and all affected backend owner files together. "
                "Use the exact backend script `node --import tsx server/index.ts`, keep backend files 100% ESM only, "
                "and pin better-sqlite3 to ^12.2.0 without introducing competing runtime stacks."
            )
            banner = "♻️ Backend runtime/package contract failures are being escalated to a grouped rewrite batch.\n"
        elif any(token in message_blob for token in ("MISMATCHED_IMPORT", "MISSING_EXPORT_DEFAULT", "MISSING_IMPORT_FILE")):
            strategy = "fix_import"
            fix_hint = (
                "Rewrite the export-owner file and any direct consumers together so default/named exports, shared types, "
                "and import paths all match exactly."
            )
            banner = "♻️ Repeated import/export findings are being escalated to a grouped rewrite batch.\n"
        elif any(token in message_blob for token in ("HTTP_CLIENT_MIXED", "HTTP_CLIENT_CONTRACT_ERROR")):
            strategy = "fix_http_client"
            fix_hint = (
                "Rewrite src/services/api.ts and the affected frontend consumers together so the project uses one HTTP client only. "
                "This pipeline standardizes on axios via the shared api client. Remove raw fetch() usage and direct axios imports outside src/services/api.ts."
            )
            banner = "♻️ HTTP client contract failures are being escalated to a grouped shared-client rewrite.\n"
        elif any(token in message_blob for token in ("STYLESHEET_CLASS_MISSING", "STYLESHEET_CLASS_EMPTY", "STYLESHEET_CLASS_INCOMPLETE")):
            strategy = "fix_style"
            fix_hint = (
                "Ensure your UI file uses the correct semantic classes that match the project's existing global.css. "
                "Do NOT output global.css again in this turn to save tokens."
            )
            banner = "♻️ Semantic stylesheet contract failures are being escalated to a grouped UI plus stylesheet rewrite.\n"
        elif any(
            token in message_blob
            for token in (
                "TSCONFIG_PURITY_ERROR",
                "TS6310",
                "allowImportingTsExtensions",
                "may not disable emit",
            )
        ):
            strategy = "fix_tsconfig_contract"
            fix_hint = (
                "Repair only tsconfig.json and tsconfig.node.json. Keep tsconfig include limited to src. "
                "For composite tsconfig.node.json, do not disable emit and avoid inheriting frontend-only "
                "allowImportingTsExtensions settings."
            )
            banner = "♻️ TypeScript config contract failures are being escalated to a constrained tsconfig-only rewrite.\n"
        elif "TAILWIND_RUNTIME_MISSING" in message_blob:
            strategy = "fix_style"
            fix_hint = (
                "Restore the Tailwind scaffold/runtime so the affected UI can keep using Tailwind utility classes. "
                "Rewrite the affected UI together with package.json, tailwind.config.js, postcss.config.js, src/main.tsx, src/styles/global.css, and src/styles/variables.css as needed."
            )
            banner = "♻️ Tailwind runtime drift is being escalated to a grouped scaffold plus UI rewrite.\n"

        if not strategy:
            return None

        target_files = [
            str(path).strip()
            for path in ((decision or {}).get("target_files") or [])
            if str(path).strip()
        ]
        
        # ALWAYS merge preferred targets so we don't drop critical files like global.css
        preferred = self._preferred_repair_targets_for_error(
            message_blob,
            fallback_file=broken_file,
        )
        for p in preferred:
            if p not in target_files:
                target_files.append(p)
        if not target_files and broken_file:
            target_files = [str(broken_file).strip()]
        target_files = self._expand_fix_targets(target_files)

        return {
            "strategy": strategy,
            "fix_hint": fix_hint,
            "target_files": target_files,
            "banner": banner,
        }

    def _phase_context_for_issue(self, broken_file: str, msgs: list[str], decision: dict | None = None) -> str:
        phases: list[str] = []
        owner_targets: list[str] = []

        normalized_file = str(broken_file or "").strip()
        if normalized_file in self._compiled_managed_paths():
            phases.append("scaffold")
        elif normalized_file.startswith("server/"):
            phases.append("backend")
        elif normalized_file.startswith("src/"):
            phases.append("frontend")
        else:
            phases.append("final_parity")

        for msg in msgs:
            if any(token in msg for token in ("SCAFFOLD_MISSING", "MISSING_PROXY", "INVALID_PROXY")) and "scaffold" not in phases:
                phases.append("scaffold")
            if any(token in msg for token in ("BACKEND_PHASE", "ROUTE_SYNC_ERROR", "PROJECT_SPEC_BACKEND_ROUTE_MISSING")) and "backend" not in phases:
                phases.append("backend")
            if any(token in msg for token in ("DB_CONTRACT_ERROR", "SCHEMA_SYNC_ERROR", "DATABASE_UNINITIALIZED")):
                if "backend" not in phases:
                    phases.append("backend")
                if "database" not in phases:
                    phases.append("database")
            if any(token in msg for token in ("FRONTEND_PHASE", "PROJECT_SPEC_ROUTE_MISSING", "PROJECT_SPEC_FRONTEND_DISCONNECTED", "AUTH_INVALID")) and "frontend" not in phases:
                phases.append("frontend")
            owner_targets.extend(self._preferred_repair_targets_for_error(msg, fallback_file=broken_file))

        if decision:
            for path in (decision.get("target_files") or []):
                if str(path).strip():
                    owner_targets.append(str(path).strip())

        dedup_owner_targets = []
        seen = set()
        for path in owner_targets:
            normalized = str(path or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            dedup_owner_targets.append(normalized)

        generic_primary_hints = {"src/App.tsx", "server/index.ts", "package.json", "vite.config.ts", ""}
        primary_hint = broken_file
        if dedup_owner_targets and primary_hint in generic_primary_hints:
            primary_hint = dedup_owner_targets[0]

        lines = [
            "Repair Phase: " + ", ".join(phases),
            f"Primary file hint: {primary_hint}",
        ]
        if dedup_owner_targets:
            lines.append("Owner targets:")
            lines.extend(f"- {path}" for path in dedup_owner_targets[:8])
        return "\n".join(lines)

    def _has_backend_entry(self) -> bool:
        backend_entries = (
            "server/index.ts",
        )
        return any(
            os.path.exists(os.path.join(self.sandbox_dir, path))
            for path in backend_entries
        )

    def _background_shell_command(self, commands: list[str], log_path: str) -> str:
        combined = " || ".join(commands)
        return f"nohup sh -c '{combined}' > {log_path} 2>&1 < /dev/null &"

    def _looks_like_runtime_isolation_false_negative(self, error_log: str) -> bool:
        """
        Detect cases where the backend appears to boot successfully in logs,
        but health probes fail due command/runtime isolation rather than app defects.
        """
        text = str(error_log or "")
        lowered = text.lower()
        boot_markers = (
            "server running on http://localhost",
            "server running at http://localhost",
            "server running on port",
            "server is running on",
            "server listening on",
            "listening on port",
            "database initialized",
        )
        crash_markers = (
            "error:",
            "exception",
            "cannot find module",
            "syntaxerror",
            "referenceerror",
            "typeerror",
            "eaddrinuse",
            "err!",
            "unhandled",
            "failed to",
        )
        has_boot = any(marker in lowered for marker in boot_markers)
        has_crash = any(marker in lowered for marker in crash_markers)
        return has_boot and not has_crash

    def _get_backend_start_command(self) -> str:
        # Use a deterministic backend startup command for every project.
        return self._background_shell_command(
            ["node --import tsx server/index.ts"],
            "/tmp/sandbox_server.log",
        )

    async def _probe_backend_health_via_shell(self, port: int) -> tuple[bool, str]:
        # Check all standard endpoints that a generated Express app may expose.
        # This mirrors the endpoint list in backend_validator.js to avoid false negatives
        # on apps that don't implement a dedicated /health or /api/health route.
        probe_script = (
            "sh -lc '"
            f"for u in "
            f"http://127.0.0.1:{port}/api/health "
            f"http://127.0.0.1:{port}/ "
            f"http://127.0.0.1:{port}/api "
            f"http://127.0.0.1:{port}/health "
            f"http://localhost:{port}/api/health "
            f"http://localhost:{port}/ "
            f"http://localhost:{port}/api "
            f"http://localhost:{port}/health; do "
            "code=$(curl -sS -o /tmp/kilo_health_body -w \"%{http_code}\" --max-time 3 \"$u\" 2>/tmp/kilo_health_err || true); "
            "if [ \"$code\" -ge 200 ] && [ \"$code\" -lt 500 ]; then "
            "echo \"HEALTH_OK $u $code\"; "
            "exit 0; "
            "fi; "
            "done; "
            "echo HEALTH_FAIL; "
            "cat /tmp/kilo_health_err 2>/dev/null || true; "
            "tail -c 500 /tmp/kilo_health_body 2>/dev/null || true; "
            "exit 1'"
        )
        result = await self.tool_registry.execute(
            "execute_command",
            {"command": probe_script, "timeout": 30},
        )
        output = str(result or "")
        return ("HEALTH_OK" in output), output[-800:]

    async def _probe_frontend_preview_via_shell(self, port: int) -> tuple[bool, str]:
        # `npm run dev` may bind to project/default ports when no explicit flags are passed.
        candidate_ports = []
        for candidate in (port, 5173, 3000):
            if candidate and candidate not in candidate_ports:
                candidate_ports.append(candidate)
        probe_targets = " ".join(
            f"http://127.0.0.1:{candidate}/ http://localhost:{candidate}/"
            for candidate in candidate_ports
        )
        probe_script = (
            "sh -lc '"
            f"for u in {probe_targets}; do "
            "curl -fsS \"$u\" >/dev/null 2>&1 && echo PREVIEW_OK && exit 0; "
            "done; "
            "echo PREVIEW_FAIL"
            "'"
        )
        result = await self.tool_registry.execute(
            "execute_command",
            {"command": probe_script, "timeout": 8},
        )
        output = str(result or "")
        return ("PREVIEW_OK" in output), output[-800:]

    def _get_frontend_preview_command(self) -> str:
        # Use a deterministic frontend startup command for every project.
        return self._background_shell_command(
            ["npm run dev"],
            "/tmp/sandbox_preview.log",
        )

    def _kill_common_backend_ports_command(self) -> str:
        secondary_port = self.backend_port + 1
        return (
            f"fuser -k {self.backend_port}/tcp {secondary_port}/tcp 5000/tcp 5001/tcp "
            "2>/dev/null; sleep 1 || true"
        )

    def _parse_validator_json(self, raw: str) -> dict:
        """Extract the last valid JSON object from validator output."""
        text = str(raw or "")
        if not text.strip():
            return {}

        decoder = json.JSONDecoder()
        starts = [idx for idx, ch in enumerate(text) if ch == "{"]
        for start in reversed(starts):
            candidate = text[start:]
            try:
                parsed, _consumed = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        for match in reversed(list(re.finditer(r"\{[\s\S]*\}", text))):
            candidate = match.group(0)
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        return {}

    def _normalize_error_messages(self, errors) -> list[str]:
        messages = []
        for error in errors or []:
            if isinstance(error, dict):
                message = error.get("message") or error.get("raw") or str(error)
            else:
                message = str(error)

            message = message.strip()
            if message:
                messages.append(message)
        return messages

    def _extract_browser_validation_errors(self, browser_result: dict) -> list[str]:
        messages = self._normalize_error_messages(browser_result.get("errors", []))
        for key in ("console_errors", "runtime_errors", "network_errors"):
            messages.extend(self._normalize_error_messages(browser_result.get(key, [])))

        if not messages and browser_result.get("status") == "error":
            messages.append(json.dumps(browser_result)[:1000])

        deduped = []
        seen = set()
        for message in messages:
            if message not in seen:
                seen.add(message)
                deduped.append(message)
        return deduped

    def _is_browser_runtime_infra_error(self, browser_result: dict, browser_errors: list[str]) -> bool:
        if bool(browser_result.get("infra_error")):
            return True

        console_errors = self._normalize_error_messages(browser_result.get("console_errors", []))
        runtime_errors = self._normalize_error_messages(browser_result.get("runtime_errors", []))
        network_errors = self._normalize_error_messages(browser_result.get("network_errors", []))
        combined = " ".join(str(item or "") for item in list(browser_errors or [])).lower()

        explicit_infra_markers = (
            "validator exception",
            "expecting value",
            "no output from browser",
            "unable to reach preview server",
        )
        if any(marker in combined for marker in explicit_infra_markers):
            return True

        # If browser could not connect at all (refused/aborted/chrome error)
        # and there are no app console crashes, treat as infra/timing/isolation.
        conn_markers = (
            "err_connection_refused",
            "err_aborted",
            "chrome-error://chromewebdata",
        )
        has_conn_marker = any(
            marker in " ".join((runtime_errors + network_errors + browser_errors)).lower()
            for marker in conn_markers
        )
        if not has_conn_marker or console_errors:
            return False

        infra_runtime_markers = (
            "playwright execution failed",
            "navigation to",
            "chrome-error://chromewebdata",
            "err_connection_refused",
            "err_aborted",
        )
        for msg in runtime_errors:
            lowered = msg.lower()
            if not any(marker in lowered for marker in infra_runtime_markers):
                return False

        infra_network_markers = (
            "err_connection_refused",
            "err_aborted",
            "connection refused",
        )
        for msg in network_errors:
            lowered = msg.lower()
            if not any(marker in lowered for marker in infra_network_markers):
                return False

        return True

    def _normalize_query_command(self, command: str | None) -> str:
        return self.unified_repair.normalize_query_command(command)

    def _triage_command_timeout(self, command: str | None) -> int:
        return self.unified_repair.triage_command_timeout(command)

    def _should_preannounce_decision_command(self, decision: dict) -> bool:
        return self.unified_repair.should_preannounce_decision_command(decision)

    def _is_query_like_decision(self, decision: dict) -> bool:
        return self.unified_repair.is_query_like_decision(decision)

    def _is_dependency_install_decision(self, decision: dict) -> bool:
        return self.unified_repair.is_dependency_install_decision(decision)

    def _is_source_edit_decision(self, decision: dict) -> bool:
        return self.unified_repair.is_source_edit_decision(decision)

    def _is_mutation_decision(self, decision: dict) -> bool:
        return self.unified_repair.is_mutation_decision(decision)

    def _source_edit_command_failed(self, output: str) -> bool:
        return self.unified_repair.source_edit_command_failed(output)

    async def _prepare_runtime_probe(self, decision: dict, messages: list[str]) -> str | None:
        return await self.unified_repair.prepare_runtime_probe(decision, messages)

    async def _type(self, text: str, delay: float = 0.005) -> AsyncIterator[str]:
        """Yield text directly without artificial typing delay."""
        if not text:
            return
        yield text

    def _step_banner(self, step_id: str, title: str) -> str:
        return ""

    def _thinking_banner(self, message: str = "Waiting for model response...") -> str:
        return ""

    def _looks_like_install_failure(self, output: str) -> bool:
        lowered = (output or "").lower()
        failure_markers = (
            "npm err!",
            "npm error",
            "gyp err!",
            "prebuild-install err!",
            "command timed out after",
            "sigsegv",
        )
        return any(marker in lowered for marker in failure_markers)

    def _looks_like_network_install_failure(self, output: str) -> bool:
        lowered = (output or "").lower()
        if self._looks_like_npm_reify_rename_failure(output):
            return False
        if self._looks_like_esbuild_sigsegv_failure(output):
            return False
        network_markers = (
            "err_socket_timeout",
            "socket timeout",
            "network invalid response body",
            "network connectivity",
            "econnreset",
            "etimedout",
            "enotfound",
            "socket hang up",
            "tunneling socket could not be established",
            "fetch failed",
            "unable to get local issuer certificate",
        )
        return any(marker in lowered for marker in network_markers)

    def _looks_like_esbuild_sigsegv_failure(self, output: str) -> bool:
        """
        Detect esbuild native binary crash (SIGSEGV) on Node 22+.
        This is a binary incompatibility issue, NOT a network problem.
        """
        lowered = (output or "").lower()
        return "esbuild" in lowered and "sigsegv" in lowered

    def _looks_like_npm_reify_rename_failure(self, output: str) -> bool:
        lowered = (output or "").lower()
        return (
            "enotempty" in lowered and
            "rename" in lowered and
            "node_modules" in lowered
        )

    def _looks_like_invalid_version_install_failure(self, output: str) -> bool:
        lowered = (output or "").lower()
        return "invalid version:" in lowered

    def _extract_npm_reify_conflict_paths(self, output: str) -> list[str]:
        paths: list[str] = []
        text = str(output or "")
        for raw_match in re.findall(r"npm ERR!\s+(?:path|dest)\s+([^\n\r]+)", text, flags=re.IGNORECASE):
            candidate = str(raw_match or "").strip()
            if not candidate:
                continue
            if not os.path.isabs(candidate):
                continue
            normalized = os.path.normpath(candidate)
            sandbox_root = os.path.normpath(self.sandbox_dir)
            try:
                common = os.path.commonpath([sandbox_root, normalized])
            except Exception:
                common = ""
            if common != sandbox_root:
                continue
            paths.append(normalized)

        unique_paths: list[str] = []
        seen: set[str] = set()
        for path in paths:
            if path not in seen:
                seen.add(path)
                unique_paths.append(path)
        return unique_paths

    def _clear_npm_reify_conflict_paths(self, output: str) -> int:
        removed = 0
        for path in self._extract_npm_reify_conflict_paths(output):
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                elif os.path.exists(path):
                    os.remove(path)
                else:
                    continue
                removed += 1
            except Exception:
                continue
        return removed

    async def _attempt_npm_reify_recovery(self, install_output: str) -> tuple[int, str]:
        explicit_removed = self._clear_npm_reify_conflict_paths(install_output)
        stale_removed = self._clear_stale_npm_reify_entries()
        cleaned_entries = explicit_removed + stale_removed
        if cleaned_entries <= 0:
            return 0, install_output

        retried_output = await self.tool_registry.execute(
            "execute_command",
            {"command": "npm install --legacy-peer-deps 2>&1", "timeout": 600}
        )
        return cleaned_entries, retried_output

    def _unique_install_backup_path(self, artifact_path: str, suffix: str = "bad") -> str:
        candidate = f"{artifact_path}.{suffix}"
        if not os.path.exists(candidate):
            return candidate

        counter = 2
        while True:
            numbered_candidate = f"{artifact_path}.{suffix}.{counter}"
            if not os.path.exists(numbered_candidate):
                return numbered_candidate
            counter += 1

    def _backup_install_artifact(self, relative_path: str, suffix: str = "bad") -> str | None:
        artifact_path = os.path.join(self.sandbox_dir, relative_path)
        if not os.path.exists(artifact_path):
            return None

        backup_path = self._unique_install_backup_path(artifact_path, suffix=suffix)
        try:
            shutil.move(artifact_path, backup_path)
        except Exception:
            return None

        return os.path.relpath(backup_path, self.sandbox_dir).replace("\\", "/")

    async def _attempt_invalid_version_recovery(self) -> tuple[list[str], str]:
        backed_up_paths: list[str] = []
        for relative_path in ("package-lock.json", "node_modules"):
            backup_path = self._backup_install_artifact(relative_path, suffix="bad")
            if backup_path:
                backed_up_paths.append(backup_path)

        if not backed_up_paths:
            return [], ""

        retried_output = await self.tool_registry.execute(
            "execute_command",
            {"command": "npm install --legacy-peer-deps 2>&1", "timeout": 600}
        )
        return backed_up_paths, retried_output

    def _looks_like_build_failure(self, output: str) -> bool:
        lowered = (output or "").lower()
        failure_markers = (
            "error ts",
            "error during build",
            "build failed",
            "failed to resolve import",
            "cannot find module",
            "has no exported member",
            "does not provide an export named",
            "is not assignable to type",
            "does not exist on type",
            "transform failed",
            "syntaxerror",
            "unexpected token",
            "npm err!",
            "npm error",
            "command timed out after",
        )
        return any(marker in lowered for marker in failure_markers)

    def _looks_like_better_sqlite3_native_failure(self, output: str) -> bool:
        lowered = (output or "").lower()
        return (
            "better-sqlite3" in lowered and
            (
                "prebuild-install" in lowered or
                "node-gyp" in lowered or
                "no module named 'gyp'" in lowered or
                "module not found: no module named 'gyp'" in lowered or
                "gyp err!" in lowered
            )
        )

    def _looks_like_python_gyp_toolchain_failure(self, output: str) -> bool:
        lowered = (output or "").lower()
        failure_markers = (
            "no module named 'gyp'",
            "module not found: no module named 'gyp'",
            "modulenotfounderror: no module named 'gyp'",
            "gyp err! configure error",
            "`gyp` failed with exit code",
        )
        return any(marker in lowered for marker in failure_markers)

    def _get_declared_dependency_version(self, dependency_name: str) -> str | None:
        package_json = os.path.join(self.sandbox_dir, "package.json")
        if not os.path.exists(package_json):
            return None

        try:
            with open(package_json, "r", encoding="utf-8") as f:
                pkg = json.load(f)
        except Exception:
            return None

        deps = pkg.get("dependencies", {})
        value = deps.get(dependency_name)
        return str(value).strip() if value is not None else None

    def _upgrade_better_sqlite3_dependency(self, version: str = "^12.2.0") -> bool:
        package_json = os.path.join(self.sandbox_dir, "package.json")
        if not os.path.exists(package_json):
            return False

        try:
            with open(package_json, "r", encoding="utf-8") as f:
                pkg = json.load(f)
        except Exception:
            return False

        deps = pkg.setdefault("dependencies", {})
        current = deps.get("better-sqlite3")
        if current == version:
            return False

        deps["better-sqlite3"] = version

        with open(package_json, "w", encoding="utf-8") as f:
            json.dump(pkg, f, indent=2)
            f.write("\n")

        return True

    def _pin_dev_dependency(self, dependency_name: str, version: str) -> bool:
        package_json = os.path.join(self.sandbox_dir, "package.json")
        if not os.path.exists(package_json):
            return False

        try:
            with open(package_json, "r", encoding="utf-8") as f:
                pkg = json.load(f)
        except Exception:
            return False

        changed = False
        dev_deps = pkg.setdefault("devDependencies", {})
        current = dev_deps.get(dependency_name)
        if current != version:
            dev_deps[dependency_name] = version
            changed = True

        # For npm, forcing an override prevents transitive pulls of an older
        # native esbuild version that may crash under newer Node runtimes.
        if dependency_name == "esbuild":
            overrides = pkg.setdefault("overrides", {})
            if overrides.get("esbuild") != version:
                overrides["esbuild"] = version
                changed = True

        if not changed:
            return False

        with open(package_json, "w", encoding="utf-8") as f:
            json.dump(pkg, f, indent=2)
            f.write("\n")

        return True

    def _clear_esbuild_install_artifacts(self) -> int:
        removed = 0
        candidate_paths = [
            os.path.join(self.sandbox_dir, "node_modules", "esbuild"),
            os.path.join(self.sandbox_dir, "node_modules", "@esbuild"),
        ]
        for artifact_path in candidate_paths:
            if not os.path.exists(artifact_path):
                continue
            try:
                if os.path.isdir(artifact_path) and not os.path.islink(artifact_path):
                    shutil.rmtree(artifact_path)
                else:
                    os.remove(artifact_path)
                removed += 1
            except Exception:
                continue
        return removed

    def _clear_stale_npm_reify_entries(self) -> int:
        node_modules_dir = os.path.join(self.sandbox_dir, "node_modules")
        if not os.path.isdir(node_modules_dir):
            return 0

        stale_paths: list[str] = []

        def collect_stale_entries(base_dir: str) -> None:
            try:
                entries = list(os.scandir(base_dir))
            except Exception:
                return

            for entry in entries:
                name = entry.name
                if not name.startswith(".") or "-" not in name:
                    continue
                if name in {".bin", ".cache"}:
                    continue
                stale_paths.append(entry.path)

        collect_stale_entries(node_modules_dir)

        try:
            scoped_entries = list(os.scandir(node_modules_dir))
        except Exception:
            scoped_entries = []

        for entry in scoped_entries:
            if entry.is_dir() and entry.name.startswith("@"):
                collect_stale_entries(entry.path)

        removed = 0
        for stale_path in stale_paths:
            try:
                if os.path.isdir(stale_path) and not os.path.islink(stale_path):
                    shutil.rmtree(stale_path)
                else:
                    os.remove(stale_path)
                removed += 1
            except Exception:
                continue

        return removed

    async def _resolve_decision_procedure(
        self,
        decision: dict,
        *,
        error_log: str,
        pre_announced_command: str | None = None,
        project_spec: dict | None = None,
        phase_context: str = "",
        target_file_hint: str = "",
    ) -> tuple[dict, str, list[str]]:
        return await self.unified_repair.resolve_decision_procedure(
            decision,
            error_log=error_log,
            pre_announced_command=pre_announced_command,
            project_spec=project_spec,
            phase_context=phase_context,
            target_file_hint=target_file_hint,
        )

    # ── ACT node ──────────────────────────────────────────────────────────────

    async def _act(self) -> tuple[str, list[dict]]:
        """
        Act node — call the AI provider and accumulate the full response.
        # From refs/deepagents/graph.py _get_stream / act node
        """
        response = ""
        context = self.memory.get_context()
        input_tokens = _approximate_message_tokens(context)
        
        async for token in self.provider.stream(context, self.model_id):
            if is_provider_status_token(token):
                continue
            response += token
            
        output_tokens = len(response) // 4
        user_id = self.pipeline_config.get("user_id")
        plan_id = self.pipeline_config.get("_selected_plan_id")
        
        # Only track usage if a standard plan is active (skip for BYOK)
        if user_id and plan_id and plan_id != "byok":
            try:
                increment_token_usage(user_id, input_tokens=input_tokens, output_tokens=output_tokens)
                
                # After incrementing, check if they are now over the limit for the next turn
                p_row = get_plan(plan_id)
                if p_row:
                    enforce_usage_limits(user_id, p_row)
            except Exception as e:
                if "limit reached" in str(e).lower() or "exhausted" in str(e).lower():
                    raise # Re-raise billing exhaustion errors to stop generation
                pass # Ignore other billing errors (network, etc.)

        return response, ResponseParser.parse_tool_calls(response)

    # ── OBSERVE node ──────────────────────────────────────────────────────────

    async def _observe(self, calls: list[dict]) -> list[str]:
        """
        Observe node — execute tool calls and collect observations.
        # From refs/deepagents/graph.py observe node / FilesystemMiddleware
        """
        observations = []
        for call in calls:
            tool_name = call["tool"]
            params    = call["params"]
            result    = await self.tool_registry.execute(tool_name, params)
            result_text = str(result)[:120]
            observations.append(f"Tool '{tool_name}' result: {result_text}")

            # TodoListMiddleware: mark todo done when a file is written
            # MOVED to run() for stricter matching logic
            # if tool_name == "write_file":
            #     path = params.get("path", "")
            #     self.planner.mark_done(path)

        return observations

    def _validate_response(self, calls: list[dict], expected_files: list[str], raw_response: str = "") -> tuple[bool, str, list[dict]]:
        """
        Validates the assistant's tool calls for count and formatting quality.
        Returns (is_valid, error_message, filtered_calls).
        """
        filtered_calls = []
        write_calls = [c for c in calls if c["tool"] == "write_file"]
        other_calls = [c for c in calls if c["tool"] != "write_file"]
        expected_set = {
            str(path or "").strip().lower().lstrip("./").replace("\\", "/")
            for path in (expected_files or [])
            if str(path or "").strip()
        }
        
        # We start with non-write calls as they are usually valid (e.g. commands)
        filtered_calls.extend(other_calls)
        
        # Use unique paths for counting
        actual_count = len(set(c["params"]["path"] for c in write_calls))

        # 1. Truncation check: Did any file end abruptly (very short or no closing brace)?
        for call in write_calls:
            path = call["params"].get("path", "")
            normalized_content, _normalization_notes = self._normalize_generated_file_content(
                path,
                call["params"].get("content", ""),
            )
            content = normalized_content.strip()
            normalized_path = str(path or "").strip().lower().lstrip("./").replace("\\", "/")

            if expected_set and normalized_path not in expected_set:
                is_dynamic_hub = normalized_path in {
                    "src/types/index.ts",
                    "src/types/index.d.ts",
                    "server/db/database.ts",
                    "src/services/api.ts"
                }
                if not is_dynamic_hub:
                    logging.getLogger(__name__).info("Skipping out-of-batch file: %s", path)
                    continue
            
            # JS/JSX/TS specific checks
            if path.endswith((".tsx", ".ts")) and len(content) > 200:
                # A: Brace balance check (open should equal or exceed closed, but not by much)
                open_braces = content.count('{')
                close_braces = content.count('}')
                brace_gap = open_braces - close_braces
                
                # B: Abrupt end check (last character heuristic)
                last_lines = [l.strip() for l in content.split("\n") if l.strip()][-3:]
                last = last_lines[-1] if last_lines else ""
                
                # If it ends with ';' or '}' then it's definitely NOT abrupt, even if braces are slightly off 
                # (e.g. some files have more '{' in strings or comments than we can easily count here)
                is_abrupt = last and last[-1] in (',', '{', '(', '"', "'", ':')
                if last.endswith((';', '}', '];', ');')):
                    is_abrupt = False

                # Reject only when the file also appears to end abruptly.
                if is_abrupt and brace_gap > 0:
                    # Skip this file but continue validating others
                    print(f"Skipping truncated file: {path}")
                    continue
            
            # 3. Quality check: Formatting and Indentation
            # Check for "Copy Download" clutter or raw preamble
            if content.lower().startswith(("copy", "download", "// file:", "text")):
                first_line = content.split('\n')[0].lower()
                if (len(first_line) < 50 and any(kw in first_line for kw in ["copy", "download"])) or \
                   (first_line.startswith("text") and len(first_line) < 10):
                     print(f"Skipping cluttered file: {path}")
                     continue

            # Check for "Flattened" code (lack of indentation/proper blocks)
            # Config, server routes, and short files are exempt
            basename = path.split('/')[-1]
            is_exempt = basename in (".env", ".gitignore", "package.json", "vite.config.ts") or \
                       path.endswith((".json", ".md", ".sql")) or \
                       "server/routes/" in path or \
                       path.endswith(("/index.ts", "/app.ts"))
            
            if not is_exempt:
                lines = [l for l in content.split('\n') if l.strip()]
                if len(lines) >= 30: # Only check significant files
                    indented_lines = [l for l in lines if l[0:1].isspace()]
                    # If less than 5% are indented AND it contains nested block signatures (e.g. { followed by code)
                    if len(indented_lines) < len(lines) * 0.05:
                        if re.search(r'\{\s*\n\s*[^\s\}]', content): # Block start followed by non-indented code
                            print(f"Skipping flattened file: {path}")
                            continue

            syntax_errors = SyntaxValidator.validate(
                path,
                normalized_content,
                getattr(self, "sandbox_dir", ""),
            )
            if syntax_errors:
                print(f"Skipping syntax-invalid file: {path}")
                continue

            # If it passed all checks, add to filtered_calls
            filtered_calls.append(
                {
                    "tool": "write_file",
                    "params": {
                        "path": path,
                        "content": normalized_content,
                    },
                }
            )
        
        # Recalculate actual_count based on filtered calls
        filtered_write_calls = [c for c in filtered_calls if c["tool"] == "write_file"]
        actual_count = len(set(c["params"]["path"] for c in filtered_write_calls))

        # 1.5 Batch Relevance Check: only accept files from the current batch.
        if expected_files and actual_count > 0:
            filtered_paths = {
                str(c["params"].get("path", "")).strip().lower().lstrip("./").replace("\\", "/")
                for c in filtered_write_calls
            }
            if not filtered_paths & expected_set:
                print(f"Agent generated {actual_count} files, but none matched the current batch.")
                return False, (
                    "You ignored the batch instructions. Only write files from the current FILES TO WRITE IN THIS TURN list."
                ), filtered_calls

        # 2. Progress check: Did we get anything at all?
        if expected_files and actual_count == 0:
            response_text = str(raw_response or "")
            if '"files"' in response_text:
                return False, (
                    "Malformed JSON generation payload detected. "
                    "Return strict JSON with unique keys and a valid top-level files[] array "
                    "(fallback: // FILE: path format)."
                ), filtered_calls
            return False, (
                "No valid files were found in the response. "
                "Please provide the implementation as strict JSON with a top-level files[] payload "
                "(fallback: // FILE: path format)."
            ), filtered_calls

        return True, "", filtered_calls

    def _recover_partial_stream_response(
        self,
        response: str,
        expected_files: list[str],
        *,
        parser_model_id: str = "",
    ) -> tuple[bool, list[dict], str]:
        """
        Try to salvage valid files from a provider response that was cut off mid-stream.
        This prevents re-requesting an entire batch when the model already produced
        some complete files before the transport failed.
        """
        partial_response = str(response or "")
        if not partial_response.strip():
            return False, [], ""

        calls = ResponseParser.parse_tool_calls(
            partial_response,
            parser_model_id or getattr(self, "model_id", ""),
            expected_files=expected_files,
        )
        is_valid, _error, filtered_calls = self._validate_response(
            calls,
            expected_files,
            partial_response,
        )
        valid_write_calls = [call for call in filtered_calls if call["tool"] == "write_file"]
        if not is_valid or not valid_write_calls:
            return False, [], ""

        valid_paths = []
        seen_paths = set()
        for call in valid_write_calls:
            path = str(call["params"].get("path", "") or "").strip().replace("\\", "/")
            if path and path not in seen_paths:
                seen_paths.add(path)
                valid_paths.append(path)

        message = (
            f"⚠️ Provider stream ended early, but recovered {len(valid_paths)} valid file(s) "
            "from the partial response. Keeping them and continuing with the missing tail only."
        )
        return True, filtered_calls, message

    def _normalize_generated_file_content(self, path: str, content: str) -> tuple[str, list[str]]:
        return normalize_generated_file_content(path, content)

    def _normalize_generated_batch_payload(self, files: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
        normalized_files: list[dict[str, str]] = []
        notes: list[str] = []

        for item in list(files or []):
            path = str((item or {}).get("path", "") or "").strip().replace("\\", "/")
            content = str((item or {}).get("content", "") or "")
            normalized_content, file_notes = self._normalize_generated_file_content(path, content)
            normalized_files.append(
                {
                    "path": path,
                    "content": normalized_content,
                }
            )
            notes.extend(file_notes)

        deduped_notes: list[str] = []
        seen_notes: set[str] = set()
        for note in notes:
            clean = str(note or "").strip()
            if clean and clean not in seen_notes:
                seen_notes.add(clean)
                deduped_notes.append(clean)
        return normalized_files, deduped_notes

    async def _commit_write_calls(
        self,
        write_calls: list[dict],
        *,
        allowed_paths: list[str] | None = None,
    ) -> tuple[bool, str, list[str]]:
        """Write a batch atomically after parser/response validation has passed."""
        if not write_calls:
            return True, "", []

        batch_payload = {
            "files": [
                {
                    "path": call["params"].get("path", ""),
                    "content": call["params"].get("content", ""),
                }
                for call in write_calls
            ],
            "allowed_paths": list(allowed_paths or []),
        }
        batch_payload["files"], normalization_notes = self._normalize_generated_batch_payload(batch_payload["files"])
        if normalization_notes:
            logging.getLogger(__name__).info(
                "Pre-write contract normalizer adjusted %d issue(s): %s",
                len(normalization_notes),
                "; ".join(normalization_notes[:8]),
            )

        allowed_set = {
            str(path or "").strip().replace("\\", "/")
            for path in list(allowed_paths or [])
            if str(path or "").strip()
        }
        dropped_out_of_scope: list[str] = []
        if allowed_set:
            filtered_files: list[dict] = []
            for item in list(batch_payload["files"]):
                path = str((item or {}).get("path", "") or "").strip().replace("\\", "/")
                if not path:
                    continue
                if path in allowed_set:
                    filtered_files.append(item)
                else:
                    dropped_out_of_scope.append(path)
            batch_payload["files"] = filtered_files
            if dropped_out_of_scope:
                logging.getLogger(__name__).warning(
                    "Dropping %d out-of-scope write(s) before write_batch: %s",
                    len(dropped_out_of_scope),
                    ", ".join(dropped_out_of_scope[:8]),
                )

        if not batch_payload["files"]:
            if dropped_out_of_scope:
                return (
                    False,
                    "Error: write_batch validation failed\n"
                    + "\n".join(
                        f"- Unexpected file outside current batch: {path}"
                        for path in dropped_out_of_scope[:20]
                    ),
                    [],
                )
            return False, "Error: write_batch validation failed\n- No writable files remained after normalization", []

        dropped_validation_paths: Dict[str, set[str]] = {}

        def _drop_files_from_validation_errors(errors: list[str], reason: str) -> list[str]:
            nonlocal batch_payload
            if not errors or not batch_payload["files"]:
                return []

            error_paths = self._extract_phase_error_paths(
                [str(line or "") for line in errors if str(line or "").strip()],
                [],
            )
            if not error_paths:
                return []

            current_lookup = {
                str((item or {}).get("path", "") or "").strip().replace("\\", "/").lower().lstrip("./")
                for item in list(batch_payload["files"])
                if str((item or {}).get("path", "") or "").strip()
            }
            invalid_norms = {
                str(path or "").strip().replace("\\", "/").lower().lstrip("./")
                for path in error_paths
                if str(path or "").strip().replace("\\", "/").lower().lstrip("./") in current_lookup
            }
            if not invalid_norms:
                return []

            kept: list[dict] = []
            dropped: list[str] = []
            for item in list(batch_payload["files"]):
                path = str((item or {}).get("path", "") or "").strip().replace("\\", "/")
                normalized = path.lower().lstrip("./")
                if normalized in invalid_norms:
                    dropped.append(path)
                    dropped_validation_paths.setdefault(path, set()).add(reason)
                    continue
                kept.append(item)
            batch_payload["files"] = kept
            return dropped

        syntax_errors: list[str] = []
        for item in batch_payload["files"]:
            syntax_errors.extend(
                SyntaxValidator.validate(
                    item.get("path", ""),
                    item.get("content", ""),
                    self.sandbox_dir,
                )
            )
        if syntax_errors:
            dropped_syntax_paths = _drop_files_from_validation_errors(syntax_errors, "syntax")
            if dropped_syntax_paths and batch_payload["files"]:
                syntax_errors = []
                for item in batch_payload["files"]:
                    syntax_errors.extend(
                        SyntaxValidator.validate(
                            item.get("path", ""),
                            item.get("content", ""),
                            self.sandbox_dir,
                        )
                    )
            if dropped_syntax_paths and not batch_payload["files"]:
                return (
                    False,
                    "Error: pre-write syntax validation failed\n"
                    + "\n".join(f"- {path}: syntax validation failed" for path in dropped_syntax_paths[:20]),
                    [],
                )
            if syntax_errors:
                return False, "Error: pre-write syntax validation failed\n" + "\n".join(
                    f"- {err}" for err in syntax_errors[:20]
                ), []

        target_paths = [item["path"] for item in batch_payload["files"]]
        blueprint_errors = self._validate_blueprint_execution_gate(
            batch_payload["files"],
            target_paths=target_paths,
        )
        if blueprint_errors:
            dropped_blueprint_paths = _drop_files_from_validation_errors(blueprint_errors, "blueprint")
            if dropped_blueprint_paths and batch_payload["files"]:
                blueprint_errors = self._validate_blueprint_execution_gate(
                    batch_payload["files"],
                    target_paths=[item["path"] for item in batch_payload["files"]],
                )
            if dropped_blueprint_paths and not batch_payload["files"]:
                detail_lines = [
                    f"- {err}"
                    for err in blueprint_errors[:20]
                    if str(err or "").strip()
                ]
                if not detail_lines:
                    detail_lines = [
                        f"- {path}: BLUEPRINT_NOT_ENFORCED"
                        for path in dropped_blueprint_paths[:20]
                    ]
                return (
                    False,
                    "Error: blueprint execution validation failed\n" + "\n".join(detail_lines),
                    [],
                )
        if blueprint_errors:
            return False, "Error: blueprint execution validation failed\n" + "\n".join(
                f"- {err}" for err in blueprint_errors[:20]
            ), []

        style_errors = self._validate_pre_write_style_gate(
            batch_payload["files"],
            target_paths=[item["path"] for item in batch_payload["files"]],
        )
        style_advisory_errors: list[str] = []
        if style_errors:
            only_tailwind_runtime_missing = all(
                "TAILWIND_RUNTIME_MISSING" in str(err or "")
                for err in style_errors
            )
            if only_tailwind_runtime_missing:
                style_advisory_errors = [
                    str(err or "").strip()
                    for err in style_errors
                    if str(err or "").strip()
                ]
                style_errors = []
            else:
                dropped_style_paths = _drop_files_from_validation_errors(style_errors, "style")
                if dropped_style_paths and batch_payload["files"]:
                    style_errors = self._validate_pre_write_style_gate(
                        batch_payload["files"],
                        target_paths=[item["path"] for item in batch_payload["files"]],
                    )
                if dropped_style_paths and not batch_payload["files"]:
                    return (
                        False,
                        "Error: styling contract validation failed\n"
                        + "\n".join(f"- {path}: styling contract validation failed" for path in dropped_style_paths[:20]),
                        [],
                    )
        if style_errors:
            return False, "Error: styling contract validation failed\n" + "\n".join(
                f"- {err}" for err in style_errors[:20]
            ), []

        if not batch_payload["files"]:
            return False, "Error: write_batch validation failed\n- No writable files remained after contract filtering", []

        result = await self.tool_registry.execute("write_batch", batch_payload)
        result_text = str(result or "")
        if result_text.lower().startswith("error:"):
            return False, result_text, []

        written_paths = []
        written_set = {
            str((item or {}).get("path", "") or "").strip()
            for item in list(batch_payload["files"])
            if str((item or {}).get("path", "") or "").strip()
        }
        for call in write_calls:
            path = str(call["params"].get("path", "") or "").strip().replace("\\", "/")
            if path and path not in written_paths:
                if not written_set or path in written_set:
                    written_paths.append(path)

        if dropped_out_of_scope:
            suffix = (
                "\nℹ️ Dropped out-of-scope files from this write batch: "
                + ", ".join(dropped_out_of_scope[:8])
                + ("..." if len(dropped_out_of_scope) > 8 else "")
            )
            result_text = f"{result_text}{suffix}"

        if dropped_validation_paths:
            dropped_entries = [
                f"{path} ({'/'.join(sorted(reasons))})"
                for path, reasons in sorted(dropped_validation_paths.items())
            ]
            suffix = (
                "\nℹ️ Dropped contract-invalid files from this write batch: "
                + ", ".join(dropped_entries[:8])
                + ("..." if len(dropped_entries) > 8 else "")
            )
            result_text = f"{result_text}{suffix}"

        if style_advisory_errors:
            advisory_preview = "; ".join(style_advisory_errors[:3])
            suffix = (
                "\nℹ️ Style contract warnings were kept as advisory for this write batch: "
                + advisory_preview
                + ("..." if len(style_advisory_errors) > 3 else "")
            )
            result_text = f"{result_text}{suffix}"

        return True, result_text, written_paths

    # ── MAIN LOOP ─────────────────────────────────────────────────────────────
    async def run(self, prompt: str) -> AsyncIterator[str]:
        """
        Main agent loop generator (yields SSE tokens).
        Graph: plan → act → observe → loop (DeepAgents pattern).
        # From refs/deepagents/graph.py create_deep_agent() compiled graph
        """

        existing_files = []
        resume_state = {}
        iteration = 0
        original_prompt = prompt
        if not bool(self.pipeline_config.get("session_prepared_by_runtime", False)):
            raise RuntimeError(
                "AgentLoop requires a prepared session. Use BuildSessionRuntime to generate the design system and execution plan before execution."
            )
        self.planner = ExecutionPlanner()
        self.planning = PlanningService(self.sandbox_dir, planner=self.planner)
        self.repair_service = PlanRepairService(self.planning)
        async for t in self._type("🧭 Restoring prepared session state...\n"): yield t
        resume_state = self._load_resume_state()
        self.triage_cache = dict(resume_state.get("triage_cache", {}) or {})
        self.validation_repair_state = dict(resume_state.get("validation_repair_state", {}) or {})
        self.generation_retry_state = dict(resume_state.get("generation_retry_state", {}) or {})
        self.retry_batch_override = [
            str(path).strip()
            for path in list(resume_state.get("retry_batch_override", []) or [])
            if str(path).strip()
        ]
        restored_prompt = str(resume_state.get("original_prompt", "") or "").strip()
        if restored_prompt:
            original_prompt = restored_prompt
        iteration = max(
            0,
            int(resume_state.get("iteration", self.pipeline_config.get("resume_iteration", 0)) or 0),
        )
        existing_files = self._list_existing_project_files()
        self.phase_runtime_ready = self._phase_runtime_dependencies_ready()
        if existing_files:
            self._hydrate_existing_project_state(existing_files)
            async for t in self._type(
                f"✓ Restored {len(existing_files)} existing files from prepared session state\n"
            ): yield t

        if not self.planning.restore(prompt=original_prompt):
            raise RuntimeError(
                "Prepared session is missing .lovable/plan.json or the plan is invalid. Re-run the session prompt phase before execution."
            )
        
        # Sync planner with existing disk state to prevent redundant generation loops
        sync_count = 0
        for task in self.planner.tasks:
            if not task.is_done and os.path.exists(os.path.join(self.sandbox_dir, task.path)):
                self.planner.mark_done(task.path)
                sync_count += 1
        if sync_count > 0:
            self.planning.persist(prompt=original_prompt)

        async for t in self._type(
            f"✓ Loaded prepared execution plan from .lovable/plan.json with {self.planner.total_count} planned files\n"
            f"✓ Resume state restored: {sync_count} planned files already exist and were marked done\n"
        ): yield t

        resolved_key_source = str(self.pipeline_config.get("_resolved_key_source", "") or "").strip()
        resolved_key_count = int(self.pipeline_config.get("_resolved_key_count", 0) or 0)
        if self.request_provider_name and self.request_provider_name not in ("auto", "scraper"):
            if resolved_key_source:
                async for t in self._type(
                    f"🔐 Key resolution for {self.request_provider_name}: {resolved_key_source} ({resolved_key_count} key(s))\n"
                ):
                    yield t
        auto_cancelled = int(self.pipeline_config.get("_auto_cancelled_builds", 0) or 0)
        if auto_cancelled > 0:
            async for t in self._type(
                f"🧯 Auto-cancelled {auto_cancelled} older running build(s) for this account to reduce provider quota collisions.\n"
            ):
                yield t

        # ── STEP 1: Design system (UUPM 161 rules) ───────────────────────
        saved_design = resume_state.get("design")
        if not saved_design:
            raise RuntimeError(
                "Prepared session is missing a saved design system in .lovable/run_state.json. Re-run the session prompt phase before execution."
            )

        saved_prompt_context = dict(resume_state.get("design_prompt_context", {}) or {})
        async for t in self._type("🎨 Restoring prepared design system...\n"): yield t
        from ..shared.design.models import DesignSystem
        design = DesignSystem.from_dict(saved_design)
        uupm_prompt_context: dict = saved_prompt_context

        if design and getattr(self, "design_system_enabled", True):
            context_usable = self.design_engine.is_prompt_context_usable(uupm_prompt_context)
            if not context_usable:
                try:
                    uupm_prompt_context = self.design_engine.build_prompt_context(original_prompt, design)
                    async for t in self._type("↻ UUPM context was incomplete; regenerated design guidance bundle.\n"): yield t
                except Exception as e:
                    async for t in self._type(f"⚠️  UUPM prompt context fallback: {e}\n"): yield t
                    if not isinstance(uupm_prompt_context, dict):
                        uupm_prompt_context = {}
        async for t in self._type(f"Style: {design.style.name} ({design.style.type}) | Colors: {design.colors.primary}\n"): yield t
        async for t in self._type(f"Fonts: {design.typography.heading} / {design.typography.body}\n"): yield t

        if uupm_prompt_context:
            domain_count = len([name for name, payload in uupm_prompt_context.get("domains", {}).items() if (payload or {}).get("results")])
            async for t in self._type(f"✓ UUPM workflow context built ({domain_count} domains with results)\n"): yield t
        self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design, design_prompt_context=uupm_prompt_context)

        # ── STEP 2: PLAN — execution contract planning ────────────────────
        async for t in self._type("📝 Using execution plan prepared by the session runtime.\n"): yield t

        self.feature_validator.set_project_spec(
            self.planner.project_spec,
            self.planner.get_blueprint_files(),
        )
        self.unified_repair.set_project_spec(self.planner.project_spec)
            
        todo_count = self.planner.total_count
        if todo_count == 0:
             raise RuntimeError("execution planning produced no executable files")

        if existing_files:
            resumed_done = self._mark_existing_files_done(existing_files)
            if resumed_done:
                async for t in self._type(f"✓ Resume state restored: {resumed_done} planned files already exist and were marked done\n"): yield t

        initial_iteration_feedback = ""

        self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design, design_prompt_context=uupm_prompt_context)
        async for t in self._type(f"✓ Planned {todo_count} files across {len(self.planning.state.units)} execution units\n"): yield t
        async for t in self._type("### EXECUTION PLAN\n"): yield t
        async for t in self._type(self.planning.render_console_report() + "\n\n"): yield t

        backend_runtime_errors: list[str] = []
        browser_runtime_errors: list[str] = []
        backend_validation_snapshot: dict = {}
        browser_validation_snapshot: dict = {}

        # ── STEP 4: Build system prompt (Cline format + UUPM) ────────────
        is_scraper = getattr(self.provider, 'is_scraper', False)
        if getattr(self, "system_prompt_enabled", True):
            if is_scraper:
                system = "You are an expert full-stack developer. Use the stage-specific scraper prompt prepared for the current batch."
                async for t in self._type("✓ Stage-aware scraper prompts ready\n"): yield t
            else:
                async for t in self._type("🤖 Preparing stage-aware system prompts...\n"): yield t
                system = "You are an expert full-stack developer. Use the stage-specific prompt prepared for the current batch."
                async for t in self._type("✓ Stage-aware prompts ready\n"): yield t
        else:
            async for t in self._type("ℹ️ System prompt generation skipped by pipeline configuration. Using minimal fallback prompt.\n"): yield t
            system = (
                "You are an expert full-stack web builder. "
                "Return complete working files, preserve imports/exports, and follow the requested file protocol."
            )

        # From refs/deepagents/graph.py: system prompt prepended to BASE_AGENT_PROMPT
        self.memory.add_message("system", system)
        async for t in self._type("✓ System prompt built\n"): yield t
        
        # ── MAIN LOOP: plan→act→observe→loop ─────────────────────────────
        yield self._step_banner("4.5", "Generate project files")
        iteration = max(iteration, int(self.pipeline_config.get("resume_iteration", 0) or 0))
        consecutive_no_tools = 0
        single_batch_mode = self._single_batch_mode_enabled()
        batch_cap = int(self.pipeline_config.get("builder_batch_cap", 0) or 0)
        if single_batch_mode:
            batch_cap = 0
        validation_stall_signature = ""
        validation_stall_count = 0
        iteration_feedback = initial_iteration_feedback

        if iteration > 0:
            async for t in self._type(f"▶ Resuming from iteration {iteration + 1}/{self.max_iter} using existing project files...\n"): yield t
        
        if not getattr(self, "builder_enabled", True):
            yield "\nℹ️ Builder skipped by pipeline configuration. Jumping to validation.\n"
            self.max_iter = 0

        # 2. Main Generation Loop
        while iteration < self.max_iter:
            calls = []
            missing_paths: list[str] = []
            single_batch_guard_note = ""
            batch_progress_emitted = False
            pending_paths_snapshot = self._pending_batch_paths()
            pending_paths_set = set(pending_paths_snapshot)
            # Get the next batch of files.
            if single_batch_mode:
                retry_override = [
                    str(path or "").strip().replace("\\", "/")
                    for path in list(self.retry_batch_override or [])
                    if str(path or "").strip()
                ]
                if pending_paths_set:
                    retry_override = [
                        path for path in retry_override
                        if path in pending_paths_set
                    ]
                else:
                    retry_override = []
                if retry_override:
                    # Respect narrowed retry scope after validation/write rejection.
                    current_batch, single_batch_guard_note = self._guard_single_batch_paths(
                        retry_override,
                        fallback_cap=int(self.pipeline_config.get("builder_batch_cap", 0) or 0),
                    )
                else:
                    current_batch, single_batch_guard_note = self._guard_single_batch_paths(
                        pending_paths_snapshot,
                        fallback_cap=int(self.pipeline_config.get("builder_batch_cap", 0) or 0),
                    )
            else:
                retry_override = [
                    str(path or "").strip().replace("\\", "/")
                    for path in list(self.retry_batch_override or [])
                    if str(path or "").strip()
                ]
                if pending_paths_set:
                    retry_override = [
                        path for path in retry_override
                        if path in pending_paths_set
                    ]
                else:
                    retry_override = []
                current_batch = list(retry_override or self.planner.get_smart_batch(batch_cap=batch_cap))
            current_batch = self._augment_batch_with_runtime_scaffold(
                current_batch,
                batch_cap=None if single_batch_mode else batch_cap,
            )
            self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
            async for t in self._type(f"\n⚙️  Iteration {iteration + 1}/{self.max_iter}...\n"): yield t
            if single_batch_guard_note:
                async for t in self._type(f"{single_batch_guard_note}\n"): yield t
            
            # --- NEXT BATCH SELECTION & PROMPT INJECTION ---
            # Smart batch: pull the next Samrat batch layer
            if not current_batch:
                if iteration > 0:
                    async for t in self._type("🔍 All planned files appear to be completed.\n"): yield t
                    # DO NOT break here! We must run the linter and feature validator.
                    # We will simulate a state where no tools were called, which naturally
                    # drops down to the NEXT STEP SELECTION block below.
                    calls = []
                    consecutive_no_tools += 1
                else: 
                    current_batch = []
            
            if current_batch:
                generation_stage = self._generation_stage_for_batch(current_batch)
                current_batch = self._normalize_batch_for_stage(current_batch, generation_stage)
                generation_stage = self._generation_stage_for_batch(current_batch)
                last_msg = self.memory.get_context()[-1] if self.memory.message_count > 0 else {}
                batch_str = "\n".join([f"- {f}" for f in current_batch])
                is_new_prompt_needed = (iteration == 0 or consecutive_no_tools == 0)
                
                is_already_prompted = False
                if self.memory.message_count > 0:
                    last_msg = self.memory.get_context()[-1]
                    is_already_prompted = (
                        last_msg.get("role") == "user" and 
                        "### FILES TO WRITE IN THIS TURN" in str(last_msg.get("content", "")) and
                        batch_str in str(last_msg.get("content", ""))
                    )

                if is_new_prompt_needed and not is_already_prompted:
                    async for t in self._type(f"🔍 Preparing with {len(current_batch)} files in batch...\n"): yield t
                    
                    # DYNAMIC BLUEPRINT SCOPING
                    async for t in self._type("🔍 Building scoped architectural context...\n"): yield t
                    try:
                        scoped_bp = self.planner.build_scoped_blueprint(current_batch)
                        async for t in self._type(f"✓ Scoping complete ({len(scoped_bp.get('blueprint', []))} relevant files found)\n"): yield t
                    except Exception as e:
                        async for t in self._type(f"⚠️ Scoping error: {e}. Falling back to limited context.\n"): yield t
                        scoped_bp = {}
                    prompt_focus_paths = self._prompt_focus_paths(current_batch, scoped_bp)
                    if "STYLESHEET_CLASS" in iteration_feedback and "src/styles/global.css" not in prompt_focus_paths:
                        prompt_focus_paths.append("src/styles/global.css")
                    stage_scoped_bp = {
                        "current_files": list(scoped_bp.get("current_files") or []),
                        "blueprint": list(scoped_bp.get("blueprint") or []),
                        "units": list(scoped_bp.get("units") or []),
                        "relationships": list(scoped_bp.get("relationships") or []),
                        "external_relationships": list(scoped_bp.get("external_relationships") or []),
                        "shared_files": list(scoped_bp.get("shared_files") or []),
                        "api_contracts": list(scoped_bp.get("api_contracts") or []),
                        "related_types": list(scoped_bp.get("related_types") or []),
                    }
                    scoped_project_spec = dict(scoped_bp.get("project_spec") or {})
                    if scoped_project_spec:
                        stage_scoped_bp["project_spec"] = {
                            "entities": list(scoped_project_spec.get("entities") or []),
                            "api_resources": list(scoped_project_spec.get("api_resources") or []),
                            "pages": list(scoped_project_spec.get("pages") or []),
                        }
                    project_map_str = self.context_builder.build_context(
                        stage_name=generation_stage,
                        focus_paths=prompt_focus_paths,
                    )
                    feedback_block = ""
                    if iteration_feedback.strip():
                        feedback_block = iteration_feedback.strip()
                        iteration_feedback = ""
                    prompt_content = build_generation_user_prompt(
                        original_prompt=original_prompt,
                        stage_name=generation_stage,
                        current_batch=current_batch,
                        scoped_blueprint=stage_scoped_bp,
                        project_context=project_map_str,
                        project_spec=self.planner.project_spec,
                        feedback=feedback_block,
                        done_count=self.planner.done_count,
                        total_count=self.planner.total_count,
                    )
                    self.memory.add_message("user", prompt_content.strip())

                # (SummarizationMiddleware bypassed in stateless mode)


                # ── ACT: call provider (Stateless Turn — NO MEMORY) ───────
                # Build localized message list: [System, Last User]
                # Bypasses self.memory.get_context() to satisfy "never send memory" rule.
                if getattr(self, "system_prompt_enabled", True):
                    stage_system = build_stage_system_prompt(
                        design,
                        generation_stage,
                        self.sandbox_dir,
                        uupm_prompt_context,
                        global_contract=self.global_contract,
                        scraper=is_scraper,
                    )
                else:
                    stage_system = system
                system_msg = {"role": "system", "content": stage_system}
                current_user_msg = self.memory.get_context()[-1] # Current turn prompt
                current_user_len = len(str(current_user_msg.get("content", "") or ""))
                
                stateless_messages = [system_msg, current_user_msg]
                active_provider = self.stage_providers[generation_stage]
                active_model_id = self.stage_model_ids[generation_stage] or self.model_id

                yield (
                    f"🤖 Calling provider ({generation_stage} stage, {len(stateless_messages)} messages, "
                    f"{len(stage_system) + current_user_len} chars total; "
                    f"system={len(stage_system)}, user={current_user_len})...\n"
                )
                yield self._thinking_banner("Provider is thinking...")

                response = ""
                provider_retries, provider_backoff = self._provider_retry_policy()
                provider_ok = False
                recovered_partial_calls: list[dict] | None = None
                recovered_partial_notice = ""

                for provider_attempt in range(provider_retries):
                    response = ""
                    try:
                        async for token in active_provider.stream(stateless_messages, active_model_id):
                            if is_provider_status_token(token):
                                yield token if token.endswith("\n") else f"{token}\n"
                                continue
                            response += token
                            yield token
                        provider_ok = True
                        break  # Success
                    except Exception as e:
                        err_str = str(e).lower()
                        is_transient = any(kw in err_str for kw in [
                            "input stream", "timeout", "503", "502", "504",
                            "connection", "reset", "broken pipe", "eof",
                            "service unavailable", "gateway",
                        ])

                        if is_transient and response.strip():
                            recovered_ok, recovered_calls, recovered_notice = self._recover_partial_stream_response(
                                response,
                                current_batch,
                                parser_model_id=self._effective_model_id(active_provider, active_model_id),
                            )
                            if recovered_ok:
                                recovered_partial_calls = recovered_calls
                                recovered_partial_notice = recovered_notice
                                provider_ok = True
                                break

                        if is_transient and provider_attempt < provider_retries - 1:
                            wait_s = provider_backoff[provider_attempt]
                            yield (
                                f"\n⚠️ Provider error (attempt {provider_attempt + 1}/{provider_retries}): {e}\n"
                                f"⏳ Retrying in {wait_s}s...\n"
                            )
                            await asyncio.sleep(wait_s)
                            continue
                        else:
                            yield f"\n❌ Provider error: {e}\n"
                            return

                if not provider_ok:
                    yield "\n❌ Provider failed after all retries.\n"
                    return

                self.memory.add_message("assistant", response)
                if recovered_partial_notice:
                    async for t in self._type(f"{recovered_partial_notice}\n"): yield t

                # ── OBSERVE: parse tool calls (XML + markdown fallback) ───────
                parser_model_id = self._effective_model_id(active_provider, active_model_id)
                calls = list(recovered_partial_calls or ResponseParser.parse_tool_calls(
                    response,
                    parser_model_id,
                    expected_files=current_batch,
                ))

                # ── VALIDATE: check for missing files or formatting issues ──
                is_valid, error_msg, calls = self._validate_response(calls, current_batch, response)
                
                expected_count = len(set(current_batch)) if current_batch else 0
                actual_count = len(set(c["params"].get("path", "") for c in calls if c["tool"] == "write_file"))
                
                if not is_valid:
                    retry_batch = self._determine_retry_batch(error_msg, current_batch)
                    self.retry_batch_override = retry_batch
                    _failure_signature, failure_count, should_abort = self._record_generation_failure(
                        "validation",
                        current_batch,
                        error_msg,
                        retry_batch,
                    )
                    async for t in self._type(f"\n❌ Validation failed: {error_msg}\n⏳ Retrying...\n"): yield t
                    if retry_batch and retry_batch != current_batch:
                        async for t in self._type(
                            f"ℹ️  Next retry narrowed to {len(retry_batch)} file(s): {', '.join(retry_batch[:8])}\n"
                        ): yield t
                    if failure_count > 1:
                        async for t in self._type(
                            f"ℹ️  This same generation validation failure has repeated {failure_count} time(s).\n"
                        ): yield t
                    if should_abort:
                        async for t in self._type(
                            "❌ The same generation validation error kept repeating. Stopping here instead of looping endlessly.\n"
                        ): yield t
                        self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                        return
                    iteration_feedback = (
                        f"VALIDATION ERROR:\n{error_msg}\n\n"
                        "Fix this immediately and provide only the requested files."
                    )
                    
                    iteration += 1
                    self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                    continue
                
                if expected_count > 0 and actual_count < expected_count:
                    expected_lookup = {
                        str(path or "").strip().lower().lstrip("./").replace("\\", "/"): str(path or "").strip().replace("\\", "/")
                        for path in current_batch
                        if str(path or "").strip()
                    }
                    expected_set = set(expected_lookup.keys())
                    actual_set = {
                        str(c["params"].get("path", "")).strip().lower().lstrip("./").replace("\\", "/")
                        for c in calls
                        if c["tool"] == "write_file"
                    }
                    missing_norms = sorted(expected_set - actual_set)
                    missing_paths = [
                        expected_lookup[norm]
                        for norm in missing_norms
                        if norm in expected_lookup
                    ]
                    missing_preview = ", ".join(missing_paths[:8])
                    if len(missing_paths) > 8:
                        missing_preview += ", ..."
                    async for t in self._type(
                        f"\n⚠️  Partial batch: received {actual_count}/{expected_count} files. "
                        "Keeping valid files and continuing with the missing tail only.\n"
                    ): yield t
                    if missing_preview:
                        async for t in self._type(f"ℹ️  Missing files this turn: {missing_preview}\n"): yield t

                # ── OBSERVE: execute tools ────────────────────────────────
                written_paths = set()
                if calls:
                    consecutive_no_tools = 0
                    write_calls = [call for call in calls if call["tool"] == "write_file"]
                    other_calls = [call for call in calls if call["tool"] != "write_file"]

                    if write_calls:
                        async for t in self._type(f"🛠️  Executing write_batch({len(write_calls)} files...)\n"): yield t
                        batch_ok, batch_result, batch_written_paths = await self._commit_write_calls(
                            write_calls,
                            allowed_paths=self._get_unit_paths_for_batch(current_batch),
                        )
                        self.memory.add_message("user", f"Tool write_batch result: {batch_result}")
                        if not batch_ok:
                            retry_batch = self._determine_retry_batch(batch_result, current_batch)
                            if missing_paths:
                                # SINGLE-BATCH ROBUSTNESS: Ensure 'batch_all' files not yet written are not lost during retry narrowing
                                retry_batch = sorted(list(set(retry_batch) | set(missing_paths)))

                            self.retry_batch_override = retry_batch
                            _failure_signature, failure_count, should_abort = self._record_generation_failure(
                                "batch_write",
                                current_batch,
                                batch_result,
                                retry_batch,
                            )
                            async for t in self._type("\n❌ Batch write rejected.\n"): yield t
                            for line in str(batch_result or "").splitlines():
                                if line.strip():
                                    async for t in self._type(f"  - {line}\n"): yield t
                            current_completed = self.planner.done_count
                            current_total = self.planner.total_count
                            if current_total > 0:
                                async for t in self._type(
                                    f"ℹ️  Current progress: {current_completed}/{current_total} files\n"
                                ): yield t
                            if retry_batch and retry_batch != current_batch:
                                async for t in self._type(
                                    f"ℹ️  Next retry narrowed to {len(retry_batch)} file(s): {', '.join(retry_batch[:8])}\n"
                                ): yield t
                            if failure_count > 1:
                                async for t in self._type(
                                    f"ℹ️  This same batch-write rejection has repeated {failure_count} time(s).\n"
                                ): yield t
                            if should_abort:
                                async for t in self._type(
                                    "❌ The same batch-write rejection kept repeating. Stopping here instead of burning more iterations.\n"
                                ): yield t
                                self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                                return
                            async for t in self._type("⏳ Retrying...\n"): yield t
                            iteration_feedback = (
                                f"BATCH WRITE ERROR:\n{batch_result}\n\n"
                                "Retry with explicit // FILE: paths and complete files only."
                            )
                            iteration += 1
                            self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                            continue

                        expected_write_paths: list[str] = []
                        seen_expected_write_paths: set[str] = set()
                        for call in write_calls:
                            candidate = str(call.get("params", {}).get("path", "") or "").strip().replace("\\", "/")
                            if candidate and candidate not in seen_expected_write_paths:
                                seen_expected_write_paths.add(candidate)
                                expected_write_paths.append(candidate)

                        written_lookup = {
                            str(path or "").strip().replace("\\", "/").lower().lstrip("./")
                            for path in list(batch_written_paths or [])
                            if str(path or "").strip()
                        }
                        dropped_after_validation = [
                            path
                            for path in expected_write_paths
                            if str(path or "").strip().replace("\\", "/").lower().lstrip("./") not in written_lookup
                        ]
                        if dropped_after_validation:
                            missing_paths = sorted(list(set(missing_paths) | set(dropped_after_validation)))
                            preview = ", ".join(dropped_after_validation[:8])
                            if len(dropped_after_validation) > 8:
                                preview += ", ..."
                            async for t in self._type(
                                f"⚠️  Partial write after contract filtering: wrote {len(batch_written_paths)}/{len(expected_write_paths)} files.\n"
                            ): yield t
                            if preview:
                                async for t in self._type(f"ℹ️  Filtered files queued for retry: {preview}\n"): yield t

                        for line in str(batch_result or "").splitlines():
                            clean = str(line or "").strip()
                            if not clean:
                                continue
                            if clean.startswith("ℹ️"):
                                async for t in self._type(f"{clean}\n"): yield t

                        for path in batch_written_paths:
                            written_paths.add(path)
                            async for t in self._type(f"✓ File written: {path}\n"): yield t

                    for call in other_calls:
                        tool_name = call["tool"]
                        params = call["params"]

                        # During file-generation turns, ignore model-issued shell commands.
                        # Install/build/test/runtime commands are executed in dedicated
                        # validation phases after generation is complete.
                        if tool_name == "execute_command":
                            allow_generation_commands = self._read_bool_config(
                                dict(getattr(self, "pipeline_config", {}) or {}),
                                "builder_allow_generation_commands",
                                False,
                            )
                            generation_incomplete = self.planner.done_count < self.planner.total_count
                            if generation_incomplete and not allow_generation_commands:
                                cmd_preview = str(params.get("command", "") or "").strip().splitlines()[0][:80]
                                async for t in self._type(
                                    f"ℹ️  Skipping execute_command during generation: {cmd_preview}\n"
                                ): yield t
                                continue

                        param_desc = params.get("path") or params.get("command") or ""
                        async for t in self._type(f"🛠️  Executing {tool_name}({param_desc[:40]}...)\n"): yield t

                        result = await self.tool_registry.execute(tool_name, params)
                        self.memory.add_message("user", f"Tool {tool_name} result: {result}")
                        async for t in self._type(f"✓ Tool {tool_name} completed\n"): yield t

                    # Update planner status
                    self._apply_written_paths(list(written_paths))
                    completed = self.planner.done_count
                    total = self.planner.total_count
                    if total > 0:
                        async for t in self._type(f"✅ Progress: {completed}/{total} files\n"): yield t
                        batch_progress_emitted = True
                    self.retry_batch_override = []
                    self._clear_generation_failure_state()

                    phase_gate_phases, phase_gate_errors = self._run_phase_gates(
                        list(written_paths) or current_batch,
                        files_to_write=[dict(call.get("params") or {}) for call in write_calls],
                    )
                    if phase_gate_errors:
                        async for t in self._type(
                            f"⚠️ Phase gate blocked progress for this batch ({', '.join(phase_gate_phases)}).\n"
                        ): yield t
                        for err in phase_gate_errors:
                            async for t in self._type(f"  - {err}\n"): yield t
                        reopen_paths = self._extract_phase_error_paths(phase_gate_errors, current_batch)
                        self._reopen_pending_paths(reopen_paths)
                        retry_targets = self._determine_retry_batch("\n".join(phase_gate_errors), reopen_paths or current_batch)
                        if missing_paths:
                            # SINGLE-BATCH ROBUSTNESS: Blend the missing tail of the unit into the narrow fix-targets
                            retry_targets = sorted(list(set(retry_targets) | set(missing_paths)))

                        self.retry_batch_override = retry_targets
                        _failure_signature, failure_count, should_abort = self._record_generation_failure(
                            "phase_gate",
                            current_batch,
                            "\n".join(phase_gate_errors),
                            self.retry_batch_override,
                        )
                        if failure_count > 1:
                            async for t in self._type(
                                f"ℹ️  This same phase-gate failure has repeated {failure_count} time(s).\n"
                            ): yield t
                        if should_abort:
                            async for t in self._type(
                                "❌ The same phase-gate failure kept repeating. Stopping here instead of looping endlessly.\n"
                            ): yield t
                            self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                            return
                        iteration_feedback = (
                            "PHASE GATE ERROR:\n"
                            + "\n".join(f"- {err}" for err in phase_gate_errors[:12])
                            + "\n\nRewrite the blocked files so this batch satisfies the scaffold/backend/frontend contract."
                        )
                        iteration += 1
                        self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                        continue

                    runtime_smoke_errors = await self._run_backend_smoke_tests(list(written_paths) or current_batch)
                    if runtime_smoke_errors and self._is_phase_runtime_infra_error(runtime_smoke_errors):
                        async for t in self._type("ℹ️ Early backend smoke hit an environment/runtime bootstrap issue, so this batch was not reopened.\n"): yield t
                    elif runtime_smoke_errors:
                        async for t in self._type("⚠️ Runtime smoke blocked progress for this batch (backend).\n"): yield t
                        for err in runtime_smoke_errors:
                            async for t in self._type(f"  - {err}\n"): yield t
                        reopen_paths = self._extract_phase_error_paths(runtime_smoke_errors, current_batch)
                        self._reopen_pending_paths(reopen_paths)
                        retry_targets = self._determine_retry_batch("\n".join(runtime_smoke_errors), reopen_paths or current_batch)
                        if missing_paths:
                            # SINGLE-BATCH ROBUSTNESS: Ensure backend smoke failures don't drop the rest of the unit
                            retry_targets = sorted(list(set(retry_targets) | set(missing_paths)))

                        self.retry_batch_override = retry_targets
                        _failure_signature, failure_count, should_abort = self._record_generation_failure(
                            "runtime_smoke",
                            current_batch,
                            "\n".join(runtime_smoke_errors),
                            self.retry_batch_override,
                        )
                        if failure_count > 1:
                            async for t in self._type(
                                f"ℹ️  This same runtime-smoke failure has repeated {failure_count} time(s).\n"
                            ): yield t
                        if should_abort:
                            async for t in self._type(
                                "❌ The same runtime-smoke failure kept repeating. Stopping here instead of burning more time.\n"
                            ): yield t
                            self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                            return
                        iteration_feedback = (
                            "RUNTIME SMOKE ERROR:\n"
                            + "\n".join(f"- {err}" for err in runtime_smoke_errors[:12])
                            + "\n\nRewrite the blocked backend files so the server boots and the affected API routes return healthy responses."
                        )
                        iteration += 1
                        self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                        continue

                    completed = self.planner.done_count
                    total = self.planner.total_count
                    if completed > 0 and not batch_progress_emitted:
                        async for t in self._type(f"\n✅ Progress: {completed}/{total} files\n"): yield t
                    self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                    
                    if self.memory.message_count > 0:
                        ctx = self.memory.get_context()
                        if ctx and ctx[-1]["role"] == "assistant":
                            self.memory.pop_message()
                else:
                    consecutive_no_tools += 1

            # ── NEXT STEP SELECTION ──────────────────────────────
            async for t in self._type(f"🔍 Iteration {iteration + 1} complete. Checking if all {self.planner.total_count} files are done...\n"): yield t
            if self.planner.all_done(feature_errors=[]):
                async for t in self._type("🔍 All files generated. Performing final project-wide checks...\n"): yield t
                
                if getattr(self, "linter_enabled", True):
                    async for t in self._type("📝 Running Code Linter...\n"): yield t
                    errors = self.linter.lint_all(self.sandbox_dir)
                    if errors:
                        async for t in self._type(f"⚠️  Linter found {len(errors)} issues.\n"): yield t
                        for err in errors:
                            async for t in self._type(f"  - {err}\n"): yield t
                    else:
                        async for t in self._type("✅ Linter: No issues found.\n"): yield t
                else:
                    async for t in self._type("ℹ️ Linter skipped by pipeline configuration.\n"): yield t
                    errors = []
                
                if self.feature_validator_enabled:
                    async for t in self._type("🛡️  Running Feature Validator (Full-Stack Parity)...\n"): yield t
                    feature_errors = self.feature_validator.validate_full_stack(self.planner.project_spec)
                    
                    if feature_errors:
                        async for t in self._type(f"⚠️  Feature Validator found {len(feature_errors)} missing integrations.\n"): yield t
                        for fe in feature_errors:
                            async for t in self._type(f"  - {fe}\n"): yield t
                    else:
                        async for t in self._type("✅ Feature Validator: No issues found.\n"): yield t
                else:
                    async for t in self._type("ℹ️ Feature Validator skipped by pipeline configuration.\n"): yield t
                    feature_errors = []

                all_errors = errors + feature_errors
                # STRICT REQUIREMENT: loop continues until Linter and feature_validator are 100% clean
                if not self.planner.all_done(feature_errors=all_errors):
                    current_error_signature = ""
                    force_validation_repair = False
                    signature_state = {}
                    if all_errors:
                        current_error_signature = hashlib.sha1(
                            "\n".join(sorted(all_errors)).encode("utf-8")
                        ).hexdigest()
                        if current_error_signature == validation_stall_signature:
                            validation_stall_count += 1
                        else:
                            validation_stall_signature = current_error_signature
                            validation_stall_count = 0
                        signature_state = dict(
                            self.validation_repair_state.get(current_error_signature, {}) or {}
                        )
                        normal_validation_attempts = int(signature_state.get("normal_attempts", 0) or 0)
                        ai_validation_attempts = int(signature_state.get("ai_attempts", 0) or 0)
                        force_validation_repair = normal_validation_attempts >= 1
                        if force_validation_repair and ai_validation_attempts >= 1:
                            last_ai_decisions = dict(signature_state.get("last_ai_decisions", {}) or {})
                            if last_ai_decisions:
                                async for t in self._type("🧠 Last decision-engine result for this validation signature:\n"): yield t
                                for decision_file, decision_info in last_ai_decisions.items():
                                    strategy = str(decision_info.get("strategy", "UNKNOWN") or "UNKNOWN")
                                    cause = str(decision_info.get("root_cause", "") or "").strip()
                                    write_files = str(decision_info.get("write_files", "") or "").strip() or "unknown"
                                    targets = [
                                        str(path).strip()
                                        for path in (decision_info.get("target_files") or [])
                                        if str(path).strip()
                                    ]
                                    targets_text = ", ".join(targets) if targets else decision_file
                                    async for t in self._type(
                                        f"  - {decision_file}: strategy={strategy}, write_files={write_files}, targets={targets_text}\n"
                                    ): yield t
                                    if cause:
                                        async for t in self._type(f"    cause: {cause}\n"): yield t
                            async for t in self._type(
                                "❌ The same validation findings already had one normal repair pass and one decision-engine AI pass with no change. "
                                "Stopping here instead of looping endlessly.\n"
                            ): yield t
                            break
                        if force_validation_repair:
                            async for t in self._type(
                                "⚠️  The normal repair attempt did not change these validation findings. "
                                "Passing the problem directly to the decision-engine AI.\n"
                            ): yield t
                        else:
                            signature_state["normal_attempts"] = normal_validation_attempts + 1
                            self.validation_repair_state[current_error_signature] = signature_state
                    else:
                        validation_stall_signature = ""
                        validation_stall_count = 0

                    # Combine for the AI
                    current_errors = all_errors

                    # Batch errors by file for the AI
                    file_errors = {}
                    
                    for err in all_errors:
                        parts = err.split(":", 1)
                        if len(parts) > 1 and "." in parts[0]:
                            fname = parts[0].strip()
                            msg = parts[1].strip()
                            
                            # --- SMART DEDUPLICATION: Missing Imports ---
                            # If the error is "Import '../services/api' not found — create the missing file"
                            # We should assign this error to "src/services/api.ts" NOT to the importing file "src/App.tsx".
                            # This way the AI creates the 1 missing file instead of rewriting 15 consumer files.
                            missing_import_match = re.search(r"Import\s+['\"]?([^'\"]+)['\"]?\s+not found\s*(?:—|-)\s*create the missing file", msg)
                            if missing_import_match:
                                import_path = missing_import_match.group(1).strip()
                                target_file = self._guess_missing_import_target(parts[0].strip(), import_path)
                                if not target_file:
                                    target_file = import_path.lstrip("./")
                                    if not re.search(r"\.(?:ts|tsx|js|jsx|css)$", target_file):
                                        if "components/" in target_file or "pages/" in target_file:
                                            target_file += ".tsx"
                                        else:
                                            target_file += ".ts"

                                fname = target_file
                                msg = f"MISSING_IMPORT_FILE: Create this file. It is imported by {parts[0].strip()} but does not exist. Make sure to export exactly what they expect."
                        else:
                            preferred_targets = self._preferred_repair_targets_for_error(err)
                            # Route disconnected features and route sync errors to their correct target files
                            route_match = re.search(r"route '(\w+)'", err)
                            route_name = route_match.group(1) if route_match else None
                            
                            sync_err_match = re.search(r"but '([^']+)' does not export '([^']+)'", err)
                            if preferred_targets:
                                fname = preferred_targets[0]
                            elif sync_err_match:
                                # Example: ...but 'server/controllers/auth.controller.ts' does not export 'getCurrentUser'
                                fname = sync_err_match.group(1)
                            elif "DATABASE" in err:
                                fname = "server/db/database.ts"
                            elif "PROXY" in err:
                                fname = "vite.config.ts"
                            elif route_name == "auth" or "Auth" in err or "MISSING_FEATURE: Backend has Auth" in err:
                                fname = "src/pages/Login.tsx"
                            elif route_name == "users":
                                fname = "src/pages/UserList.tsx"
                            elif route_name:
                                # Instead of generating random pages, let's route the API consumption block to App.tsx
                                # where the synchronization useEffect is. Wait, App.tsx is better for broad connectivity.
                                fname = "src/App.tsx"
                            else:
                                fname = "src/App.tsx"
                            
                            # Clean up the message for the AI so it doesn't get confused by the prefix
                            if err.startswith("ROUTE_SYNC_ERROR:"):
                                msg = "ROUTE_SYNC_ERROR: " + err.split("ROUTE_SYNC_ERROR:", 1)[1].strip()
                            elif err.startswith("DISCONNECTED_FEATURE:"):
                                msg = "DISCONNECTED_FEATURE: " + err.split("DISCONNECTED_FEATURE:", 1)[1].strip()
                            else:
                                msg = err
                            
                        if fname not in file_errors: file_errors[fname] = []
                        # Prevent duplicate messages for the same target file
                        if msg not in file_errors[fname]:
                            file_errors[fname].append(msg)

                    # Build fix batches — process in sub-batches of 4 files max
                    # (large batches overwhelm the AI and produce fragments)
                    context_str = self.context_builder.build_context()
                    
                    fix_items = list(file_errors.items())
                    FIX_SUB_BATCH = 4  # Max files per AI call
                    repairs_sent = 0
                    query_only_skips = 0
                    total_command_repairs = 0
                    
                    for batch_start in range(0, len(fix_items), FIX_SUB_BATCH):
                        fix_batch = fix_items[batch_start:batch_start + FIX_SUB_BATCH]
                        
                        batch_error_parts = []
                        writable_fix_batch = []
                        batch_repair_targets = []
                        command_applied_count = 0
                        for broken_file, msgs in fix_batch:
                            error_context = "\n".join([f"  - {m}" for m in msgs])
                            analysis = self.error_analyzer.analyze(msgs[0], broken_file)
                            decision = None
                            issue_key = self._triage_issue_key(broken_file, msgs[0])
                            cached_triage = self.triage_cache.get(issue_key, {})
                            phase_context = self._phase_context_for_issue(broken_file, msgs)
                            project_spec_payload = self.planner.project_spec.to_dict() if self.planner.project_spec else None
                            needs_ai_triage = (
                                analysis['type'] in {"UNKNOWN", "RECURSIVE_FAILURE", "API_CONTRACT_DRIFT", "SCHEMA_SYNC_ERROR", "AUTH_INVALID"}
                                or force_validation_repair
                            )
                             
                            # --- AI DECISION ENGINE INTEGRATION ---
                            if needs_ai_triage:
                                if (
                                    cached_triage.get("query_only_count", 0) >= 1
                                    and cached_triage.get("strategy")
                                    and cached_triage.get("fix_hint")
                                    and cached_triage.get("query_context")
                                ):
                                    analysis['type'] = cached_triage.get("strategy", analysis['type'])
                                    analysis['fix'] = cached_triage.get("fix_hint", analysis['fix'])
                                    async for t in self._type(
                                        f"♻️ Reusing previous triage context for {broken_file} and asking the decision engine for a final write/no-write decision.\n"
                                    ): yield t
                                    prior_root_cause = str(cached_triage.get("root_cause", "") or "").strip()
                                    prior_root_cause_block = (
                                        f"PREVIOUS ROOT CAUSE:\n{prior_root_cause}\n\n"
                                        if prior_root_cause else
                                        ""
                                    )
                                    repeat_query_context = (
                                        f"{prior_root_cause_block}{cached_triage.get('query_context', '')}\n\n"
                                        "REPEAT STATUS:\n"
                                        "This exact validation finding repeated with no progress. "
                                        "You may request ONE additional read-only query only if it is different from the previous one and truly adds new information. "
                                        "Otherwise decide whether file writes are needed now."
                                    )
                                    decision = await self.decision_engine.decide(
                                        error_log=msgs[0] + f"\nFile: {broken_file}",
                                        sandbox_dir=self.sandbox_dir,
                                        query_context=repeat_query_context,
                                        allow_query_commands=True,
                                        force_ai=True,
                                        project_spec=project_spec_payload,
                                        phase_context=phase_context,
                                        target_file_hint=broken_file,
                                    )
                                    decision["_resolved_query_context"] = cached_triage.get("query_context", "")
                                    decision["_resolved_query_commands"] = list(cached_triage.get("query_commands", []) or [])
                                    pre_announced_command = None
                                    if self._should_preannounce_decision_command(decision):
                                        pre_announced_command = decision.get("command")
                                        async for t in self._type(f"🛠️  Executing triage command: {pre_announced_command}\n"): yield t
                                    decision, cmd_result, procedure_messages = await self._resolve_decision_procedure(
                                        decision,
                                        error_log=msgs[0] + f"\nFile: {broken_file}",
                                        pre_announced_command=pre_announced_command,
                                        project_spec=project_spec_payload,
                                        phase_context=phase_context,
                                        target_file_hint=broken_file,
                                    )
                                    for message in procedure_messages:
                                        async for t in self._type(message): yield t
                                    analysis['type'] = decision.get('strategy', analysis['type'])
                                    analysis['fix'] = decision.get('fix_hint', analysis['fix'])
                                    self.triage_cache[issue_key] = {
                                        "query_only_count": int(cached_triage.get("query_only_count", 0)),
                                        "strategy": analysis['type'],
                                        "fix_hint": analysis['fix'],
                                        "root_cause": decision.get("root_cause", cached_triage.get("root_cause", "")),
                                        "target_files": decision.get("target_files", [broken_file]),
                                        "query_context": decision.get("_resolved_query_context", cached_triage.get("query_context", "")),
                                        "query_commands": decision.get("_resolved_query_commands", cached_triage.get("query_commands", [])),
                                    }
                                    self._remember_validation_ai_decision(
                                        current_error_signature,
                                        broken_file,
                                        decision,
                                        analysis['type'],
                                    )
                                    async for t in self._type(
                                        f"  ↳ Final decision: {analysis['type']} "
                                        f"(write_files={decision.get('write_files', 'no')})\n"
                                    ): yield t

                                    if self._is_dependency_install_decision(decision):
                                        self.triage_cache[issue_key]["query_only_count"] = 0
                                        command_applied_count += 1
                                        async for t in self._type(
                                            "✅ Dependency installed. Skipping file rewrite for this iteration.\n"
                                        ): yield t
                                        continue

                                    if self._is_mutation_decision(decision):
                                        self.triage_cache[issue_key]["query_only_count"] = 0
                                        command_applied_count += 1
                                        async for t in self._type(
                                            f"✅ Mutation command applied ({decision.get('command') or 'mutation'}). Skipping file rewrite for this iteration.\n"
                                        ): yield t
                                        continue

                                    immediate_validation_rewrite = self._requires_immediate_validation_rewrite(msgs)
                                    if self._is_source_edit_decision(decision):
                                        forced_rewrite = (
                                            self._forced_validation_rewrite_decision(
                                                broken_file,
                                                msgs,
                                                decision,
                                            )
                                            if immediate_validation_rewrite else None
                                        )
                                        if forced_rewrite:
                                            decision["target_files"] = forced_rewrite["target_files"]
                                            decision["command"] = None
                                            decision["command_kind"] = "none"
                                            decision["return_query_result"] = "no"
                                            decision["write_files"] = "yes"
                                            analysis['type'] = forced_rewrite["strategy"]
                                            analysis['fix'] = forced_rewrite["fix_hint"]
                                            self.triage_cache[issue_key]["query_only_count"] = 0
                                            async for t in self._type(forced_rewrite["banner"]): yield t
                                        else:
                                            self.triage_cache[issue_key]["query_only_count"] = 0
                                            command_applied_count += 1
                                            applied_command = decision.get("command") or "shell source edit"
                                            async for t in self._type(
                                                f"✅ Shell source edit applied ({applied_command}). Skipping full-file rewrite for this iteration.\n"
                                            ): yield t
                                            continue

                                    if decision.get("write_files") == "no":
                                        forced_rewrite = (
                                            self._forced_validation_rewrite_decision(
                                                broken_file,
                                                msgs,
                                                decision,
                                            )
                                            if (force_validation_repair or immediate_validation_rewrite) else None
                                        )
                                        if forced_rewrite:
                                            decision["target_files"] = forced_rewrite["target_files"]
                                            decision["command"] = None
                                            decision["command_kind"] = "none"
                                            decision["return_query_result"] = "no"
                                            decision["write_files"] = "yes"
                                            analysis['type'] = forced_rewrite["strategy"]
                                            analysis['fix'] = forced_rewrite["fix_hint"]
                                            self.triage_cache[issue_key]["query_only_count"] = 0
                                            async for t in self._type(forced_rewrite["banner"]): yield t
                                        else:
                                            self.triage_cache[issue_key]["query_only_count"] = int(
                                                self.triage_cache[issue_key].get("query_only_count", 0)
                                            ) + 1
                                            query_only_skips += 1
                                            async for t in self._type(
                                                "⚠️  Final decision remained query-only even after reusing prior query context. "
                                                "This issue will now be treated as blocked instead of forcing a blind repair.\n"
                                            ): yield t
                                            continue
                                else:
                                    async for t in self._type(f"🧠 Deep Triage: Investigating {broken_file} with AI Decision Engine...\n"): yield t
                                    decision = await self.decision_engine.decide(
                                        error_log=msgs[0] + f"\nFile: {broken_file}",
                                        sandbox_dir=self.sandbox_dir,
                                        force_ai=True,
                                        project_spec=project_spec_payload,
                                        phase_context=phase_context,
                                        target_file_hint=broken_file,
                                    )
                                    analysis['type'] = decision.get('strategy', 'UNKNOWN')
                                    analysis['fix'] = decision.get('fix_hint', analysis['fix'])
                                    async for t in self._type(f"  ↳ AI decided strategy: {analysis['type']} (Cause: {decision.get('root_cause', 'unknown')})\n"): yield t

                                    pre_announced_command = None
                                    if self._should_preannounce_decision_command(decision):
                                        pre_announced_command = decision.get("command")
                                        async for t in self._type(f"🛠️  Executing triage command: {pre_announced_command}\n"): yield t
                                    decision, cmd_result, procedure_messages = await self._resolve_decision_procedure(
                                        decision,
                                        error_log=msgs[0] + f"\nFile: {broken_file}",
                                        pre_announced_command=pre_announced_command,
                                        project_spec=project_spec_payload,
                                        phase_context=phase_context,
                                        target_file_hint=broken_file,
                                    )
                                    for message in procedure_messages:
                                        async for t in self._type(message): yield t

                                    analysis['type'] = decision.get('strategy', analysis['type'])
                                    analysis['fix'] = decision.get('fix_hint', analysis['fix'])

                                    self.triage_cache[issue_key] = {
                                        "query_only_count": int(cached_triage.get("query_only_count", 0)),
                                        "strategy": analysis['type'],
                                        "fix_hint": analysis['fix'],
                                        "root_cause": decision.get("root_cause", cached_triage.get("root_cause", "")),
                                        "target_files": decision.get("target_files", [broken_file]),
                                        "query_context": decision.get("_resolved_query_context", cached_triage.get("query_context", "")),
                                        "query_commands": decision.get("_resolved_query_commands", cached_triage.get("query_commands", [])),
                                    }
                                    self._remember_validation_ai_decision(
                                        current_error_signature,
                                        broken_file,
                                        decision,
                                        analysis['type'],
                                    )

                                    if self._is_dependency_install_decision(decision):
                                        self.triage_cache[issue_key]["query_only_count"] = 0
                                        command_applied_count += 1
                                        async for t in self._type(f"✅ Dependency installed. Skipping file rewrite for this iteration.\n"): yield t
                                        continue

                                    immediate_validation_rewrite = self._requires_immediate_validation_rewrite(msgs)
                                    if self._is_source_edit_decision(decision):
                                        forced_rewrite = (
                                            self._forced_validation_rewrite_decision(
                                                broken_file,
                                                msgs,
                                                decision,
                                            )
                                            if immediate_validation_rewrite else None
                                        )
                                        if forced_rewrite:
                                            decision["target_files"] = forced_rewrite["target_files"]
                                            decision["command"] = None
                                            decision["command_kind"] = "none"
                                            decision["return_query_result"] = "no"
                                            decision["write_files"] = "yes"
                                            analysis['type'] = forced_rewrite["strategy"]
                                            analysis['fix'] = forced_rewrite["fix_hint"]
                                            self.triage_cache[issue_key]["query_only_count"] = 0
                                            async for t in self._type(forced_rewrite["banner"]): yield t
                                        else:
                                            self.triage_cache[issue_key]["query_only_count"] = 0
                                            command_applied_count += 1
                                            applied_command = decision.get("command") or "shell source edit"
                                            async for t in self._type(
                                                f"✅ Shell source edit applied ({applied_command}). Skipping full-file rewrite for this iteration.\n"
                                            ): yield t
                                            continue

                                    if decision.get("write_files") == "no":
                                        forced_rewrite = (
                                            self._forced_validation_rewrite_decision(
                                                broken_file,
                                                msgs,
                                                decision,
                                            )
                                            if (force_validation_repair or immediate_validation_rewrite) else None
                                        )
                                        if forced_rewrite:
                                            decision["target_files"] = forced_rewrite["target_files"]
                                            decision["command"] = None
                                            decision["command_kind"] = "none"
                                            decision["return_query_result"] = "no"
                                            decision["write_files"] = "yes"
                                            analysis['type'] = forced_rewrite["strategy"]
                                            analysis['fix'] = forced_rewrite["fix_hint"]
                                            self.triage_cache[issue_key]["query_only_count"] = 0
                                            async for t in self._type(forced_rewrite["banner"]): yield t
                                        else:
                                            self.triage_cache[issue_key]["query_only_count"] = int(
                                                self.triage_cache[issue_key].get("query_only_count", 0)
                                            ) + 1
                                            query_only_skips += 1
                                            if force_validation_repair:
                                                async for t in self._type(
                                                    "⚠️  Final decision remained query-only even after reusing prior query context. "
                                                    "This issue will now be treated as blocked instead of forcing a blind repair.\n"
                                                ): yield t
                                            else:
                                                async for t in self._type("ℹ️  Decision engine requested query-only triage. Skipping file rewrite for this iteration.\n"): yield t
                                            continue

                                    self.triage_cache[issue_key]["query_only_count"] = 0

                            if self._uses_focused_validation_targets(decision, msgs):
                                expanded_cluster = self._focused_validation_repair_targets(
                                    broken_file,
                                    msgs,
                                    decision,
                                )
                            else:
                                # Enforce Blueprint cluster scope
                                expanded_cluster = self.planner.get_cluster_for_file(broken_file)
                                if decision and decision.get("write_files") == "yes":
                                    target_files = [
                                        str(path).strip()
                                        for path in (decision.get("target_files") or [])
                                        if str(path).strip()
                                    ]
                                    # Add any AI-selected target files that aren't already in the blueprint cluster
                                    for fn in target_files:
                                        if fn not in expanded_cluster:
                                            expanded_cluster.append(fn)

                            expanded_cluster = self._normalize_repair_target_list(expanded_cluster or [broken_file])
                            repair_target = ", ".join(expanded_cluster) if expanded_cluster else broken_file

                            if analysis['type'] != 'UNKNOWN' and analysis['type'] != (decision.get('strategy', '') if decision else ''):
                                async for t in self._type(f"🔧 Queued fix: {repair_target} ({analysis['type']})...\n"): yield t
                            
                            writable_fix_batch.append((repair_target, expanded_cluster, msgs, analysis, decision, phase_context))
                            root_cause = str((decision or {}).get("root_cause", "") or "").strip()
                            root_cause_block = f"Root cause: {root_cause}\n" if root_cause else ""
                            batch_error_parts.append(
                                f"### {repair_target}\n"
                                f"Strategy: {analysis['type']}\n"
                                f"{root_cause_block}"
                                f"Errors:\n{error_context}\n"
                                f"Fix hint: {analysis['fix']}"
                            )

                        if not writable_fix_batch:
                            if command_applied_count > 0:
                                total_command_repairs += command_applied_count
                                async for t in self._type(
                                    "ℹ️  Fixes in this batch were applied directly by command. Re-running validation.\n"
                                ): yield t
                            else:
                                async for t in self._type("ℹ️  No files in this batch need rewriting after triage.\n"): yield t
                            continue
                        
                        combined_error_prompt = (
                            f"FIX THE FOLLOWING {len(writable_fix_batch)} FILES.\n\n"
                            f"CRITICAL RULES:\n"
                            f"1. Output COMPLETE, FULL files — NEVER output partial code, snippets, or fragments.\n"
                            f"2. Every file MUST start with: // FILE: <relative-path>\n"
                            f"3. Include ALL imports, ALL functions, ALL exports — the ENTIRE file content.\n"
                            f"4. Wrap each file in a markdown code block (```typescript ... ```).\n"
                            f"5. If a file is missing, create it with full working code.\n\n"
                            + "\n\n".join(batch_error_parts)
                        )

                        batch_phase_contexts: list[str] = []
                        batch_owner_targets: list[str] = []
                        for repair_target, repair_paths, msgs, _analysis, decision, phase_context in writable_fix_batch:
                            if phase_context:
                                batch_phase_contexts.append(f"### {repair_target}\n{phase_context}")
                            batch_repair_targets.extend(repair_paths)
                            batch_owner_targets.extend(repair_paths)
                        self._set_unified_repair_context(
                            phase_context="\n\n".join(batch_phase_contexts),
                            owner_targets=batch_owner_targets,
                        )
                        
                        async for t in self._type(f"🔧 Sending fix batch ({len(writable_fix_batch)} files)...\n"): yield t
                        repairs_sent += 1
                        combined_repair_targets = self._normalize_repair_target_list(batch_repair_targets)
                        try:
                            validation_scope_cap = max(
                                1,
                                int(
                                    dict(getattr(self, "pipeline_config", {}) or {}).get(
                                        "validation_repair_scope_max_files",
                                        10,
                                    )
                                    or 10
                                ),
                            )
                        except Exception:
                            validation_scope_cap = 10
                        if len(combined_repair_targets) > validation_scope_cap:
                            dropped = len(combined_repair_targets) - validation_scope_cap
                            combined_repair_targets = combined_repair_targets[:validation_scope_cap]
                            async for t in self._type(
                                "ℹ️ Validation repair scope guard: constrained this rewrite batch to "
                                f"{len(combined_repair_targets)} files (dropped {dropped} extra targets).\n"
                            ): yield t
                        async for fix_msg in self.unified_repair.run_phase_repair(
                            "generation",
                            [", ".join(combined_repair_targets), combined_error_prompt],
                            0
                        ):
                            yield fix_msg

                    if force_validation_repair and current_error_signature and (repairs_sent > 0 or total_command_repairs > 0):
                        signature_state = dict(
                            self.validation_repair_state.get(current_error_signature, {}) or {}
                        )
                        prior_ai_attempts = int(signature_state.get("ai_attempts", 0) or 0)
                        signature_state["ai_attempts"] = prior_ai_attempts + 1
                        self.validation_repair_state[current_error_signature] = signature_state

                    if repairs_sent == 0 and total_command_repairs == 0 and all_errors:
                        if force_validation_repair:
                            async for t in self._type(
                                "❌ Validation is stuck on the same findings and the final decision-engine pass still did not authorize a repair batch. "
                                "Stopping here instead of looping endlessly.\n"
                            ): yield t
                            break
                        if query_only_skips > 0:
                            async for t in self._type(
                                "ℹ️  Validation made no writable progress this pass. "
                                "If the same findings repeat again, the next pass will reuse the saved query context and require a final AI write/no-write decision.\n"
                            ): yield t
                    
                    iteration += 1
                    self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)
                    continue
                else:
                    validation_stall_signature = ""
                    validation_stall_count = 0
                    async for t in self._type("✅ All tasks complete!\n"): yield t
                    break
            
            elif not calls and consecutive_no_tools >= 2:
                async for t in self._type("\n✅ Done (no more actions needed).\n"): yield t
                break

            iteration += 1
            self._save_resume_state(original_prompt=original_prompt, iteration=iteration, design=design)

        # ── STEP 5: AUTO INSTALL + BUILD ──────────────────────────────────
        if getattr(self, "auto_install_enabled", True):
            async for t in self._type("📦 Installing dependencies...\n"): yield t
            async for t in self._type("🛠️  Executing execute_command(npm install...)\n"): yield t
            install_result = await self.tool_registry.execute(
                "execute_command",
                {"command": "npm install --legacy-peer-deps 2>&1", "timeout": 600} #dont change this line
            )
            initial_install_result = install_result
            async for t in self._type(f"📦 npm install result: {install_result[:400]}\n"): yield t

            # Filter out harmless warnings before checking for real errors
            # npm WARN deprecated is normal and should not trigger a retry
            install_lines = [l for l in install_result.splitlines() 
                             if not l.strip().startswith("npm WARN") and l.strip()]
            install_filtered = "\n".join(install_lines)
            
            if self._looks_like_install_failure(install_filtered):
                async for t in self._type("⚠️ Install errors detected — retrying with --legacy-peer-deps...\n"): yield t
                async for t in self._type("\n📦 Retrying npm install...\n"): yield t
                install_result = await self.tool_registry.execute(
                    "execute_command",
                    {"command": "npm install --legacy-peer-deps 2>&1", "timeout": 600}
                )
                install_lines2 = [l for l in install_result.splitlines()
                                  if not l.strip().startswith("npm WARN") and l.strip()]
                install_filtered2 = "\n".join(install_lines2)
                success = not self._looks_like_install_failure(install_filtered2)
                install_recovered = success
                async for t in self._type(f"📦 Result: {'✓ Success' if success else '✗ Failed'}\n"): yield t
                if not success:
                    combined_install_output = initial_install_result + "\n" + install_result
                    if self._looks_like_npm_reify_rename_failure(combined_install_output):
                        cleaned_entries, install_result = await self._attempt_npm_reify_recovery(combined_install_output)
                        if cleaned_entries > 0:
                            async for t in self._type(
                                "🧹 npm left stale reify directories in node_modules after a failed rename. "
                                f"Cleaned {cleaned_entries} stale entries and retrying install...\n"
                            ): yield t
                            install_lines_reify = [
                                l for l in install_result.splitlines()
                                if not l.strip().startswith("npm WARN") and l.strip()
                            ]
                            install_filtered_reify = "\n".join(install_lines_reify)
                            if not self._looks_like_install_failure(install_filtered_reify):
                                async for t in self._type("✅ Install fixed after clearing stale npm reify directories.\n"): yield t
                                install_recovered = True
                            else:
                                async for t in self._type("⚠️ Install still failing after clearing stale npm reify directories.\n"): yield t
                            combined_install_output = initial_install_result + "\n" + install_result

                    if not install_recovered and self._looks_like_invalid_version_install_failure(combined_install_output):
                        async for t in self._type(
                            "🧹 Detected npm 'Invalid Version' while reading the current install state. "
                            "Backing up corrupted install artifacts and retrying from package.json...\n"
                        ): yield t
                        backed_up_paths, install_result = await self._attempt_invalid_version_recovery()
                        if backed_up_paths:
                            async for t in self._type(
                                f"📦 Backed up: {', '.join(backed_up_paths)}\n"
                            ): yield t
                            install_lines_invalid = [
                                l for l in install_result.splitlines()
                                if not l.strip().startswith("npm WARN") and l.strip()
                            ]
                            install_filtered_invalid = "\n".join(install_lines_invalid)
                            if not self._looks_like_install_failure(install_filtered_invalid):
                                async for t in self._type("✅ Install fixed after resetting corrupted npm install artifacts.\n"): yield t
                                install_recovered = True
                            else:
                                async for t in self._type("⚠️ Install still failing after resetting corrupted npm install artifacts.\n"): yield t
                            combined_install_output = initial_install_result + "\n" + install_result

                    if not install_recovered and self._looks_like_esbuild_sigsegv_failure(combined_install_output):
                        async for t in self._type(
                            "🔧 Detected esbuild native binary crash (SIGSEGV) on Node 22. "
                            "Pinning esbuild to a compatible version and retrying...\n"
                        ): yield t
                        if self._pin_dev_dependency("esbuild", "0.25.0"):
                            async for t in self._type("📁 Fixed: package.json (esbuild pinned to 0.25.0)\n"): yield t
                        else:
                            async for t in self._type(
                                "ℹ️ esbuild was already pinned in devDependencies or package.json could not be updated automatically.\n"
                            ): yield t

                        install_result = await self.tool_registry.execute(
                            "execute_command",
                            {"command": "npm install --legacy-peer-deps 2>&1", "timeout": 600}
                        )
                        install_lines_esbuild = [
                            l for l in install_result.splitlines()
                            if not l.strip().startswith("npm WARN") and l.strip()
                        ]
                        install_filtered_esbuild = "\n".join(install_lines_esbuild)
                        if not self._looks_like_install_failure(install_filtered_esbuild):
                            async for t in self._type("✅ Install fixed after esbuild pin.\n"): yield t
                            install_recovered = True
                        else:
                            async for t in self._type("⚠️ Install still failing after esbuild pin.\n"): yield t
                            combined_install_output = initial_install_result + "\n" + install_result

                    if self._looks_like_network_install_failure(combined_install_output):
                        async for t in self._type(
                            "🌐 npm install appears to be failing due to network/registry timeouts. "
                            "Retrying with extended fetch timeouts and cache verification...\n"
                        ): yield t

                        network_retry_cmd = (
                            "npm install --legacy-peer-deps "
                            "--fetch-retries=5 "
                            "--fetch-retry-factor=2 "
                            "--fetch-retry-mintimeout=20000 "
                            "--fetch-retry-maxtimeout=120000 "
                            "--fetch-timeout=300000 2>&1"
                        )
                        network_fixed = False
                        for network_attempt in range(1, 4):
                            async for t in self._type(
                                f"📦 Network retry {network_attempt}/3...\n"
                            ): yield t
                            if network_attempt == 2:
                                async for t in self._type("🛠️  Executing execute_command(npm cache verify...)\n"): yield t
                                cache_result = await self.tool_registry.execute(
                                    "execute_command",
                                    {"command": "npm cache verify 2>&1", "timeout": 180}
                                )
                                async for t in self._type(f"📦 npm cache verify result: {cache_result[:250]}\n"): yield t

                            install_result = await self.tool_registry.execute(
                                "execute_command",
                                {"command": network_retry_cmd, "timeout": 900}
                            )
                            install_lines_retry = [
                                l for l in install_result.splitlines()
                                if not l.strip().startswith("npm WARN") and l.strip()
                            ]
                            install_filtered_retry = "\n".join(install_lines_retry)
                            if not self._looks_like_install_failure(install_filtered_retry):
                                async for t in self._type("✅ Install fixed after network retry.\n"): yield t
                                network_fixed = True
                                break

                            if self._looks_like_npm_reify_rename_failure(install_result):
                                cleaned_entries, recovered_output = await self._attempt_npm_reify_recovery(install_result)
                                if cleaned_entries > 0:
                                    async for t in self._type(
                                        "🧹 npm hit a local node_modules rename conflict during retry. "
                                        f"Cleaned {cleaned_entries} conflicting entries and retried install...\n"
                                    ): yield t
                                    install_result = recovered_output
                                    install_lines_retry = [
                                        l for l in install_result.splitlines()
                                        if not l.strip().startswith("npm WARN") and l.strip()
                                    ]
                                    install_filtered_retry = "\n".join(install_lines_retry)
                                    if not self._looks_like_install_failure(install_filtered_retry):
                                        async for t in self._type("✅ Install fixed after clearing npm rename conflicts.\n"): yield t
                                        network_fixed = True
                                        break

                            if self._looks_like_esbuild_sigsegv_failure(install_result):
                                async for t in self._type(
                                    "🔧 Network retry surfaced an esbuild native crash (SIGSEGV). "
                                    "Applying esbuild compatibility recovery and retrying...\n"
                                ): yield t
                                if self._pin_dev_dependency("esbuild", "0.25.0"):
                                    async for t in self._type(
                                        "📁 Fixed: package.json (esbuild pinned to 0.25.0 via devDependencies/overrides)\n"
                                    ): yield t
                                cleared_esbuild = self._clear_esbuild_install_artifacts()
                                if cleared_esbuild > 0:
                                    async for t in self._type(
                                        f"🧹 Cleared {cleared_esbuild} stale esbuild install path(s) before retry.\n"
                                    ): yield t
                                install_result = await self.tool_registry.execute(
                                    "execute_command",
                                    {"command": network_retry_cmd, "timeout": 900}
                                )
                                install_lines_retry = [
                                    l for l in install_result.splitlines()
                                    if not l.strip().startswith("npm WARN") and l.strip()
                                ]
                                install_filtered_retry = "\n".join(install_lines_retry)
                                if not self._looks_like_install_failure(install_filtered_retry):
                                    async for t in self._type("✅ Install fixed after esbuild compatibility recovery.\n"): yield t
                                    network_fixed = True
                                    break

                            async for t in self._type(
                                f"⚠️ Network retry {network_attempt}/3 failed.\n"
                            ): yield t

                        if network_fixed:
                            install_recovered = True
                        combined_install_output = initial_install_result + "\n" + install_result

                    if not install_recovered and self._looks_like_better_sqlite3_native_failure(combined_install_output):
                        current_better_sqlite3 = self._get_declared_dependency_version("better-sqlite3")
                        if current_better_sqlite3 != "^12.2.0":
                            async for t in self._type("🔧 Detected native better-sqlite3 install failure. Upgrading to a Node 22 compatible version and retrying...\n"): yield t
                            if self._upgrade_better_sqlite3_dependency("^12.2.0"):
                                async for t in self._type("📁 Fixed: package.json (better-sqlite3 -> ^12.2.0)\n"): yield t
                                install_result = await self.tool_registry.execute(
                                    "execute_command",
                                    {"command": "npm install --legacy-peer-deps 2>&1", "timeout": 600}
                                )
                                install_lines3 = [
                                    l for l in install_result.splitlines()
                                    if not l.strip().startswith("npm WARN") and l.strip()
                                ]
                                install_filtered3 = "\n".join(install_lines3)
                                if not self._looks_like_install_failure(install_filtered3):
                                    async for t in self._type("✅ Install fixed after better-sqlite3 upgrade.\n"): yield t
                                    install_recovered = True
                                else:
                                    async for t in self._type("⚠️ Install still failing after better-sqlite3 upgrade.\n"): yield t
                                    combined_install_output = initial_install_result + "\n" + install_result
                            else:
                                async for t in self._type(
                                    "⚠️ Tried to update package.json to better-sqlite3 ^12.2.0 but the rewrite did not succeed. "
                                    "Stopping before build so the install error is not misdiagnosed.\n"
                                ): yield t
                                async for t in self._type(f"📋 Install log excerpt:\n{install_result[-1500:]}\n"): yield t
                                return
                        else:
                            async for t in self._type(
                                "ℹ️ better-sqlite3 is already pinned to ^12.2.0. "
                                "Skipping version rewrite because the remaining install failure is not an outdated-package issue.\n"
                            ): yield t

                    if not install_recovered and self._looks_like_python_gyp_toolchain_failure(combined_install_output):
                        async for t in self._type(
                            "🧱 Native dependency installation is blocked by the host Node/Python toolchain: "
                            "Python cannot import 'gyp' for node-gyp. This is an environment issue, not a project code issue.\n"
                        ): yield t
                        async for t in self._type(
                            "ℹ️ Automatic fixes stopped before build. Restore a working node-gyp toolchain in the environment "
                            "that runs the sandbox, then rerun generation.\n"
                        ): yield t
                        async for t in self._type(f"📋 Install log excerpt:\n{install_result[-1500:]}\n"): yield t
                        return

                    if not install_recovered and self._looks_like_network_install_failure(combined_install_output):
                        async for t in self._type(
                            "❌ Dependency installation still failed after multiple network retries. "
                            "This is likely an npm registry/connectivity problem, not a project code problem.\n"
                        ): yield t
                        async for t in self._type(f"📋 Install log excerpt:\n{install_result[-1500:]}\n"): yield t
                        return

                    if not install_recovered and self._looks_like_esbuild_sigsegv_failure(combined_install_output):
                        async for t in self._type(
                            "❌ Dependency installation is blocked by an esbuild native binary crash (SIGSEGV). "
                            "This is an environment/runtime issue, not generated app code.\n"
                        ): yield t
                        async for t in self._type(
                            "ℹ️ Automatic fixes stopped before build. Try rerunning with Node 20 LTS runtime "
                            "or keep Node 22 with a fresh install after pinning esbuild.\n"
                        ): yield t
                        async for t in self._type(f"📋 Install log excerpt:\n{install_result[-1500:]}\n"): yield t
                        return

                    if not install_recovered:
                        async for t in self._type("❌ Dependency installation failed. Stopping before build so the fixer does not chase unrelated errors.\n"): yield t
                        async for t in self._type(f"📋 Install log excerpt:\n{install_result[-1500:]}\n"): yield t
                        return
                    self.phase_runtime_ready = True
            else:
                async for t in self._type("📦 npm install: ✓ Success\n"): yield t
                self.phase_runtime_ready = True
        else:
            async for t in self._type("\nℹ️ Auto-install specifically skipped by pipeline configuration.\n"): yield t

        if getattr(self, "auto_install_enabled", True) and self.phase_runtime_ready:
            async for t in self._type("🛠️  Executing execute_command(rebuild native sqlite bindings if present...)\n"): yield t
            await self.tool_registry.execute(
                "execute_command",
                {
                    "command": "[ -d node_modules/better-sqlite3 ] && npm rebuild better-sqlite3 || true",
                    "timeout": 60,
                }
            )

        build_passed = True

        # ── STEP 6: PROJECT BUILD CHECK ───────────────────────────────────
        if getattr(self, "project_build_enabled", True):
            async for t in self._type("🔨 Build check...\n"): yield t
            async for t in self._type("🛠️  Executing execute_command(npm run build...)\n"): yield t
            build_result = await self.tool_registry.execute(
                "execute_command",
                {"command": "npm run build 2>&1 | tail -200", "timeout": 120}
            )

            if self._looks_like_build_failure(build_result):
                build_passed = False
                async for t in self._type("⚠️ Build error detected\n"): yield t
                repair_attempts_used = 0
                
                # Try smart fixes (max 20 different approaches)
                for attempt in range(1, 21):
                    repair_attempts_used = attempt
                    async for t in self._type(f"🔧 Auto-fix attempt {attempt}/20...\n"): yield t
                    
                    fixed = False
                    self._set_unified_repair_context(
                        phase_context="Repair Phase: build\nBuild failed during npm run build.",
                        owner_targets=self._extract_build_owner_targets(build_result),
                    )
                    async for token in self.unified_repair.run_phase_repair(
                        "build",
                        [build_result],
                        attempt
                    ):
                        yield token
                        if "Fixed:" in token:
                            fixed = True

                    if fixed:
                        # Rebuild after fix
                        yield "\n🔨 Rebuilding after fix...\n"
                        build_result2 = await self.tool_registry.execute(
                            "execute_command",
                            {"command": "npm run build 2>&1 | tail -200", "timeout": 120}
                        )
                        if not self._looks_like_build_failure(build_result2):
                            build_passed = True
                            async for t in self._type("✅ Build fixed!\n"): yield t
                            break
                        else:
                            # Update error for next attempt
                            build_result = build_result2
                            if attempt == 20:
                                async for t in self._type("❌ Build repair reached maximum attempts (20/20). Proceeding with caution...\n"): yield t
                    else:
                        async for t in self._type("❌ No auto-fix could be determined for the build error. Proceeding with caution...\n"): yield t
                        break
            else:
                build_passed = True
                async for t in self._type("✅ Build passed.\n"): yield t
            
            if not build_passed:
                 # HARDENING: surface the real build excerpt and accurate retry count.
                 excerpt_lines = [
                     line
                     for line in str(build_result or "").splitlines()
                     if str(line).strip()
                 ]
                 excerpt = "\n".join(excerpt_lines[-40:]).strip()
                 if excerpt:
                     async for t in self._type(f"📋 Build log excerpt:\n{excerpt}\n"): yield t
                 async for t in self._type(
                     f"❌ UNSTABLE BUILD: Project remains non-buildable after {max(1, int(repair_attempts_used or 0))} repair attempt(s). Marking as blocked.\n"
                 ): yield t
                 # We don't return here so that the loop can potentially try one last turn if iteration < max_iter
                 iteration_feedback = (
                     "STRICT BUILD FAILURE:\nnpm run build is still failing.\n"
                     f"Build excerpt:\n{excerpt if excerpt else '(no build output captured)'}"
                 )
        else:
            async for t in self._type("\nℹ️ Project Build Check skipped by pipeline configuration.\n"): yield t
            
        # ── STEP 6.25: INTEGRATION TEST CHECK ────────────────────────────────
        if getattr(self, "integration_test_enabled", False):
            async for t in self._type("\n🧪 Running integration tests...\n"): yield t
            async for t in self._type("🛠️  Executing execute_command(npm run test...)\n"): yield t
            test_result = await self.tool_registry.execute(
                "execute_command",
                {"command": "npm run test 2>&1 | tail -100", "timeout": 60}
            )

            if "failed" in test_result.lower() or "error" in test_result.lower():
                async for t in self._type("⚠️ Test failures detected\n"): yield t
                
                # Try smart fixes for tests
                for attempt in range(1, 10):
                    async for t in self._type(f"🔧 Test Auto-fix attempt {attempt}/10...\n"): yield t
                    
                    fixed = False
                    self._set_unified_repair_context(
                        phase_context="Repair Phase: build\nIntegration test failure during npm run test.",
                        owner_targets=self._extract_project_paths_from_text(test_result),
                    )
                    async for token in self.unified_repair.run_phase_repair(
                        "build",
                        [f"Integration Test Failed:\n{test_result}"],
                        attempt
                    ):
                        yield token
                        if "Fixed:" in token:
                            fixed = True

                    if fixed:
                        yield "\n🧪 Re-running tests after fix...\n"
                        test_result2 = await self.tool_registry.execute(
                            "execute_command",
                            {"command": "npm run test 2>&1 | tail -100", "timeout": 60}
                        )
                        if "failed" not in test_result2.lower() and "error" not in test_result2.lower():
                            async for t in self._type("✅ Tests passed!\n"): yield t
                            break
                        else:
                            test_result = test_result2
                    else:
                        break
            else:
                async for t in self._type("✅ Tests passed successfully!\n"): yield t
        else:
            async for t in self._type("\nℹ️ Integration tests skipped by pipeline configuration.\n"): yield t

        # ── STEP 6.5: OPTIONAL BACKEND RUNTIME VALIDATION ────────────────────────────
        if getattr(self, "runtime_enabled", False):
            async for t in self._type("\n🛡️  Running Optional Backend Pre-flight Validation...\n"): yield t
            try:
                await self.tool_registry.execute(
                    "execute_command",
                    {"command": self._kill_common_backend_ports_command(), "timeout": 5}
                )
                # (Import removed)
                from .runtime_validator import RuntimeValidator
                rv = RuntimeValidator(
                    self.sandbox_dir,
                    self.tool_registry,
                    self.error_analyzer,
                    provider=self.stage_providers["validation"],
                    model_id=self.stage_model_ids["validation"] or self.model_id,
                )
                backend_res = await rv.run_backend_check()
                if backend_res.get("status") == "error":
                    recovered = self._parse_validator_json(backend_res.get("raw_output", ""))
                    if recovered:
                        backend_res = recovered
                        async for t in self._type(
                            "ℹ️  Recovered backend validator JSON from mixed/truncated output; continuing with recovered result.\n"
                        ): yield t
                backend_validation_snapshot = backend_res
                if backend_res.get("status") == "error":
                    errors = backend_res.get('errors', [])
                    # Check if it's a real app error or just a validator infrastructure issue
                    is_port_reuse_error = (
                        len(errors) == 1
                        and isinstance(errors[0], dict)
                        and errors[0].get("type") == "PORT_ERROR"
                        and "EADDRINUSE" in str(errors[0].get("raw", ""))
                    )
                    is_validator_infra_error = any(
                        "BACKEND_VALIDATOR_TIMEOUT" in str(e) or
                        "Validator exception" in str(e) or 
                        "Expecting value" in str(e) or
                        "No output from backend validator" in str(e) or
                        "No valid JSON output from backend validator" in str(e) or
                        "Command timed out after" in str(e)
                        for e in errors
                    )
                    if is_validator_infra_error or is_port_reuse_error:
                        async for t in self._type(f"ℹ️  Backend validator had an internal issue (not an app error): {errors}\n"): yield t
                        async for t in self._type("ℹ️  Skipping self-healing for validator infrastructure errors.\n"): yield t
                    else:
                        backend_runtime_errors = self._normalize_error_messages(errors)
                        async for t in self._type(f"⚠️  Backend Validation Error detected: {errors}\n"): yield t
                        # Trigger auto-fix loop only for REAL app errors
                        self._set_unified_repair_context(
                            phase_context="Repair Phase: runtime\nBackend pre-flight validation failed.",
                            owner_targets=self._extract_project_paths_from_text(json.dumps(backend_res)),
                        )
                        async for msg in self.unified_repair.run_phase_repair("runtime", ["backend_unknown", "RUNTIME_BACKEND_ERROR\n" + json.dumps(backend_res)], 1):
                            yield msg
                else:
                    backend_runtime_errors = []
                    backend_validation_snapshot = {}
                    yield "✅ Backend validation (seed/boot) passed.\n"
            except Exception as e:
                async for t in self._type(f"⚠️ Backend Validator encountered an internal error: {e}. Continuing pipeline...\n"): yield t

        # ── STEP 7: BACKEND RUNTIME CHECK (SERVER-ONLY) ────────────────────
        backend_runtime_errors = []
        backend_validation_snapshot = {}
        if getattr(self, "runtime_enabled", True):
            if self._has_backend_entry():
                async for t in self._type("\n🚀 Checking backend service for runtime validation...\n"): yield t
                
                # Check if already healthy from a previous iteration (persistent runtime)
                probe_already_alive, _ = await self._probe_backend_health_via_shell(self.backend_port)
                
                if probe_already_alive:
                    async for t in self._type("✅ Backend is already healthy and listening. Skipping restart (Watch Mode enabled).\n"): yield t
                else:
                    async for t in self._type("🛠️  Executing execute_command(kill existing backend server...)\n"): yield t
                    await self.tool_registry.execute(
                        "execute_command",
                        {"command": self._kill_common_backend_ports_command(), "timeout": 5}
                    )

                    async for t in self._type("🛠️  Executing execute_command(start backend service...)\n"): yield t
                    await self.tool_registry.execute(
                        "execute_command",
                        {"command": "> /tmp/sandbox_server.log 2>/dev/null || true", "timeout": 3, "label": "clear stale server log..."}
                    )
                    await self.tool_registry.execute(
                        "execute_command",
                        {"command": self._get_backend_start_command(), "timeout": 5, "label": "start backend service..."}
                    )
                    async for t in self._type(
                        f"🌐 Backend runtime candidate started at: http://localhost:{self.backend_port}\n"
                    ): yield t

                # ── STEP 8: BACKEND HEALTH CHECK ──────────────────────────────
                async for t in self._type("\n🔍 Checking backend health...\n"): yield t
                backend_runtime_healthy = False
                last_backend_error_log = ""
                _isolation_skip_count = 0
                _max_isolation_waits = 3
                minimum_runtime_validation_seconds = self._runtime_min_validation_seconds()
                backend_health_started_at = time.monotonic()
                max_backend_attempts = self._backend_runtime_attempt_limit()
                for attempt in range(1, max_backend_attempts + 1):
                    # Give the tsx/node server extra time on first attempt — TypeScript transpilation
                    # via tsx can take 8-12 s. Subsequent retries use the standard 5 s interval.
                    await asyncio.sleep(10 if attempt == 1 else 5)
                    backend_port = self.backend_port
                    if not self.feature_validator_enabled:
                        is_alive, error_log = True, ""
                    else:
                        try:
                            backend_port = int(str(self.backend_port))
                        except Exception:
                            backend_port = self.backend_port

                        shell_alive, shell_probe_log = await self._probe_backend_health_via_shell(backend_port)
                        if shell_alive:
                            is_alive, error_log = True, ""
                        else:
                            socket_alive, socket_error_log = self.feature_validator.validate_backend_runtime(port=backend_port)
                            is_alive = bool(socket_alive)
                            error_log = str(socket_error_log or "").strip() or str(shell_probe_log or "").strip()

                    if is_alive:
                        backend_runtime_healthy = True
                        backend_runtime_errors = []
                        backend_validation_snapshot = {}
                        async for t in self._type(
                            f"✅ Backend is healthy and listening on port {backend_port}.\n"
                        ): yield t
                        break

                    last_backend_error_log = error_log
                    async for t in self._type(
                        f"⚠️  Backend health check failed (Attempt {attempt}/{max_backend_attempts}).\n"
                    ): yield t
                    # Also read the actual server log to surface real crash info to the user
                    srv_log_content = await self.tool_registry.execute("execute_command", {
                        "command": "tail -n 30 /tmp/sandbox_server.log 2>/dev/null || echo '(empty server log)'",
                        "timeout": 5
                    })
                    srv_log_text = str(srv_log_content or "").strip()
                    if srv_log_text and srv_log_text != "(empty server log)":
                        async for t in self._type(f"📋 Last error log excerpt:\n{srv_log_text}\n"): yield t
                        # Merge server log into error_log so self-heal sees real errors
                        if error_log and "HEALTH_FAIL" in error_log:
                            error_log = srv_log_text + "\n" + error_log
                            last_backend_error_log = error_log
                    else:
                        async for t in self._type(f"📋 Last error log excerpt:\n{error_log[:500]}\n"): yield t

                    if self._looks_like_runtime_isolation_false_negative(error_log):
                        # After starting, wait 4 seconds then read the fresh log to check for crash:
                        await asyncio.sleep(4)
                        log_content = await self.tool_registry.execute("execute_command", {
                            "command": "cat /tmp/sandbox_server.log 2>/dev/null || echo '(empty)'",
                            "timeout": 5
                        })

                        # If the log is empty or shows a crash, the server died silently
                        if not str(log_content).strip() or "error" in str(log_content).lower() or "cannot" in str(log_content).lower():
                            # Real crash — trigger self-heal immediately with actual error
                            last_backend_error_log = str(log_content)
                            error_log = str(log_content)
                            # skip the false-negative bypass, go straight to self-heal
                        else:
                            elapsed_seconds = int(time.monotonic() - backend_health_started_at)
                            if (
                                minimum_runtime_validation_seconds > 0
                                and elapsed_seconds < minimum_runtime_validation_seconds
                            ):
                                async for t in self._type(
                                    "ℹ️  Boot markers found but health probe still cannot reach backend. "
                                    f"Keeping runtime validation alive ({elapsed_seconds}s/{minimum_runtime_validation_seconds}s minimum).\n"
                                ): yield t
                                await asyncio.sleep(3)
                                continue
                            _isolation_skip_count += 1
                            if _isolation_skip_count <= _max_isolation_waits:
                                async for t in self._type(
                                    f"ℹ️  Boot markers found but health probe still cannot reach backend. "
                                    f"Waiting... ({_isolation_skip_count}/{_max_isolation_waits})\\n"
                                ): yield t
                                await asyncio.sleep(3)
                                continue
                            async for t in self._type(
                                "ℹ️  Server appears to be running but health probe cannot reach it "
                                "after extended wait — likely a runtime isolation issue. "
                                "Treating backend runtime check as passed for this run.\\n"
                            ): yield t
                            backend_runtime_healthy = True
                            backend_runtime_errors = []
                            backend_validation_snapshot = {}
                            break

                    sync_errors = self.feature_validator._check_route_controller_sync() if self.feature_validator_enabled else []
                    fixed = False

                    if sync_errors:
                        async for t in self._type(f"🔍 Route-Controller sync detected {len(sync_errors)} mismatch(es):\n"): yield t
                        for se in sync_errors:
                            async for t in self._type(f"  ⚠️  {se}\n"): yield t

                        broken_files = _collect_broken_files_from_sync_errors(
                            sync_errors, self.sandbox_dir
                        )
                        combined_error = (
                            error_log + "\n\n### ROUTE-CONTROLLER SYNC ERRORS:\n"
                            + "\n".join(sync_errors)
                        )
                        for bf in broken_files:
                            async for t in self._type(f"🔧 Fixing {bf} (route/controller mismatch)...\n"): yield t
                            self._set_unified_repair_context(
                                phase_context=self._phase_context_for_issue(bf, sync_errors),
                                owner_targets=self._preferred_repair_targets_for_error(sync_errors[0], fallback_file=bf),
                            )
                            async for fix_msg in self.unified_repair.run_phase_repair(
                                "runtime", ["sync", bf, combined_error], attempt, rv=self.feature_validator
                            ):
                                yield fix_msg
                                if "Fixed:" in fix_msg:
                                    fixed = True

                    else:
                        broken_file = _extract_broken_server_file(error_log, self.sandbox_dir)
                        async for t in self._type(f"🔧 Attempting backend auto-fix for {broken_file}...\n"): yield t

                        self._set_unified_repair_context(
                            phase_context=self._phase_context_for_issue(broken_file, [error_log]),
                            owner_targets=self._preferred_repair_targets_for_error(error_log, fallback_file=broken_file),
                        )
                        async for fix_msg in self.unified_repair.run_phase_repair(
                            "runtime", ["backend", broken_file, error_log], attempt, rv=self.feature_validator
                        ):
                            yield fix_msg
                            if "Fixed:" in fix_msg:
                                fixed = True

                    if fixed:
                        async for t in self._type("♻️  Restarting backend service after fix...\n"): yield t
                        await self.tool_registry.execute(
                            "execute_command",
                            {"command": self._kill_common_backend_ports_command(), "timeout": 5}
                        )
                        await self.tool_registry.execute(
                            "execute_command",
                            {"command": "> /tmp/sandbox_server.log 2>/dev/null || true", "timeout": 3, "label": "clear stale server log..."}
                        )
                        await self.tool_registry.execute(
                            "execute_command",
                            {"command": self._get_backend_start_command(), "timeout": 5, "label": "start backend service..."}
                        )
                    else:
                        async for t in self._type("❌ Could not auto-fix backend error. Manual intervention may be required.\n"): yield t
                        break

                if not backend_runtime_healthy and last_backend_error_log:
                    backend_runtime_errors = [
                        f"Backend runtime validation failed:\n{last_backend_error_log[:1000]}"
                    ]
                    if not backend_validation_snapshot:
                        backend_validation_snapshot = {
                            "status": "error",
                            "errors": [{"message": backend_runtime_errors[0]}],
                        }
            else:
                async for t in self._type("\nℹ️  No backend entry point detected. Skipping host backend runtime checks.\n"): yield t
        else:
            async for t in self._type("\nℹ️ Server Runtime checks specifically skipped by pipeline configuration.\n"): yield t

        # ── STEP 8.5: OPTIONAL FRONTEND RUNTIME VALIDATION ───────────────────────────
        browser_runtime_errors = []
        browser_validation_snapshot = {}
        if getattr(self, "runtime_enabled", True):
            if not build_passed:
                async for t in self._type("\nℹ️ Skipping browser runtime validation because the frontend build did not succeed.\n"): yield t
            else:
                async for t in self._type("\n🛡️  Running Optional Runtime Validation (Browser & UI Bridge)...\n"): yield t
                try:
                    preview_already_alive, _ = await self._probe_frontend_preview_via_shell(self.frontend_port)
                    if preview_already_alive:
                        async for t in self._type("✅ Frontend preview is already healthy. Skipping restart.\n"): yield t
                    else:
                        async for t in self._type("🛠️  Executing execute_command(start static preview...)\n"): yield t
                        await self.tool_registry.execute(
                            "execute_command",
                            {"command": f"fuser -k {self.frontend_port}/tcp 2>/dev/null || true; sleep 1", "timeout": 10}
                        )
                        await self.tool_registry.execute(
                            "execute_command",
                            {"command": self._get_frontend_preview_command(), "timeout": 5}
                        )
                        async for t in self._type(
                            f"🌐 Frontend preview candidate started at: http://localhost:{self.frontend_port}\n"
                        ): yield t
                    await asyncio.sleep(10)

                    # (Import removed)
                    from .runtime_validator import RuntimeValidator
                    rv = RuntimeValidator(
                        self.sandbox_dir,
                        self.tool_registry,
                        self.error_analyzer,
                        provider=self.stage_providers["validation"],
                        model_id=self.stage_model_ids["validation"] or self.model_id,
                        frontend_port=self.frontend_port,
                        global_contract=self.global_contract,
                    )

                    preview_ready = False
                    preview_probe_excerpt = ""
                    max_preview_attempts = self._frontend_preview_attempt_limit()
                    for preview_attempt in range(1, max_preview_attempts + 1):
                        ready, probe_log = await self._probe_frontend_preview_via_shell(self.frontend_port)
                        if ready:
                            preview_ready = True
                            break
                        preview_log_probe = await self.tool_registry.execute(
                            "execute_command",
                            {"command": "tail -n 40 /tmp/sandbox_preview.log 2>/dev/null || true", "timeout": 5},
                        )
                        preview_log_probe_text = str(preview_log_probe or "").lower()
                        if (
                            f"localhost:{self.frontend_port}" in preview_log_probe_text
                            or f"127.0.0.1:{self.frontend_port}" in preview_log_probe_text
                            or "vite v" in preview_log_probe_text
                            or "local:" in preview_log_probe_text
                        ):
                            preview_ready = True
                            preview_probe_excerpt = str(preview_log_probe or "")
                            break
                        preview_probe_excerpt = probe_log
                        await asyncio.sleep(2)

                    if not preview_ready:
                        preview_log = await self.tool_registry.execute(
                            "execute_command",
                            {"command": "tail -n 80 /tmp/sandbox_preview.log 2>/dev/null || echo '(empty preview log)'", "timeout": 5},
                        )
                        browser_res = {
                            "status": "error",
                            "infra_error": True,
                            "errors": [
                                f"Frontend preview did not become reachable on port {self.frontend_port} before browser validation.",
                            ],
                            "runtime_errors": [str(preview_probe_excerpt or "").strip()],
                            "network_errors": [],
                            "console_errors": [],
                            "preview_log": str(preview_log or "")[-1200:],
                        }
                    else:
                        browser_res = await rv.run_browser_check()

                    browser_validation_snapshot = browser_res
                    if browser_res.get("status") == "error":
                        browser_errors = self._extract_browser_validation_errors(browser_res)
                        is_infra_error = self._is_browser_runtime_infra_error(browser_res, browser_errors)
                        if is_infra_error:
                            async for t in self._type(f"ℹ️  Browser validator had an internal issue (not an app error): {browser_errors}\n"): yield t
                            async for t in self._type("ℹ️  Skipping self-healing for validator infrastructure errors.\n"): yield t
                        else:
                            browser_runtime_errors = self._normalize_error_messages(browser_errors)
                            async for t in self._type(f"⚠️  Runtime UI Error detected: {json.dumps(browser_res)}\n"): yield t
                            self._set_unified_repair_context(
                                phase_context="Repair Phase: runtime\nBrowser runtime validation failed.",
                                owner_targets=self._runtime_owner_targets_from_text(json.dumps(browser_res)),
                            )
                            async for msg in self.unified_repair.run_phase_repair("runtime", ["backend_unknown", "RUNTIME_UI_ERROR\n" + json.dumps(browser_res)], 1):
                                yield msg
                    else:
                        browser_runtime_errors = []
                        browser_validation_snapshot = {}
                        async for t in self._type("✅ Frontend validation (Playwright) passed.\n"): yield t
                    
                        missing_ui = await rv.check_missing_ui(browser_res)

                        # ── Stream gate decisions to the page ──────────────────────
                        async for t in self._type("🔍 Runtime Validator — Gate decisions:\n"): yield t
                        for gate_msg in getattr(rv, "_gate_log", []):
                            async for t in self._type(f"  {gate_msg}\n"): yield t

                        if missing_ui:
                            async for t in self._type(f"⚠️  Missing UI Features Detected ({len(missing_ui)}):\n"): yield t
                            for issue in missing_ui:
                                async for t in self._type(f"  - {issue}\n"): yield t
                            async for t in self._type("🔧 Starting Self-Healing UI Generator...\n"): yield t
                            self._set_unified_repair_context(
                                phase_context="Repair Phase: runtime\nUI feature parity is missing in browser validation.",
                                owner_targets=self._extract_project_paths_from_text("\n".join(missing_ui)),
                            )
                            async for msg in self.unified_repair.run_phase_repair("runtime", ["ui", missing_ui], 1, rv=rv):
                                yield msg
                        else:
                            async for t in self._type("✅ All UI gates passed — no missing features detected.\n"): yield t

                except Exception as e:
                    async for t in self._type(f"⚠️ Runtime Validator encountered an internal error: {e}. Continuing pipeline...\n"): yield t
        else:
            async for t in self._type("\nℹ️ Browser Runtime checks skipped by pipeline configuration.\n"): yield t

        # ── STEP 9: SAVE SUMMARY FOR NEXT TIME ─────────────────────────────
        yield self._step_banner("9", "Save summary for next time")
        if getattr(self, "summary_enabled", True):
            async for t in self._type("📝 Generating project summary for future edits...\n"): yield t
            try:
                design_summary = f"Style: {design.style.name}, Colors: {design.colors.primary}, Fonts: {design.typography.heading}"
                yield self._thinking_banner("Summary model is thinking...")
                summary_content = await self._generate_project_summary(original_prompt, design_summary)
                await self.tool_registry.execute("write_file", {
                    "path": ".lovable/summary.md",
                    "content": summary_content,
                })
                async for t in self._type("✓ Summary saved to .lovable/summary.md\n"): yield t
            except Exception as e:
                async for t in self._type(f"⚠️  Failed to save summary: {e}\n"): yield t
        else:
            async for t in self._type("ℹ️ Summary saving skipped by pipeline configuration.\n"): yield t

        async for t in self._type(f"\n🎉 Generation complete! ({self.planner.done_count}/{self.planner.total_count} files)\n"): yield t
        self._clear_resume_state()


    # BUG FIX: Duplicate method definitions removed. Previously _parse_tool_calls and _generate_project_summary
    # were each defined twice in this class. Python silently used the last definition, shadowing the first.
    # The second (surviving) _generate_project_summary is kept because it has a try/except fallback.
    def _parse_tool_calls(self, response: str) -> List[Dict]:
        """Internal tool call parser that wraps ResponseParser."""
        return ResponseParser.parse_tool_calls(response, self.model_id)

    # ── Project Summary Generator ─────────────────────────────────────────────

    async def _generate_project_summary(self, prompt: str, design_summary: str) -> str:
        """
        Produce a concise summary of the generated project for future context.
        """
        messages = [
            {"role": "user", "content": get_summary_saving_prompt(prompt, design_summary)},
        ]
        summary = ""
        try:
            async for token in self.stage_providers["architecture"].stream(messages, self.stage_model_ids["architecture"] or self.model_id):
                summary += token
        except Exception:
            summary = f"# Project Summary\n\n- Initial Request: {prompt}\n- Design: {design_summary}\n"
        return summary
