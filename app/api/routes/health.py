"""Health and bootstrap routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import effective_config
from app.api.schemas import BootstrapResponse, HealthResponse

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
    return BootstrapResponse(
        title=cfg.ui.title,
        description=cfg.ui.description,
        onboarding_completed=False,
        vault_path="",
        api_key_configured=cfg.has_api_key(),
        indexed_files=0,
        last_sync_at=None,
    )
