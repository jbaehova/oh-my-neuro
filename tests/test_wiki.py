from pathlib import Path

from app.config.loader import AppConfig
from app.vault.scanner import scan_vault
from app.wiki.service import WikiService


class FakeLLM:
    def wiki_source_summary(self, *, source: str, doc_type: str, title: str, text: str) -> str:
        return f"""# {title}
## Summary
- Summary for {source}
## Key Facts
- The document mentions {text.split()[0]}.
## Concepts
- Test Concept: Demonstrates wiki generation.
## Open Questions
- None
## Source Anchors
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
