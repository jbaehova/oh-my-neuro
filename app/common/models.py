"""Shared Pydantic models for OH-MY-NEURO."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceKind = Literal["document", "mcp", "wiki", "web"]


class Citation(BaseModel):
    """답변 출처."""

    source: str
    location: str = ""
    page: int | None = None
    doc_type: str | None = None
    kind: SourceKind = "document"
    snippet: str | None = None

    def render(self) -> str:
        parts = [self.source]
        if self.page is not None:
            parts.append(f"p.{self.page}")
        elif self.location:
            parts.append(self.location)
        labels = {"document": "문서", "mcp": "외부", "wiki": "위키", "web": "웹"}
        label = labels.get(self.kind, "문서")
        return f"[{label}] {' · '.join(parts)}"


class Chunk(BaseModel):
    """ChromaDB에 저장되는 청크 단위."""

    chunk_id: str
    content: str
    source: str
    page: int | None = None
    location: str = ""
    doc_type: str = ""
    uploaded_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    extras: dict[str, Any] = Field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        md: dict[str, Any] = {
            "source": self.source,
            "page": self.page if self.page is not None else -1,
            "location": self.location,
            "doc_type": self.doc_type,
            "uploaded_at": self.uploaded_at,
        }
        for k, v in self.extras.items():
            if isinstance(v, str | int | float | bool) or v is None:
                md[k] = v
        return md


class RetrievedChunk(BaseModel):
    chunk_id: str
    content: str
    metadata: dict[str, Any]
    score: float = 0.0

    @property
    def source(self) -> str:
        return str(self.metadata.get("source", ""))

    @property
    def page(self) -> int | None:
        v = self.metadata.get("page")
        if v is None or v == -1:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @property
    def location(self) -> str:
        return str(self.metadata.get("location", ""))

    @property
    def doc_type(self) -> str:
        return str(self.metadata.get("doc_type", ""))

    def as_citation(self) -> Citation:
        kind = str(self.metadata.get("kind") or "document")
        if kind not in ("document", "mcp", "wiki", "web"):
            kind = "document"
        source = self.source
        location = self.location
        if kind == "wiki" and self.metadata.get("original_source"):
            source = str(self.metadata.get("original_source") or source)
            location = self.source
        return Citation(
            source=source,
            location=location,
            page=self.page,
            doc_type=self.doc_type,
            kind=kind,  # type: ignore[arg-type]
            snippet=(self.content[:180] + "…") if len(self.content) > 180 else self.content,
        )


class MCPResult(BaseModel):
    tool: str
    title: str = ""
    content: str = ""
    url: str | None = None
    kind: Literal["mcp", "web"] = "mcp"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_citation(self) -> Citation:
        source = self.title or self.tool
        location = self.url or self.tool
        return Citation(
            source=source,
            location=location,
            kind=self.kind,
            snippet=(self.content[:180] + "…") if len(self.content) > 180 else self.content,
        )


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class SkippedFile(BaseModel):
    """sync 도중 건너뛴 파일."""

    path: str
    reason: str  # "too_large" | "parse_failed" | "unreadable" | "unsupported_ext"


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    used_mcp: bool = False
    rewritten_question: str | None = None
    retrieval_count: int = 0
    wiki_count: int = 0
    raw_count: int = 0
    used_web_search: bool = False
    web_search_requested: bool = False
    web_search_error: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)

    def render_with_sources(self) -> str:
        if not self.citations:
            return self.answer
        lines = [self.answer.rstrip(), "", "**출처**"]
        for idx, cit in enumerate(self.citations, start=1):
            lines.append(f"{idx}. {cit.render()}")
        return "\n".join(lines)


class ChatResponseChunk(BaseModel):
    """``RAGService.ask_stream`` 가 방출하는 스트리밍 청크.

    kind:
      * ``meta``  — 출처·재작성·MCP 사용 여부 등 메타정보. 첫 번째에 한 번 내려온다.
      * ``token`` — 답변 토큰 delta.
      * ``error`` — 비-치명적 에러(폴백 후 진행 가능).
      * ``done``  — 스트림 종료 신호. 비-스트리밍 경로에선 ``text`` 에 완성된 응답이 실린다.
    """

    kind: Literal["meta", "token", "done", "error"]
    text: str = ""
    citations: list[Citation] = Field(default_factory=list)
    used_mcp: bool = False
    rewritten_question: str | None = None
    retrieval_count: int = 0
    wiki_count: int = 0
    raw_count: int = 0
    used_web_search: bool = False
    web_search_requested: bool = False
    web_search_error: str = ""


class IndexingDocumentResult(BaseModel):
    file: str
    source: str
    doc_type: str
    chunks: int
    status: Literal["ok", "error"]
    message: str = ""


class IndexingResult(BaseModel):
    documents: list[IndexingDocumentResult] = Field(default_factory=list)
    skipped: list[SkippedFile] = Field(default_factory=list)

    @property
    def total_chunks(self) -> int:
        return sum(d.chunks for d in self.documents if d.status == "ok")

    @property
    def succeeded(self) -> int:
        return sum(1 for d in self.documents if d.status == "ok")

    @property
    def failed(self) -> int:
        return sum(1 for d in self.documents if d.status == "error")

    def summary(self) -> str:
        if not self.documents:
            return "처리된 문서가 없습니다."
        return (
            f"총 {len(self.documents)}개 파일 중 성공 {self.succeeded}건, "
            f"실패 {self.failed}건, 저장 청크 {self.total_chunks}개"
        )


class SyncResult(BaseModel):
    added: int = 0
    updated: int = 0
    deleted: int = 0
    total_chunks: int = 0
    skipped: list[SkippedFile] = Field(default_factory=list)
    duration_s: float = 0.0
    wiki_pages: int = 0
    wiki_sources: int = 0
    wiki_error: str = ""

    def summary(self) -> str:
        base = (
            f"추가 {self.added} · 수정 {self.updated} · 삭제 {self.deleted} · "
            f"건너뜀 {len(self.skipped)} · {self.duration_s:.1f}초"
        )
        if self.wiki_error:
            return f"{base} · Wiki 오류"
        if self.wiki_pages:
            return f"{base} · Wiki {self.wiki_pages} pages"
        return base
