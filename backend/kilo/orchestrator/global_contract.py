from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any


DEFAULT_GLOBAL_CONTRACT: dict[str, Any] = {
    "layout": {
        "require_canonical_shell": True,
        "required_shell_parts": ["sidebar", "topbar", "main_outlet"],
        "enforce_for_app_kinds": ["dashboard", "web_app", "webapp", "admin_portal"],
    },
    "routing": {
        "nav_targets_must_exist": True,
        "wildcard_route_required": True,
    },
    "theme": {
        "storage_key": "theme",
        "must_toggle_root_class": True,
        "must_restore_on_boot": True,
    },
    "styles": {
        "required_token_file": "src/styles/variables.css",
        "required_global_css": "src/styles/global.css",
        "required_tokens": [
            "--color-primary",
            "--color-background",
            "--color-foreground",
            "--color-border",
        ],
    },
    "backend": {
        "schema_query_parity_required": True,
        "db_init_required": True,
    },
    "batching": {
        "constrained_batching": True,
        "validate_connected_cluster": True,
        "retry_cluster_expansion_on_contract_error": True,
    },
    "runtime_smoke": {
        "min_validation_seconds": 180,
        "required_routes": ["/"],
        "required_api": ["/api/health"],
        "require_theme_toggle_check": True,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in dict(override or {}).items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(dict(merged[key] or {}), value)
        else:
            merged[key] = value
    return merged


def normalize_global_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_GLOBAL_CONTRACT, dict(contract or {}))

    layout = dict(merged.get("layout") or {})
    layout["required_shell_parts"] = [
        str(part).strip().lower()
        for part in list(layout.get("required_shell_parts") or [])
        if str(part).strip()
    ] or list(DEFAULT_GLOBAL_CONTRACT["layout"]["required_shell_parts"])
    layout["enforce_for_app_kinds"] = [
        str(kind).strip().lower()
        for kind in list(layout.get("enforce_for_app_kinds") or [])
        if str(kind).strip()
    ] or list(DEFAULT_GLOBAL_CONTRACT["layout"]["enforce_for_app_kinds"])
    merged["layout"] = layout

    routing = dict(merged.get("routing") or {})
    routing["nav_targets_must_exist"] = bool(routing.get("nav_targets_must_exist", True))
    routing["wildcard_route_required"] = bool(routing.get("wildcard_route_required", True))
    merged["routing"] = routing

    theme = dict(merged.get("theme") or {})
    theme["storage_key"] = str(theme.get("storage_key", "theme") or "theme").strip() or "theme"
    theme["must_toggle_root_class"] = bool(theme.get("must_toggle_root_class", True))
    theme["must_restore_on_boot"] = bool(theme.get("must_restore_on_boot", True))
    merged["theme"] = theme

    styles = dict(merged.get("styles") or {})
    styles["required_token_file"] = str(
        styles.get("required_token_file", "src/styles/variables.css") or "src/styles/variables.css"
    ).strip().replace("\\", "/")
    styles["required_global_css"] = str(
        styles.get("required_global_css", "src/styles/global.css") or "src/styles/global.css"
    ).strip().replace("\\", "/")
    styles["required_tokens"] = [
        str(token).strip()
        for token in list(styles.get("required_tokens") or [])
        if str(token).strip()
    ] or list(DEFAULT_GLOBAL_CONTRACT["styles"]["required_tokens"])
    merged["styles"] = styles

    backend = dict(merged.get("backend") or {})
    backend["schema_query_parity_required"] = bool(backend.get("schema_query_parity_required", True))
    backend["db_init_required"] = bool(backend.get("db_init_required", True))
    merged["backend"] = backend

    batching = dict(merged.get("batching") or {})
    batching["constrained_batching"] = bool(batching.get("constrained_batching", True))
    batching["validate_connected_cluster"] = bool(batching.get("validate_connected_cluster", True))
    batching["retry_cluster_expansion_on_contract_error"] = bool(
        batching.get("retry_cluster_expansion_on_contract_error", True)
    )
    merged["batching"] = batching

    runtime_smoke = dict(merged.get("runtime_smoke") or {})
    try:
        runtime_smoke["min_validation_seconds"] = max(
            0, int(runtime_smoke.get("min_validation_seconds", 180) or 180)
        )
    except Exception:
        runtime_smoke["min_validation_seconds"] = 180
    runtime_smoke["required_routes"] = [
        str(route).strip()
        for route in list(runtime_smoke.get("required_routes") or [])
        if str(route).strip()
    ] or ["/"]
    runtime_smoke["required_api"] = [
        str(route).strip()
        for route in list(runtime_smoke.get("required_api") or [])
        if str(route).strip()
    ] or ["/api/health"]
    runtime_smoke["require_theme_toggle_check"] = bool(
        runtime_smoke.get("require_theme_toggle_check", True)
    )
    merged["runtime_smoke"] = runtime_smoke

    return merged


def _load_contract_from_file(path: str) -> dict[str, Any] | None:
    full_path = str(path or "").strip()
    if not full_path or not os.path.exists(full_path):
        return None
    try:
        with open(full_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def load_global_contract(sandbox_dir: str, pipeline_config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(pipeline_config or {})
    explicit_path = str(cfg.get("global_contract_path", "") or "").strip()
    env_path = str(os.environ.get("KILO_GLOBAL_CONTRACT_PATH", "") or "").strip()
    default_path = os.path.join(str(sandbox_dir or "").strip(), "global_contract.json")
    repo_default = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "global_contract.json")
    )

    candidate_paths: list[str] = []
    for candidate in (explicit_path, env_path, default_path, repo_default):
        clean = str(candidate or "").strip()
        if clean and clean not in candidate_paths:
            candidate_paths.append(clean)

    for candidate in candidate_paths:
        loaded = _load_contract_from_file(candidate)
        if loaded is not None:
            return normalize_global_contract(loaded)

    return normalize_global_contract({})
