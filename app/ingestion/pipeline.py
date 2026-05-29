"""Ingestion pipeline: vault scan → delta → chunk → embed → upsert."""

from __future__ import annotations

import time
from collections.abc import Callable

from app.common.logging import get_logger
from app.common.models import SkippedFile, SyncResult
from app.config import AppConfig, get_config
from app.ingestion.chunking import chunk_pages
from app.ingestion.loaders import load_document
from app.storage.chroma_store import ChromaStore
from app.vault.manager import VaultManager
from app.vault.scanner import FileEntry, compute_hash, scan_vault

log = get_logger(__name__)

# 3-arity 콜백: (파일명, 단계 메시지, 0~1 진행률 혹은 None)
ProgressCallback = Callable[..., None]


def _notify(cb: ProgressCallback | None, name: str, stage: str, fraction: float | None) -> None:
    if cb is None:
        return
    try:
        cb(name, stage, fraction)
    except TypeError:
        try:
            cb(name, stage)
        except Exception:
            log.debug("progress 콜백 실패: 무시")


def _ingest_file(
    entry: FileEntry,
    cfg: AppConfig,
    store: ChromaStore,
    synced_at: str,
) -> tuple[int, SkippedFile | None]:
    """한 파일을 로드→청크→업서트. 성공 시 (chunks, None), 실패 시 (0, SkippedFile)."""
    try:
        pages = load_document(entry.absolute_path, relative_path=entry.relative_path)
    except Exception as e:
        log.warning("로드 실패 %s: %s", entry.relative_path, e)
        return 0, SkippedFile(path=entry.relative_path, reason="parse_failed")
    if not pages:
        return 0, SkippedFile(path=entry.relative_path, reason="parse_failed")

    try:
        content_hash = compute_hash(entry.absolute_path)
    except OSError as e:
        log.warning("해시 실패 %s: %s", entry.relative_path, e)
        return 0, SkippedFile(path=entry.relative_path, reason="unreadable")

    chunks = chunk_pages(
        pages,
        chunk_size=cfg.retrieval.chunk_size,
        chunk_overlap=cfg.retrieval.chunk_overlap,
        extras={
            "relative_path": entry.relative_path,
            "mtime_ns": entry.mtime_ns,
            "size": entry.size,
            "content_hash": content_hash,
            "synced_at": synced_at,
        },
    )
    if not chunks:
        return 0, SkippedFile(path=entry.relative_path, reason="parse_failed")

    store.upsert_chunks(chunks, source=entry.relative_path)
    return len(chunks), None


def index_vault_delta(
    cfg: AppConfig | None = None,
    store: ChromaStore | None = None,
    progress: ProgressCallback | None = None,
) -> SyncResult:
    from datetime import UTC, datetime

    cfg = cfg or get_config()
    cfg.ensure_dirs()
    root = cfg.vault.path_abs
    if root is None:
        raise ValueError("Vault 경로가 설정되어 있지 않습니다.")

    own_store = False
    if store is None:
        store = ChromaStore.from_config(cfg)
        own_store = True

    start = time.monotonic()
    synced_at = datetime.now(UTC).isoformat()

    current_entries, scan_skipped = scan_vault(root, cfg.vault)
    indexed = store.list_indexed_files()
    delta = VaultManager.compute_delta(
        current=current_entries,
        indexed=indexed,
        hash_check=lambda e: compute_hash(e.absolute_path),
    )

    added = 0
    updated = 0
    deleted = 0
    total_chunks = 0
    skipped: list[SkippedFile] = list(scan_skipped)

    total_ops = max(1, len(delta.delete) + len(delta.update) + len(delta.add))

    # 1) DELETE 먼저
    for i, rel in enumerate(delta.delete):
        _notify(progress, rel, "삭제 중", i / total_ops)
        store.delete_by_source(rel)
        deleted += 1

    # 2) UPDATE
    ops_done = len(delta.delete)
    for entry in delta.update:
        _notify(progress, entry.relative_path, "재인덱싱 중", ops_done / total_ops)
        n, skip = _ingest_file(entry, cfg, store, synced_at)
        if skip:
            skipped.append(skip)
        else:
            updated += 1
            total_chunks += n
        ops_done += 1

    # 3) ADD
    for entry in delta.add:
        _notify(progress, entry.relative_path, "인덱싱 중", ops_done / total_ops)
        n, skip = _ingest_file(entry, cfg, store, synced_at)
        if skip:
            skipped.append(skip)
        else:
            added += 1
            total_chunks += n
        ops_done += 1

    _notify(progress, "", "완료", 1.0)

    if own_store:
        store.close()

    wiki_pages = 0
    wiki_sources = 0
    wiki_error = ""
    if cfg.wiki.enabled and cfg.wiki.update_on_sync:
        if not cfg.has_api_key():
            wiki_error = "OPENAI_API_KEY is required to build the wiki."
        else:
            try:
                from app.wiki.service import WikiService

                _notify(progress, "", "위키 갱신 중", None)
                wiki_result = WikiService(cfg).rebuild(progress=progress)
                wiki_pages = wiki_result.pages_written
                wiki_sources = wiki_result.sources_processed
                wiki_error = wiki_result.error
            except Exception as e:
                log.warning("Wiki 갱신 실패: %s", e)
                wiki_error = str(e)

    return SyncResult(
        added=added,
        updated=updated,
        deleted=deleted,
        total_chunks=total_chunks,
        skipped=skipped,
        duration_s=time.monotonic() - start,
        wiki_pages=wiki_pages,
        wiki_sources=wiki_sources,
        wiki_error=wiki_error,
    )


def list_indexed_sources(store: ChromaStore | None = None, config: AppConfig | None = None) -> list[dict]:
    cfg = config or get_config()
    close_after = False
    if store is None:
        store = ChromaStore.from_config(cfg)
        close_after = True
    try:
        indexed = store.list_indexed_files()
        return [
            {
                "source": rel,
                "doc_type": meta.get("doc_type", ""),
                "size": meta.get("size", 0),
                "synced_at": meta.get("synced_at", ""),
            }
            for rel, meta in sorted(indexed.items())
        ]
    finally:
        if close_after:
            store.close()


def clear_all(store: ChromaStore | None = None, config: AppConfig | None = None) -> int:
    cfg = config or get_config()
    close_after = False
    if store is None:
        store = ChromaStore.from_config(cfg)
        close_after = True
    try:
        return store.clear()
    finally:
        if close_after:
            store.close()
