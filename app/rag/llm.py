"""OpenAI-backed LLM clients used by the RAG graph."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.common.logging import get_logger
from app.common.models import ChatMessage
from app.config import AppConfig
from app.rag import prompts

log = get_logger(__name__)


def _content_to_text(content: Any) -> str:
    """ChatOpenAI 응답 content(문자열/블록리스트/메시지객체)를 평문으로 정규화.

    LangChain 1.x + OpenAI Responses API 환경에서 응답 content가 content block
    리스트일 수 있다. 블록 중 ``type in ('text', 'output_text')`` 인 항목의 텍스트만
    취합한다. 메시지 객체(.content 속성)도 투과적으로 처리한다.
    """
    if content is None:
        return ""
    if hasattr(content, "content") and not isinstance(content, str | list | dict):
        return _content_to_text(content.content)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("type")
                if t in ("text", "output_text"):
                    parts.append(str(item.get("text") or ""))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        if content.get("type") in ("text", "output_text"):
            return str(content.get("text") or "")
        return ""
    return str(content)


def _retry_exceptions() -> tuple[type[BaseException], ...]:
    """OpenAI API의 일시적 장애만 재시도 대상으로 삼는다."""
    exc: list[type[BaseException]] = []
    try:
        from openai import (
            APIConnectionError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        )

        exc.extend([APIConnectionError, APITimeoutError, InternalServerError, RateLimitError])
    except ImportError:  # pragma: no cover
        pass
    if not exc:
        exc.append(ConnectionError)
    return tuple(exc)


_RETRYABLE = _retry_exceptions()


def _retry(func):
    return retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        retry=retry_if_exception_type(_RETRYABLE),
    )(func)


def _history_block(history: Iterable[ChatMessage], limit: int = 6) -> str:
    msgs = list(history)[-limit:]
    if not msgs:
        return "(없음)"
    out = []
    for m in msgs:
        role = "사용자" if m.role == "user" else "어시스턴트"
        out.append(f"{role}: {m.content}")
    return "\n".join(out)


class OpenAILLM:
    """grader, rewriter, answer 생성용 래퍼."""

    def __init__(self, cfg: AppConfig) -> None:
        if not cfg.has_api_key():
            raise RuntimeError("OPENAI_API_KEY가 설정되어야 합니다.")
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("langchain-openai 패키지가 필요합니다.") from e
        self._cfg = cfg
        self._chat = ChatOpenAI(
            model=cfg.llm.chat_model,
            api_key=cfg.openai_api_key,
            temperature=cfg.llm.temperature,
            timeout=cfg.llm.request_timeout,
        )
        self._grader = ChatOpenAI(
            model=cfg.llm.grader_model,
            api_key=cfg.openai_api_key,
            temperature=0.0,
            timeout=cfg.llm.request_timeout,
        )
        self._rewriter = ChatOpenAI(
            model=cfg.llm.rewriter_model,
            api_key=cfg.openai_api_key,
            temperature=0.0,
            timeout=cfg.llm.request_timeout,
        )

    @_retry
    def grade(self, question: str, document: str) -> bool:
        content = [
            ("system", prompts.GRADER_SYSTEM),
            ("user", prompts.GRADER_USER.format(question=question, document=document[:2000])),
        ]
        resp = self._grader.invoke(content)
        text = _content_to_text(resp.content).strip().lower()
        return text.startswith("y")

    @_retry
    def rewrite(self, question: str, history: list[ChatMessage]) -> str:
        content = [
            ("system", prompts.REWRITER_SYSTEM),
            (
                "user",
                prompts.REWRITER_USER.format(
                    question=question,
                    history=_history_block(history),
                ),
            ),
        ]
        resp = self._rewriter.invoke(content)
        text = _content_to_text(resp.content).strip().strip('"').strip("'")
        return text or question

    @_retry
    def generate(self, question: str, context_block: str) -> str:
        content = [
            ("system", prompts.ANSWER_SYSTEM),
            ("user", prompts.ANSWER_USER.format(question=question, context=context_block)),
        ]
        resp = self._chat.invoke(content)
        return _content_to_text(resp.content).strip() or prompts.EMPTY_ANSWER

    @_retry
    def classify_intent(
        self, question: str, history: list[ChatMessage] | None = None
    ) -> str:
        """문서 검색 vs 일반 대화 분류. 'search' 또는 'chat' 반환.

        분류 실패 시 보수적으로 'chat'(일반 대화)로 떨어뜨려, RAG 우회 응답이라도
        주도록 한다. 빈 vault 케이스에서도 사용자가 그냥 인사할 수 있어야 한다.
        """
        try:
            content = [
                ("system", prompts.INTENT_SYSTEM),
                (
                    "user",
                    prompts.INTENT_USER.format(
                        question=question,
                        history=_history_block(history or []),
                    ),
                ),
            ]
            resp = self._grader.invoke(content)
            text = _content_to_text(resp.content).strip().lower()
            if "search" in text:
                return "search"
            return "chat"
        except Exception as e:  # pragma: no cover
            log.warning("intent 분류 실패, chat으로 폴백: %s", e)
            return "chat"

    @_retry
    def chat(self, question: str, history: list[ChatMessage]) -> str:
        """RAG 우회 — 컨텍스트 없이 LLM 직접 호출 (인사/잡담/메타 질문용)."""
        content: list = [("system", prompts.CHAT_SYSTEM)]
        for m in (history or [])[-6:]:
            role = m.role if m.role in ("user", "assistant", "system") else "user"
            content.append((role, m.content))
        content.append(("user", question))
        resp = self._chat.invoke(content)
        return _content_to_text(resp.content).strip()

    def chat_stream(self, question: str, history: list[ChatMessage]) -> Iterator[str]:
        """RAG 우회 스트리밍."""
        content: list = [("system", prompts.CHAT_SYSTEM)]
        for m in (history or [])[-6:]:
            role = m.role if m.role in ("user", "assistant", "system") else "user"
            content.append((role, m.content))
        content.append(("user", question))
        try:
            stream = self._chat.stream(content)
        except Exception as e:  # pragma: no cover
            log.warning("chat stream 사용 불가, 비-스트리밍 폴백: %s", e)
            yield self.chat(question, history)
            return
        emitted = False
        try:
            for chunk in stream:
                text = _content_to_text(getattr(chunk, "content", chunk))
                if text:
                    emitted = True
                    yield text
        except Exception as e:  # pragma: no cover
            log.warning("chat stream 중 오류, 폴백: %s", e)
            if not emitted:
                yield self.chat(question, history)
            return
        if not emitted:
            yield self.chat(question, history)

    def generate_stream(self, question: str, context_block: str) -> Iterator[str]:
        """토큰 단위로 응답을 yield. 스트리밍 불가 시 비-스트리밍 ``generate`` 로 폴백."""
        content = [
            ("system", prompts.ANSWER_SYSTEM),
            ("user", prompts.ANSWER_USER.format(question=question, context=context_block)),
        ]
        try:
            stream = self._chat.stream(content)
        except Exception as e:  # pragma: no cover
            log.warning("stream 사용 불가, 비-스트리밍 폴백: %s", e)
            yield self.generate(question, context_block)
            return

        emitted = False
        try:
            for chunk in stream:
                raw = getattr(chunk, "content", chunk)
                text = _content_to_text(raw)
                if text:
                    emitted = True
                    yield text
        except Exception as e:  # pragma: no cover
            log.warning("stream 중 오류, 폴백: %s", e)
            if not emitted:
                yield self.generate(question, context_block)
            return

        if not emitted:
            yield prompts.EMPTY_ANSWER
