from app.common.models import ChatMessage, MCPResult, RetrievedChunk
from app.config.loader import AppConfig
from app.rag.service import RAGService

FOLLOW_UP_REWRITE = "diffusion GAN VAE 생성 모델 비교"
LAW_FOLLOW_UP_REWRITE = "헌법 제1조 제2항"


class FakeStore:
    def __init__(self, docs_by_query: dict[str, list[RetrievedChunk]] | None = None) -> None:
        self.docs_by_query = {k.lower(): v for k, v in (docs_by_query or {}).items()}
        self.queries: list[str] = []

    def count(self) -> int:
        return 1

    def search(self, query: str, top_k: int = 5, fetch_k: int | None = None) -> list[RetrievedChunk]:
        self.queries.append(query)
        q = query.lower()
        for needle, docs in self.docs_by_query.items():
            if needle in q:
                return docs
        return []


class ExplodingStore:
    def count(self) -> int:
        raise AssertionError("direct chat should not inspect the vault")


class FakeLLM:
    def __init__(self) -> None:
        self.rewrite_calls: list[tuple[str, list[str]]] = []
        self.chat_questions: list[str] = []
        self.generate_questions: list[str] = []
        self.generate_stream_questions: list[str] = []

    def classify_intent(self, question: str, history: list[ChatMessage] | None = None) -> str:
        raise AssertionError("RAGService should not use nondeterministic intent classification")

    def rewrite(self, question: str, history: list[ChatMessage]) -> str:
        self.rewrite_calls.append((question, [m.content for m in history]))
        if question == "비교해줘":
            return FOLLOW_UP_REWRITE
        if question == "2항도 알려줘":
            return LAW_FOLLOW_UP_REWRITE
        return question

    def grade(self, question: str, document: str) -> bool:
        return "diffusion" in question.lower() and "diffusion" in document.lower()

    def generate(self, question: str, context_block: str) -> str:
        self.generate_questions.append(question)
        return f"generated: {question}"

    def generate_stream(self, question: str, context_block: str):
        self.generate_stream_questions.append(question)
        yield "streamed: "
        yield question

    def chat(self, question: str, history: list[ChatMessage]) -> str:
        self.chat_questions.append(question)
        return "direct chat"

    def chat_stream(self, question: str, history: list[ChatMessage]):
        self.chat_questions.append(question)
        yield "direct"
        yield " chat"


class FakeMCP:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def is_available(self) -> bool:
        return True

    def search_law(self, query: str) -> list[MCPResult]:
        self.queries.append(query)
        return [
            MCPResult(
                tool="korean_law_search",
                title="법령 검색 결과",
                content=f"law result for {query}",
            )
        ]


def _doc(content: str = "Diffusion, GAN, VAE comparison") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk-1",
        content=content,
        metadata={"source": "models.pdf", "page": 1, "doc_type": "pdf"},
        score=0.95,
    )


def _cfg(*, mcp_enabled: bool = False, max_rewrites: int = 1) -> AppConfig:
    return AppConfig(
        openai_api_key="test-key",
        retrieval={"max_rewrites": max_rewrites},
        wiki={"enabled": False},
        mcp={"enabled": mcp_enabled, "law_keywords": []},
    )


def _service(
    *,
    store,
    llm: FakeLLM,
    mcp: FakeMCP | None = None,
    mcp_enabled: bool = False,
    max_rewrites: int = 1,
) -> RAGService:
    service = RAGService(cfg=_cfg(mcp_enabled=mcp_enabled, max_rewrites=max_rewrites), store=store, mcp=mcp)
    service._llm = llm
    return service


def test_direct_chat_skips_empty_vault_check_and_intent_classifier() -> None:
    llm = FakeLLM()
    service = _service(store=ExplodingStore(), llm=llm)

    response = service.ask("안녕,")

    assert response.answer == "direct chat"
    assert response.retrieval_count == 0
    assert llm.chat_questions == ["안녕,"]


