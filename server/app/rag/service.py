"""High-level RAG service used by UI / CLI."""

from __future__ import annotations

import concurrent.futures
import re
import threading
import time
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


_DIRECT_CHAT_PHRASES = frozenset(
    {
        "안녕",
        "안녕하세요",
        "ㅎㅇ",
        "하이",
        "hi",
        "hello",
        "hey",
        "뭐해",
        "고마워",
        "고맙습니다",
        "감사",
        "감사합니다",
        "thanks",
        "thankyou",
        "help",
        "도움말",
        "사용법",
        "너는뭐야",
        "뭐할수있어",
        "무엇을할수있어",
    }
)

_MAX_HISTORY_MESSAGES = 40
_MAX_HISTORY_CONTENT_CHARS = 4000

_DOCUMENT_INTENT_MARKERS = (
    "문서",
    "파일",
    "vault",
    "볼트",
    "업로드",
    "인덱스",
    "인덱싱",
    "동기화",
    "출처",
    "근거",
    "인용",
    "pdf",
    "docx",
    "txt",
    "markdown",
    "위키",
    "wiki",
    "첨부",
)

_WEB_EXPLICIT_INTENT_MARKERS = (
    "웹",
    "인터넷",
    "웹검색",
    "인터넷 검색",
    "구글 검색",
    "구글",
    "뉴스",
    "기사",
)

_WEB_FRESHNESS_INTENT_MARKERS = (
    "오늘",
    "현재",
    "최신",
    "최근",
    "실시간",
    "방금",
)

_WEB_PUBLIC_INTENT_MARKERS = (
    "뉴스",
    "기사",
    "발표",
    "공개",
    "릴리즈",
    "업데이트",
    "동향",
)

_LAW_INTENT_MARKERS = (
    "헌법",
    "형법",
    "민법",
    "상법",
    "법률",
    "법령",
    "조항",
    "판례",
    "처벌",
    "범죄",
    "위반",
    "저촉",
    "법적",
    "어떤 법",
    "무슨 법",
)

