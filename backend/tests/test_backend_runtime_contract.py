import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.agents.codegen.linter import CodeLinter
from kilo.agents.unified_self_healing import UnifiedSelfHealing
from kilo.orchestrator.error_analyzer import ErrorAnalyzer
from kilo.orchestrator.feature_validator import FeatureValidator
from kilo.orchestrator.loop import AgentLoop
from kilo.tools.registry import ToolRegistry


class DummyProvider:
    provider_name = "test"

    async def stream(self, _messages, _model_id):
        if False:
            yield ""


def _write(rel_path: str, content: str, root: str) -> None:
    full_path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as handle:
        handle.write(content)


class TestBackendRuntimeContract:
    def test_agent_loop_backend_startup_uses_only_canonical_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write("server/app.ts", "module.exports = {};\n", tmp)
            loop = AgentLoop(
                provider=DummyProvider(),
                tool_registry=ToolRegistry(base_dir=tmp),
                model_id="test-model",
                pipeline_config={"session_prepared_by_runtime": True},
            )

            assert loop._has_backend_entry() is False

            _write("server/index.ts", "module.exports = {};\n", tmp)

            assert loop._has_backend_entry() is True

            command = loop._get_backend_start_command()
            assert "server/index.ts" in command
            assert "server/app.ts" not in command
            assert "server/server.ts" not in command
            assert "node server/index.js" not in command

    def test_feature_validator_mount_checks_only_canonical_backend_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                "server/app.ts",
                "const app = { use() {} };\napp.use('/api/projects', require('./routes/projectRoutes'));\n",
                tmp,
            )
            validator = FeatureValidator(tmp)

            assert validator._route_is_mounted_in_backend("/api/projects") is False

            _write(
                "server/index.ts",
                "const app = { use() {} };\napp.use('/api/projects', require('./routes/projectRoutes'));\n",
                tmp,
            )

            assert validator._route_is_mounted_in_backend("/api/projects") is True

    def test_package_json_rejects_module_type_and_missing_server_script(self):
        linter = CodeLinter()
        package_json = json.dumps(
            {
                "name": "demo",
                "type": "module",
                "scripts": {
                    "dev": "vite",
                },
            },
            indent=2,
        )

        errors = linter.lint_file("package.json", package_json)

        assert any("Missing 'server' script" in error for error in errors), errors
        assert any('Remove "type": "module"' in error for error in errors), errors

    def test_package_json_server_script_must_use_canonical_entry(self):
        linter = CodeLinter()
        package_json = json.dumps(
            {
                "name": "demo",
                "scripts": {
                    "dev": "vite",
                    "server": "node --import tsx server/app.ts",
                },
            },
            indent=2,
        )

        errors = linter.lint_file("package.json", package_json)

        assert any("canonical backend entrypoint" in error for error in errors), errors

    def test_self_healing_normalizes_legacy_backend_entry_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            healer = UnifiedSelfHealing(
                sandbox_dir=tmp,
                provider=DummyProvider(),
                tool_registry=ToolRegistry(base_dir=tmp),
                error_analyzer=ErrorAnalyzer(),
                context_builder=None,
                model_id="test-model",
            )

            assert healer._target_hint_from_error_log(
                "Error [ERR_MODULE_NOT_FOUND]: Cannot find module 'server/app.ts'"
            ) == "server/index.ts"
            assert healer._target_hint_from_error_log(
                "Runtime crashed while loading server/server.ts"
            ) == "server/index.ts"

    def test_backend_validator_startup_candidates_are_canonical(self):
        validator_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "kilo",
            "tools",
            "backend_validator.js",
        )
        with open(validator_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        assert "server/index.ts" in content
        assert "server/app.ts" not in content
        assert "server/server.ts" not in content
        assert "node server/index.js" not in content
