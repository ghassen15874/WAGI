from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionAgentProfile:
    """Minimal Kilo-style agent role descriptor for builder sessions."""

    name: str
    mode: str
    description: str
    owns: tuple[str, ...]


class SessionAgentRegistry:
    """Central registry for the active builder session roles."""

    def __init__(self) -> None:
        self._profiles = {
            "plan": SessionAgentProfile(
                name="plan",
                mode="read_only",
                description="Owns execution planning and persists the plan contract before code generation starts.",
                owns=("design", "project_spec", "plan_json", "run_state"),
            ),
            "builder": SessionAgentProfile(
                name="builder",
                mode="execution",
                description="Consumes a prepared plan and generates the current execution wave.",
                owns=("generation_loop", "batch_execution", "phase_gates"),
            ),
            "repair": SessionAgentProfile(
                name="repair",
                mode="execution",
                description="Repairs only the failing contract slice and keeps related files together.",
                owns=("validation_retries", "runtime_retries", "blueprint_cluster_repair"),
            ),
            "orchestrator": SessionAgentProfile(
                name="orchestrator",
                mode="session",
                description="Owns session lifecycle and hands off from planning to builder/repair.",
                owns=("session_runtime", "state_hydration", "processor_handoff"),
            ),
        }

    def get(self, name: str) -> SessionAgentProfile:
        return self._profiles[str(name or "").strip().lower()]

    def list(self) -> list[SessionAgentProfile]:
        return list(self._profiles.values())