def test_direct_chat_strips_colon_punctuation() -> None:
    llm = FakeLLM()
    service = _service(store=ExplodingStore(), llm=llm)

    response = service.ask("hi:")

    assert response.answer == "direct chat"
    assert response.retrieval_count == 0
    assert llm.chat_questions == ["hi:"]


def test_follow_up_comparison_rewrites_before_first_retrieval() -> None:
    store = FakeStore({"diffusion gan vae": [_doc()]})
    llm = FakeLLM()
    service = _service(store=store, llm=llm)
    history = [
        ChatMessage(role="user", content="diffusion, GAN, VAE 차이를 설명해줘"),
        ChatMessage(role="assistant", content="세 모델의 차이를 요약했습니다."),
    ]

    response = service.ask("비교해줘", history)

    assert store.queries[0] == FOLLOW_UP_REWRITE
    assert response.rewritten_question == FOLLOW_UP_REWRITE
    assert response.retrieval_count == 1
    assert llm.generate_questions == [FOLLOW_UP_REWRITE]
    assert llm.chat_questions == []


def test_law_follow_up_uses_rewritten_question_for_mcp() -> None:
    store = FakeStore()
    llm = FakeLLM()
    mcp = FakeMCP()
    service = _service(store=store, llm=llm, mcp=mcp, mcp_enabled=True, max_rewrites=0)
    history = [
        ChatMessage(role="user", content="헌법 제1조 1항은 뭐야?"),
        ChatMessage(role="assistant", content="대한민국은 민주공화국입니다."),
    ]

    response = service.ask("2항도 알려줘", history)

    assert response.used_mcp is True
    assert response.rewritten_question == LAW_FOLLOW_UP_REWRITE
    assert mcp.queries == [LAW_FOLLOW_UP_REWRITE]
    assert response.citations[0].kind == "mcp"
    assert llm.generate_questions == [LAW_FOLLOW_UP_REWRITE]


def test_law_question_routes_to_mcp_without_explicit_statute_keyword() -> None:
    store = FakeStore()
    llm = FakeLLM()
    mcp = FakeMCP()
    service = _service(store=store, llm=llm, mcp=mcp, mcp_enabled=True, max_rewrites=0)
    question = "보이스 피싱은 어떤 법에 저촉되는 행위인가요?"

    response = service.ask(question)

    assert response.used_mcp is True
    assert mcp.queries == [question]
    assert response.citations[0].kind == "mcp"


def test_prior_law_history_does_not_route_unrelated_question_to_mcp() -> None:
    question = "업로드한 diffusion 문서 비교해줘"
    store = FakeStore({"diffusion": [_doc()]})
    llm = FakeLLM()
    mcp = FakeMCP()
    service = _service(store=store, llm=llm, mcp=mcp, mcp_enabled=True)
    history = [
        ChatMessage(role="user", content="헌법 제1조 1항은 뭐야?"),
        ChatMessage(role="assistant", content="대한민국은 민주공화국입니다."),
    ]

    response = service.ask(question, history)

    assert response.used_mcp is False
    assert mcp.queries == []
    assert response.retrieval_count == 1
    assert llm.generate_questions == [question]


def test_streaming_uses_same_rewritten_question_for_generation() -> None:
    store = FakeStore({"diffusion gan vae": [_doc()]})
    llm = FakeLLM()
    service = _service(store=store, llm=llm)
    history = [
        ChatMessage(role="user", content="diffusion, GAN, VAE 차이를 설명해줘"),
        ChatMessage(role="assistant", content="세 모델의 차이를 요약했습니다."),
    ]

    chunks = list(service.ask_stream("비교해줘", history))
    meta = chunks[0]
    streamed = "".join(chunk.text for chunk in chunks if chunk.kind == "token")

    assert meta.kind == "meta"
    assert meta.rewritten_question == FOLLOW_UP_REWRITE
    assert meta.retrieval_count == 1
    assert streamed == f"streamed: {FOLLOW_UP_REWRITE}"
    assert llm.generate_stream_questions == [FOLLOW_UP_REWRITE]
