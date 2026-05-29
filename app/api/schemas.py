"""Pydantic DTOs for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.common.models import ChatMessage, Citation, SkippedFile
from app.vault.state import SyncHistoryEntry


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
    wiki: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponseDTO(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    used_mcp: bool = False
    rewritten_question: str | None = None
    retrieval_count: int = 0
    wiki_count: int = 0
    raw_count: int = 0


class VaultPathRequest(BaseModel):
    path: str


class VaultStatusResponse(BaseModel):
    vault_path: str
    onboarding_completed: bool
    last_sync_at: str | None = None
    sync_history: list[SyncHistoryEntry] = Field(default_factory=list)
    indexed_files: int = 0
    api_key_configured: bool = False
    wiki: dict[str, Any] = Field(default_factory=dict)


class IndexedFile(BaseModel):
    source: str
    doc_type: str = ""
    size: int = 0
    synced_at: str = ""


class IndexedFilesResponse(BaseModel):
    files: list[IndexedFile] = Field(default_factory=list)


class SyncDoneEvent(BaseModel):
    kind: Literal["done"] = "done"
    result: dict[str, Any]
    skipped: list[SkippedFile] = Field(default_factory=list)


class SettingsResponse(BaseModel):
    app: dict[str, Any]
    llm: dict[str, Any]
    retrieval: dict[str, Any]
    storage: dict[str, Any]
    wiki: dict[str, Any]
    vault: dict[str, Any]
    mcp: dict[str, Any]
    ui: dict[str, Any]
    api_key_configured: bool


class SettingsPatch(BaseModel):
    retrieval: dict[str, Any] | None = None
    wiki: dict[str, Any] | None = None
    mcp: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None


class ClearRequest(BaseModel):
    force: bool = False


class ClearResponse(BaseModel):
    deleted_chunks: int
