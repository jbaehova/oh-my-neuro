"""Settings and index maintenance routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import effective_config
from app.api.schemas import (
    ApiKeyRequest,
    ClearRequest,
    ClearResponse,
    SettingsPatch,
    SettingsResponse,
)
from app.config import get_config
from app.config.loader import PROJECT_ROOT
from app.ingestion.pipeline import clear_all
from app.mcp.client import reset_mcp_client
from app.rag.service import reset_service
from app.storage.chroma_store import reset_vector_store

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    cfg = effective_config()
    return SettingsResponse(
        app=cfg.app.model_dump(mode="json"),
        llm=cfg.llm.model_dump(mode="json"),
        retrieval=cfg.retrieval.model_dump(mode="json"),
        storage=cfg.storage.model_dump(mode="json"),
        vault=cfg.vault.model_dump(mode="json"),
        mcp=cfg.mcp.model_dump(mode="json"),
        ui=cfg.ui.model_dump(mode="json"),
        api_key_configured=cfg.has_api_key(),
    )


@router.patch("/settings", response_model=SettingsResponse)
def patch_settings(payload: SettingsPatch) -> SettingsResponse:
    cfg = get_config()
    if payload.retrieval:
        _apply_known(cfg.retrieval, payload.retrieval)
    if payload.mcp:
        _apply_known(cfg.mcp, payload.mcp)
        reset_mcp_client()
    if payload.ui:
        _apply_known(cfg.ui, payload.ui)
    reset_service()
    return get_settings()


@router.post("/settings/api-key", response_model=SettingsResponse)
def set_api_key(payload: ApiKeyRequest) -> SettingsResponse:
    """OPENAI_API_KEY를 입력받아 .env에 저장하고 즉시(재시작 없이) 적용한다.

    보안: 키 값은 응답·로그 어디에도 노출하지 않는다. 적용 결과는
    ``api_key_configured`` 불리언으로만 반환한다.
    """
    key = (payload.api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="API 키가 비어 있습니다.")

    # 1) .env 영속화 (있으면 교체, 없으면 추가, 다른 키는 보존)
    try:
        _upsert_env_var("OPENAI_API_KEY", key)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f".env 저장에 실패했습니다: {e}") from e

    # 2) 즉시 적용 — 프로세스 환경 + 싱글톤 config + 서비스 캐시 갱신
    os.environ["OPENAI_API_KEY"] = key
    get_config().openai_api_key = key
    reset_service()

    return get_settings()


def _upsert_env_var(name: str, value: str) -> None:
    """프로젝트 루트 .env에서 ``name`` 라인을 교체하거나 새로 추가한다."""
    env_path = PROJECT_ROOT / ".env"
    line = f"{name}={value}"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        replaced = False
        for i, existing in enumerate(lines):
            stripped = existing.lstrip()
            if stripped.startswith(f"{name}=") and not stripped.startswith("#"):
                lines[i] = line
                replaced = True
                break
        if not replaced:
            lines.append(line)
        content = "\n".join(lines) + "\n"
    else:
        content = line + "\n"
    env_path.write_text(content, encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError:
        pass


@router.post("/index/clear", response_model=ClearResponse)
def clear_index(payload: ClearRequest) -> ClearResponse:
    if not payload.force:
        raise HTTPException(status_code=400, detail="전체 삭제에는 force=true가 필요합니다.")
    cfg = effective_config()
    deleted = clear_all(config=cfg)
    reset_vector_store()
    reset_service()
    return ClearResponse(deleted_chunks=deleted)


def _apply_known(section: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if not hasattr(section, key):
            raise HTTPException(status_code=400, detail=f"알 수 없는 설정입니다: {key}")
        setattr(section, key, value)