_CHAT_INTENT_MARKERS = (
    "농담",
    "잡담",
    "수다",
    "안부",
    "너는",
    "너가",
    "네가",
    "너의",
    "너 뭐",
    "대화",
    "채팅",
    "기분",
    "어때",
    "방금",
    "아까",
    "내 질문",
    "질문 흐름",
    "흐름",
    "이전 질문",
    "이전 답변",
    "앞서",
    "위 답변",
    "위에서",
    "내가 물어",
    "내가 말",
    "네 답변",
    "말투",
    "톤",
    "번역",
    "영어로",
    "한국어로",
    "문장",
    "메일",
    "글 작성",
    "다듬",
    "고쳐",
    "쉽게 설명",
    "다시 설명",
)


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
        self._wiki_store = None
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

    def _ensure_wiki_store(self):
        if not self._cfg.wiki.enabled:
            return None
        if self._wiki_store is None:
            from app.wiki.store import wiki_root, wiki_vector_store

            root = wiki_root(self._cfg)
            if root is None or not root.exists():
                return None
            self._wiki_store = wiki_vector_store(self._cfg)
        return self._wiki_store

    def _build_deps(self) -> GraphDeps:
        store = self._ensure_store()
        llm = self._ensure_llm()
        mcp = self._ensure_mcp() if self._cfg.mcp.enabled else None
        wiki_store = self._ensure_wiki_store()
        return GraphDeps(retriever=store, llm=llm, mcp=mcp, wiki_retriever=wiki_store, config=self._cfg)

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
        web_search: bool = False,
    ) -> ChatResponse:
        q = (question or "").strip()
        if not q:
            return ChatResponse(answer="질문을 입력해 주세요.")
        if not self._cfg.has_api_key():
            return ChatResponse(
                answer=(
                    "OPENAI_API_KEY가 설정되어 있지 않습니다. "
                    "Settings에서 OpenAI API 키 설정을 완료하세요."
                )
            )

        coerced_history = _coerce_history(history)

        try:
            llm = self._ensure_llm()
        except Exception as e:
            log.exception("LLM 초기화 실패")
            return ChatResponse(answer=f"LLM 초기화에 실패했습니다: {e}")
        if _should_answer_directly(q):
            try:
                answer = llm.chat(q, coerced_history)
            except Exception as e:
                log.exception("일반 대화 응답 실패")
                return ChatResponse(answer=f"응답 생성 중 오류가 발생했습니다: {e}")
            return ChatResponse(answer=answer or "...", citations=[], retrieval_count=0)

        store = self._ensure_store()
        if store.count() == 0 and not web_search:
            if _should_fallback_to_chat(q):
                try:
                    answer = llm.chat(q, coerced_history)
                except Exception as e:
                    log.exception("빈 Vault 후 일반 대화 폴백 실패")
                    return ChatResponse(answer=f"응답 생성 중 오류가 발생했습니다: {e}")
                return ChatResponse(answer=answer or "...", citations=[], retrieval_count=0)
            return ChatResponse(
                answer=(
                    "Vault가 비어 있거나 아직 동기화되지 않았습니다. Vault 페이지에서 SYNC를 실행해 주세요."
                )
            )

        try:
            graph = self._ensure_graph()
        except Exception as e:
            log.exception("RAG 그래프 초기화 실패")
            return ChatResponse(answer=f"시스템 초기화에 실패했습니다: {e}")

        state = _initial_state(q, coerced_history, web_search=web_search)
        timeout = max(10, self._cfg.llm.request_timeout + 30)
        started = time.perf_counter()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(graph.invoke, state)
                result = future.result(timeout=timeout)
                log.info("rag.ask.prepare_and_generate %.3fs", time.perf_counter() - started)
        except concurrent.futures.TimeoutError:
            log.error("RAG 실행 타임아웃 (%ss)", timeout)
            return ChatResponse(
                answer=f"답변 생성이 {timeout}초 내에 완료되지 않았습니다. 질문을 더 구체적으로 다시 시도해 주세요."
            )
        except Exception as e:
            log.exception("RAG 실행 실패")
            return ChatResponse(answer=f"답변 생성 중 오류가 발생했습니다: {e}")

        context_block = result.get("context_block") or ""
        if not context_block and _should_fallback_to_chat(q):
            try:
                answer = llm.chat(q, coerced_history)
            except Exception as e:
                log.exception("빈 RAG 컨텍스트 후 일반 대화 폴백 실패")
                return ChatResponse(answer=f"응답 생성 중 오류가 발생했습니다: {e}")
            return ChatResponse(answer=answer or "...", citations=[], retrieval_count=0)

        answer = result.get("answer") or ""
        citations: list[Citation] = list(result.get("citations") or [])
        graded = result.get("graded_docs") or []
        wiki = result.get("graded_wiki_docs") or []
        return ChatResponse(
            answer=answer,
            citations=citations,
            used_mcp=bool(result.get("used_mcp")),
            rewritten_question=result.get("rewritten_question"),
            retrieval_count=len(graded) + len(wiki),
            raw_count=len(graded),
            wiki_count=len(wiki),
            used_web_search=bool(result.get("used_web_search")),
            web_search_requested=bool(result.get("web_search_requested")),
            web_search_error=str(result.get("web_search_error") or ""),
        )

    def ask_stream(
        self,
        question: str,
        history: Iterable[ChatMessage] | list[dict[str, Any]] | None = None,
        web_search: bool = False,
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
                kind="error",
                text=(
                    "OPENAI_API_KEY가 설정되어 있지 않습니다. "
                    "Settings에서 OpenAI API 키 설정을 완료하세요."
                ),
            )
            return

        coerced_history = _coerce_history(history)

        try:
            llm_for_direct = self._ensure_llm()
        except Exception as e:
            log.exception("LLM 초기화 실패")
            yield ChatResponseChunk(kind="meta")
            yield ChatResponseChunk(kind="error", text=f"LLM 초기화 실패: {e}")
            yield ChatResponseChunk(kind="done")
            return

        if _should_answer_directly(q):
            yield ChatResponseChunk(
                kind="meta",
                citations=[],
                used_mcp=False,
                used_web_search=False,
                rewritten_question=None,
                retrieval_count=0,
            )
            try:
                for piece in llm_for_direct.chat_stream(q, coerced_history):
                    if piece:
                        yield ChatResponseChunk(kind="token", text=piece)
            except Exception as e:
                log.exception("일반 대화 스트리밍 실패")
                yield ChatResponseChunk(kind="error", text=f"응답 오류: {e}")
            yield ChatResponseChunk(kind="done")
            return

        store = self._ensure_store()
        if store.count() == 0 and not web_search:
            yield ChatResponseChunk(kind="meta")
            if _should_fallback_to_chat(q):
                try:
                    for piece in llm_for_direct.chat_stream(q, coerced_history):
                        if piece:
                            yield ChatResponseChunk(kind="token", text=piece)
                except Exception as e:
                    log.exception("빈 Vault 후 일반 대화 스트리밍 폴백 실패")
                    yield ChatResponseChunk(kind="error", text=f"응답 오류: {e}")
                yield ChatResponseChunk(kind="done")
                return
            yield ChatResponseChunk(
                kind="done",
                text=(
                    "Vault가 비어 있거나 아직 동기화되지 않았습니다. Vault 페이지에서 SYNC를 실행해 주세요."
                ),
            )
            return

        try:
            graph = self._ensure_graph_ctx()
        except Exception as e:
            log.exception("RAG 그래프(ctx) 초기화 실패")
            yield ChatResponseChunk(kind="meta")
            yield ChatResponseChunk(kind="error", text=f"시스템 초기화에 실패했습니다: {e}")
            yield ChatResponseChunk(kind="done")
            return

        state = _initial_state(q, coerced_history, web_search=web_search)
        timeout = max(10, self._cfg.llm.request_timeout + 30)
        started = time.perf_counter()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(graph.invoke, state)
                prepared = future.result(timeout=timeout)
                log.info("rag.stream.prepare_context %.3fs", time.perf_counter() - started)
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
        used_web_search = bool(prepared.get("used_web_search"))
        web_search_requested = bool(prepared.get("web_search_requested"))
        web_search_error = str(prepared.get("web_search_error") or "")
        rewritten = prepared.get("rewritten_question")
        retrieval_count = len(prepared.get("graded_docs") or [])
        wiki_count = len(prepared.get("graded_wiki_docs") or [])
        raw_count = retrieval_count
        retrieval_count += wiki_count
        context_block = prepared.get("context_block") or ""

        yield ChatResponseChunk(
            kind="meta",
            citations=citations,
            used_mcp=used_mcp,
            used_web_search=used_web_search,
            web_search_requested=web_search_requested,
            web_search_error=web_search_error,
            rewritten_question=rewritten,
            retrieval_count=retrieval_count,
            raw_count=raw_count,
            wiki_count=wiki_count,
        )

        if not context_block:
            from app.rag import prompts as _prompts

            if _should_fallback_to_chat(q):
                try:
                    for piece in llm_for_direct.chat_stream(q, coerced_history):
                        if piece:
                            yield ChatResponseChunk(kind="token", text=piece)
                except Exception as e:
                    log.exception("빈 RAG 컨텍스트 후 일반 대화 스트리밍 폴백 실패")
                    yield ChatResponseChunk(kind="error", text=f"응답 오류: {e}")
                yield ChatResponseChunk(kind="done")
                return
            yield ChatResponseChunk(kind="done", text=_prompts.EMPTY_ANSWER)
            return

        llm = self._ensure_llm()
        generation_question = rewritten or q
        generation_started = time.perf_counter()
        first_piece_logged = False
        pieces = 0
        try:
            for piece in llm.generate_stream(generation_question, context_block):
                if piece:
                    if not first_piece_logged:
                        log.info(
                            "rag.stream.first_token %.3fs",
                            time.perf_counter() - generation_started,
                        )
                        first_piece_logged = True
                    pieces += 1
                    yield ChatResponseChunk(kind="token", text=piece)
        except Exception as e:
            log.exception("스트리밍 생성 실패")
            yield ChatResponseChunk(kind="error", text=f"스트리밍 오류: {e}")
        log.info(
            "rag.stream.generate %.3fs pieces=%d",
            time.perf_counter() - generation_started,
            pieces,
        )
        yield ChatResponseChunk(kind="done")


