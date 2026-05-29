"""Health and bootstrap routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import effective_config
from app.api.schemas import BootstrapResponse, HealthResponse
from app.ingestion.pipeline import list_indexed_sources
from app.vault.state import VaultState
from app.wiki.service import WikiService

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    cfg = effective_config()
    return HealthResponse(
        app=cfg.app.name,
        api_key_configured=cfg.has_api_key(),
    )


@router.get("/bootstrap", response_model=BootstrapResponse)
def bootstrap() -> BootstrapResponse:
    cfg = effective_config()
    state = VaultState.load()
    try:
        indexed_files = len(list_indexed_sources(config=cfg))
    except Exception:
        indexed_files = 0
    return BootstrapResponse(
        title=cfg.ui.title,
        description=cfg.ui.description,
        onboarding_completed=state.onboarding_completed,
        vault_path=state.vault_path,
        api_key_configured=cfg.has_api_key(),
        indexed_files=indexed_files,
        last_sync_at=state.last_sync_at,
        wiki=WikiService(cfg).status().model_dump(mode="json"),
    )
