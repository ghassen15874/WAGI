import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.orchestrator.planner import ExecutionPlanner
from kilo.orchestrator.planning_service import PlanningService
from kilo.orchestrator.run_state import GenerationRunStateStore
from kilo.session.prompt import BuildSessionPrompt
from kilo.shared.design.engine import DesignEngine
from kilo.tools.registry import ToolRegistry


class BrokenProvider:
    async def stream(self, _messages, _model_id):
        if False:
            yield ""
        raise RuntimeError("planning provider unavailable")


def test_prepare_rebuilds_design_prompt_context_when_resume_state_is_stale():
    with tempfile.TemporaryDirectory() as tmp:
        planning = PlanningService(tmp, planner=ExecutionPlanner())
        run_state = GenerationRunStateStore(tmp)
        tool_registry = ToolRegistry(base_dir=tmp)
        design_engine = DesignEngine()

        prompt_phase = BuildSessionPrompt(
            provider=BrokenProvider(),
            tool_registry=tool_registry,
            design_engine=design_engine,
            planning=planning,
            run_state_store=run_state,
            model_id="test-model",
            pipeline_config={"clear_sandbox_enabled": False, "design_system_enabled": True},
        )
        asyncio.run(prompt_phase.prepare("Build a portfolio website for a designer"))

        run_state_path = os.path.join(tmp, ".lovable", "run_state.json")
        with open(run_state_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["design_prompt_context"] = {}
        with open(run_state_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

        resumed_prompt_phase = BuildSessionPrompt(
            provider=BrokenProvider(),
            tool_registry=tool_registry,
            design_engine=design_engine,
            planning=planning,
            run_state_store=run_state,
            model_id="test-model",
            pipeline_config={"clear_sandbox_enabled": False, "design_system_enabled": True},
        )
        _design, prompt_context, restored = asyncio.run(
            resumed_prompt_phase.prepare("Build a portfolio website for a designer")
        )

        assert restored is True
        assert design_engine.is_prompt_context_usable(prompt_context) is True
