"""Settings and index maintenance routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import effective_config
from app.api.schemas import ClearRequest, ClearResponse, SettingsPatch, SettingsResponse
from app.config import get_config
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
        wiki=cfg.wiki.model_dump(mode="json"),
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
    if payload.wiki:
        _apply_known(cfg.wiki, payload.wiki)
    if payload.mcp:
        _apply_known(cfg.mcp, payload.mcp)
        reset_mcp_client()
    if payload.ui:
        _apply_known(cfg.ui, payload.ui)
    reset_service()
    return get_settings()


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