def _initial_state(question: str, history: Any, *, web_search: bool = False) -> dict:
    return {
        "question": question,
        "rewritten_question": None,
        "chat_history": _coerce_history(history),
        "retrieved_docs": [],
        "wiki_docs": [],
        "graded_docs": [],
        "graded_wiki_docs": [],
        "mcp_results": [],
        "web_results": [],
        "used_mcp": False,
        "used_web_search": False,
        "web_search_enabled": web_search,
        "web_search_requested": False,
        "web_search_error": "",
        "rewrites": 0,
    }


def _should_answer_directly(question: str) -> bool:
    if _chat_phrase_key(question) in _DIRECT_CHAT_PHRASES:
        return True
    if _has_retrieval_intent(question):
        return False
    return _has_marker(question, _CHAT_INTENT_MARKERS)


def _should_fallback_to_chat(question: str) -> bool:
    return not _has_retrieval_intent(question)


def _chat_phrase_key(question: str) -> str:
    lowered = (question or "").strip().lower()
    return re.sub(r"[\s.!?？。~…'\"`,，、:：;；]+", "", lowered)


def _has_retrieval_intent(question: str) -> bool:
    return (
        _has_marker(question, _DOCUMENT_INTENT_MARKERS)
        or _has_web_intent(question)
        or _has_marker(question, _LAW_INTENT_MARKERS)
    )


