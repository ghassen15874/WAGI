import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.orchestrator.loop import AgentLoop


class _StubUnifiedRepair:
    def __init__(self) -> None:
        self.decision_call = None

    def normalize_query_command(self, command):
        return f"normalized:{command}"

    def triage_command_timeout(self, command):
        return 77 if command else 30

    def should_preannounce_decision_command(self, decision):
        return decision.get("command") == "echo test"

    def is_query_like_decision(self, decision):
        return decision.get("command_kind") == "query"

    def is_dependency_install_decision(self, decision):
        return decision.get("command_kind") == "dependency_install"

    def is_source_edit_decision(self, decision):
        return decision.get("command_kind") == "source_edit"

    def source_edit_command_failed(self, output):
        return "failed" in str(output)

    async def prepare_runtime_probe(self, decision, messages):
        messages.append("probe\n")
        return decision.get("probe_path")

    async def resolve_decision_procedure(
        self,
        decision,
        *,
        error_log,
        pre_announced_command=None,
        project_spec=None,
        phase_context="",
        target_file_hint="",
    ):
        self.decision_call = {
            "decision": decision,
            "error_log": error_log,
            "pre_announced_command": pre_announced_command,
            "project_spec": project_spec,
            "phase_context": phase_context,
            "target_file_hint": target_file_hint,
        }
        return {"ok": True}, "command-result", ["message\n"]


class TestLoopRepairDelegation:
    def test_loop_delegates_repair_helpers_to_unified_repair(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.unified_repair = _StubUnifiedRepair()

        assert loop._normalize_query_command("Echo Test") == "normalized:Echo Test"
        assert loop._triage_command_timeout("npm install") == 77
        assert loop._should_preannounce_decision_command({"command": "echo test"}) is True
        assert loop._is_query_like_decision({"command_kind": "query"}) is True
        assert loop._is_dependency_install_decision({"command_kind": "dependency_install"}) is True
        assert loop._is_source_edit_decision({"command_kind": "source_edit"}) is True
        assert loop._source_edit_command_failed("shell failed badly") is True

        messages: list[str] = []
        result = asyncio.run(loop._prepare_runtime_probe({"probe_path": ".lovable/triage/check.py"}, messages))
        assert result == ".lovable/triage/check.py"
        assert messages == ["probe\n"]

    def test_loop_delegates_decision_resolution_to_unified_repair(self):
        loop = AgentLoop.__new__(AgentLoop)
        stub = _StubUnifiedRepair()
        loop.unified_repair = stub

        result = asyncio.run(
            loop._resolve_decision_procedure(
                {"command": "echo test"},
                error_log="broken import",
                pre_announced_command="echo test",
                project_spec={"summary": "demo"},
                phase_context="build phase",
                target_file_hint="src/App.tsx",
            )
        )

        assert result == ({"ok": True}, "command-result", ["message\n"])
        assert stub.decision_call == {
            "decision": {"command": "echo test"},
            "error_log": "broken import",
            "pre_announced_command": "echo test",
            "project_spec": {"summary": "demo"},
            "phase_context": "build phase",
            "target_file_hint": "src/App.tsx",
        }
