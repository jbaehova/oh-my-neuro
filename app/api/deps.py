"""Shared API helpers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.config import AppConfig, get_config


def effective_config(cfg: AppConfig | None = None) -> AppConfig:
    """Return the active application config."""
    return cfg or get_config()


def json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=_json_default) + "\n"


def iter_ndjson(items: Iterator[dict[str, Any]]) -> Iterator[str]:
    for item in items:
        yield json_line(item)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    return str(value)
