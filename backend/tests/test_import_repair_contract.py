import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.orchestrator.loop import AgentLoop


class TestImportRepairContract:
    def test_loop_targets_missing_relative_component_import_as_tsx_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = AgentLoop.__new__(AgentLoop)
            loop.sandbox_dir = tmp

            target = loop._guess_missing_import_target(
                "src/pages/Home.tsx",
                "../components/KanbanColumn",
            )

            assert target == "src/components/KanbanColumn.tsx"

    def test_loop_targets_missing_relative_service_import_as_ts_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = AgentLoop.__new__(AgentLoop)
            loop.sandbox_dir = tmp

            target = loop._guess_missing_import_target(
                "src/pages/Home.tsx",
                "../services/api",
            )

            assert target == "src/services/api.ts"
