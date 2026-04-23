"""Compatibility wrapper around the vendored UUPM design-system module."""
from .vendor import load_uupm_modules

_, _DESIGN_MODULE, _ = load_uupm_modules()

DesignSystemGenerator = _DESIGN_MODULE.DesignSystemGenerator
format_ascii_box = _DESIGN_MODULE.format_ascii_box
format_markdown = _DESIGN_MODULE.format_markdown
generate_design_system = _DESIGN_MODULE.generate_design_system
persist_design_system = _DESIGN_MODULE.persist_design_system
format_master_md = _DESIGN_MODULE.format_master_md
format_page_override_md = _DESIGN_MODULE.format_page_override_md
