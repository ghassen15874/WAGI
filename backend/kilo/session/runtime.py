from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from ..orchestrator.planner import ExecutionPlanner
from ..orchestrator.planning_service import PlanningService
from ..orchestrator.run_state import GenerationRunStateStore
from ..shared.design.engine import DesignEngine
from ..tools.registry import ToolRegistry
from .agent_registry import SessionAgentRegistry
from .processor import BuildSessionProcessor
from .prompt import BuildSessionPrompt


class BuildSessionRuntime:
    """
    Kilo-style session owner for builder runs.

    Responsibilities:
    - own the read-only planning phase
    - persist session state before execution starts
    - hand the prepared session to the execution processor

    The execution processor consumes a prepared session instead of being created
    directly by the HTTP route.
    """

    def __init__(
        self,
        provider: Any,
        *,
        sandbox_dir: str | None = None,
        tool_registry: ToolRegistry | None = None,
        design_engine: DesignEngine | None = None,
        model_id: str = "",
        pipeline_config: dict[str, Any] | None = None,
        processor_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.provider = provider
        self.model_id = model_id
        self.pipeline_config = dict(pipeline_config or {})
        self.tool_registry = tool_registry or ToolRegistry(base_dir=sandbox_dir)
        self.sandbox_dir = str(self.tool_registry.base_dir)
        self.design_engine = design_engine or DesignEngine()
        self.agent_registry = SessionAgentRegistry()
        self.processor_factory = processor_factory

        self.planner = ExecutionPlanner()
        self.planning = PlanningService(self.sandbox_dir, planner=self.planner)
        self.run_state_store = GenerationRunStateStore(self.sandbox_dir)
        self.prompt_phase = BuildSessionPrompt(
            provider=self.provider,
            tool_registry=self.tool_registry,
            design_engine=self.design_engine,
            planning=self.planning,
            run_state_store=self.run_state_store,
            model_id=self.model_id,
            pipeline_config=self.pipeline_config,
        )
        self.processor = BuildSessionProcessor(
            provider=self.provider,
            tool_registry=self.tool_registry,
            design_engine=self.design_engine,
            model_id=self.model_id,
            pipeline_config=self.pipeline_config,
            processor_factory=self.processor_factory,
        )

    async def _emit(self, message: str) -> AsyncIterator[str]:
        text = str(message or "")
        if text:
            yield text if text.endswith("\n") else f"{text}\n"

    async def prepare_session(self, prompt: str) -> tuple[Any, dict[str, Any], bool]:
        return await self.prompt_phase.prepare(prompt)

    async def run(self, prompt: str) -> AsyncIterator[str]:
        orchestrator = self.agent_registry.get("orchestrator")
        planner = self.agent_registry.get("plan")
        builder = self.agent_registry.get("builder")

        async for chunk in self._emit(
            f"🧭 Session runtime ({orchestrator.name}) preparing Kilo-style planning handoff..."
        ):
            yield chunk

        design, _prompt_context, restored = await self.prepare_session(prompt)
        if restored:
            async for chunk in self._emit("✓ Restored prepared session state from .lovable/plan.json"):
                yield chunk
        else:
            async for chunk in self._emit(f"✓ {planner.name} prepared .lovable/plan.json before execution"):
                yield chunk
            async for chunk in self._emit(
                f"Style: {design.style.name} ({design.style.type}) | Colors: {design.colors.primary}"
            ):
                yield chunk
            async for chunk in self._emit(
                f"Fonts: {design.typography.heading} / {design.typography.body}"
            ):
                yield chunk

        async for chunk in self._emit(
            f"🚀 Handing prepared session to {builder.name} processor..."
        ):
            yield chunk

        async for chunk in self.processor.run(prompt):
            yield chunk
