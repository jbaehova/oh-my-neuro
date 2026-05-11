"""CLI entry point for OH-MY-NEURO."""

from __future__ import annotations

import argparse
import sys

from app.common.logging import get_logger, setup_logging
from app.config import get_config, load_config, reset_config_cache

log = get_logger(__name__)


def _ensure_config(path: str | None):
    if path:
        reset_config_cache()
        cfg = load_config(path)
    else:
        cfg = get_config()
    setup_logging(cfg.app.log_level)
    cfg.ensure_dirs()
    if not cfg.has_api_key():
        log.warning("OPENAI_API_KEY가 설정되지 않았습니다. RAG 기능은 비활성 상태입니다.")
    return cfg


def cmd_ui(args: argparse.Namespace) -> int:
    cfg = _ensure_config(args.config)
    from app.api.main import run_server

    run_server(cfg, host=getattr(args, "host", None), port=getattr(args, "port", None))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oh-my-neuro",
        description="OH-MY-NEURO — 로컬 Vault 기반 RAG 문서 검색",
    )
    parser.add_argument("--config", help="app.yaml 경로", default=None)
    sub = parser.add_subparsers(dest="command")

    ui = sub.add_parser("ui", help="FastAPI/React UI 실행 (기본)")
    ui.add_argument("--host", default=None)
    ui.add_argument("--port", type=int, default=None)
    ui.set_defaults(func=cmd_ui)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args.func = cmd_ui
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover
        print("\n중단됨.")
        return 130
    except Exception as e:
        log.exception("실행 오류")
        print(f"오류: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
