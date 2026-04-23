from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from ..orchestrator.loop import AgentLoop
from ..shared.design.engine import DesignEngine
from ..tools.registry import ToolRegistry


class BuildSessionProcessor:
    """
    Kilo-style execution processor.

    It assumes planning and run-state preparation have already been completed by
    the session prompt/runtime, and then delegates execution to the builder
    processor implementation.
    """

    def __init__(
        self,
        provider: Any,
        *,
        tool_registry: ToolRegistry,
        design_engine: DesignEngine,
        model_id: str = "",
        pipeline_config: dict[str, Any] | None = None,
        processor_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.provider = provider
        self.tool_registry = tool_registry
        self.design_engine = design_engine
        self.model_id = model_id
        self.pipeline_config = dict(pipeline_config or {})
        self.processor_factory = processor_factory or AgentLoop

    def _create_execution_processor(self) -> Any:
        processor_config = dict(self.pipeline_config)
        processor_config["clear_sandbox_enabled"] = False
        processor_config["session_prepared_by_runtime"] = True
        processor_config["resume_iteration"] = int(processor_config.get("resume_iteration", 0) or 0)
        return self.processor_factory(
            provider=self.provider,
            tool_registry=self.tool_registry,
            design_engine=self.design_engine,
            model_id=self.model_id,
            pipeline_config=processor_config,
        )

    async def run(self, prompt: str) -> AsyncIterator[str]:
        processor = self._create_execution_processor()
        result = processor.run(prompt)
        async for chunk in result:
            yield chunk