def _has_web_intent(question: str) -> bool:
    if _has_marker(question, _WEB_EXPLICIT_INTENT_MARKERS):
        return True
    return _has_marker(question, _WEB_FRESHNESS_INTENT_MARKERS) and _has_marker(
        question,
        _WEB_PUBLIC_INTENT_MARKERS,
    )


def _has_marker(question: str, markers: tuple[str, ...]) -> bool:
    lowered = (question or "").lower()
    compact = "".join(lowered.split())
    return any(marker.lower() in lowered or marker.lower().replace(" ", "") in compact for marker in markers)


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
            if item.role in ("user", "assistant") and item.content:
                out.append(ChatMessage(role=item.role, content=_trim_history_content(item.content)))
        elif isinstance(item, dict):
            role = str(item.get("role") or "user")
            content = str(item.get("content") or "")
            if role not in ("user", "assistant"):
                continue
            if content:
                out.append(ChatMessage(role=role, content=_trim_history_content(content)))
        elif isinstance(item, tuple) and len(item) == 2:
            user_msg, assistant_msg = item
            if user_msg:
                out.append(ChatMessage(role="user", content=_trim_history_content(str(user_msg))))
            if assistant_msg:
                out.append(ChatMessage(role="assistant", content=_trim_history_content(str(assistant_msg))))
    return out[-_MAX_HISTORY_MESSAGES:]


def _trim_history_content(content: str) -> str:
    value = (content or "").strip()
    if len(value) <= _MAX_HISTORY_CONTENT_CHARS:
        return value
    return f"{value[:_MAX_HISTORY_CONTENT_CHARS].rstrip()}..."
