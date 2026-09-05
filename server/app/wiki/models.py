"""Models for the generated Vault wiki."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class WikiSourceState(BaseModel):
    content_hash: str
    source_page: str
    title: str
    updated_at: str
    concepts: dict[str, str] = Field(default_factory=dict)
    open_questions: list[str] = Field(default_factory=list)
    excerpt: str = ""


class WikiContradiction(BaseModel):
    concept: str
    source_a: str
    source_b: str
    description_a: str
    description_b: str
    summary: str


class WikiState(BaseModel):
    version: int = 1
    last_built_at: str | None = None
    sources: dict[str, WikiSourceState] = Field(default_factory=dict)
    contradictions: list[WikiContradiction] = Field(default_factory=list)


class WikiStatus(BaseModel):
    enabled: bool
    configured: bool
    path: str = ""
    page_count: int = 0
    generated_page_count: int = 0
    document_count: int = 0
    indexed_chunks: int = 0
    source_count: int = 0
    last_built_at: str | None = None
    error: str = ""


class WikiPageSummary(BaseModel):
    id: str
    path: str
    title: str
    section: str
    size: int = 0
    updated_at: str = ""
    excerpt: str = ""


class WikiPageContent(WikiPageSummary):
    content: str
    linked_source_pages: list[str] = Field(default_factory=list)


class WikiBuildResult(BaseModel):
    pages_written: int = 0
    indexed_chunks: int = 0
    sources_processed: int = 0
    sources_skipped: int = 0
    duration_s: float = 0.0
    error: str = ""


class WikiLintIssue(BaseModel):
    severity: Literal["info", "warning", "error"] = "info"
    code: str
    message: str
    page: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class WikiGraphNode(BaseModel):
    id: str
    label: str
    kind: Literal["concept", "source", "page"]
    page_id: str
    source_path: str = ""


class WikiGraphEdge(BaseModel):
    source: str
    target: str
    label: str = ""


class WikiGraph(BaseModel):
    nodes: list[WikiGraphNode] = Field(default_factory=list)
    edges: list[WikiGraphEdge] = Field(default_factory=list)


class WikiEasyIndexMatch(BaseModel):
    kind: Literal["wiki", "document"]
    page_id: str = ""
    page_title: str = ""
    source: str = ""
    snippet: str = ""
    score: float = 0.0


class WikiEasyIndexResult(BaseModel):
    source: str
    title: str
    doc_type: str = ""
    score: float = 0.0
    excerpt: str = ""
    concepts: list[str] = Field(default_factory=list)
    matches: list[WikiEasyIndexMatch] = Field(default_factory=list)


class WikiEasyIndexResponse(BaseModel):
    query: str
    semantic_available: bool = True
    error: str = ""
    results: list[WikiEasyIndexResult] = Field(default_factory=list)
