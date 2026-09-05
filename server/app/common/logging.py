"""Project-wide logging helper."""

from __future__ import annotations

import logging
import os

_INITIALIZED = False


def setup_logging(level: str | int | None = None) -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    resolved = level or os.getenv("OMN_LOG_LEVEL") or "INFO"
    if isinstance(resolved, str):
        resolved = resolved.upper()
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "chromadb", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
