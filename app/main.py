"""CLI entry point for OH-MY-NEURO."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.common.logging import get_logger, setup_logging
from app.config import get_config, load_config, reset_config_cache
from app.ingestion.pipeline import (
    clear_all,
    index_vault_delta,
    list_indexed_sources,
)
from app.rag.service import get_service
from app.vault.state import VaultState

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


def cmd_sync(args: argparse.Namespace) -> int:
    cfg = _ensure_config(args.config)
    if cfg.vault.path_abs is None:
        print("Vault 경로가 설정되어 있지 않습니다. `oh-my-neuro vault <path>` 로 먼저 설정하세요.")
        return 2

    def _progress(name: str, stage: str, frac: float | None = None) -> None:
        pct = f"{int(frac * 100):3d}%" if isinstance(frac, float) else "  ?%"
        if name:
            print(f"[{pct}] {name} — {stage}")
        else:
            print(f"[{pct}] {stage}")

    if getattr(args, "dry_run", False):
        from app.storage.chroma_store import ChromaStore
        from app.vault.manager import VaultManager
        from app.vault.scanner import scan_vault

        current, scan_skipped = scan_vault(cfg.vault.path_abs, cfg.vault)
        store = ChromaStore.from_config(cfg)
        try:
            indexed = store.list_indexed_files()
        finally:
            store.close()
        delta = VaultManager.compute_delta(current=current, indexed=indexed)
        print(f"추가 예정: {len(delta.add)}")
        for e in delta.add:
            print(f"  + {e.relative_path}")
        print(f"수정 예정: {len(delta.update)}")
        for e in delta.update:
            print(f"  ~ {e.relative_path}")
        print(f"삭제 예정: {len(delta.delete)}")
        for rel in delta.delete:
            print(f"  - {rel}")
        print(f"건너뜀: {len(scan_skipped)}")
        return 0

    result = index_vault_delta(cfg=cfg, progress=_progress)
    print(result.summary())

    state = VaultState.load()
    if not state.vault_path:
        state.vault_path = str(cfg.vault.path_abs)
    state.record_sync(
        added=result.added,
        updated=result.updated,
        deleted=result.deleted,
        skipped=len(result.skipped),
        duration_s=result.duration_s,
    )
    state.save()
    return 0


def cmd_vault(args: argparse.Namespace) -> int:
    _ensure_config(args.config)
    path = args.path.strip()
    if not path:
        print("Vault 경로를 입력하세요.", file=sys.stderr)
        return 2
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        print(f"디렉토리가 존재하지 않습니다: {target}", file=sys.stderr)
        return 2
    state = VaultState.load()
    state.vault_path = str(target)
    state.onboarding_completed = True
    state.save()
    print(f"Vault 경로 설정됨: {target}")
    print("이제 `oh-my-neuro sync` 로 첫 동기화를 실행하세요.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _ensure_config(args.config)
    state = VaultState.load()
    files = list_indexed_sources(config=cfg)
    print(f"Vault 경로     : {state.vault_path or '(미설정)'}")
    print(f"마지막 동기화  : {state.last_sync_at or '(없음)'}")
    print(f"인덱싱된 파일  : {len(files)}")
    if state.sync_history:
        latest = state.sync_history[0]
        print(
            f"최근 sync 결과 : 추가 {latest.added} · 수정 {latest.updated} · "
            f"삭제 {latest.deleted} · 건너뜀 {latest.skipped} · {latest.duration_s:.1f}초"
        )
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    _ensure_config(args.config)
    service = get_service()
    if getattr(args, "stream", False):
        printed_tokens = False
        citations: list = []
        for chunk in service.ask_stream(args.question):
            if chunk.kind == "meta":
                citations = list(chunk.citations)
                if chunk.rewritten_question and chunk.rewritten_question != args.question:
                    print(f"🔁 재작성: {chunk.rewritten_question}\n")
                if chunk.used_mcp:
                    print("🔗 MCP 결과 포함\n")
            elif chunk.kind == "token":
                print(chunk.text, end="", flush=True)
                printed_tokens = True
            elif chunk.kind == "error":
                print(f"\n❌ {chunk.text}")
            elif chunk.kind == "done":
                if chunk.text and not printed_tokens:
                    print(chunk.text)
                print()
        if citations:
            print("출처")
            for i, c in enumerate(citations, start=1):
                print(f"  {i}. {c.render()}")
        return 0
    resp = service.ask(args.question)
    print(resp.render_with_sources())
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = _ensure_config(args.config)
    rows = list_indexed_sources(config=cfg)
    if not rows:
        print("인덱싱된 파일이 없습니다. `oh-my-neuro sync` 를 실행하세요.")
        return 0
    print(f"{'파일 경로':<60} {'형식':<6} {'크기':<8} 동기화 시각")
    for r in rows:
        print(f"{r['source']:<60} {r.get('doc_type', ''):<6} {r['size']:<8} {r.get('synced_at', '')}")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    cfg = _ensure_config(args.config)
    if not getattr(args, "force", False):
        print("전체 인덱스를 삭제합니다. 확인하려면 --force 플래그를 추가하세요.")
        return 2
    n = clear_all(config=cfg)
    print(f"인덱스 초기화 완료 ({n}개 청크 제거)")
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

    syncp = sub.add_parser("sync", help="Vault 델타 동기화")
    syncp.add_argument("--dry-run", action="store_true", help="실행 계획만 출력")
    syncp.set_defaults(func=cmd_sync)

    vaultp = sub.add_parser("vault", help="Vault 경로 설정")
    vaultp.add_argument("path", help="Vault 디렉토리 경로")
    vaultp.set_defaults(func=cmd_vault)

    statusp = sub.add_parser("status", help="현재 상태 요약")
    statusp.set_defaults(func=cmd_status)

    ask = sub.add_parser("ask", help="질문에 답변")
    ask.add_argument("question")
    ask.add_argument("--stream", action="store_true")
    ask.set_defaults(func=cmd_ask)

    lst = sub.add_parser("list", help="인덱싱된 파일 목록")
    lst.set_defaults(func=cmd_list)

    clr = sub.add_parser("clear", help="인덱스 초기화")
    clr.add_argument("--force", action="store_true", help="확인 없이 삭제")
    clr.set_defaults(func=cmd_clear)

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
