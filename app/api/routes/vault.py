"""Vault state and sync routes."""

from __future__ import annotations

import os
import platform
import queue
import re
import subprocess
import threading
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.api.deps import effective_config, iter_ndjson
from app.api.schemas import IndexedFilesResponse, VaultPathRequest, VaultStatusResponse, VaultValidateResponse
from app.ingestion.pipeline import index_vault_delta, list_indexed_sources
from app.rag.service import reset_service
from app.storage.chroma_store import reset_vector_store
from app.vault.state import VaultState
from app.wiki.service import WikiService

router = APIRouter(prefix="/vault", tags=["vault"])

VAULT_BROWSE_REQUEST_HEADER = "oh-my-neuro"
VAULT_VALIDATION_MAX_DOCUMENTS = 2000
VAULT_VALIDATION_MAX_DIRECTORIES = 5000


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


@router.post("/browse", response_model=None)
def browse_folder(x_requested_with: str = Header(default="")) -> dict | Response:
    """OS 네이티브 폴더 선택 다이얼로그를 열어 선택된 경로를 반환합니다."""
    if x_requested_with != VAULT_BROWSE_REQUEST_HEADER:
        raise HTTPException(status_code=403, detail="허용되지 않은 요청입니다.")

    system = platform.system()
    selected = ""

    if system == "Darwin":
        result = subprocess.run(
            ["osascript", "-e", "POSIX path of (choose folder)"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            selected = result.stdout.strip().rstrip("/")
    elif system == "Linux":
        for cmd in [
            ["zenity", "--file-selection", "--directory", "--title=Vault 폴더 선택"],
            ["kdialog", "--getexistingdirectory", str(Path.home())],
        ]:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    selected = result.stdout.strip()
                    break
            except FileNotFoundError:
                continue
        else:
            selected = _tkinter_browse()
    else:
        selected = _tkinter_browse()

    if not selected:
        return Response(status_code=204)
    return {"path": selected}


def _tkinter_browse() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        path = filedialog.askdirectory(title="Vault 폴더 선택")
        root.destroy()
        return path or ""
    except Exception:
        return ""


@router.get("/validate", response_model=VaultValidateResponse)
def validate_vault(path: str) -> VaultValidateResponse:
    """경로 존재 여부와 지원 문서 수를 확인합니다 (상태 변경 없음)."""
    stripped = path.strip()
    if not stripped:
        return VaultValidateResponse(valid=False, error="경로를 입력해 주세요.")
    target = Path(stripped).expanduser().resolve()
    if not target.exists():
        return VaultValidateResponse(valid=False, resolved_path=str(target), error="존재하지 않는 경로입니다.")
    if not target.is_dir():
        return VaultValidateResponse(valid=False, resolved_path=str(target), error="디렉토리가 아닙니다.")

    cfg = effective_config()
    doc_count, extensions, truncated = _scan_vault_validation(target, cfg.vault)

    return VaultValidateResponse(
        valid=True,
        resolved_path=str(target),
        doc_count=doc_count,
        extensions=extensions,
        truncated=truncated,
    )


def _scan_vault_validation(root: Path, cfg: Any) -> tuple[int, list[str], bool]:
    """Fast path for live UI validation without a full ingest-scale scan."""
    import os

    exts = {ext.lower() for ext in cfg.include_extensions}
    max_bytes = cfg.max_file_mb * 1024 * 1024
    excluded_dirs = set(cfg.excluded_dirs)
    ext_counts: Counter[str] = Counter()
    doc_count = 0
    truncated = False

    def _is_excluded(name: str) -> bool:
        return name.startswith(".") or name in excluded_dirs

    def _process_file(path: Path) -> bool:
        nonlocal doc_count
        ext = path.suffix.lower()
        if ext not in exts:
            return False
        try:
            if path.stat().st_size > max_bytes:
                return False
        except OSError:
            return False
        ext_counts[ext] += 1
        doc_count += 1
        return doc_count >= VAULT_VALIDATION_MAX_DOCUMENTS

    if cfg.recursive:
        walk = os.walk(root, followlinks=False)
        for directories_seen, (dirpath, dirnames, filenames) in enumerate(walk, start=1):
            if directories_seen > VAULT_VALIDATION_MAX_DIRECTORIES:
                truncated = True
                break
            dirnames[:] = [name for name in dirnames if not _is_excluded(name)]
            for name in filenames:
                if _process_file(Path(dirpath) / name):
                    truncated = True
                    break
            if truncated:
                break
    else:
        for item in sorted(root.iterdir()):
            if item.is_file() and _process_file(item):
                truncated = True
                break

    return doc_count, sorted(ext_counts), truncated


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
    reset_service()
    return status()


@router.get("/files", response_model=IndexedFilesResponse)
def files() -> IndexedFilesResponse:
    cfg = effective_config()
    rows = list_indexed_sources(config=cfg)
    return IndexedFilesResponse(files=rows)


@router.get("/files/open")
def open_file(source: str) -> dict:
    cfg = effective_config()
    vault_root = cfg.vault.path_abs
    if vault_root is None:
        raise HTTPException(status_code=400, detail="Vault 경로가 설정되어 있지 않습니다.")
    source = _resolve_wiki_source(vault_root, cfg.wiki.directory, source)
    file_path = (vault_root / source).resolve()
    if not file_path.is_relative_to(vault_root.resolve()):
        raise HTTPException(status_code=403, detail="허용되지 않는 경로입니다.")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {source}")
    system = platform.system()
    if system == "Windows":
        try:
            os.startfile(str(file_path))
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"파일 열기에 실패했습니다: {exc}") from exc
    elif system == "Darwin":
        result = subprocess.run(["open", str(file_path)], check=False)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail="파일 열기에 실패했습니다.")
    else:
        result = subprocess.run(["xdg-open", str(file_path)], check=False)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail="파일 열기에 실패했습니다.")
    return {"opened": source}


def _resolve_wiki_source(vault_root: Path, wiki_directory: str, source: str) -> str:
    normalized = source.strip().lstrip("/\\")
    wiki_name = wiki_directory.strip().strip("/\\")
    prefix = f"{wiki_name}/"
    if not normalized.startswith(prefix):
        return normalized
    wiki_path = (vault_root / normalized).resolve()
    if not wiki_path.is_relative_to(vault_root.resolve()) or not wiki_path.exists():
        return normalized
    try:
        text = wiki_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return normalized
    match = re.search(r"<!--\s*source:\s*(.*?)\s*-->", text)
    return match.group(1).strip() if match else normalized


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
            reset_vector_store()
            reset_service()
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
