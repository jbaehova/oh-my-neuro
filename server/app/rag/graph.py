"""Corrective RAG pipeline built with LangGraph."""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from app.common.logging import get_logger
from app.common.models import ChatMessage, Citation, MCPResult, RetrievedChunk
from app.config import AppConfig, get_config
from app.rag import prompts

log = get_logger(__name__)


class Retriever(Protocol):
    def search(self, query: str, top_k: int = 5, fetch_k: int | None = None) -> list[RetrievedChunk]: ...


class LLMClient(Protocol):
    def grade(self, question: str, document: str) -> bool: ...
    def rewrite(self, question: str, history: list[ChatMessage]) -> str: ...
    def generate(self, question: str, context_block: str) -> str: ...
    def generate_stream(self, question: str, context_block: str) -> Iterable[str]: ...


class MCPBridge(Protocol):
    def is_available(self) -> bool: ...
    def search_law(self, query: str) -> list[MCPResult]: ...
    def search_web(self, query: str) -> list[MCPResult]: ...


@dataclass(slots=True)
class GraphDeps:
    retriever: Retriever
    llm: LLMClient
    mcp: MCPBridge | None = None
    wiki_retriever: Retriever | None = None
    config: AppConfig | None = None


class RAGState(TypedDict, total=False):
    question: str
    rewritten_question: str | None
    chat_history: list[ChatMessage]
    retrieved_docs: list[RetrievedChunk]
    wiki_docs: list[RetrievedChunk]
    graded_docs: list[RetrievedChunk]
    graded_wiki_docs: list[RetrievedChunk]
    mcp_results: list[MCPResult]
    web_results: list[MCPResult]
    used_mcp: bool
    used_web_search: bool
    web_search_enabled: bool
    web_search_requested: bool
    web_search_error: str
    rewrites: int
    answer: str
    citations: list[Citation]
    context_block: str
    route: str


Terminal = Literal["generate", "prepare_context"]


