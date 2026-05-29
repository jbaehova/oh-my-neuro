"""Vault state and sync routes."""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import effective_config, iter_ndjson
from app.api.schemas import IndexedFilesResponse, VaultPathRequest, VaultStatusResponse
from app.ingestion.pipeline import index_vault_delta, list_indexed_sources
from app.vault.state import VaultState
from app.wiki.service import WikiService

router = APIRouter(prefix="/vault", tags=["vault"])


@router.get("/status", response_model=VaultStatusResponse)
def status() -> VaultStatusResponse:
    cfg = effective_config()
    state = VaultState.load()
    try:
        indexed_files = len(list_indexed_sources(config=cfg))
    except Exception:
        indexed_files = 0
    return VaultStatusResponse(
        vault_path=state.vault_path,
        onboarding_completed=state.onboarding_completed,
        last_sync_at=state.last_sync_at,
        sync_history=state.sync_history,
        indexed_files=indexed_files,
        api_key_configured=cfg.has_api_key(),
        wiki=WikiService(cfg).status().model_dump(mode="json"),
    )


@router.post("", response_model=VaultStatusResponse)
def set_vault(payload: VaultPathRequest) -> VaultStatusResponse:
    path = payload.path.strip()
    if not path:
        raise HTTPException(status_code=400, detail="Vault path를 입력해 주세요.")
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail=f"디렉토리가 존재하지 않습니다: {target}")
    state = VaultState.load()
    state.vault_path = str(target)
    state.onboarding_completed = True
    state.save()
    return status()


@router.get("/files", response_model=IndexedFilesResponse)
def files() -> IndexedFilesResponse:
    cfg = effective_config()
    rows = list_indexed_sources(config=cfg)
    return IndexedFilesResponse(files=rows)


@router.post("/sync")
def sync() -> StreamingResponse:
    cfg = effective_config()
    if cfg.vault.path_abs is None:
        raise HTTPException(status_code=400, detail="Vault 경로가 설정되어 있지 않습니다.")

    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def _progress(name: str, stage: str, fraction: float | None = None) -> None:
        events.put(
            {
                "kind": "progress",
                "file": name,
                "stage": stage,
                "fraction": fraction,
            }
        )

    def _worker() -> None:
        try:
            result = index_vault_delta(cfg=cfg, progress=_progress)
            state = VaultState.load()
            if not state.vault_path and cfg.vault.path_abs:
                state.vault_path = str(cfg.vault.path_abs)
            state.onboarding_completed = True
            state.record_sync(
                added=result.added,
                updated=result.updated,
                deleted=result.deleted,
                skipped=len(result.skipped),
                duration_s=result.duration_s,
            )
            state.save()
            events.put(
                {
                    "kind": "done",
                    "result": result.model_dump(mode="json"),
                    "skipped": [item.model_dump(mode="json") for item in result.skipped],
                }
            )
        except Exception as exc:
            events.put({"kind": "error", "text": f"동기화 중 오류가 발생했습니다: {exc}"})
        finally:
            events.put(None)

    def _event_iter() -> Iterator[dict[str, Any]]:
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        while True:
            item = events.get()
            if item is None:
                break
            yield item
        thread.join(timeout=1)

    return StreamingResponse(
        iter_ndjson(_event_iter()),
        media_type="application/x-ndjson; charset=utf-8",
    )
