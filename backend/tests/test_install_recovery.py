import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.orchestrator.loop import AgentLoop


class _StubToolRegistry:
    def __init__(self, result: str = "ok") -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, tool_name: str, params: dict) -> str:
        self.calls.append((tool_name, params))
        return self.result


class TestInstallRecovery:
    def test_extracts_only_sandbox_npm_reify_conflict_paths(self, tmp_path):
        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()
        other_dir = tmp_path / "outside"
        other_dir.mkdir()

        loop = AgentLoop.__new__(AgentLoop)
        loop.sandbox_dir = str(sandbox_dir)

        output = f"""
npm ERR! code ENOTEMPTY
npm ERR! syscall rename
npm ERR! path {sandbox_dir}/node_modules/eslint
npm ERR! dest {sandbox_dir}/node_modules/.eslint-G69xE6nN
npm ERR! path {other_dir}/node_modules/typescript
""".strip()

        paths = loop._extract_npm_reify_conflict_paths(output)

        assert paths == [
            os.path.normpath(f"{sandbox_dir}/node_modules/eslint"),
            os.path.normpath(f"{sandbox_dir}/node_modules/.eslint-G69xE6nN"),
        ]

    def test_clear_conflict_paths_removes_path_and_dest_inside_sandbox(self, tmp_path):
        sandbox_dir = tmp_path / "sandbox"
        node_modules = sandbox_dir / "node_modules"
        node_modules.mkdir(parents=True)
        source_dir = node_modules / "eslint"
        dest_dir = node_modules / ".eslint-G69xE6nN"
        source_dir.mkdir()
        dest_dir.mkdir()
        (source_dir / "package.json").write_text("{}", encoding="utf-8")
        (dest_dir / "package.json").write_text("{}", encoding="utf-8")

        loop = AgentLoop.__new__(AgentLoop)
        loop.sandbox_dir = str(sandbox_dir)

        output = f"""
npm ERR! code ENOTEMPTY
npm ERR! syscall rename
npm ERR! path {source_dir}
npm ERR! dest {dest_dir}
""".strip()

        removed = loop._clear_npm_reify_conflict_paths(output)

        assert removed == 2
        assert not source_dir.exists()
        assert not dest_dir.exists()

    def test_attempt_invalid_version_recovery_backs_up_lockfile_and_node_modules(self, tmp_path):
        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()
        node_modules = sandbox_dir / "node_modules"
        node_modules.mkdir()
        package_lock = sandbox_dir / "package-lock.json"
        package_lock.write_text('{"name":"demo"}\n', encoding="utf-8")
        (node_modules / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")

        loop = AgentLoop.__new__(AgentLoop)
        loop.sandbox_dir = str(sandbox_dir)
        loop.tool_registry = _StubToolRegistry("npm install: ok")

        backed_up_paths, install_result = asyncio.run(loop._attempt_invalid_version_recovery())

        assert install_result == "npm install: ok"
        assert backed_up_paths == ["package-lock.json.bad", "node_modules.bad"]
        assert not package_lock.exists()
        assert not node_modules.exists()
        assert (sandbox_dir / "package-lock.json.bad").exists()
        assert (sandbox_dir / "node_modules.bad").exists()
        assert loop.tool_registry.calls == [
            ("execute_command", {"command": "npm install --legacy-peer-deps 2>&1", "timeout": 600})
        ]

    def test_detects_invalid_version_install_failure(self):
        loop = AgentLoop.__new__(AgentLoop)
        assert loop._looks_like_invalid_version_install_failure("npm ERR! Invalid Version:\n")
        assert not loop._looks_like_invalid_version_install_failure("npm ERR! code ENOTEMPTY\n")
