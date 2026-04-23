import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.session.runtime import BuildSessionRuntime
from kilo.orchestrator.loop import AgentLoop
from kilo.orchestrator.session_service import ACTIVE_GENERATIONS, iter_project_logs
from kilo.orchestrator.project_map import ProjectMapManager
from kilo.orchestrator.ai_context_builder import AIContextBuilder
from kilo.tools.registry import ToolRegistry


class BrokenProvider:
    async def stream(self, _messages, _model_id):
        if False:
            yield ""
        raise RuntimeError("planning provider unavailable")


class HangingProvider:
    async def stream(self, _messages, _model_id):
        if False:
            yield ""
        await asyncio.sleep(3600)


class FakeProcessor:
    created_kwargs = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.created_kwargs.append(kwargs)

    async def run(self, prompt: str):
        yield f"processor received: {prompt}\n"


class TestSessionRuntime:
    def setup_method(self):
        FakeProcessor.created_kwargs = []

    def test_prepare_session_persists_plan_and_run_state_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = BuildSessionRuntime(
                provider=BrokenProvider(),
                tool_registry=ToolRegistry(base_dir=tmp),
                model_id="test-model",
                pipeline_config={"clear_sandbox_enabled": True},
                processor_factory=FakeProcessor,
            )

            design, prompt_context, restored = asyncio.run(
                runtime.prepare_session("Build a portfolio website for a designer")
            )

            assert restored is False
            assert design.style.name
            assert isinstance(prompt_context, dict)
            assert os.path.exists(os.path.join(tmp, ".lovable", "plan.json"))
            assert os.path.exists(os.path.join(tmp, ".lovable", "run_state.json"))

            with open(os.path.join(tmp, ".lovable", "run_state.json"), "r", encoding="utf-8") as handle:
                run_state = json.load(handle)

            assert run_state["original_prompt"] == "Build a portfolio website for a designer"
            assert run_state["plan_path"] == ".lovable/plan.json"
            assert "design" in run_state

    def test_runtime_hands_prepared_session_to_processor(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = BuildSessionRuntime(
                provider=BrokenProvider(),
                tool_registry=ToolRegistry(base_dir=tmp),
                model_id="test-model",
                pipeline_config={"clear_sandbox_enabled": True},
                processor_factory=FakeProcessor,
            )

            async def _collect() -> list[str]:
                chunks = []
                async for chunk in runtime.run("Build a portfolio website for a designer"):
                    chunks.append(chunk)
                return chunks

            chunks = asyncio.run(_collect())
            output = "".join(chunks)

            assert "Session runtime (orchestrator) preparing Kilo-style planning handoff" in output
            assert "prepared .lovable/plan.json before execution" in output
            assert "Handing prepared session to builder processor" in output
            assert "processor received: Build a portfolio website for a designer" in output
            assert FakeProcessor.created_kwargs
            processor_kwargs = FakeProcessor.created_kwargs[-1]
            assert processor_kwargs["pipeline_config"]["session_prepared_by_runtime"] is True
            assert processor_kwargs["pipeline_config"]["clear_sandbox_enabled"] is False

    def test_prepare_session_times_out_planning_provider_and_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = BuildSessionRuntime(
                provider=HangingProvider(),
                tool_registry=ToolRegistry(base_dir=tmp),
                model_id="deepseek-reasoner",
                pipeline_config={
                    "clear_sandbox_enabled": True,
                    "planning_timeout_seconds": 0.01,
                },
                processor_factory=FakeProcessor,
            )

            design, prompt_context, restored = asyncio.run(
                runtime.prepare_session("Build a portfolio website for a designer")
            )

            assert restored is False
            assert design.style.name
            assert isinstance(prompt_context, dict)

            with open(os.path.join(tmp, ".lovable", "run_state.json"), "r", encoding="utf-8") as handle:
                run_state = json.load(handle)

            assert any("Planning provider timed out" in message for message in run_state.get("planning_status", []))

    def test_prepare_session_rehydrates_missing_design_prompt_context_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_runtime = BuildSessionRuntime(
                provider=BrokenProvider(),
                tool_registry=ToolRegistry(base_dir=tmp),
                model_id="test-model",
                pipeline_config={"clear_sandbox_enabled": False},
                processor_factory=FakeProcessor,
            )
            asyncio.run(first_runtime.prepare_session("Build a portfolio website for a designer"))

            run_state_path = os.path.join(tmp, ".lovable", "run_state.json")
            with open(run_state_path, "r", encoding="utf-8") as handle:
                run_state = json.load(handle)
            run_state["design_prompt_context"] = {}
            with open(run_state_path, "w", encoding="utf-8") as handle:
                json.dump(run_state, handle)

            resumed_runtime = BuildSessionRuntime(
                provider=BrokenProvider(),
                tool_registry=ToolRegistry(base_dir=tmp),
                model_id="test-model",
                pipeline_config={"clear_sandbox_enabled": False},
                processor_factory=FakeProcessor,
            )
            _design, prompt_context, restored = asyncio.run(
                resumed_runtime.prepare_session("Build a portfolio website for a designer")
            )

            assert restored is True
            assert resumed_runtime.design_engine.is_prompt_context_usable(prompt_context) is True

    def test_agent_loop_requires_prepared_session_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = AgentLoop(
                provider=BrokenProvider(),
                tool_registry=ToolRegistry(base_dir=tmp),
                model_id="test-model",
                pipeline_config={},
            )

            async def _collect() -> list[str]:
                chunks = []
                async for chunk in loop.run("Build a portfolio website for a designer"):
                    chunks.append(chunk)
                return chunks

            try:
                asyncio.run(_collect())
            except RuntimeError as exc:
                assert "requires a prepared session" in str(exc)
            else:
                raise AssertionError("AgentLoop unexpectedly ran without a prepared session")

    def test_iter_project_logs_keeps_local_generation_stream_open_without_db_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            lovable_dir = os.path.join(tmp, ".lovable")
            os.makedirs(lovable_dir, exist_ok=True)
            log_path = os.path.join(lovable_dir, "build.log")
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write("planning started\n")

            project_id = "project_local_test_stream"

            async def _assert_stream_behavior() -> None:
                task = asyncio.create_task(asyncio.sleep(5))
                ACTIVE_GENERATIONS[project_id] = task
                stream = iter_project_logs(project_id, tmp, log_path, from_end=False)
                try:
                    first = await asyncio.wait_for(stream.__anext__(), timeout=0.5)
                    assert '"type": "token"' in first
                    try:
                        await asyncio.wait_for(stream.__anext__(), timeout=0.5)
                    except asyncio.TimeoutError:
                        pass
                    else:
                        raise AssertionError("Local generation log stream closed while task was still active")
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    ACTIVE_GENERATIONS.pop(project_id, None)
                    await stream.aclose()

            asyncio.run(_assert_stream_behavior())

    def test_agent_loop_ignores_hidden_runtime_artifact_directories_when_resuming(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".pki", "nssdb"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "src"), exist_ok=True)
            with open(os.path.join(tmp, ".pki", "nssdb", "key4.db"), "w", encoding="utf-8") as handle:
                handle.write("binary-ish")
            with open(os.path.join(tmp, "src", "App.tsx"), "w", encoding="utf-8") as handle:
                handle.write("export default function App() { return null; }\n")

            loop = AgentLoop.__new__(AgentLoop)
            loop.sandbox_dir = tmp

            existing_files = loop._list_existing_project_files()

            assert "src/App.tsx" in existing_files
            assert all(not path.startswith(".pki/") for path in existing_files)

    def test_ai_context_builder_ignores_hidden_runtime_artifact_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".pki", "nssdb"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "src"), exist_ok=True)
            with open(os.path.join(tmp, ".pki", "nssdb", "key4.db"), "w", encoding="utf-8") as handle:
                handle.write("binary-ish")
            with open(os.path.join(tmp, "src", "App.tsx"), "w", encoding="utf-8") as handle:
                handle.write("export default function App() { return <main>Hello</main>; }\n")
            with open(os.path.join(tmp, "src", "theme.css"), "w", encoding="utf-8") as handle:
                handle.write(":root { --color-primary: #1E3A5F; }\n")

            builder = AIContextBuilder(ProjectMapManager(tmp))

            context = builder.build_context()

            assert "src/theme.css" in context
            assert ".pki" not in context