_LAW_TRIGGER_PHRASES = (
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

_LAW_FOLLOW_UP_MARKERS = (
    "조항",
    "몇 조",
    "몇 항",
    "그 조",
    "그 항",
    "해당 조",
    "해당 항",
    "위 조",
    "위 항",
)

_WEB_EXPLICIT_TRIGGER_PHRASES = (
    "웹",
    "인터넷",
    "웹검색",
    "인터넷 검색",
    "구글 검색",
    "구글",
    "뉴스",
    "기사",
)

_WEB_FRESHNESS_TRIGGER_PHRASES = (
    "오늘",
    "현재",
    "최신",
    "최근",
    "실시간",
    "방금",
)

_WEB_PUBLIC_TRIGGER_PHRASES = (
    "뉴스",
    "기사",
    "발표",
    "공개",
    "릴리즈",
    "업데이트",
    "동향",
)

_FOLLOW_UP_REFERENCE_PHRASES = (
    "아까",
    "방금",
    "이전",
    "앞서",
    "위에서",
    "위 내용",
    "위 답변",
    "위 질문",
    "그거",
    "그것",
    "그 내용",
    "그 문서",
    "그 질문",
    "그 답변",
    "저거",
    "계속",
    "이어서",
    "연결해서",
    "관련해서",
    "방금 말한",
    "전에 말한",
)

_SHORT_FOLLOW_UP_MARKERS = (
    "비교",
    "정리",
    "요약",
    "설명",
    "다시",
    "더",
    "추가",
    "자세히",
    "예시",
    "차이",
    "공통점",
    "문제점",
    "리스크",
)

_STANDALONE_QUERY_MARKERS = (
    "문서",
    "파일",
    "vault",
    "볼트",
    "업로드",
    "pdf",
    "docx",
    "txt",
    "위키",
    "wiki",
)


def _is_law_question(
    question: str,
    cfg: AppConfig,
    history: list[ChatMessage] | None = None,
    original_question: str | None = None,
) -> bool:
    if _has_law_trigger(question, cfg):
        return True
    if not history or not _is_law_follow_up(original_question or question):
        return False
    return any(_has_law_trigger(m.content, cfg) for m in history[-4:] if m.role == "user")


def _has_law_trigger(text: str, cfg: AppConfig) -> bool:
    triggers = [kw for kw in [*cfg.mcp.law_keywords, *_LAW_TRIGGER_PHRASES] if kw.strip()]
    lowered = text.lower()
    compact = "".join(lowered.split())
    for trigger in triggers:
        needle = trigger.lower()
        if needle in lowered or needle.replace(" ", "") in compact:
            return True
    return False


def _is_law_follow_up(question: str) -> bool:
    text = question.lower()
    compact = "".join(text.split())
    if any(marker.replace(" ", "") in compact for marker in _LAW_FOLLOW_UP_MARKERS):
        return True
    return bool(re.search(r"(제\s*)?\d+\s*(조|항)", text))


def _should_search_web(state: RAGState) -> bool:
    if not state.get("web_search_enabled"):
        return False
    candidates = [state["question"]]
    rewritten = state.get("rewritten_question")
    if rewritten:
        candidates.append(rewritten)
    return any(_has_web_trigger(q) for q in candidates)


def _web_query(state: RAGState) -> str:
    question = state["question"]
    rewritten = state.get("rewritten_question")
    if rewritten and _has_web_trigger(rewritten):
        return rewritten
    if _has_web_trigger(question):
        return question
    return rewritten or question


def _has_web_trigger(question: str) -> bool:
    lowered = question.lower()
    compact = "".join(lowered.split())
    has_explicit = any(marker.replace(" ", "") in compact for marker in _WEB_EXPLICIT_TRIGGER_PHRASES)
    has_freshness = any(marker.replace(" ", "") in compact for marker in _WEB_FRESHNESS_TRIGGER_PHRASES)
    has_public = any(marker.replace(" ", "") in compact for marker in _WEB_PUBLIC_TRIGGER_PHRASES)
    return has_explicit or (has_freshness and has_public)


def _should_use_history_for_query(question: str, history: list[ChatMessage]) -> bool:
    """Only let prior turns affect retrieval when the current question is underspecified."""
    if not history:
        return False
    lowered = question.lower()
    compact = "".join(lowered.split())
    if any(marker.replace(" ", "") in compact for marker in _FOLLOW_UP_REFERENCE_PHRASES):
        return True
    if _is_law_follow_up(question):
        return True
    if any(marker.replace(" ", "") in compact for marker in _STANDALONE_QUERY_MARKERS):
        return False
    tokenish_length = len(re.sub(r"\s+", "", question))
    if tokenish_length > 28:
        return False
    return any(marker.replace(" ", "") in compact for marker in _SHORT_FOLLOW_UP_MARKERS)


def _render_context(
    wiki_docs: list[RetrievedChunk],
    docs: list[RetrievedChunk],
    mcp_results: list[MCPResult],
    web_results: list[MCPResult],
) -> tuple[str, list[Citation]]:
    lines: list[str] = []
    citations: list[Citation] = []
    idx = 1
    for doc in wiki_docs:
        cit = doc.as_citation()
        citations.append(cit)
        lines.append(f"[{idx}] 출처: {cit.render()}\n{doc.content}")
        idx += 1
    for doc in docs:
        cit = doc.as_citation()
        citations.append(cit)
        lines.append(f"[{idx}] 출처: {cit.render()}\n{doc.content}")
        idx += 1
    for mcp in mcp_results:
        cit = mcp.as_citation()
        citations.append(cit)
        body = mcp.content or mcp.title or ""
        lines.append(f"[{idx}] 출처: {cit.render()}\n{body}")
        idx += 1
    for web in web_results:
        cit = web.as_citation()
        citations.append(cit)
        body = web.content or web.title or ""
        lines.append(f"[{idx}] 출처: {cit.render()}\n{body}")
        idx += 1
    return "\n\n".join(lines), citations


def build_graph(deps: GraphDeps, terminal: Terminal = "generate"):
    """LangGraph StateGraph를 빌드해 컴파일된 파이프라인을 반환한다.

    Parameters
    ----------
    deps
        리트리버·LLM·MCP 주입.
    terminal
        ``"generate"`` (기본) 이면 답변까지 생성하고 종료, ``"prepare_context"`` 이면
        컨텍스트 렌더링 단계에서 종료한다. 후자는 외부에서 스트리밍 생성을 수행할 때 쓴다.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("langgraph 패키지가 필요합니다.") from e

    cfg = deps.config or get_config()
    top_k = cfg.retrieval.top_k
    fetch_k = cfg.retrieval.fetch_k
    max_rewrites = cfg.retrieval.max_rewrites
    threshold = cfg.retrieval.relevance_threshold
    use_llm_grader = cfg.retrieval.use_llm_grader

    def prepare_query_node(state: RAGState) -> RAGState:
        started = time.perf_counter()
        question = state["question"]
        history = state.get("chat_history") or []
        if not _should_use_history_for_query(question, history):
            log.info("rag.stage.prepare_query %.3fs rewrite=skipped", time.perf_counter() - started)
            return {"rewritten_question": None}
        try:
            new_q = deps.llm.rewrite(question, history).strip()
        except Exception as e:
            log.warning("initial rewrite 실패, 원본 유지: %s", e)
            new_q = question
        new_q = new_q or question
        log.info(
            "rag.stage.prepare_query %.3fs rewritten=%s %r -> %r",
            time.perf_counter() - started,
            new_q != question,
            question[:60],
            new_q[:60],
        )
        return {"rewritten_question": new_q}

    def retrieve_node(state: RAGState) -> RAGState:
        started = time.perf_counter()
        q = state.get("rewritten_question") or state["question"]
        raw_started = time.perf_counter()
        docs = deps.retriever.search(q, top_k=top_k, fetch_k=fetch_k)
        raw_elapsed = time.perf_counter() - raw_started
        wiki_docs: list[RetrievedChunk] = []
        wiki_elapsed = 0.0
        if deps.wiki_retriever is not None:
            try:
                wiki_started = time.perf_counter()
                wiki_docs = deps.wiki_retriever.search(q, top_k=top_k, fetch_k=fetch_k)
                wiki_elapsed = time.perf_counter() - wiki_started
            except Exception as e:
                log.warning("wiki retrieve 실패: %s", e)
                wiki_docs = []
                wiki_elapsed = time.perf_counter() - wiki_started
        log.info(
            "rag.stage.retrieve %.3fs raw=%.3fs wiki=%.3fs raw_count=%d wiki_count=%d query=%r",
            time.perf_counter() - started,
            raw_elapsed,
            wiki_elapsed,
            len(docs),
            len(wiki_docs),
            q[:60],
        )
        return {"retrieved_docs": docs, "wiki_docs": wiki_docs}

    def grade_node(state: RAGState) -> RAGState:
        started = time.perf_counter()
        docs = state.get("retrieved_docs") or []
        wiki_docs = state.get("wiki_docs") or []
        question = state.get("rewritten_question") or state["question"]
        graded = _grade_docs(question, docs, "raw")
        graded_wiki = _grade_docs(question, wiki_docs, "wiki")
        log.info(
            "rag.stage.grade %.3fs raw=%d/%d wiki=%d/%d llm_grader=%s",
            time.perf_counter() - started,
            len(graded),
            len(docs),
            len(graded_wiki),
            len(wiki_docs),
            use_llm_grader,
        )
        return {"graded_docs": graded, "graded_wiki_docs": graded_wiki}

    def _grade_docs(question: str, docs: list[RetrievedChunk], label: str) -> list[RetrievedChunk]:
        if not use_llm_grader:
            return [doc for doc in docs if doc.score >= threshold]
        graded: list[RetrievedChunk] = []
        for doc in docs:
            try:
                ok = deps.llm.grade(question, doc.content)
            except Exception as e:
                log.warning("%s grader 실패, score로 대체: %s", label, e)
                ok = doc.score >= threshold
            if ok:
                graded.append(doc)
        return graded

    def should_rewrite(state: RAGState) -> str:
        graded = state.get("graded_docs") or []
        rewrites = int(state.get("rewrites", 0))
        wiki = state.get("graded_wiki_docs") or []
        if graded or wiki:
            return "route"
        if rewrites >= max_rewrites:
            return "route"
        return "rewrite"

    def rewrite_node(state: RAGState) -> RAGState:
        started = time.perf_counter()
        question = state.get("rewritten_question") or state["question"]
        history = state.get("chat_history") or []
        query_history = history if _should_use_history_for_query(state["question"], history) else []
        try:
            new_q = deps.llm.rewrite(question, query_history)
        except Exception as e:
            log.warning("rewrite 실패, 원본 유지: %s", e)
            new_q = question
        rewrites = int(state.get("rewrites", 0)) + 1
        log.info(
            "rag.stage.rewrite %.3fs count=%d %r -> %r",
            time.perf_counter() - started,
            rewrites,
            question[:60],
            new_q[:60],
        )
        return {"rewritten_question": new_q, "rewrites": rewrites}

    def route_node(state: RAGState) -> RAGState:
        started = time.perf_counter()
        q = state.get("rewritten_question") or state["question"]
        history = state.get("chat_history") or []
        web_enabled = bool(state.get("web_search_enabled"))
        should_use_law = _is_law_question(q, cfg, history, state["question"])
        should_use_web = web_enabled and _should_search_web(state)
        route = "prepare_context"
        mcp_available = False
        if deps.mcp and (should_use_law or should_use_web):
            mcp_available = deps.mcp.is_available()
            if mcp_available:
                route = "mcp" if should_use_law else "web"
        log.info(
            "rag.stage.route %.3fs route=%s law=%s web=%s mcp_available=%s",
            time.perf_counter() - started,
            route,
            should_use_law,
            should_use_web,
            mcp_available,
        )
        return {"route": route}

    def route_branch(state: RAGState) -> str:
        return state.get("route") or "prepare_context"

    def after_mcp_branch(state: RAGState) -> str:
        return "web" if _should_search_web(state) else "prepare_context"

    def mcp_node(state: RAGState) -> RAGState:
        started = time.perf_counter()
        q = state.get("rewritten_question") or state["question"]
        try:
            results = deps.mcp.search_law(q) if deps.mcp else []
        except Exception as e:
            log.warning("MCP 호출 실패: %s", e)
            results = []
        log.info("rag.stage.mcp %.3fs results=%d", time.perf_counter() - started, len(results))
        return {"mcp_results": results, "used_mcp": bool(results)}

    def web_node(state: RAGState) -> RAGState:
        started = time.perf_counter()
        q = _web_query(state)
        error = ""
        try:
            results = deps.mcp.search_web(q) if deps.mcp else []
        except Exception as e:
            log.warning("MCP 웹검색 호출 실패: %s", e)
            results = []
            error = str(e)
        if not results and deps.mcp is not None and not error:
            reporter = getattr(deps.mcp, "last_web_error", None)
            if callable(reporter):
                error = str(reporter() or "")
        if not results and not error:
            error = "웹검색 결과가 없습니다."
        log.info(
            "rag.stage.web %.3fs results=%d error=%s",
            time.perf_counter() - started,
            len(results),
            bool(error and not results),
        )
        return {
            "web_results": results,
            "used_web_search": bool(results),
            "web_search_requested": True,
            "web_search_error": "" if results else error,
        }

    def prepare_context_node(state: RAGState) -> RAGState:
        started = time.perf_counter()
        docs = state.get("graded_docs") or []
        wiki_docs = state.get("graded_wiki_docs") or []
        mcp_results = state.get("mcp_results") or []
        web_results = state.get("web_results") or []
        if not docs and not wiki_docs and not mcp_results and not web_results:
            log.info("rag.stage.prepare_context %.3fs empty=true", time.perf_counter() - started)
            return {"context_block": "", "citations": []}
        context, citations = _render_context(wiki_docs, docs, mcp_results, web_results)
        log.info(
            "rag.stage.prepare_context %.3fs chars=%d citations=%d",
            time.perf_counter() - started,
            len(context),
            len(citations),
        )
        return {"context_block": context, "citations": citations}

    def generate_node(state: RAGState) -> RAGState:
        started = time.perf_counter()
        context = state.get("context_block") or ""
        citations = state.get("citations") or []
        if not context:
            log.info("rag.stage.generate %.3fs empty=true", time.perf_counter() - started)
            return {"answer": prompts.EMPTY_ANSWER, "citations": []}
        question = state.get("rewritten_question") or state["question"]
        try:
            answer = deps.llm.generate(question, context)
        except Exception as e:
            log.exception("generate 실패: %s", e)
            answer = f"답변 생성 중 오류가 발생했습니다: {e}"
        log.info(
            "rag.stage.generate %.3fs answer_chars=%d",
            time.perf_counter() - started,
            len(answer),
        )
        return {"answer": answer, "citations": citations}

    graph = StateGraph(RAGState)
    graph.add_node("prepare_query", prepare_query_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("grade", grade_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("route", route_node)
    graph.add_node("mcp", mcp_node)
    graph.add_node("web", web_node)
    graph.add_node("prepare_context", prepare_context_node)
    if terminal == "generate":
        graph.add_node("generate", generate_node)

    graph.add_edge(START, "prepare_query")
    graph.add_edge("prepare_query", "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges("grade", should_rewrite, {"rewrite": "rewrite", "route": "route"})
    graph.add_edge("rewrite", "retrieve")
    graph.add_conditional_edges(
        "route",
        route_branch,
        {"mcp": "mcp", "web": "web", "prepare_context": "prepare_context"},
    )
    graph.add_conditional_edges("mcp", after_mcp_branch, {"web": "web", "prepare_context": "prepare_context"})
    graph.add_edge("web", "prepare_context")

    if terminal == "generate":
        graph.add_edge("prepare_context", "generate")
        graph.add_edge("generate", END)
    else:
        graph.add_edge("prepare_context", END)

    return graph.compile()


def describe() -> dict:
    """그래프 노드 구조 설명 (테스트/디버그용)."""
    return {
        "nodes": [
            "prepare_query",
            "retrieve",
            "grade",
            "rewrite",
            "route",
            "mcp",
            "web",
            "prepare_context",
            "generate",
        ]
    }


def build_rag_graph() -> dict:
    """스펙 호환용. 실 사용은 build_graph()."""
    return describe()
