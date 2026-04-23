"""Runtime key registry shared by providers and HTTP settings routes."""

from __future__ import annotations

RUNTIME_KEYS: dict[str, str] = {}


def get_runtime_keys() -> dict[str, str]:
    return RUNTIME_KEYS


def get_runtime_key(name: str, default: str = "") -> str:
    return str(RUNTIME_KEYS.get(name, default) or default)


def set_runtime_key(name: str, value: str) -> None:
    normalized = str(value or "").strip()
    if normalized:
        RUNTIME_KEYS[name] = normalized
    else:
        RUNTIME_KEYS.pop(name, None)


def snapshot_runtime_keys() -> dict[str, str]:
    return dict(RUNTIME_KEYS)

