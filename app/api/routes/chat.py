"""Chat routes."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import effective_config, iter_ndjson
from app.api.schemas import ChatRequest, ChatResponseDTO
from app.rag.service import RAGService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponseDTO)
def ask(payload: ChatRequest) -> ChatResponseDTO:
    cfg = effective_config()
    response = RAGService(cfg=cfg).ask(payload.question, payload.history, web_search=payload.web_search)
    return ChatResponseDTO(
        answer=response.answer,
        citations=response.citations,
        used_mcp=response.used_mcp,
        used_web_search=response.used_web_search,
        web_search_requested=response.web_search_requested,
        web_search_error=response.web_search_error,
        rewritten_question=response.rewritten_question,
        retrieval_count=response.retrieval_count,
        wiki_count=response.wiki_count,
        raw_count=response.raw_count,
    )


@router.post("/stream")
def ask_stream(payload: ChatRequest) -> StreamingResponse:
    cfg = effective_config()

    def _events() -> Iterator[dict]:
        service = RAGService(cfg=cfg)
        for chunk in service.ask_stream(payload.question, payload.history, web_search=payload.web_search):
            yield chunk.model_dump(mode="json")

    return StreamingResponse(
        iter_ndjson(_events()),
        media_type="application/x-ndjson; charset=utf-8",
    )
