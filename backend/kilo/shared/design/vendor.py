"""Loader for the vendored UUPM design engine."""
from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType


def _load_module(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module {module_name} from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vendored_uupm_root() -> Path:
    """Return the local copy of the UUPM bundle."""
    return Path(__file__).resolve().parent / "uupm"


@lru_cache(maxsize=1)
def load_uupm_modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    """Load the vendored UUPM core, design-system, and search modules."""
    root = vendored_uupm_root()
    scripts_dir = root / "scripts"
    data_dir = root / "data"

    core_path = scripts_dir / "core.py"
    design_path = scripts_dir / "design_system.py"
    search_path = scripts_dir / "search.py"

    cache_suffix = abs(hash((str(core_path), str(design_path), str(search_path), str(data_dir))))
    core_module_name = f"_vendored_uupm_core_{cache_suffix}"
    design_module_name = f"_vendored_uupm_design_system_{cache_suffix}"
    search_module_name = f"_vendored_uupm_search_{cache_suffix}"

    saved_core = sys.modules.pop("core", None)
    saved_design = sys.modules.pop("design_system", None)
    try:
        core_module = _load_module(core_module_name, core_path)
        core_module.DATA_DIR = data_dir
        sys.modules["core"] = core_module

        design_module = _load_module(design_module_name, design_path)
        sys.modules["design_system"] = design_module

        search_module = _load_module(search_module_name, search_path)
    finally:
        sys.modules.pop("core", None)
        sys.modules.pop("design_system", None)
        if saved_core is not None:
            sys.modules["core"] = saved_core
        if saved_design is not None:
            sys.modules["design_system"] = saved_design

    return core_module, design_module, search_module
