"""High-level RAG service used by UI / CLI."""

from __future__ import annotations

import concurrent.futures
import threading
from collections.abc import Iterable, Iterator
from typing import Any

from app.common.logging import get_logger
from app.common.models import ChatMessage, ChatResponse, ChatResponseChunk, Citation
from app.config import AppConfig, get_config
from app.mcp.client import MCPClient, get_mcp_client
from app.rag.graph import GraphDeps, build_graph
from app.rag.llm import OpenAILLM
from app.storage.chroma_store import ChromaStore

log = get_logger(__name__)


class RAGService:
    """UI/CLI에서 호출하는 단일 진입점."""

    def __init__(
        self,
        cfg: AppConfig | None = None,
        store: ChromaStore | None = None,
        mcp: MCPClient | None = None,
    ) -> None:
        self._cfg = cfg or get_config()
        self._store = store
        self._mcp = mcp
        self._llm: OpenAILLM | None = None
        self._graph = None  # terminal="generate"
        self._graph_ctx = None  # terminal="prepare_context"
        self._lock = threading.Lock()

    # --- lazy singletons ---------------------------------------------------
    def _ensure_store(self) -> ChromaStore:
        if self._store is None:
            from app.storage import chroma_store

            self._store = chroma_store.get_vector_store(self._cfg)
        return self._store

    def _ensure_llm(self) -> OpenAILLM:
        if self._llm is None:
            self._llm = OpenAILLM(self._cfg)
        return self._llm

    def _ensure_mcp(self) -> MCPClient:
        if self._mcp is None:
            self._mcp = get_mcp_client(self._cfg)
        return self._mcp

    def _build_deps(self) -> GraphDeps:
        store = self._ensure_store()
        llm = self._ensure_llm()
        mcp = self._ensure_mcp() if self._cfg.mcp.enabled else None
        return GraphDeps(retriever=store, llm=llm, mcp=mcp, config=self._cfg)

    def _ensure_graph(self):
        if self._graph is not None:
            return self._graph
        with self._lock:
            if self._graph is None:
                self._graph = build_graph(self._build_deps(), terminal="generate")
        return self._graph

    def _ensure_graph_ctx(self):
        if self._graph_ctx is not None:
            return self._graph_ctx
        with self._lock:
            if self._graph_ctx is None:
                self._graph_ctx = build_graph(self._build_deps(), terminal="prepare_context")
        return self._graph_ctx

    # --- public API --------------------------------------------------------
    def ask(
        self,
        question: str,
        history: Iterable[ChatMessage] | list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        q = (question or "").strip()
        if not q:
            return ChatResponse(answer="질문을 입력해 주세요.")
        if not self._cfg.has_api_key():
            return ChatResponse(
                answer=(
                    "OPENAI_API_KEY가 설정되어 있지 않습니다. "
                    "프로젝트 루트에 `.env` 파일을 만들고 `OPENAI_API_KEY=...`를 지정하세요."
                )
            )

        coerced_history = _coerce_history(history)

        store = self._ensure_store()
        if store.count() == 0:
            return ChatResponse(
                answer=(
                    "Vault가 비어 있거나 아직 동기화되지 않았습니다. Vault 페이지에서 SYNC를 실행해 주세요."
                )
            )

        # Intent 분류 — 일반 대화/인사면 RAG 그래프 우회
        try:
            llm = self._ensure_llm()
        except Exception as e:
            log.exception("LLM 초기화 실패")
            return ChatResponse(answer=f"LLM 초기화에 실패했습니다: {e}")
        intent = _classify_intent(llm, q, coerced_history)
        if intent == "chat":
            try:
                answer = llm.chat(q, coerced_history)
            except Exception as e:
                log.exception("일반 대화 응답 실패")
                return ChatResponse(answer=f"응답 생성 중 오류가 발생했습니다: {e}")
            return ChatResponse(answer=answer or "...", citations=[], retrieval_count=0)

        try:
            graph = self._ensure_graph()
        except Exception as e:
            log.exception("RAG 그래프 초기화 실패")
            return ChatResponse(answer=f"시스템 초기화에 실패했습니다: {e}")

        state = _initial_state(q, history)
        timeout = max(10, self._cfg.llm.request_timeout + 30)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(graph.invoke, state)
                result = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            log.error("RAG 실행 타임아웃 (%ss)", timeout)
            return ChatResponse(
                answer=f"답변 생성이 {timeout}초 내에 완료되지 않았습니다. 질문을 더 구체적으로 다시 시도해 주세요."
            )
        except Exception as e:
            log.exception("RAG 실행 실패")
            return ChatResponse(answer=f"답변 생성 중 오류가 발생했습니다: {e}")

        answer = result.get("answer") or ""
        citations: list[Citation] = list(result.get("citations") or [])
        graded = result.get("graded_docs") or []
        return ChatResponse(
            answer=answer,
            citations=citations,
            used_mcp=bool(result.get("used_mcp")),
            rewritten_question=result.get("rewritten_question"),
            retrieval_count=len(graded),
        )

    def ask_stream(
        self,
        question: str,
        history: Iterable[ChatMessage] | list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatResponseChunk]:
        """스트리밍 답변. meta → token* → done 청크를 순서대로 yield."""
        q = (question or "").strip()
        if not q:
            yield ChatResponseChunk(kind="meta")
            yield ChatResponseChunk(kind="done", text="질문을 입력해 주세요.")
            return
        if not self._cfg.has_api_key():
            yield ChatResponseChunk(kind="meta")
            yield ChatResponseChunk(
                kind="done",
                text=(
                    "OPENAI_API_KEY가 설정되어 있지 않습니다. "
                    "프로젝트 루트에 `.env` 파일을 만들고 `OPENAI_API_KEY=...`를 지정하세요."
                ),
            )
            return

        coerced_history = _coerce_history(history)

        store = self._ensure_store()
        if store.count() == 0:
            yield ChatResponseChunk(kind="meta")
            yield ChatResponseChunk(
                kind="done",
                text=(
                    "Vault가 비어 있거나 아직 동기화되지 않았습니다. Vault 페이지에서 SYNC를 실행해 주세요."
                ),
            )
            return

        # Intent 분류 — 일반 대화/인사면 RAG 그래프 우회하고 chat_stream 호출
        try:
            llm_for_intent = self._ensure_llm()
        except Exception as e:
            log.exception("LLM 초기화 실패")
            yield ChatResponseChunk(kind="meta")
            yield ChatResponseChunk(kind="error", text=f"LLM 초기화 실패: {e}")
            yield ChatResponseChunk(kind="done")
            return

        intent = _classify_intent(llm_for_intent, q, coerced_history)
        if intent == "chat":
            yield ChatResponseChunk(
                kind="meta",
                citations=[],
                used_mcp=False,
                rewritten_question=None,
                retrieval_count=0,
            )
            try:
                for piece in llm_for_intent.chat_stream(q, coerced_history):
                    if piece:
                        yield ChatResponseChunk(kind="token", text=piece)
            except Exception as e:
                log.exception("일반 대화 스트리밍 실패")
                yield ChatResponseChunk(kind="error", text=f"응답 오류: {e}")
            yield ChatResponseChunk(kind="done")
            return

        try:
            graph = self._ensure_graph_ctx()
        except Exception as e:
            log.exception("RAG 그래프(ctx) 초기화 실패")
            yield ChatResponseChunk(kind="meta")
            yield ChatResponseChunk(kind="error", text=f"시스템 초기화에 실패했습니다: {e}")
            yield ChatResponseChunk(kind="done")
            return

        state = _initial_state(q, history)
        timeout = max(10, self._cfg.llm.request_timeout + 30)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(graph.invoke, state)
                prepared = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            log.error("RAG ctx 실행 타임아웃 (%ss)", timeout)
            yield ChatResponseChunk(kind="meta")
            yield ChatResponseChunk(
                kind="done",
                text=f"답변 생성이 {timeout}초 내에 완료되지 않았습니다.",
            )
            return
        except Exception as e:
            log.exception("RAG ctx 실행 실패")
            yield ChatResponseChunk(kind="meta")
            yield ChatResponseChunk(kind="error", text=f"답변 생성 중 오류: {e}")
            yield ChatResponseChunk(kind="done")
            return

        citations: list[Citation] = list(prepared.get("citations") or [])
        used_mcp = bool(prepared.get("used_mcp"))
        rewritten = prepared.get("rewritten_question")
        retrieval_count = len(prepared.get("graded_docs") or [])
        context_block = prepared.get("context_block") or ""

        yield ChatResponseChunk(
            kind="meta",
            citations=citations,
            used_mcp=used_mcp,
            rewritten_question=rewritten,
            retrieval_count=retrieval_count,
        )

        if not context_block:
            from app.rag import prompts as _prompts

            yield ChatResponseChunk(kind="done", text=_prompts.EMPTY_ANSWER)
            return

        llm = self._ensure_llm()
        try:
            for piece in llm.generate_stream(q, context_block):
                if piece:
                    yield ChatResponseChunk(kind="token", text=piece)
        except Exception as e:
            log.exception("스트리밍 생성 실패")
            yield ChatResponseChunk(kind="error", text=f"스트리밍 오류: {e}")
        yield ChatResponseChunk(kind="done")


def _initial_state(question: str, history: Any) -> dict:
    return {
        "question": question,
        "rewritten_question": None,
        "chat_history": _coerce_history(history),
        "retrieved_docs": [],
        "graded_docs": [],
        "mcp_results": [],
        "used_mcp": False,
        "rewrites": 0,
    }


def _classify_intent(llm: Any, question: str, history: list[ChatMessage]) -> str:
    classifier = getattr(llm, "classify_intent", None)
    if classifier is None:
        return "search"
    try:
        intent = str(classifier(question, history)).strip().lower()
    except Exception:
        log.warning("intent 분류 실패, 검색 경로로 폴백", exc_info=True)
        return "search"
    return "chat" if intent == "chat" else "search"


_DEFAULT_SERVICE: RAGService | None = None


def get_service(cfg: AppConfig | None = None) -> RAGService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = RAGService(cfg or get_config())
    return _DEFAULT_SERVICE


def reset_service() -> None:
    global _DEFAULT_SERVICE
    _DEFAULT_SERVICE = None


def answer_question(
    question: str, history: Iterable[ChatMessage] | list[dict[str, Any]] | None = None
) -> ChatResponse:
    return get_service().ask(question, history)


def _coerce_history(history: Any) -> list[ChatMessage]:
    if history is None:
        return []
    out: list[ChatMessage] = []
    for item in history:
        if isinstance(item, ChatMessage):
            out.append(item)
        elif isinstance(item, dict):
            role = str(item.get("role") or "user")
            content = str(item.get("content") or "")
            if role not in ("user", "assistant", "system"):
                role = "user"
            if content:
                out.append(ChatMessage(role=role, content=content))
        elif isinstance(item, tuple) and len(item) == 2:
            user_msg, assistant_msg = item
            if user_msg:
                out.append(ChatMessage(role="user", content=str(user_msg)))
            if assistant_msg:
                out.append(ChatMessage(role="assistant", content=str(assistant_msg)))
    return out
