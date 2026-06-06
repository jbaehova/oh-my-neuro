"""Settings and index maintenance routes."""

from __future__ import annotations

import contextlib
import os
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import effective_config
from app.api.schemas import (
    ApiKeyRequest,
    ClearRequest,
    ClearResponse,
    MCPServerDTO,
    MCPServersResponse,
    SettingsPatch,
    SettingsResponse,
)
from app.config import MCPConfig, MCPServerSpec, get_config, load_user_mcp_config, save_mcp_config
from app.config.loader import PROJECT_ROOT
from app.ingestion.pipeline import clear_all
from app.mcp.client import get_mcp_client, reset_mcp_client
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
    if payload.llm:
        _apply_known(cfg.llm, payload.llm)
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


@router.get("/settings/mcp/status")
def get_mcp_status(connect: bool = False) -> dict[str, Any]:
    cfg = effective_config()
    return get_mcp_client(cfg).status(connect=connect)


@router.get("/settings/mcp/servers", response_model=MCPServersResponse)
def list_mcp_servers() -> MCPServersResponse:
    cfg = get_config()
    mcp_cfg = load_user_mcp_config(cfg.mcp.config_path_abs, cfg.mcp.user_config_path_abs)
    return MCPServersResponse(
        servers=[MCPServerDTO(**server.model_dump(mode="json")) for server in mcp_cfg.servers.values()]
    )


@router.post("/settings/mcp/servers", response_model=MCPServersResponse)
def create_mcp_server(payload: MCPServerDTO) -> MCPServersResponse:
    cfg = get_config()
    mcp_cfg = load_user_mcp_config(cfg.mcp.config_path_abs, cfg.mcp.user_config_path_abs)
    server = _validate_mcp_server(payload)
    if server.name in mcp_cfg.servers:
        raise HTTPException(status_code=409, detail=f"이미 존재하는 MCP 서버입니다: {server.name}")
    mcp_cfg.servers[server.name] = server
    _save_mcp_servers(mcp_cfg)
    return list_mcp_servers()


@router.put("/settings/mcp/servers/{name}", response_model=MCPServersResponse)
def update_mcp_server(name: str, payload: MCPServerDTO) -> MCPServersResponse:
    cfg = get_config()
    mcp_cfg = load_user_mcp_config(cfg.mcp.config_path_abs, cfg.mcp.user_config_path_abs)
    if name not in mcp_cfg.servers:
        raise HTTPException(status_code=404, detail=f"MCP 서버를 찾을 수 없습니다: {name}")
    server = _validate_mcp_server(payload)
    if server.name != name and server.name in mcp_cfg.servers:
        raise HTTPException(status_code=409, detail=f"이미 존재하는 MCP 서버입니다: {server.name}")
    if server.name != name:
        mcp_cfg.servers.pop(name, None)
    mcp_cfg.servers[server.name] = server
    _save_mcp_servers(mcp_cfg)
    return list_mcp_servers()


@router.delete("/settings/mcp/servers/{name}", response_model=MCPServersResponse)
def delete_mcp_server(name: str) -> MCPServersResponse:
    cfg = get_config()
    mcp_cfg = load_user_mcp_config(cfg.mcp.config_path_abs, cfg.mcp.user_config_path_abs)
    if name not in mcp_cfg.servers:
        raise HTTPException(status_code=404, detail=f"MCP 서버를 찾을 수 없습니다: {name}")
    mcp_cfg.servers.pop(name, None)
    _save_mcp_servers(mcp_cfg)
    return list_mcp_servers()


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
    reset_vector_store()
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
    with contextlib.suppress(OSError):
        env_path.chmod(0o600)


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


def _validate_mcp_server(payload: MCPServerDTO) -> MCPServerSpec:
    try:
        server = MCPServerSpec(**payload.model_dump(mode="json"))
        server.to_adapter_spec()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return server


def _save_mcp_servers(config: MCPConfig) -> None:
    cfg = get_config()
    try:
        save_mcp_config(config, cfg.mcp.user_config_path_abs)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"MCP 설정 저장에 실패했습니다: {e}") from e
    reset_mcp_client()
    reset_service()
