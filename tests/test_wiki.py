from pathlib import Path

from app.config.loader import AppConfig
from app.vault.scanner import scan_vault
from app.wiki.service import WikiService


class FakeLLM:
    def wiki_source_summary(self, *, source: str, doc_type: str, title: str, text: str) -> str:
        if source.endswith(("a.md", "b.md")):
            concept = "Shared Concept"
            desc = "Definition A" if source.endswith("a.md") else "Definition B"
        else:
            concept = "Test Concept"
            desc = "Demonstrates wiki generation."
        first_word = text.split()[0] if text.split() else "document"
        return f"""# {title}
## 핵심 요약
- {source} 문서의 핵심 내용을 정리한 노트입니다.
- 문서에는 {first_word} 관련 업무 맥락이 포함되어 있습니다.
## 관련 배경
- 이 문서는 Vault 내부 업무 자료로 사용됩니다.
## 주요 내용
- 문서 본문에 {first_word}가 언급됩니다.
- {source} 경로의 자료를 기준으로 정리했습니다.
## 실무상 주의할 점
- 원문과 대조하지 않으면 해석이 어긋날 수 있습니다.
## 확인해야 할 질문
- {source}의 최신 버전인지 확인했는가?
## 근거 문서
- {source}
## Concepts
- {concept}: {desc}
## Source Anchors
- {source}
"""

    def wiki_contradiction_check(
        self,
        *,
        concept: str,
        source_a: str,
        description_a: str,
        source_b: str,
        description_b: str,
    ) -> bool:
        return description_a != description_b

    def wiki_concept_page(self, *, concept: str, source_blocks: str) -> str:
        concept_note = concept
        source = "source.md"
        for line in source_blocks.splitlines():
            if line.startswith("Source path:"):
                source = line.split(":", 1)[1].strip()
            if line.startswith("Concept note:"):
                concept_note = line.split(":", 1)[1].strip()
        return f"""# {concept}
## 주제 정리
{concept}은(는) {source} 문서에서 다루는 주제입니다. {concept_note}
## 관련 배경
- {source} 문서 맥락에서 등장합니다.
## 핵심 내용
- {concept_note} ({source})
## 실무상 주의할 점
- 원문과 대조하지 않으면 해석이 어긋날 수 있습니다.
## 확인해야 할 질문
- {source}의 최신 버전과 관련 조항을 확인했는가?
## 근거 문서
- {source}
"""


def test_scan_vault_excludes_configured_generated_wiki(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
    wiki_dir = tmp_path / "generated-wiki"
    wiki_dir.mkdir()
    (wiki_dir / "generated.md").write_text("generated", encoding="utf-8")

    cfg = AppConfig(vault={"path": str(tmp_path)}, wiki={"directory": "generated-wiki"})
    entries, skipped = scan_vault(tmp_path, cfg.vault)

    assert [entry.relative_path for entry in entries] == ["keep.md"]
    assert skipped == []


def test_wiki_rebuild_writes_markdown_without_indexing(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("Alpha beta gamma", encoding="utf-8")
    cfg = AppConfig(
        vault={"path": str(tmp_path)},
        wiki={"enabled": True, "update_on_sync": True, "directory": "_omn_wiki"},
        openai_api_key="",
    )

    result = WikiService(cfg, llm=FakeLLM()).rebuild(index=False)

    assert result.error == ""
    assert result.sources_processed == 1
    assert (tmp_path / "_omn_wiki" / "index.md").exists()
    assert (tmp_path / "_omn_wiki" / "sources").exists()
    assert "Test Concept" in (tmp_path / "_omn_wiki" / "index.md").read_text(encoding="utf-8")


def test_wiki_build_graph(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("Alpha beta gamma", encoding="utf-8")
    cfg = AppConfig(
        vault={"path": str(tmp_path)},
        wiki={"enabled": True, "directory": "_omn_wiki"},
        openai_api_key="",
    )
    WikiService(cfg, llm=FakeLLM()).rebuild(index=False)
    graph = WikiService(cfg, llm=FakeLLM()).build_graph()

    assert graph.nodes
    assert any(node.kind == "concept" for node in graph.nodes)
    assert graph.edges


def test_render_concept_merges_source_key_facts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source_rel = "case/memo.md"
    (vault / "case").mkdir()
    (vault / source_rel).write_text("memo", encoding="utf-8")
    wiki_root = vault / "_omn_wiki"
    wiki_root.mkdir()
    from app.wiki.service import _render_concept, _slug
    from app.wiki.store import WikiFileStore

    source_page = wiki_root / f"sources/{_slug(source_rel)}.md"
    source_page.parent.mkdir(parents=True)
    source_page.write_text(
        """# memo
## Summary
- Short summary line.
## Key Facts
- Fact one about the case.
- Fact two about deadlines.
## Concepts
- Test Concept: Short concept note.
""",
        encoding="utf-8",
    )

    content = _render_concept(
        WikiFileStore(wiki_root),
        "Test Concept",
        [(source_rel, "Short concept note.")],
        "2026-06-05T00:00:00+00:00",
    )
    assert "## 주제 정리" in content
    assert "## 핵심 내용" in content
    assert "Fact one about the case." in content
    assert "Short concept note." in content


def test_linked_source_pages_for_concept(tmp_path: Path) -> None:
    from app.wiki.models import WikiSourceState, WikiState
    from app.wiki.service import _linked_source_pages

    content = """# Concept
## Source Notes
- case/memo.md: note
"""
    state = WikiState(
        sources={
            "case/memo.md": WikiSourceState(
                content_hash="abc",
                source_page="sources/case-memo.md-aaaaaaaa.md",
                title="memo",
                updated_at="now",
            )
        }
    )
    linked = _linked_source_pages(state, content, "concepts/test.md")
    assert linked == ["sources/case-memo.md-aaaaaaaa.md"]

    (tmp_path / "a.md").write_text("Alpha one", encoding="utf-8")
    (tmp_path / "b.md").write_text("Beta two", encoding="utf-8")
    cfg = AppConfig(
        vault={"path": str(tmp_path)},
        wiki={"enabled": True, "directory": "_omn_wiki"},
        openai_api_key="",
    )
    WikiService(cfg, llm=FakeLLM()).rebuild(index=False)
    contradictions = (tmp_path / "_omn_wiki" / "contradictions.md").read_text(encoding="utf-8")

    assert "Shared Concept" in contradictions
    assert "Definition A" in contradictions
    assert "Definition B" in contradictions
