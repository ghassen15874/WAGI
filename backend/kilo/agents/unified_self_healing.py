import os
import re
import logging
import asyncio
import json
from typing import AsyncIterator

from .codegen.prompts import get_repair_prompt
from .codegen.linter import SyntaxValidator
from ..shared.write_guard import is_safe_generated_path, normalize_generated_file_content

logger = logging.getLogger(__name__)

_LEGACY_BACKEND_ENTRY_HINTS = {
    "server/app.ts",
    "server/app.js",
    "server/server.ts",
    "server/server.js",
}

class UnifiedSelfHealing:
    """
    Unified Self-Healing Engine that preserves all specific repair phases:
    1. generation: Linting/Syntax fixes
    2. build: Missing imports, terser bugs, vite errors
    3. runtime: UI synchronization and server crashes
    """
    def __init__(self, sandbox_dir, provider, tool_registry, error_analyzer, context_builder, model_id, memory=None, backend_port=3001):
        self.sandbox_dir = sandbox_dir
        self.provider = provider
        self.tool_registry = tool_registry
        self.error_analyzer = error_analyzer
        self.context_builder = context_builder
        self.model_id = model_id
        self.memory = memory
        self.project_spec = None
        self.project_spec_context = ""
        self.phase_context = ""
        self.owner_context = ""
        self.backend_port = backend_port
        
        from .decision_engine import DecisionEngine
        self.decision_engine = DecisionEngine(
            error_analyzer=self.error_analyzer,
            provider=self.provider,
            model_id=self.model_id,
            backend_port=self.backend_port
        )

    def set_project_spec(self, project_spec) -> None:
        self.project_spec = project_spec.to_dict() if hasattr(project_spec, "to_dict") else project_spec

    def set_repair_context(self, *, project_spec_context: str = "", phase_context: str = "", owner_context: str = "") -> None:
        self.project_spec_context = str(project_spec_context or "").strip()
        self.phase_context = str(phase_context or "").strip()
        self.owner_context = str(owner_context or "").strip()

    def _compose_repair_context(self, base_context: str) -> str:
        sections = [str(base_context or "").strip()]
        if self.project_spec_context:
            sections.append(f"### PROJECT SPEC\n{self.project_spec_context}")
        if self.phase_context:
            sections.append(f"### PHASE CONTEXT\n{self.phase_context}")
        if self.owner_context:
            sections.append(f"### OWNER CONTEXT\n{self.owner_context}")
        return "\n\n".join(section for section in sections if section)

    def _combined_phase_context(self, phase_context: str = "") -> str:
        sections = []
        base = str(phase_context or "").strip()
        if base:
            sections.append(base)
        if self.phase_context:
            sections.append(self.phase_context)
        if self.owner_context:
            sections.append(f"Owner targets:\n{self.owner_context}")
        deduped: list[str] = []
        seen: set[str] = set()
        for section in sections:
            normalized = section.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return "\n\n".join(deduped)

    def _target_hint_from_error_log(self, error_log: str, fallback: str = "") -> str:
        for match in re.finditer(r'(?:server|src)/[^\s:()"\',]+\.(?:tsx|ts|jsx|js)', str(error_log or "")):
            candidate = match.group(0).strip()
            if candidate and "node_modules" not in candidate:
                if candidate.replace("\\", "/") in _LEGACY_BACKEND_ENTRY_HINTS:
                    return "server/index.ts"
                return candidate

        normalized_fallback = str(fallback or "").strip().replace("\\", "/")
        if normalized_fallback in _LEGACY_BACKEND_ENTRY_HINTS:
            return "server/index.ts"
        return normalized_fallback

    def _parse_tool_calls(self, response: str, expected_files: list[str] | None = None):
        from .codegen.parser import ResponseParser
        return ResponseParser.parse_tool_calls(response, self.model_id, expected_files=expected_files)

    def _normalize_repair_targets(self, paths: list[str] | None) -> list[str]:
        normalized_targets: list[str] = []
        seen: set[str] = set()
        for raw_path in list(paths or []):
            clean = str(raw_path or "").strip().replace("\\", "/")
            if not clean or clean in seen or not is_safe_generated_path(clean):
                continue
            seen.add(clean)
            normalized_targets.append(clean)
        return normalized_targets

    def _context_repair_targets(self) -> list[str]:
        extracted: list[str] = []

        for line in str(self.owner_context or "").splitlines():
            clean = line.strip()
            if clean.startswith("-"):
                clean = clean[1:].strip()
            if clean:
                extracted.append(clean)

        for match in re.finditer(
            r'(?:server|src)/[^\s:()"\',<>]+\.(?:tsx|ts|jsx|js|css)|(?:package\.json|vite\.config\.ts|tailwind\.config\.js|postcss\.config\.js|tsconfig(?:\.node)?\.json)',
            str(self.phase_context or ""),
        ):
            extracted.append(match.group(0).strip())

        return self._normalize_repair_targets(extracted)

    def _merge_repair_targets(self, *path_groups: list[str] | None) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in path_groups:
            for clean in self._normalize_repair_targets(group):
                if clean in seen:
                    continue
                seen.add(clean)
                merged.append(clean)
        return merged

    def _is_tsconfig_contract_error(self, error_log: str) -> bool:
        lowered = str(error_log or "").lower()
        if not lowered:
            return False
        has_core = any(
            marker in lowered
            for marker in (
                "ts6310",
                "tsconfig_purity_error",
                "allowimportingtsextensions",
                "may not disable emit",
                "referenced project",
                "noemit",
            )
        )
        return has_core and "tsconfig" in lowered

    def _write_canonical_tsconfig_pair(self, sandbox: str) -> list[str]:
        tsconfig_path = os.path.join(sandbox, "tsconfig.json")
        tsconfig_node_path = os.path.join(sandbox, "tsconfig.node.json")

        canonical_tsconfig = {
            "compilerOptions": {
                "target": "ES2020",
                "useDefineForClassFields": True,
                "lib": ["ES2020", "DOM", "DOM.Iterable"],
                "module": "ESNext",
                "skipLibCheck": True,
                "moduleResolution": "bundler",
                "resolveJsonModule": True,
                "isolatedModules": True,
                "noEmit": True,
                "jsx": "react-jsx",
                "strict": True,
                "noUnusedLocals": True,
                "noUnusedParameters": True,
                "noFallthroughCasesInSwitch": True,
                "baseUrl": ".",
                "paths": {"@/*": ["src/*"]},
            },
            "include": ["src"],
            "references": [{"path": "./tsconfig.node.json"}],
        }

        canonical_tsconfig_node = {
            "compilerOptions": {
                "composite": True,
                "module": "ESNext",
                "moduleResolution": "bundler",
                "allowSyntheticDefaultImports": True,
                "skipLibCheck": True,
                "allowImportingTsExtensions": False,
                "noEmit": False,
            },
            "include": ["vite.config.ts"],
        }

        with open(tsconfig_path, "w", encoding="utf-8") as f:
            json.dump(canonical_tsconfig, f, indent=2)
            f.write("\n")
        with open(tsconfig_node_path, "w", encoding="utf-8") as f:
            json.dump(canonical_tsconfig_node, f, indent=2)
            f.write("\n")
        return ["tsconfig.json", "tsconfig.node.json"]

    def _normalize_query_command(self, command: str | None) -> str:
        if not command:
            return ""
        return re.sub(r"\s+", " ", command.strip().lower())

    def normalize_query_command(self, command: str | None) -> str:
        return self._normalize_query_command(command)

    def _triage_command_timeout(self, command: str | None) -> int:
        lowered = str(command or "").strip().lower()
        if not lowered:
            return 30
        if self.decision_engine._is_query_command(lowered):
            return 15
        if "install" in lowered or " add " in f" {lowered} " or " update " in f" {lowered} ":
            return 120
        return 30

    def triage_command_timeout(self, command: str | None) -> int:
        return self._triage_command_timeout(command)

    def _should_preannounce_decision_command(self, decision: dict) -> bool:
        command = decision.get("command")
        if not command:
            return False
        normalized_command = self._normalize_query_command(command)
        seen_queries = set(decision.get("_resolved_query_commands", []) or [])
        return not (normalized_command and normalized_command in seen_queries)

    def should_preannounce_decision_command(self, decision: dict) -> bool:
        return self._should_preannounce_decision_command(decision)

    def _is_query_like_decision(self, decision: dict) -> bool:
        return str(decision.get("command_kind", "")).strip().lower() in {"query", "runtime_probe"}

    def is_query_like_decision(self, decision: dict) -> bool:
        return self._is_query_like_decision(decision)

    def _is_dependency_install_decision(self, decision: dict) -> bool:
        if str(decision.get("command_kind", "")).strip().lower() == "dependency_install":
            return True
        command = str(decision.get("command", "") or "").strip().lower()
        return bool(command) and "install" in command

    def is_dependency_install_decision(self, decision: dict) -> bool:
        return self._is_dependency_install_decision(decision)

    def _is_source_edit_decision(self, decision: dict) -> bool:
        if str(decision.get("command_kind", "")).strip().lower() == "source_edit":
            return True
        command = str(decision.get("command", "") or "").strip().lower()
        return self.decision_engine._is_source_mutating_command(command)

    def is_source_edit_decision(self, decision: dict) -> bool:
        return self._is_source_edit_decision(decision)

    def _is_mutation_decision(self, decision: dict) -> bool:
        return str(decision.get("command_kind", "")).strip().lower() == "mutation"

    def is_mutation_decision(self, decision: dict) -> bool:
        return self._is_mutation_decision(decision)

    def _source_edit_command_failed(self, output: str) -> bool:
        lowered = str(output or "").strip().lower()
        if not lowered:
            return False
        failure_markers = (
            "syntax error",
            "unterminated quoted string",
            "no such file or directory",
            "command not found",
            "/bin/sh:",
            "sed:",
            "traceback",
            "exception",
            "invalid command code",
            "can't read",
        )
        return any(marker in lowered for marker in failure_markers)

    def source_edit_command_failed(self, output: str) -> bool:
        return self._source_edit_command_failed(output)

    def _dependency_install_command_failed(self, output: str) -> bool:
        lowered = str(output or "").strip().lower()
        if not lowered:
            return False
        failure_markers = (
            "npm err!",
            "npm error",
            "yarn error",
            "pnpm error",
            "gyp err!",
            "prebuild-install err!",
            "command timed out after",
            "invalid version:",
        )
        return any(marker in lowered for marker in failure_markers)

    async def _prepare_runtime_probe(self, decision: dict, messages: list[str]) -> str | None:
        probe_path = str(decision.get("probe_path", "") or "").strip()
        probe_content = str(decision.get("probe_content", "") or "")
        if str(decision.get("command_kind", "")).strip().lower() != "runtime_probe":
            return None
        if not probe_path or not probe_content.strip():
            messages.append("⚠️ Runtime probe request was missing probe_path or probe_content.\n")
            return None
        if not probe_path.startswith(".lovable/triage/") or not probe_path.endswith(".py"):
            messages.append("⚠️ Runtime probe path must stay inside .lovable/triage/ and end with .py.\n")
            return None

        await self.tool_registry.execute(
            "write_file",
            {
                "path": probe_path,
                "content": probe_content,
            },
        )
        if not decision.get("command"):
            decision["command"] = f"python3 {probe_path}"
        messages.append(f"🧪 Prepared runtime probe: {probe_path}\n")
        return probe_path

    async def prepare_runtime_probe(self, decision: dict, messages: list[str]) -> str | None:
        return await self._prepare_runtime_probe(decision, messages)

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
        messages = []
        command_result = ""
        query_context_blocks = []
        seen_queries = set(decision.get("_resolved_query_commands", []) or [])
        existing_query_context = str(decision.get("_resolved_query_context", "") or "").strip()
        if existing_query_context:
            query_context_blocks.append(existing_query_context)

        repeated_query_blocks = 0
        # ── Triage loop caps ──────────────────────────────────────────────
        # Reduce max_query_rounds when the rule engine already has a high-
        # confidence classification — extra inspection is unlikely to help.
        source_confidence = str(decision.get("confidence", "")).strip().upper()
        source_kind = str(decision.get("source", "")).strip().lower()
        if source_kind == "rule" and source_confidence == "HIGH":
            max_query_rounds = 1
        else:
            max_query_rounds = 2

        # Hard cap: after N consecutive no-write decisions, force resolution
        consecutive_no_write = 0
        max_no_write_decisions = 2

        query_round = 0
        force_ai_followup = str(decision.get("source", "") or "").strip().lower() == "ai"
        effective_project_spec = project_spec if project_spec is not None else self.project_spec
        effective_phase_context = self._combined_phase_context(phase_context)
        effective_target_file_hint = str(target_file_hint or "").strip()

        while query_round < max_query_rounds:
            await self._prepare_runtime_probe(decision, messages)
            command = decision.get("command")
            if not command:
                break

            normalized_command = self._normalize_query_command(command)
            is_query_like = self._is_query_like_decision(decision)
            if is_query_like and normalized_command and normalized_command in seen_queries:
                repeated_query_blocks += 1
                messages.append(
                    "♻️ Repeated query command detected. Asking the decision engine to use existing evidence or choose a different query.\n"
                )
                combined_query_context = "\n\n".join(block for block in query_context_blocks if block.strip())
                combined_query_context = (
                    f"{combined_query_context}\n\n"
                    f"REPEATED QUERY COMMAND BLOCKED:\n{command}\n"
                    "The exact same query command was already executed. "
                    "Choose a different read-only query only if it adds new information; otherwise decide whether file writes are needed now."
                ).strip()
                decision = await self.decision_engine.decide(
                    error_log=error_log,
                    sandbox_dir=self.sandbox_dir,
                    query_context=combined_query_context,
                    allow_query_commands=(repeated_query_blocks < 2),
                    force_ai=force_ai_followup,
                    project_spec=effective_project_spec,
                    phase_context=effective_phase_context,
                    target_file_hint=effective_target_file_hint,
                )
                continue

            if not (query_round == 0 and pre_announced_command and command == pre_announced_command):
                messages.append(f"🛠️ Executing triage command: {command}\n")
            command_result = await self.tool_registry.execute(
                "execute_command",
                {
                    "command": command,
                    "timeout": self._triage_command_timeout(command),
                },
            )
            if is_query_like and normalized_command:
                seen_queries.add(normalized_command)

            if self._is_source_edit_decision(decision) and self._source_edit_command_failed(command_result):
                excerpt = str(command_result).strip()[:1500] or "(no output)"
                ticks = "`" * 3
                messages.append(
                    f"⚠️ Shell source edit failed:\n{ticks}text\n{excerpt}\n{ticks}\n"
                )
                messages.append("🔁 Falling back to full file rewrite for this fix.\n")
                decision["command"] = None
                decision["command_kind"] = "none"
                decision["return_query_result"] = "no"
                if decision.get("target_files"):
                    decision["write_files"] = "yes"
                break

            if self._is_dependency_install_decision(decision) and self._dependency_install_command_failed(command_result):
                excerpt = str(command_result).strip()[:1500] or "(no output)"
                ticks = "`" * 3
                messages.append(
                    f"⚠️ Dependency install command failed:\n{ticks}text\n{excerpt}\n{ticks}\n"
                )
                messages.append("🔁 Falling back to manifest/file repair for this fix.\n")
                decision["command"] = None
                decision["command_kind"] = "none"
                decision["return_query_result"] = "no"
                if decision.get("target_files"):
                    decision["write_files"] = "yes"
                break

            if decision.get("return_query_result") == "yes":
                excerpt = str(command_result).strip()[:1500] or "(no output)"
                ticks = "`" * 3
                messages.append(f"📦 Command result:\n{ticks}text\n{excerpt}\n{ticks}\n")
                query_label = "PROBE COMMAND" if decision.get("command_kind") == "runtime_probe" else "QUERY COMMAND"
                query_context_blocks.append(f"{query_label}:\n{command}\n\nQUERY RESULT:\n{excerpt}")
                query_round += 1
                if decision.get("write_files") == "no":
                    consecutive_no_write += 1
                    # Hard cap: force the engine to commit or label as false positive
                    if consecutive_no_write >= max_no_write_decisions:
                        messages.append(
                            "⚠️ Triage cap reached: too many consecutive no-write decisions. "
                            "Forcing resolution — committing to file rewrite if targets exist.\n"
                        )
                        if decision.get("target_files"):
                            decision["write_files"] = "yes"
                            decision["issue_class"] = decision.get("issue_class", "GENERATION_ERROR")
                        else:
                            decision["issue_class"] = "VALIDATOR_FALSE_POSITIVE"
                        break

                    messages.append("🔁 Re-running decision with query result before allowing file writes...\n")
                    decision = await self.decision_engine.decide(
                        error_log=error_log,
                        sandbox_dir=self.sandbox_dir,
                        query_context="\n\n".join(query_context_blocks),
                        allow_query_commands=True,
                        force_ai=force_ai_followup,
                        project_spec=effective_project_spec,
                        phase_context=effective_phase_context,
                        target_file_hint=effective_target_file_hint,
                    )
                    messages.append(
                        f"  ↳ Refined strategy: {decision.get('strategy', 'unknown')} "
                        f"(Cause: {decision.get('root_cause', 'unknown')})\n"
                    )
                    continue
            break

        decision["_resolved_query_context"] = "\n\n".join(query_context_blocks)
        decision["_resolved_query_commands"] = sorted(seen_queries)
        return decision, str(command_result), messages

    async def resolve_decision_procedure(
        self,
        decision: dict,
        *,
        error_log: str,
        pre_announced_command: str | None = None,
        project_spec: dict | None = None,
        phase_context: str = "",
        target_file_hint: str = "",
    ) -> tuple[dict, str, list[str]]:
        return await self._resolve_decision_procedure(
            decision,
            error_log=error_log,
            pre_announced_command=pre_announced_command,
            project_spec=project_spec,
            phase_context=phase_context,
            target_file_hint=target_file_hint,
        )


    async def _apply_parsed_calls(
        self,
        parsed_calls: list[dict],
        *,
        allowed_paths: list[str] | None = None,
    ) -> tuple[list[str], int, list[str]]:
        """
        Apply parsed repair actions with atomic file writes.
        Keeps execute_command support intact for the decision engine.
        """
        messages: list[str] = []
        write_entries: list[dict] = []
        written_paths: list[str] = []
        executed = 0

        for call in parsed_calls:
            if call["tool"] == "write_file":
                path = call["params"].get("path", "")
                content = call["params"].get("content", "")
                nonempty_lines = [line for line in str(content or "").splitlines() if line.strip()]
                looks_structurally_complete = any(
                    marker in str(content or "")
                    for marker in (
                        "export ",
                        "module.exports",
                        "require(",
                        "import ",
                        "function ",
                        "const ",
                        "let ",
                        "class ",
                        "interface ",
                        "type ",
                    )
                )
                if (
                    len(nonempty_lines) < 2
                    and not looks_structurally_complete
                    and not path.endswith((".json", ".env", ".gitignore", ".css"))
                ):
                    messages.append(f"⚠️ Rejected fragment for {path} ({len(nonempty_lines)} lines)\n")
                    continue
                if not path or not is_safe_generated_path(path):
                    messages.append(f"⚠️ Rejected invalid path: '{path}' (must be explicit and relative)\n")
                    continue
                normalized_content, notes = normalize_generated_file_content(path, content)
                syntax_errors = SyntaxValidator.validate(path, normalized_content, self.sandbox_dir)
                if syntax_errors:
                    preview = "; ".join(syntax_errors[:2])
                    messages.append(f"⚠️ Rejected syntax-invalid repair file {path}: {preview}\n")
                    continue
                for note in notes:
                    messages.append(f"ℹ️ {note}\n")
                write_entries.append({"path": path, "content": normalized_content})

        allowed_set = {
            str(path or "").strip().replace("\\", "/")
            for path in list(allowed_paths or [])
            if str(path or "").strip()
        }
        filtered_entries: list[dict] = []
        dropped_out_of_scope: list[str] = []
        for entry in write_entries:
            path = str((entry or {}).get("path", "") or "").strip().replace("\\", "/")
            if not path:
                continue
            if allowed_set and path not in allowed_set:
                dropped_out_of_scope.append(path)
                continue
            filtered_entries.append({"path": path, "content": str((entry or {}).get("content", "") or "")})

        if dropped_out_of_scope:
            preview = ", ".join(dropped_out_of_scope[:8]) + ("..." if len(dropped_out_of_scope) > 8 else "")
            messages.append(
                "ℹ️ Ignored out-of-scope repair file(s): "
                f"{preview}\n"
            )

        if filtered_entries:
            result = await self.tool_registry.execute(
                "write_batch",
                {
                    "files": filtered_entries,
                    "allowed_paths": list(allowed_paths or []),
                },
            )
            result_text = str(result or "")
            if result_text.lower().startswith("error:"):
                messages.append(f"⚠️ Batch write rejected:\n{result_text}\n")
            else:
                written_paths = [entry["path"] for entry in filtered_entries]

        for call in parsed_calls:
            if call["tool"] != "execute_command":
                continue
            cmd = call["params"].get("command", "")
            messages.append(f"🛠️ Executing command: {cmd}\n")
            try:
                await self.tool_registry.execute(call["tool"], call["params"])
                executed += 1
            except Exception as e:
                messages.append(f"⚠️ Command failed: {str(e)}\n")

        return written_paths, executed, messages

    async def run_phase_repair(self, phase: str, errors: list, attempt: int = 1, rv=None) -> AsyncIterator[str]:
        """
        Main entry point. Routes to the specific phase repair mechanism.
        errors format depends on phase.
        """
        if phase == "generation":
            broken_file = errors[0]
            error_log = errors[1]
            async for msg in self._fix_syntax_error(self.sandbox_dir, broken_file, error_log, attempt):
                yield msg

        elif phase == "build":
            build_error = errors[0]
            async for msg in self._auto_fix_build(self.sandbox_dir, build_error, attempt):
                yield msg

        elif phase == "runtime":
            error_type = errors[0]
            if error_type == "ui":
                issues = errors[1]
                async for msg in self._run_ui_self_healing(rv, issues):
                    yield msg
            elif error_type == "sync":
                bf = errors[1]
                combined_error = errors[2]
                async for msg in self._fix_syntax_error(self.sandbox_dir, bf, combined_error, attempt):
                    yield msg
            elif error_type == "backend":
                broken_file = errors[1]
                error_log = errors[2]
                async for msg in self._run_backend_self_healing(rv, broken_file, error_log):
                    yield msg
            elif error_type == "backend_unknown":
                error_log = errors[1]
                yield f"🧠 Deep Triage: Investigating runtime error with AI Decision Engine...\n"
                decision = await self.decision_engine.decide(
                    error_log=error_log,
                    sandbox_dir=self.sandbox_dir,
                    force_ai=True,
                    project_spec=self.project_spec,
                    phase_context=self._combined_phase_context("runtime phase: backend_unknown"),
                    target_file_hint=self._target_hint_from_error_log(error_log),
                )
                pre_announced_command = None
                if self._should_preannounce_decision_command(decision):
                    pre_announced_command = decision.get("command")
                    yield f"🛠️ Executing triage command: {pre_announced_command}\n"
                decision, _cmd_result, procedure_messages = await self._resolve_decision_procedure(
                    decision,
                    error_log=error_log,
                    pre_announced_command=pre_announced_command,
                    project_spec=self.project_spec,
                    phase_context="runtime phase: backend_unknown",
                    target_file_hint=self._target_hint_from_error_log(error_log),
                )
                for message in procedure_messages:
                    yield message

                if self._is_dependency_install_decision(decision):
                    yield f"Fixed: Dependency installed ({decision['command']}). Retrying...\n"
                    return
                if self._is_source_edit_decision(decision):
                    yield f"Fixed: Shell source edit applied ({decision.get('command') or 'source edit'}). Retrying...\n"
                    return
                if self._is_mutation_decision(decision):
                    yield f"Fixed: Mutation command applied ({decision.get('command') or 'mutation'}). Retrying...\n"
                    return
                if decision.get("write_files") == "no":
                    yield "ℹ️ Query-only triage indicated no file rewrite is needed right now.\n"
                    return

                triage_log = (
                    "Runtime Error Triage:\n"
                    f"Root Cause: {decision.get('root_cause', 'Unknown')}\n"
                    f"Hint: {decision.get('fix_hint', 'Investigate the failing runtime path carefully.')}\n"
                    f"Targets: {', '.join(decision.get('target_files', []))}\n\n"
                    f"Original Error:\n{error_log}"
                )
                async for msg in self._fix_unknown_error(self.sandbox_dir, triage_log, attempt):
                    yield msg
            else:
                broken_file = errors[1]
                error_log = errors[2]

                analysis = self.error_analyzer.analyze(error_log)
                if analysis["type"] == "UNKNOWN" or "DEPENDENCY" in analysis["type"]:
                    yield f"🧠 Deep Triage: Investigating runtime error with AI Decision Engine...\n"
                    decision = await self.decision_engine.decide(
                        error_log=error_log,
                        sandbox_dir=self.sandbox_dir,
                        force_ai=True,
                        project_spec=self.project_spec,
                        phase_context=self._combined_phase_context(f"runtime phase: {error_type}"),
                        target_file_hint=self._target_hint_from_error_log(error_log, broken_file),
                    )
                    analysis["type"] = decision.get("strategy", analysis["type"])
                    analysis["fix"]  = decision.get("fix_hint", analysis.get("fix", ""))
                    pre_announced_command = None
                    if self._should_preannounce_decision_command(decision):
                        pre_announced_command = decision.get("command")
                        yield f"🛠️ Executing triage command: {pre_announced_command}\n"
                    decision, _cmd_result, procedure_messages = await self._resolve_decision_procedure(
                        decision,
                        error_log=error_log,
                        pre_announced_command=pre_announced_command,
                        project_spec=self.project_spec,
                        phase_context=f"runtime phase: {error_type}",
                        target_file_hint=self._target_hint_from_error_log(error_log, broken_file),
                    )
                    for message in procedure_messages:
                        yield message

                    analysis["type"] = decision.get("strategy", analysis["type"])
                    analysis["fix"]  = decision.get("fix_hint", analysis.get("fix", ""))
                    if self._is_dependency_install_decision(decision):
                        yield f"Fixed: Dependency installed ({decision['command']}). Retrying...\n"
                        return
                    if self._is_source_edit_decision(decision):
                        yield f"Fixed: Shell source edit applied ({decision.get('command') or 'source edit'}). Retrying...\n"
                        return
                    if self._is_mutation_decision(decision):
                        yield f"Fixed: Mutation command applied ({decision.get('command') or 'mutation'}). Retrying...\n"
                        return
                    if decision.get("write_files") == "no":
                        yield "ℹ️ Query-only triage indicated no file rewrite is needed right now.\n"
                        return
                    if decision.get("target_files"):
                        broken_file = ", ".join(decision["target_files"])

                yield f"  ↳ Strategy: {analysis['type']} (Target: {broken_file})\n"

                # If it's a generic install or terminal fix, generic triage handles commands better:
                if "install" in analysis["type"].lower() or "dependency" in analysis["type"].lower():
                    async for msg in self._fix_unknown_error(self.sandbox_dir, error_log + f"\n\nHint: {analysis.get('fix', '')}", attempt):
                        yield msg
                else:
                    async for msg in self._fix_syntax_error(self.sandbox_dir, broken_file, f"Runtime Error Triage:\nHint: {analysis.get('fix', '')}\n\nOriginal Error:\n{error_log}", attempt):
                        yield msg

        elif phase == "unknown_error":
            error_log = errors[0]
            async for msg in self._fix_unknown_error(self.sandbox_dir, error_log, attempt):
                yield msg
        else:
            yield f"⚠️ Unknown phase: {phase}\n"

    async def _run_ui_self_healing(self, rv, issues: list) -> AsyncIterator[str]:
        from .ui_fix_engine import UIFixEngine

        UI_HEAL_MAX = 10  # increased from 5 to 10
        api_base = "/api"
        try:
            vite_cfg = os.path.join(self.sandbox_dir, "vite.config.ts")
            if os.path.exists(vite_cfg):
                with open(vite_cfg, "r") as f:
                    cfg_text = f.read()
                m = re.search(r"target:\s*['\"]http[s]?://[^'\"]+:(\d+)['\"]", cfg_text)
                if m:
                    api_base = f"http://localhost:{m.group(1)}/api"
        except Exception:
            pass

        existing_files = []
        for root, _dirs, files in os.walk(os.path.join(self.sandbox_dir, "src")):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), self.sandbox_dir)
                existing_files.append(rel)

        context = {
            "sandbox_dir":    self.sandbox_dir,
            "api_base":       api_base,
            "existing_files": existing_files,
        }

        engine = UIFixEngine(self.sandbox_dir, self.tool_registry, provider=self.provider)
        engine.logger = self.logger if hasattr(self, "logger") else logging.getLogger(__name__)

        try:
            actions = await engine.generate_ui_fix(issues, context)
        except Exception as e:
            yield f"⚠️  UIFixEngine.generate_ui_fix failed: {e}. Falling back to AI fix...\n"
            async for msg in self._fix_unknown_error(self.sandbox_dir, "FEATURE_VALIDATION_BRIDGE_ERROR\n" + "\n".join(issues), 1):
                yield msg
            return

        if not actions:
            yield "ℹ️  UIFixEngine produced no actions — delegating to AI fix path...\n"
            async for msg in self._fix_unknown_error(self.sandbox_dir, "FEATURE_VALIDATION_BRIDGE_ERROR\n" + "\n".join(issues), 1):
                yield msg
            return

        yield f"🧩 UIFixEngine planned {len(actions)} file action(s):\n"
        for a in actions:
            yield f"  [{a['type'].upper()}] {a['file']}\n"

        for action in actions:
            try:
                status = await engine.apply_action(action)
                yield f"  {status}\n"
            except Exception as e:
                yield f"  ❌ apply_action failed for {action.get('file', '?')}: {e}\n"

        patch_status = await engine.patch_app_jsx(actions)
        yield f"  {patch_status}\n"

        has_navbar_action = any("Navbar" in a.get("file", "") for a in actions)
        if has_navbar_action:
            nav_status = await engine.inject_navbar()
            yield f"  {nav_status}\n"

        for heal_attempt in range(1, UI_HEAL_MAX + 1):
            yield f"\n🔍 UI Self-Heal validation (attempt {heal_attempt}/{UI_HEAL_MAX})...\n"
            try:
                re_check = await rv.run_browser_check()
            except Exception as e:
                yield f"  ⚠️  browser_check failed: {e}\n"
                break

            remaining = await rv.check_missing_ui(re_check)
            if not remaining:
                yield "✅ All UI features now detected — self-healing complete!\n"
                return
            yield f"  Still missing ({len(remaining)}): {remaining}\n"
            if heal_attempt == UI_HEAL_MAX:
                yield "❌ Self-healing could not fully resolve UI issues. Delegating to AI fix...\n"
                async for msg in self._fix_unknown_error(self.sandbox_dir, "FEATURE_VALIDATION_BRIDGE_ERROR\n" + "\n".join(remaining), heal_attempt):
                    yield msg

    async def _run_backend_self_healing(self, rv, broken_file: str, error_log: str) -> AsyncIterator[str]:
        """
        Granular loop that attempts to fix backend crashes by checking health
        after each repair attempt.
        """
        BACKEND_HEAL_MAX = 5
        
        for heal_attempt in range(1, BACKEND_HEAL_MAX + 1):
            yield f"\n🔍 Backend Self-Heal validation (attempt {heal_attempt}/{BACKEND_HEAL_MAX})...\n"
            
            # 1. First attempt uses the error log passed from AgentLoop
            current_log = error_log if heal_attempt == 1 else None
            
            # 2. Subsequent attempts need a fresh check
            if not current_log:
                try:
                    # Check if the validator is RuntimeValidator or FeatureValidator
                    if hasattr(rv, "run_backend_check"):
                        res = await rv.run_backend_check()
                    elif hasattr(rv, "validate_backend_runtime"):
                        is_ok, err = rv.validate_backend_runtime()
                        res = {"status": "ok" if is_ok else "error", "errors": [err] if err else []}
                    else:
                        yield "  ⚠️ No compatible validator method found on rv object.\n"
                        break

                    if res.get("status") != "error":
                        yield "✅ Backend is now healthy — self-healing complete!\n"
                        yield f"Fixed: Backend validated at http://localhost:{self.backend_port}/api/health\n"
                        return
                    current_log = res.get("errors", ["Backend initialization failed"])[0]
                except Exception as e:
                    yield f"  ⚠️ Validation failed: {e}\n"
                    break

            # 3. Analyze and fix
            decision = await self.decision_engine.decide(
                error_log=current_log,
                sandbox_dir=self.sandbox_dir,
                project_spec=self.project_spec,
                phase_context=self._combined_phase_context("runtime phase: backend"),
                target_file_hint=self._target_hint_from_error_log(current_log, broken_file),
            )
            target_list = decision.get("target_files") or [broken_file]
            target = ", ".join(target_list)
            
            yield f"  ↳ Detected: {decision.get('strategy', 'Unknown')} on {target}\n"
            
            pre_announced_command = None
            if self._should_preannounce_decision_command(decision):
                pre_announced_command = decision.get("command")
                yield f"  🛠️ Executing triage command: {pre_announced_command}\n"
            decision, _cmd_result, procedure_messages = await self._resolve_decision_procedure(
                decision,
                error_log=current_log,
                pre_announced_command=pre_announced_command,
                project_spec=self.project_spec,
                phase_context="runtime phase: backend",
                target_file_hint=self._target_hint_from_error_log(current_log, broken_file),
            )
            for message in procedure_messages:
                yield f"  {message}" if not message.startswith("  ") else message

            target_list = decision.get("target_files") or [broken_file]
            target = ", ".join(target_list)
            if self._is_dependency_install_decision(decision):
                yield f"  ✅ Dependency installed ({decision.get('command')}). Restarting backend for re-validation...\n"
            elif self._is_source_edit_decision(decision):
                yield f"  ✅ Shell source edit applied ({decision.get('command') or 'source edit'}). Restarting backend for re-validation...\n"
            elif decision.get("write_files") == "no":
                yield "  ℹ️ Query-only triage requested no file rewrite for this attempt.\n"
                break
            else:
                strategy_key = str(decision.get("strategy", "") or "").strip().lower()
                no_rewrite_runtime_strategies = {
                    "backend_server_running_no_error",
                    "successful_server_start_no_errors",
                    "verify_server_startup",
                }
                if strategy_key in no_rewrite_runtime_strategies:
                    probe_result = await self.tool_registry.execute(
                        "execute_command",
                        {
                            "command": (
                                f"curl -fsS http://127.0.0.1:{self.backend_port}/api/health "
                                ">/tmp/.backend_health_probe 2>/dev/null && echo HEALTH_OK || echo HEALTH_FAIL"
                            ),
                            "timeout": 8,
                        },
                    )
                    if "HEALTH_OK" in str(probe_result or ""):
                        yield "✅ Backend is now healthy — self-healing complete!\n"
                        yield f"Fixed: Backend validated at http://localhost:{self.backend_port}/api/health\n"
                        return
                    yield (
                        "  ℹ️ Decision indicates backend already booted without runtime errors. "
                        "Skipping redundant file rewrite for this attempt.\n"
                    )
                    continue

                # 4. Prompt AI for code fix
                async for msg in self._fix_syntax_error(self.sandbox_dir, target, current_log, heal_attempt):
                    yield msg
            
            # 5. Restart backend for next check
            yield "  ♻️ Restarting backend for re-validation...\n"
            # Generated projects use `dev` for Vite and `server` for the backend.
            # Restart only the backend process here to avoid Vite watcher explosions.
            secondary_port = int(self.backend_port) + 1
            restart_cmd = (
                f"fuser -k {self.backend_port}/tcp {secondary_port}/tcp 5000/tcp 5001/tcp "
                "2>/dev/null || true; sleep 1; "
                "sh -lc '"
                "npm run server > /tmp/sandbox_server.log 2>&1 || "
                "node --import tsx server/index.ts > /tmp/sandbox_server.log 2>&1 || "
                "npx tsx server/index.ts > /tmp/sandbox_server.log 2>&1 || "
                "./node_modules/.bin/tsx server/index.ts > /tmp/sandbox_server.log 2>&1"
                "' >/dev/null 2>&1 & echo $!"
            )
            await self.tool_registry.execute("execute_command", {
                "command": restart_cmd,
                "timeout": 10
            })
            await asyncio.sleep(5) # Give it time to boot

        yield "❌ Backend self-healing reached max attempts without success.\n"

    async def _auto_fix_build(self, sandbox: str, build_error: str, attempt: int) -> AsyncIterator[str]:
        if attempt >= 20:
             return

        if self._is_tsconfig_contract_error(build_error):
            yield "🔧 Deterministic TSConfig repair: applying constrained tsconfig-only fix.\n"
            for path in self._write_canonical_tsconfig_pair(sandbox):
                yield f"📁 Fixed: {path}\n"
            return

        analysis = self.error_analyzer.analyze(build_error)
        
        # --- AI DECISION ENGINE INTEGRATION ---
        # Missing dependencies should go through the decision engine too so it can
        # return an install command instead of falling into generic file rewrites.
        if analysis["type"] in {"UNKNOWN", "MISSING_DEPENDENCY"}:
            yield f"🧠 Deep Triage: Investigating build error with AI Decision Engine...\n"
            decision = await self.decision_engine.decide(
                error_log=build_error,
                sandbox_dir=sandbox,
                force_ai=True,
                project_spec=self.project_spec,
                phase_context=self._combined_phase_context("build phase"),
                target_file_hint=self._target_hint_from_error_log(build_error),
            )
            analysis["type"] = decision.get("strategy", "UNKNOWN")
            analysis["fix"]  = decision.get("fix_hint", analysis.get("fix", ""))
            
            pre_announced_command = None
            if self._should_preannounce_decision_command(decision):
                pre_announced_command = decision.get("command")
                yield f"🛠️ Executing triage command: {pre_announced_command}\n"
            decision, _cmd_result, procedure_messages = await self._resolve_decision_procedure(
                decision,
                error_log=build_error,
                pre_announced_command=pre_announced_command,
                project_spec=self.project_spec,
                phase_context="build phase",
                target_file_hint=self._target_hint_from_error_log(build_error),
            )
            for message in procedure_messages:
                yield message

            analysis["type"] = decision.get("strategy", analysis["type"])
            analysis["fix"]  = decision.get("fix_hint", analysis.get("fix", ""))
            if self._is_dependency_install_decision(decision):
                yield f"Fixed: Dependency installed ({decision['command']}). Rebuilding...\n"
                return
            if self._is_source_edit_decision(decision):
                yield f"Fixed: Shell source edit applied ({decision.get('command') or 'source edit'}). Rebuilding...\n"
                return
            if decision.get("write_files") == "no":
                yield "ℹ️ Query-only triage indicated no file rewrite is needed right now.\n"
                return

            decision_targets = self._normalize_repair_targets(decision.get("target_files") or [])
            decision_text = " ".join(
                [
                    str(decision.get("strategy", "") or ""),
                    str(decision.get("root_cause", "") or ""),
                    str(decision.get("fix_hint", "") or ""),
                ]
            ).lower()
            if any(path.startswith("tsconfig") for path in decision_targets) and (
                "noemit" in decision_text
                or "composite" in decision_text
                or "allowimportingtsextensions" in decision_text
            ):
                repair_scope = ["tsconfig.json", "tsconfig.node.json"]
            else:
                repair_scope = self._merge_repair_targets(
                    decision_targets,
                    self._context_repair_targets(),
                    [self._target_hint_from_error_log(build_error)],
                )
            if len(repair_scope) > 6:
                original_size = len(repair_scope)
                repair_scope = repair_scope[:6]
                yield (
                    "ℹ️ Build-phase precision guard: constrained repair scope "
                    f"from {original_size} to {len(repair_scope)} files.\n"
                )
            # If the engine actually found a specific file to target, we should hijack the fix
            # and send it strictly to that file instead of doing a generic overall "UNKNOWN Fix"
            if analysis["type"] != "UNKNOWN" and repair_scope:
                target_preview = ", ".join(repair_scope[:6])
                if len(repair_scope) > 6:
                    target_preview += ", ..."
                yield f"  ↳ AI decided repair scope: {target_preview} (Strategy: {analysis['type']})\n"
                # We can't use _fix_missing_import (since it expects a missing module) but we CAN use _fix_syntax_error 
                # because the system prompts for syntax errors just pass the file and the error log directly.
                async for token in self._fix_syntax_error(
                    sandbox,
                    ", ".join(repair_scope),
                    f"Build Error Triage:\n{decision.get('root_cause', '')}\n\nHint: {analysis['fix']}\n\nOriginal Error:\n{build_error}",
                    attempt,
                    authorized_targets=repair_scope,
                ):
                    yield token
                return

        if analysis["type"] == "RECURSIVE_FAILURE":
             yield "🛑 Stopping: AI is repeating the same invalid fix. Manual intervention required or strategy switch.\n"
             return

        # --- BUILD CONFIGURATION HARDENING ---
        # Prioritize checking tsconfig.json validity before we fall into any "export mismatch" hallucinations
        tsconfig_path = os.path.join(sandbox, "tsconfig.json")
        has_invalid_tsconfig = False
        if os.path.exists(tsconfig_path):
            try:
                with open(tsconfig_path, "r") as f:
                    ts_content = f.read()
                # Remove comments to parse JSON
                clean_ts = re.sub(r'//.*?\n|/\*.*?\*/', '', ts_content, flags=re.S)
                cfg = json.loads(clean_ts)
                mod_res = cfg.get("compilerOptions", {}).get("moduleResolution", "")
                include_paths = cfg.get("include", [])
                if str(mod_res).lower() in ["node", "node10", ""]:
                    has_invalid_tsconfig = True
                    yield f"⚠️ Warning: tsconfig.json has deprecated moduleResolution '{mod_res}'.\n"
                if any(str(path).strip() == "server" for path in include_paths):
                    has_invalid_tsconfig = True
                    yield "⚠️ Warning: tsconfig.json includes 'server', which causes frontend builds to typecheck CommonJS backend files.\n"
            except Exception as e:
                # Syntax error or unreadable
                has_invalid_tsconfig = True
                yield f"⚠️ JSON Syntax Error in tsconfig.json: {e}\n"

        if has_invalid_tsconfig or self._is_tsconfig_contract_error(build_error) or (
            "tsconfig.json" in build_error and ("TS50" in build_error or "TS60" in build_error)
        ):
            yield "🔧 Forcing rebuild with deterministic tsconfig pair (no broad rewrite).\n"
            for path in self._write_canonical_tsconfig_pair(sandbox):
                yield f"📁 Fixed: {path}\n"
            return

        yield f"📝 Analyzed error: {analysis['type']}. Severity: {analysis.get('severity', 'MEDIUM')}.\n"
        if analysis["type"] == "UNKNOWN" and "decision" in locals():
            yield f"  ↳ Root Cause: {decision.get('root_cause', 'Unknown')}\n"
        
        import_match = re.search(r"Module not found: Error: Can't resolve '(.*?)' in '(.*?)'", build_error)
        if import_match:
            missing_import = import_match.group(1)
            source_file = import_match.group(2)
            yield f"⚠️ Missing import: {missing_import} in {source_file}\n"
            async for token in self._fix_missing_import(sandbox, missing_import, source_file, attempt):
                yield token
            return

        if "terser" in build_error.lower():
            vite_path = os.path.join(sandbox, "vite.config.ts")
            if os.path.exists(vite_path):
                with open(vite_path) as f:
                    content = f.read()
                if "build:" not in content:
                    new_content = content.replace("export default defineConfig({", "export default defineConfig({\n  build: { minify: false },")
                else:
                    new_content = content.replace("build: {", "build: { minify: false,")
                with open(vite_path, "w") as f:
                    f.write(new_content)
                yield "📦 Fixed: vite.config.ts (disabled terser)\n"
                return

        import_match = re.search(r'Failed to resolve import ["\']([^"\']+)["\'] from ["\']([^"\']+)["\']', build_error)
        if import_match:
            missing_import = import_match.group(1)
            source_file = import_match.group(2)
            yield f"⚠️ Missing import: {missing_import} in {source_file}\n"
            async for token in self._fix_missing_import(sandbox, missing_import, source_file, attempt):
                yield token
            return

        syntax_match = re.search(r'(?:SyntaxError|Transform failed).*\n\s*(?:at\s+)?(?P<path>[^:\s]+\.(?:jsx?|tsx?))', build_error, re.IGNORECASE)
        if syntax_match:
            clean_path = syntax_match.group("path").split("?")[0].strip()
            if os.path.isabs(clean_path):
                rel_path = os.path.relpath(clean_path, sandbox) if clean_path.startswith(sandbox) else clean_path
            else:
                rel_path = clean_path
            yield f"⚠️ Syntax error in: {rel_path}\n"
            async for token in self._fix_syntax_error(sandbox, rel_path, build_error, attempt):
                yield token
            return

        export_match = re.search(r'["\'](.*?)["\'] is not exported by ["\'](.*?)["\'], imported by ["\'](.*?)["\']\.', build_error)
        if export_match:
            missing_export = export_match.group(1)
            source_file = export_match.group(2)
            importing_file = export_match.group(3)
            yield f"⚠️ Export mismatch: '{missing_export}' not found in {source_file} (imported by {importing_file})\n"
            async for token in self._fix_syntax_error(sandbox, importing_file, f"Build Error: {importing_file} tries to import '{missing_export}' from {source_file}, but it is not exported. Update the import statement in {importing_file} to match the actual exports of {source_file}.", attempt):
                yield token
            return

        # TypeScript build output includes precise file paths. Prefer those over
        # generic AI triage so we don't drift into unrelated server fixes.
        ts_targets = []
        for match in re.finditer(r'((?:src|server)/[^(\s]+\.(?:ts|tsx|js|jsx))\(\d+,\d+\):\s*error\s*TS\d+', build_error, re.IGNORECASE):
            path = match.group(1)
            if path not in ts_targets:
                ts_targets.append(path)
            if len(ts_targets) >= 4:
                break

        if ts_targets:
            broken_files = ", ".join(ts_targets)
            yield f"⚠️ TypeScript build errors detected in: {broken_files}\n"
            async for token in self._fix_syntax_error(sandbox, broken_files, build_error, attempt):
                yield token
            return

        async for token in self._fix_unknown_error(sandbox, build_error, attempt):
            yield token

    async def _fix_missing_import(self, sandbox: str, missing_import: str, source_file: str, attempt: int) -> AsyncIterator[str]:
        from ..providers import is_provider_status_token
        analysis = self.error_analyzer.analyze(f"Missing import: {missing_import}", source_file)
        context = self.context_builder.build_context()
        full_path = os.path.join(sandbox, source_file.lstrip("/"))
        try:
            with open(full_path, "r", encoding="utf-8") as f: content = f.read()
        except: content = "// File not found or empty"

        repair_prompt = get_repair_prompt(
            filename=missing_import,
            error_log=f"Build Error: Failed to resolve import '{missing_import}' from '{source_file}'",
            content="// (New file to be created)",
            context=self._compose_repair_context(f"Imported by {source_file}:\n{content[:2000]}\n\n{context}"),
            strategy=analysis["fix"],
        )
        messages = [
            {"role": "system", "content": (
                "You are fixing code files. STRICT RULES:\n"
                "1. Output COMPLETE, FULL files — NEVER output partial snippets.\n"
                "2. EVERY file MUST start with: // FILE: <relative-path>\n"
                "3. Include ALL imports, ALL functions, ALL exports.\n"
                "4. Wrap each file in a markdown code block.\n"
                "5. Do NOT output explanations, only code blocks.\n"
                "6. Avoid 'sudo' commands. For ENOSPC errors, configure 'usePolling: true' in vite.config.ts instead of changing system limits."
            )},
            {"role": "user", "content": repair_prompt}
        ]
        response = ""
        async for token in self.provider.stream(messages, self.model_id):
            if is_provider_status_token(token):
                yield token if str(token).endswith("\n") else f"{token}\n"
                continue
            response += token
            yield token

        written_paths, _executed, messages = await self._apply_parsed_calls(self._parse_tool_calls(response))
        for message in messages:
            yield message
        for path in written_paths:
            yield f"📁 Created/Fixed: {path}\n"

    async def _fix_syntax_error(
        self,
        sandbox: str,
        broken_file: str,
        error_log: str,
        attempt: int,
        authorized_targets: list[str] | None = None,
    ) -> AsyncIterator[str]:
        from ..providers import is_provider_status_token
        requested_targets = [f.strip() for f in broken_file.split(",") if f.strip()]
        if authorized_targets:
            file_names = self._merge_repair_targets(
                requested_targets,
                authorized_targets,
            ) or self._normalize_repair_targets(authorized_targets)
        else:
            file_names = self._merge_repair_targets(
                requested_targets,
                self._context_repair_targets(),
            ) or requested_targets
        file_contents_parts = []
        for fname in file_names:
            full_path = os.path.join(sandbox, fname)
            try:
                with open(full_path, "r", encoding="utf-8") as f: file_contents_parts.append(f"// CURRENT FILE: {fname}\n{f.read()}")
            except Exception: file_contents_parts.append(f"// CURRENT FILE: {fname}\n[FILE NOT FOUND]")
        all_file_contents = "\n\n".join(file_contents_parts)
        context = self.context_builder.build_context()

        repair_prompt = get_repair_prompt(
            filename=broken_file,
            error_log=error_log,
            content=all_file_contents,
            context=self._compose_repair_context(context),
            strategy=(
                "The Master Blueprint Contract is the primary source of truth. "
                "Review the ERROR LOG carefully. If there is architectural drift, "
                "regenerate ALL affected files in this cluster to maintain consistency with the blueprint. "
                "Rewrite each file COMPLETELY with its FULL content."
            ),
            authorized_targets=file_names,
        )
        messages = [
            {"role": "system", "content": (
                "You are fixing code files and build processes. STRICT RULES:\n"
                "1. If you need to rewrite a file, output the COMPLETE, FULL file — NEVER partial snippets.\n"
                "2. 1 BLOCK = 1 FILE: NEVER group multiple files into a single code block. Each file MUST have its own dedicated markdown block starting with exactly one path: // FILE: <relative-path>.\n"
                "3. CRITICAL BACKEND POLICY: files under server/ MUST form a 100% ESM architecture (`import`, `export`). NO legacy CommonJS (`require`, `module.exports`) is allowed!\n"
                "4. Use the MASTER BLUEPRINT CONTRACT as the source of truth for all exports, imports, and dependencies.\n"
                "5. Wrap each file in markdown code blocks (```typescript ... ```).\n"
                "6. Terminal Commands: If you also (or only) need to run a command (like npm install), output:\n"
                "<execute_command><command>npm install package-name</command></execute_command>\n"
                "7. Combine file modifications and terminal commands in a single response to resolve the error.\n"
                "8. Do NOT output explanations. VIOLATION OF ANY RULE = INVALID OUTPUT.\n"
                "9. Avoid 'sudo'. For ENOSPC, use 'usePolling: true' in vite.config.ts."
            )},
            {"role": "user", "content": repair_prompt}
        ]
        response = ""
        async for token in self.provider.stream(messages, self.model_id):
            if is_provider_status_token(token):
                yield token if str(token).endswith("\n") else f"{token}\n"
                continue
            response += token
            yield token

        parsed_calls = self._parse_tool_calls(response, expected_files=file_names)
        written_paths, executed, messages = await self._apply_parsed_calls(
            parsed_calls,
            allowed_paths=file_names,
        )
        for message in messages:
            yield message
        for path in written_paths:
            yield f"📁 Fixed: {path}\n"
        
        if len(written_paths) == 0 and executed == 0 and len(file_names) > 0:
            yield "⚠️ No valid files or commands were produced by the AI — fix may have failed.\n"

    async def _fix_unknown_error(
        self,
        sandbox: str,
        build_error: str,
        attempt: int,
        authorized_targets: list[str] | None = None,
    ) -> AsyncIterator[str]:
        from ..providers import is_provider_status_token
        """
        Fix an unknown error by reading all files mentioned in the error log first,
        then sending their full content to the AI for repair.
        """
        context = self.context_builder.build_context()

        # ── Step 1: Extract file paths from the error log ──────────────────────
        # Look for patterns like server/foo.ts, src/components/Bar.tsx etc.
        mentioned_files = []
        for match in re.finditer(
            r'(?:server|src)/[^\s:()"\',]+\.(?:tsx|ts|jsx|js)',
            build_error
        ):
            fpath = match.group(0).strip()
            if 'node_modules' not in fpath and fpath not in mentioned_files:
                mentioned_files.append(fpath)

        # ── Step 2: Read full content of each mentioned file ───────────────────
        if authorized_targets:
            repair_scope = self._merge_repair_targets(
                mentioned_files,
                authorized_targets,
            ) or self._normalize_repair_targets(authorized_targets)
        else:
            repair_scope = self._merge_repair_targets(
                mentioned_files,
                self._context_repair_targets(),
            )

        file_contents_parts = []
        if repair_scope:
            for fname in repair_scope[:5]:  # cap at 5 files to avoid token overload
                full_path = os.path.join(sandbox, fname)
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    file_contents_parts.append(
                        f"// CURRENT FILE: {fname}\n{content}"
                    )
                except Exception:
                    file_contents_parts.append(
                        f"// CURRENT FILE: {fname}\n[FILE NOT FOUND OR UNREADABLE]"
                    )
        else:
            file_contents_parts.append(
                "// No specific file identified in error log — see error details below"
            )

        all_file_contents = "\n\n".join(file_contents_parts)

        repair_prompt = get_repair_prompt(
            filename="Unknown (see error log)",
            error_log=build_error,
            content=all_file_contents,
            context=self._compose_repair_context(context),
            strategy=(
                "Analyze the ERROR LOG carefully. Identify which file(s) contain the bug. "
                "Rewrite each broken file completely with its FULL content — "
                "do NOT truncate or omit any part of the file."
            ),
            authorized_targets=repair_scope,
        )
        messages = [
            {"role": "system", "content": (
                "You are fixing code files and build processes. STRICT RULES:\n"
                "1. If you need to rewrite a file, output the COMPLETE, FULL file — NEVER partial snippets.\n"
                "2. 1 BLOCK = 1 FILE: NEVER group multiple files into a single code block. Each file MUST have its own dedicated markdown block starting with exactly one path: // FILE: <relative-path>.\n"
                "3. CRITICAL BACKEND POLICY: files under server/ MUST form a 100% ESM architecture (`import`, `export`). NO legacy CommonJS (`require`, `module.exports`) is allowed!\n"
                "4. Wrap each file in a markdown code block.\n"
                "5. Terminal Commands: If you also (or only) need to run a command (like npm install or testing setups), output:\n"
                "<execute_command><command>npm install package-name</command></execute_command>\n"
                "6. You can freely combine file modifications and terminal commands in a single response to resolve the error.\n"
                "7. Do NOT output explanations.\n"
                "8. Avoid 'sudo'. For ENOSPC errors, configure 'usePolling: true' in vite.config.ts instead of changing system limits."
            )},
            {"role": "user",   "content": repair_prompt}
        ]
        response = ""
        async for token in self.provider.stream(messages, self.model_id):
            if is_provider_status_token(token):
                yield token if str(token).endswith("\n") else f"{token}\n"
                continue
            response += token
            yield token

        written_paths, _executed, messages = await self._apply_parsed_calls(
            self._parse_tool_calls(response, expected_files=repair_scope),
            allowed_paths=repair_scope,
        )
        for message in messages:
            yield message
        for path in written_paths:
            yield f"📁 Fixed: {path}\n"
