"""Design system data models."""
from dataclasses import asdict, dataclass, field
from typing import Dict, Any

@dataclass
class PatternDef:
    name: str = ""
    sections: str = ""
    cta_placement: str = ""
    color_strategy: str = ""
    conversion: str = ""

@dataclass
class StyleDef:
    name: str = ""
    type: str = ""
    effects: str = ""
    keywords: str = ""
    best_for: str = ""
    performance: str = ""
    accessibility: str = ""

@dataclass
class ColorsDef:
    primary: str = ""
    secondary: str = ""
    cta: str = ""
    background: str = ""
    text: str = ""
    notes: str = ""

@dataclass
class TypographyDef:
    heading: str = ""
    body: str = ""
    mood: str = ""
    best_for: str = ""
    google_fonts_url: str = ""
    css_import: str = ""

@dataclass
class DesignSystem:
    project_name: str = ""
    category: str = ""
    pattern: PatternDef = field(default_factory=PatternDef)
    style: StyleDef = field(default_factory=StyleDef)
    colors: ColorsDef = field(default_factory=ColorsDef)
    typography: TypographyDef = field(default_factory=TypographyDef)
    key_effects: str = ""
    anti_patterns: str = ""
    decision_rules: Dict[str, Any] = field(default_factory=dict)
    severity: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "DesignSystem":
        return cls(
            project_name=data.get("project_name", ""),
            category=data.get("category", ""),
            pattern=PatternDef(**data.get("pattern", {})),
            style=StyleDef(**data.get("style", {})),
            colors=ColorsDef(**data.get("colors", {})),
            typography=TypographyDef(**data.get("typography", {})),
            key_effects=data.get("key_effects", ""),
            anti_patterns=data.get("anti_patterns", ""),
            decision_rules=data.get("decision_rules", {}),
            severity=data.get("severity", "")
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def css_variables(self) -> str:
        """Generate CSS custom properties from design system."""
        return f"""
:root {{
  --color-primary: {self.colors.primary};
  --color-secondary: {self.colors.secondary};
  --color-cta: {self.colors.cta};
  --color-background: {self.colors.background};
  --color-text: {self.colors.text};
  --font-heading: '{self.typography.heading}', sans-serif;
  --font-body: '{self.typography.body}', sans-serif;
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --space-2xl: 48px;
  --space-3xl: 64px;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.1);
  --shadow-lg: 0 10px 15px rgba(0,0,0,0.1);
  --shadow-xl: 0 20px 25px rgba(0,0,0,0.15);
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --transition: 200ms ease;
}}
""".strip()

    @property
    def prompt_decision_rules(self) -> str:
        """Render design-engine decision rules into a compact prompt block."""
        rules = self.decision_rules or {}
        if not isinstance(rules, dict) or not rules:
            return ""

        lines: list[str] = []
        for key, value in rules.items():
            clean_key = str(key or "").strip().replace("_", " ")
            clean_value = str(value or "").strip()
            if clean_key and clean_value:
                lines.append(f"- {clean_key}: {clean_value}")
        return "\n".join(lines)
