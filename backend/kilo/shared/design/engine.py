"""Builder-facing wrapper around the vendored UUPM design engine."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .core import search
from .design_system import DesignSystemGenerator
from .models import DesignSystem
from .vendor import vendored_uupm_root


def _compact_text(*parts: str) -> str:
    return " ".join(part.strip() for part in parts if str(part or "").strip())


def _contains_query_term(query: str, keywords: tuple[str, ...]) -> bool:
    lowered = query.lower()
    return any(keyword in lowered for keyword in keywords)


class DesignEngine:
    """Use the vendored UUPM engine directly for design-system generation."""

    def __init__(self, data_dir: str | None = None):
        root = vendored_uupm_root()
        self.source = str(root)
        self.data_dir = Path(data_dir) if data_dir else root / "data"
        self._engine = DesignSystemGenerator()

    def generate(self, description: str) -> DesignSystem:
        result_dict = self._engine.generate(description)
        return DesignSystem.from_dict(result_dict)

    def build_prompt_context(self, description: str, design: DesignSystem | None = None) -> dict:
        """Build a UUPM-style research bundle for prompt construction."""
        design = design or self.generate(description)
        fallback_seed = _compact_text(
            description,
            design.category,
            design.style.name,
            design.pattern.name,
        ) or description

        def _search_domain(domain: str, query: str, limit: int, fallback_query: str = "") -> dict:
            primary = search(query or description, domain, limit)
            if list((primary or {}).get("results") or []):
                return primary
            fallback = _compact_text(fallback_query, fallback_seed, domain, "website")
            secondary = search(fallback or description, domain, limit)
            if list((secondary or {}).get("results") or []):
                return secondary
            return primary

        style_query = _compact_text(description, design.style.name, design.style.type)
        color_query = _compact_text(description, design.category, design.colors.notes)
        landing_query = _compact_text(description, design.pattern.name, design.pattern.sections)
        typography_query = _compact_text(description, design.typography.mood, design.typography.best_for)
        ux_query = _compact_text(description, design.category, "accessibility navigation interaction responsive")
        react_query = _compact_text(description, "react performance loading rerender forms routes")
        web_query = _compact_text(description, "semantic accessibility forms navigation responsive")
        icon_query = _compact_text(description, design.category, design.style.name, "iconography")

        domains: dict[str, dict] = {
            "product": _search_domain("product", description, 3),
            "style": _search_domain("style", style_query or description, 3, design.style.keywords),
            "color": _search_domain("color", color_query or description, 3, design.colors.notes),
            "landing": _search_domain("landing", landing_query or description, 3, design.pattern.sections),
            "typography": _search_domain("typography", typography_query or description, 3, design.typography.mood),
            "ux": _search_domain("ux", ux_query, 2, design.category),
            "react": _search_domain("react", react_query, 2, "react vite ui"),
            "web": _search_domain("web", web_query, 2, "semantic accessibility responsive"),
            "icons": _search_domain("icons", icon_query, 2, design.style.name),
        }

        if _contains_query_term(description, ("dashboard", "analytics", "chart", "charts", "metrics", "report", "reports", "data", "insights")):
            chart_query = _compact_text(description, design.category, "chart analytics visualization dashboard")
            domains["chart"] = _search_domain("chart", chart_query, 2, "chart dashboard")

        return {
            "source": self.source,
            "workflow": [
                "Analyze the request and map it to a product type and audience.",
                "Start from the UUPM design-system recommendation as the primary direction.",
                "Use the supplementary domain searches below to refine layout, style, color, typography, UX, and implementation details.",
                "Keep the selected UUPM direction consistent across components, pages, and interactions.",
            ],
            "design": asdict(design),
            "domains": domains,
        }

    def is_prompt_context_usable(self, prompt_context: dict | None, *, min_domains_with_results: int = 2) -> bool:
        """Return True when a saved UUPM prompt context is rich enough to reuse."""
        context = dict(prompt_context or {})
        workflow = [
            str(step).strip()
            for step in list(context.get("workflow") or [])
            if str(step).strip()
        ]
        design = context.get("design")
        domains = dict(context.get("domains") or {})

        domain_hits = 0
        for payload in domains.values():
            if not isinstance(payload, dict):
                continue
            results = [
                item
                for item in list(payload.get("results") or [])
                if isinstance(item, dict) and item
            ]
            if results:
                domain_hits += 1

        has_design = isinstance(design, dict) and bool(design)
        required_hits = max(1, int(min_domains_with_results or 1))
        return bool(workflow and has_design and domain_hits >= required_hits)
