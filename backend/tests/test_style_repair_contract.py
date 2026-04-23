import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.agents.decision_engine import DecisionEngine
from kilo.orchestrator.feature_validator import FeatureValidator
from kilo.orchestrator.loop import AgentLoop


def _write(rel_path: str, content: str, root: str) -> None:
    full_path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as handle:
        handle.write(content)


class TestStyleRepairContract:
    def test_feature_validator_rejects_empty_placeholder_css_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                "src/components/Footer.tsx",
                """
export default function Footer() {
  return (
    <footer className="footer footer-bottom footer-brand footer-content footer-copyright footer-credits">
      Footer
    </footer>
  );
}
""".strip(),
                tmp,
            )
            _write(
                "src/styles/global.css",
                """
.footer {}
.footer-bottom {}
.footer-brand {}
.footer-content {}
.footer-copyright {}
.footer-credits {}
""".strip(),
                tmp,
            )

            errors = FeatureValidator(tmp)._check_frontend_styling_contract()

            assert any(
                "STYLESHEET_CLASS_EMPTY" in error or "STYLESHEET_CLASS_INCOMPLETE" in error
                for error in errors
            ), errors

    def test_decision_engine_blocks_shell_stub_edits_for_style_contract_repairs(self):
        engine = DecisionEngine(error_analyzer=None)

        decision = engine._normalize_decision(
            {
                "layer": "frontend",
                "confidence": "HIGH",
                "strategy": "fix_style",
                "target_files": ["src/components/Hero.tsx", "src/styles/global.css"],
                "root_cause": "Semantic CSS classes are missing from the owning stylesheet.",
                "fix_hint": "Implement the referenced semantic CSS classes in the stylesheet.",
                "command": "echo '\\n.hero-content {}\\n.hero-actions {}' >> src/styles/global.css",
                "command_kind": "source_edit",
                "return_query_result": "no",
                "write_files": "no",
            }
        )

        assert decision["command"] is None
        assert decision["command_kind"] == "none"
        assert decision["write_files"] == "yes"

    def test_loop_forces_grouped_rewrite_for_stylesheet_contract_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = AgentLoop.__new__(AgentLoop)
            loop.sandbox_dir = tmp
            loop.planner = type("PlannerStub", (), {"project_spec": None, "get_cluster_for_paths": lambda self, paths: []})()
            loop.repair_service = type(
                "RepairStub",
                (),
                {"extract_blueprint_scope_cluster": lambda self, text: []},
            )()

            rewrite = loop._forced_validation_rewrite_decision(
                "src/components/Hero.tsx",
                [
                    "src/components/Hero.tsx: STYLESHEET_CLASS_MISSING: "
                    "This file references semantic CSS classes (btn, btn-primary, hero-actions, hero-content, hero-description, btn-outline) "
                    "that are not implemented as real project stylesheet rules."
                ],
            )

            assert rewrite is not None
            assert rewrite["strategy"] == "fix_style"
            assert "src/components/Hero.tsx" in rewrite["target_files"]
            assert "src/styles/global.css" in rewrite["target_files"]
            assert "src/styles/variables.css" in rewrite["target_files"]

    def test_loop_uses_focused_style_repair_targets_instead_of_planner_cluster(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = type(
            "PlannerStub",
            (),
            {
                "project_spec": None,
                "get_cluster_for_paths": lambda self, paths: [],
            },
        )()
        loop.repair_service = type(
            "RepairStub",
            (),
            {"extract_blueprint_scope_cluster": lambda self, text: []},
        )()

        decision = {
            "strategy": "fix_style",
            "target_files": [
                "src/components/Hero.tsx",
                "src/styles/global.css",
                "src/styles/variables.css",
            ],
        }
        msgs = [
            "src/components/Hero.tsx: STYLESHEET_CLASS_MISSING: "
            "This file references semantic CSS classes (btn, hero-content, hero-cta)."
        ]

        targets = loop._focused_validation_repair_targets(
            "src/components/Hero.tsx",
            msgs,
            decision,
        )

        assert targets == [
            "src/components/Hero.tsx",
            "src/styles/global.css",
            "src/styles/variables.css",
        ]

    def test_loop_detects_style_contract_repairs_as_focused_batches(self):
        loop = AgentLoop.__new__(AgentLoop)

        assert loop._uses_focused_validation_targets(
            {"strategy": "fix_style"},
            ["src/components/Footer.tsx: STYLESHEET_CLASS_MISSING"],
        )

    def test_loop_restores_tailwind_scaffold_for_runtime_failures(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = type(
            "PlannerStub",
            (),
            {
                "project_spec": None,
                "get_cluster_for_paths": lambda self, paths: [],
            },
        )()
        loop.repair_service = type(
            "RepairStub",
            (),
            {"extract_blueprint_scope_cluster": lambda self, text: []},
        )()

        rewrite = loop._forced_validation_rewrite_decision(
            "src/pages/Home.tsx",
            [
                "src/pages/Home.tsx: TAILWIND_RUNTIME_MISSING: "
                "This file uses Tailwind-style utility classes (min-h-screen, bg-white, px-4) "
                "but the project does not include Tailwind config/runtime."
            ],
        )

        assert rewrite is not None
        assert rewrite["strategy"] == "fix_style"
        assert "package.json" in rewrite["target_files"]
        assert "tailwind.config.js" in rewrite["target_files"]
        assert "postcss.config.js" in rewrite["target_files"]
        assert "src/main.tsx" in rewrite["target_files"]
        assert "Restore the Tailwind scaffold/runtime" in rewrite["fix_hint"]

    def test_loop_uses_tailwind_runtime_targets_when_runtime_is_missing(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = type(
            "PlannerStub",
            (),
            {
                "project_spec": None,
                "get_cluster_for_paths": lambda self, paths: [],
            },
        )()
        loop.repair_service = type(
            "RepairStub",
            (),
            {"extract_blueprint_scope_cluster": lambda self, text: []},
        )()

        targets = loop._focused_validation_repair_targets(
            "src/pages/Home.tsx",
            [
                "src/pages/Home.tsx: TAILWIND_RUNTIME_MISSING: "
                "This file uses Tailwind-style utility classes (min-h-screen, bg-white, px-4) "
                "but the project does not include Tailwind config/runtime."
            ],
            {"strategy": "fix_style", "target_files": ["src/pages/Home.tsx"]},
        )

        assert "package.json" in targets
        assert "tailwind.config.js" in targets
        assert "postcss.config.js" in targets
        assert "src/main.tsx" in targets
