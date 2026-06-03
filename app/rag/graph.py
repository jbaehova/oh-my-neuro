"""Corrective RAG pipeline built with LangGraph."""

from __future__ import annotations

import re
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
    used_mcp: bool
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


def _render_context(
    wiki_docs: list[RetrievedChunk],
    docs: list[RetrievedChunk],
    mcp_results: list[MCPResult],
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

    def prepare_query_node(state: RAGState) -> RAGState:
        question = state["question"]
        history = state.get("chat_history") or []
        if not history:
            return {"rewritten_question": None}
        try:
            new_q = deps.llm.rewrite(question, history).strip()
        except Exception as e:
            log.warning("initial rewrite 실패, 원본 유지: %s", e)
            new_q = question
        new_q = new_q or question
        log.info("prepare_query: %r → %r", question[:60], new_q[:60])
        return {"rewritten_question": new_q}

    def retrieve_node(state: RAGState) -> RAGState:
        q = state.get("rewritten_question") or state["question"]
        docs = deps.retriever.search(q, top_k=top_k, fetch_k=fetch_k)
        wiki_docs: list[RetrievedChunk] = []
        if deps.wiki_retriever is not None:
            try:
                wiki_docs = deps.wiki_retriever.search(q, top_k=top_k, fetch_k=fetch_k)
            except Exception as e:
                log.warning("wiki retrieve 실패: %s", e)
                wiki_docs = []
        log.info("retrieve: %d raw, %d wiki candidates for %r", len(docs), len(wiki_docs), q[:60])
        return {"retrieved_docs": docs, "wiki_docs": wiki_docs}

    def grade_node(state: RAGState) -> RAGState:
        docs = state.get("retrieved_docs") or []
        wiki_docs = state.get("wiki_docs") or []
        question = state.get("rewritten_question") or state["question"]
        graded: list[RetrievedChunk] = []
        for doc in docs:
            try:
                ok = deps.llm.grade(question, doc.content)
            except Exception as e:
                log.warning("grader 실패, score로 대체: %s", e)
                ok = doc.score >= threshold
            if ok:
                graded.append(doc)
        graded_wiki: list[RetrievedChunk] = []
        for doc in wiki_docs:
            try:
                ok = deps.llm.grade(question, doc.content)
            except Exception as e:
                log.warning("wiki grader 실패, score로 대체: %s", e)
                ok = doc.score >= threshold
            if ok:
                graded_wiki.append(doc)
        log.info("grade: %d / %d raw, %d / %d wiki kept", len(graded), len(docs), len(graded_wiki), len(wiki_docs))
        return {"graded_docs": graded, "graded_wiki_docs": graded_wiki}

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
        question = state.get("rewritten_question") or state["question"]
        history = state.get("chat_history") or []
        try:
            new_q = deps.llm.rewrite(question, history)
        except Exception as e:
            log.warning("rewrite 실패, 원본 유지: %s", e)
            new_q = question
        rewrites = int(state.get("rewrites", 0)) + 1
        log.info("rewrite(%d): %r → %r", rewrites, question[:60], new_q[:60])
        return {"rewritten_question": new_q, "rewrites": rewrites}

    def route_node(state: RAGState) -> RAGState:
        q = state.get("rewritten_question") or state["question"]
        history = state.get("chat_history") or []
        if deps.mcp and _is_law_question(q, cfg, history, state["question"]) and deps.mcp.is_available():
            return {"route": "mcp"}
        return {"route": "prepare_context"}

    def route_branch(state: RAGState) -> str:
        return state.get("route") or "prepare_context"

    def mcp_node(state: RAGState) -> RAGState:
        q = state.get("rewritten_question") or state["question"]
        try:
            results = deps.mcp.search_law(q) if deps.mcp else []
        except Exception as e:
            log.warning("MCP 호출 실패: %s", e)
            results = []
        return {"mcp_results": results, "used_mcp": bool(results)}

    def prepare_context_node(state: RAGState) -> RAGState:
        docs = state.get("graded_docs") or []
        wiki_docs = state.get("graded_wiki_docs") or []
        mcp_results = state.get("mcp_results") or []
        if not docs and not wiki_docs and not mcp_results:
            return {"context_block": "", "citations": []}
        context, citations = _render_context(wiki_docs, docs, mcp_results)
        return {"context_block": context, "citations": citations}

    def generate_node(state: RAGState) -> RAGState:
        context = state.get("context_block") or ""
        citations = state.get("citations") or []
        if not context:
            return {"answer": prompts.EMPTY_ANSWER, "citations": []}
        question = state.get("rewritten_question") or state["question"]
        try:
            answer = deps.llm.generate(question, context)
        except Exception as e:
            log.exception("generate 실패: %s", e)
            answer = f"답변 생성 중 오류가 발생했습니다: {e}"
        return {"answer": answer, "citations": citations}

    graph = StateGraph(RAGState)
    graph.add_node("prepare_query", prepare_query_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("grade", grade_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("route", route_node)
    graph.add_node("mcp", mcp_node)
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
        {"mcp": "mcp", "prepare_context": "prepare_context"},
    )
    graph.add_edge("mcp", "prepare_context")

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
            "prepare_context",
            "generate",
        ]
    }


def build_rag_graph() -> dict:
    """스펙 호환용. 실 사용은 build_graph()."""
    return describe()
