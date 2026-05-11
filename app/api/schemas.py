"""Pydantic DTOs for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    ok: bool = True
    app: str
    api_key_configured: bool


class BootstrapResponse(BaseModel):
    title: str
    description: str
    onboarding_completed: bool
    vault_path: str
    api_key_configured: bool
    indexed_files: int
    last_sync_at: str | None = None
