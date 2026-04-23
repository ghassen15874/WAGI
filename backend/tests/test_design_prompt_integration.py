import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.agents.codegen.prompts import build_design_spec
from kilo.shared.design.engine import DesignEngine


class TestDesignPromptIntegration:
    def test_frontend_design_prompt_uses_shared_design_css_contract(self):
        engine = DesignEngine()
        design = engine.generate("Create a portfolio website for a designer")

        prompt = build_design_spec(design, "frontend")

        assert design.css_variables in prompt
        assert "--shadow-xl:" in prompt
        assert f"--color-primary: {design.colors.primary};" in prompt
        assert f"--font-heading: '{design.typography.heading}', sans-serif;" in prompt

    def test_frontend_design_prompt_includes_design_decision_rules_when_present(self):
        engine = DesignEngine()
        design = engine.generate("Create a blog platform with categories")

        prompt = build_design_spec(design, "frontend")

        assert "### DESIGN DECISION RULES" in prompt
        assert "must have: category-navigation" in prompt.lower()

    def test_frontend_design_prompt_is_tailwind_first(self):
        engine = DesignEngine()
        design = engine.generate("Create a SaaS website")

        prompt = build_design_spec(design, "frontend")

        assert "Tailwind is available in this scaffold." in prompt
        assert "Tailwind is not available unless the scaffold explicitly includes it." not in prompt
        assert "Keep `src/styles/global.css` limited" in prompt

    def test_design_engine_prompt_context_is_usable(self):
        engine = DesignEngine()
        design = engine.generate("Create a restaurant website with warm branding")
        context = engine.build_prompt_context("Create a restaurant website with warm branding", design)

        assert engine.is_prompt_context_usable(context) is True
