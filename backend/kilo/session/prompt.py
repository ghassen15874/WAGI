from __future__ import annotations

from typing import Any

from ..orchestrator.planning_service import PlanningService
from ..orchestrator.run_state import GenerationRunStateStore
from ..shared.design.engine import DesignEngine
from ..tools.registry import ToolRegistry


class BuildSessionPrompt:
    """
    Kilo-style read-only planning/preparation phase for builder sessions.

    Owns:
    - sandbox clearing for fresh sessions
    - design generation / restoration
    - execution plan creation / restoration
    - run-state persistence before execution
    """

    def __init__(
        self,
        provider: Any,
        *,
        tool_registry: ToolRegistry,
        design_engine: DesignEngine,
        planning: PlanningService,
        run_state_store: GenerationRunStateStore,
        model_id: str = "",
        pipeline_config: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.tool_registry = tool_registry
        self.design_engine = design_engine
        self.planning = planning
        self.run_state_store = run_state_store
        self.model_id = model_id
        self.pipeline_config = dict(pipeline_config or {})

    async def prepare(self, prompt: str) -> tuple[Any, dict[str, Any], bool]:
        resume_requested = not bool(self.pipeline_config.get("clear_sandbox_enabled", True))
        design_enabled = bool(self.pipeline_config.get("design_system_enabled", True))

        if resume_requested:
            if self.planning.restore(prompt=prompt):
                state = self.run_state_store.load()
                saved_design = state.get("design")
                saved_prompt_context = dict(state.get("design_prompt_context", {}) or {})
                if saved_design:
                    from ..shared.design.models import DesignSystem

                    design = DesignSystem.from_dict(saved_design)
                    prompt_context = saved_prompt_context
                    if design_enabled and not self.design_engine.is_prompt_context_usable(prompt_context):
                        prompt_context = self.design_engine.build_prompt_context(prompt, design)
                        payload = dict(state or {})
                        payload["original_prompt"] = prompt
                        payload["design"] = design.to_dict()
                        payload["design_prompt_context"] = prompt_context
                        payload["plan_path"] = ".lovable/plan.json"
                        self.run_state_store.save(payload)
                    return design, prompt_context, True
                design = self.design_engine.generate(prompt)
                prompt_context = self.design_engine.build_prompt_context(prompt, design)
                payload = dict(state or {})
                payload["original_prompt"] = prompt
                payload["design"] = design.to_dict()
                payload["design_prompt_context"] = prompt_context
                payload["plan_path"] = ".lovable/plan.json"
                self.run_state_store.save(payload)
                return design, prompt_context, True

        if self.pipeline_config.get("clear_sandbox_enabled", True):
            await self.tool_registry.execute("clear_sandbox", {})
            self.planning.clear()
            self.run_state_store.clear()

        design = self.design_engine.generate(prompt)
        prompt_context = self.design_engine.build_prompt_context(prompt, design)

        status_messages: list[str] = []

        async def _status_hook(message: str) -> None:
            text = str(message or "").strip()
            if text:
                status_messages.append(text)

        await self.planning.create_plan(
            prompt,
            design,
            self.provider,
            self.model_id,
            existing_files_summary="",
            status_hook=_status_hook,
            planning_timeout_seconds=self.pipeline_config.get("planning_timeout_seconds"),
        )

        payload = {
            "original_prompt": prompt,
            "iteration": 0,
            "design": design.to_dict(),
            "design_prompt_context": prompt_context,
            "plan_path": ".lovable/plan.json",
        }
        if status_messages:
            payload["planning_status"] = status_messages
        self.run_state_store.save(payload)

        return design, prompt_context, False
