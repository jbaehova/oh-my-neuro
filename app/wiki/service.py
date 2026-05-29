"""Build, index, and query the generated Vault wiki."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.common.logging import get_logger
from app.common.models import RetrievedChunk
from app.config import AppConfig, get_config
from app.ingestion.loaders import LoadedPage, load_document
from app.vault.scanner import FileEntry, scan_vault
from app.wiki.models import (
    WikiBuildResult,
    WikiLintIssue,
    WikiPageContent,
    WikiPageSummary,
    WikiSourceState,
    WikiState,
    WikiStatus,
)
from app.wiki.store import WikiFileStore, chunk_wiki_pages, source_hash, wiki_root, wiki_vector_store

log = get_logger(__name__)

ProgressCallback = Callable[[str, str, float | None], None]


class WikiService:
    def __init__(
        self,
        cfg: AppConfig | None = None,
        llm: Any | None = None,
    ) -> None:
        self._cfg = cfg or get_config()
        self._llm = llm

    def status(self) -> WikiStatus:
        root = wiki_root(self._cfg)
        if root is None:
            return WikiStatus(enabled=self._cfg.wiki.enabled, configured=False, error="Vault path is not set.")
        store = WikiFileStore(root)
        state = store.load_state()
        page_count = len(store.markdown_pages())
        indexed_chunks = 0
        if self._cfg.wiki.enabled and self._cfg.has_api_key():
            vec = wiki_vector_store(self._cfg)
            try:
                indexed_chunks = vec.count()
            finally:
                vec.close()
        return WikiStatus(
            enabled=self._cfg.wiki.enabled,
            configured=True,
            path=str(root),
            page_count=page_count,
            indexed_chunks=indexed_chunks,
            source_count=len(state.sources),
            last_built_at=state.last_built_at,
        )

    def list_pages(self, query: str = "") -> list[WikiPageSummary]:
        root = wiki_root(self._cfg)
        if root is None:
            return []
        q = query.strip().lower()
        pages: list[WikiPageSummary] = []
        for path in WikiFileStore(root).markdown_pages():
            rel = path.relative_to(root).as_posix()
            content = path.read_text(encoding="utf-8", errors="replace")
            title = _title_from_markdown(content, rel)
            if q and q not in rel.lower() and q not in title.lower() and q not in content.lower():
                continue
            pages.append(_page_summary(root, path, content, title))
        return pages

    def get_page(self, page_id: str) -> WikiPageContent | None:
        root = wiki_root(self._cfg)
        if root is None:
            return None
        rel = _normalize_page_id(page_id)
        path = root / rel
        if not path.exists() or not path.is_file() or path.suffix.lower() != ".md":
            return None
        try:
            path.relative_to(root)
        except ValueError:
            return None
        content = path.read_text(encoding="utf-8", errors="replace")
        summary = _page_summary(root, path, content, _title_from_markdown(content, rel))
        return WikiPageContent(**summary.model_dump(), content=content)

    def rebuild(
        self,
        *,
        index: bool = True,
        progress: ProgressCallback | None = None,
    ) -> WikiBuildResult:
        start = time.monotonic()
        cfg = self._cfg
        if not cfg.wiki.enabled:
            return WikiBuildResult(error="Wiki is disabled.")
        root = wiki_root(cfg)
        if root is None:
            return WikiBuildResult(error="Vault path is not set.")
        if not cfg.has_api_key() and self._llm is None:
            return WikiBuildResult(error="OPENAI_API_KEY is required to build the wiki.")

        file_store = WikiFileStore(root)
        file_store.ensure()
        state = file_store.load_state()
        now = datetime.now(UTC).isoformat()

        entries, skipped = scan_vault(cfg.vault.path_abs, cfg.vault)  # type: ignore[arg-type]
        entry_by_source = {entry.relative_path: entry for entry in entries}
        current_sources = set(entry_by_source)
        removed = set(state.sources) - current_sources
        for rel in sorted(removed):
            file_store.delete(state.sources[rel].source_page)
            state.sources.pop(rel, None)

        pages_written = 0
        processed = 0
        skipped_count = len(skipped)
        total = max(1, len(entries))
        for idx, entry in enumerate(entries):
            _notify(progress, entry.relative_path, "wiki source scan", idx / total)
            try:
                changed, source_state = self._build_source_page(file_store, state, entry, now)
            except Exception as exc:
                log.warning("wiki source build failed for %s: %s", entry.relative_path, exc)
                skipped_count += 1
                continue
            state.sources[entry.relative_path] = source_state
            processed += 1
            if changed:
                pages_written += 1

        _notify(progress, "", "wiki aggregate pages", None)
        pages_written += self._write_aggregate_pages(file_store, state, now)
        state.last_built_at = now
        file_store.save_state(state)
        _append_log(file_store, state, now, processed, pages_written, skipped_count)

        indexed_chunks = 0
        if index:
            _notify(progress, "", "wiki vector index", None)
            indexed_chunks = self.reindex()

        duration = time.monotonic() - start
        return WikiBuildResult(
            pages_written=pages_written,
            indexed_chunks=indexed_chunks,
            sources_processed=processed,
            sources_skipped=skipped_count,
            duration_s=duration,
        )

    def reindex(self) -> int:
        root = wiki_root(self._cfg)
        if root is None or not root.exists():
            return 0
        chunks = chunk_wiki_pages(self._cfg, root)
        vec = wiki_vector_store(self._cfg)
        try:
            vec.clear()
            return vec.upsert_chunks(chunks)
        finally:
            vec.close()

    def search(self, query: str, top_k: int = 5, fetch_k: int | None = None) -> list[RetrievedChunk]:
        if not self._cfg.wiki.enabled:
            return []
        root = wiki_root(self._cfg)
        if root is None or not root.exists():
            return []
        vec = wiki_vector_store(self._cfg)
        try:
            return vec.search(query, top_k=top_k, fetch_k=fetch_k)
        finally:
            vec.close()

    def lint(self) -> list[WikiLintIssue]:
        status = self.status()
        issues: list[WikiLintIssue] = []
        if not status.configured:
            return [WikiLintIssue(severity="warning", code="vault_missing", message=status.error)]
        if status.page_count == 0:
            issues.append(
                WikiLintIssue(
                    severity="warning",
                    code="wiki_empty",
                    message="Wiki has no Markdown pages. Run a rebuild after syncing the Vault.",
                )
            )
        if status.page_count > 0 and status.indexed_chunks == 0 and self._cfg.has_api_key():
            issues.append(
                WikiLintIssue(
                    severity="warning",
                    code="wiki_not_indexed",
                    message="Wiki pages exist but the wiki vector index is empty.",
                )
            )
        root = wiki_root(self._cfg)
        if root is not None:
            for page in WikiFileStore(root).markdown_pages():
                text = page.read_text(encoding="utf-8", errors="replace")
                if "## Source Anchors" not in text and "/sources/" in page.as_posix():
                    issues.append(
                        WikiLintIssue(
                            severity="warning",
                            code="missing_source_anchors",
                            message="Source wiki page is missing Source Anchors.",
                            page=page.relative_to(root).as_posix(),
                        )
                    )
        if not issues:
            issues.append(WikiLintIssue(code="ok", message="No wiki lint issues found."))
        return issues

    def _ensure_llm(self) -> Any:
        if self._llm is None:
            from app.rag.llm import OpenAILLM

            self._llm = OpenAILLM(self._cfg)
        return self._llm

    def _build_source_page(
        self,
        store: WikiFileStore,
        state: WikiState,
        entry: FileEntry,
        now: str,
    ) -> tuple[bool, WikiSourceState]:
        digest = source_hash(entry.absolute_path)
        existing = state.sources.get(entry.relative_path)
        if existing and existing.content_hash == digest and (store.root / existing.source_page).exists():
            return False, existing

        pages = load_document(entry.absolute_path, relative_path=entry.relative_path)
        text = _loaded_pages_text(pages, self._cfg.wiki.max_source_chars)
        llm = self._ensure_llm()
        if not hasattr(llm, "wiki_source_summary"):
            raise RuntimeError("LLM client does not implement wiki_source_summary.")
        title = _source_title(entry.relative_path)
        content = llm.wiki_source_summary(
            source=entry.relative_path,
            doc_type=Path(entry.relative_path).suffix.lstrip(".") or "text",
            title=title,
            text=text,
        )
        content = _with_source_header(content, entry.relative_path, digest, now)
        rel_page = f"sources/{_slug(entry.relative_path)}.md"
        store.write_text(rel_page, content)
        concepts = _parse_concepts(content)
        open_questions = _parse_open_questions(content)
        return True, WikiSourceState(
            content_hash=digest,
            source_page=rel_page,
            title=title,
            updated_at=now,
            concepts=concepts,
            open_questions=open_questions,
            excerpt=_excerpt(content),
        )

    def _write_aggregate_pages(self, store: WikiFileStore, state: WikiState, now: str) -> int:
        concept_map: dict[str, list[tuple[str, str]]] = {}
        open_questions: list[tuple[str, str]] = []
        for source, source_state in sorted(state.sources.items()):
            for concept, desc in source_state.concepts.items():
                concept_map.setdefault(concept, []).append((source, desc))
            for question in source_state.open_questions:
                if question.lower() != "none":
                    open_questions.append((source, question))

        pages = {
            "index.md": _render_index(state, concept_map, now),
            "open-questions.md": _render_open_questions(open_questions, now),
            "contradictions.md": _render_contradictions(now),
        }
        written = 0
        for rel, text in pages.items():
            store.write_text(rel, text)
            written += 1

        existing_concept_pages = {p.relative_to(store.root).as_posix() for p in (store.root / "concepts").glob("*.md")}
        next_concept_pages: set[str] = set()
        for concept, refs in sorted(concept_map.items()):
            rel = f"concepts/{_slug(concept)}.md"
            next_concept_pages.add(rel)
            store.write_text(rel, _render_concept(concept, refs, now))
            written += 1
        for rel in existing_concept_pages - next_concept_pages:
            store.delete(rel)
        return written


def _notify(progress: ProgressCallback | None, name: str, stage: str, fraction: float | None) -> None:
    if progress is None:
        return
    try:
        progress(name, stage, fraction)
    except Exception:
        log.debug("wiki progress callback failed", exc_info=True)


def _loaded_pages_text(pages: list[LoadedPage], max_chars: int) -> str:
    blocks = []
    remaining = max_chars
    for page in pages:
        label = page.location or (f"page={page.page}" if page.page is not None else "body")
        block = f"[{label}]\n{page.text.strip()}"
        if len(block) > remaining:
            blocks.append(block[:remaining])
            break
        blocks.append(block)
        remaining -= len(block)
        if remaining <= 0:
            break
    return "\n\n".join(blocks).strip()


def _with_source_header(content: str, source: str, digest: str, updated_at: str) -> str:
    body = content.strip()
    meta = (
        f"<!-- generated-by: oh-my-neuro wiki -->\n"
        f"<!-- source: {source} -->\n"
        f"<!-- source-hash: {digest} -->\n"
        f"<!-- updated-at: {updated_at} -->\n\n"
    )
    return meta + body


def _source_title(source: str) -> str:
    return Path(source).stem.replace("_", " ").replace("-", " ").strip() or source


def _slug(value: str) -> str:
    base = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", value).strip("-._").lower()
    if not base:
        base = "page"
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{base[:64]}-{digest}"


def _title_from_markdown(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _page_summary(root: Path, path: Path, content: str, title: str) -> WikiPageSummary:
    rel = path.relative_to(root).as_posix()
    section = rel.split("/", 1)[0] if "/" in rel else "root"
    stat = path.stat()
    return WikiPageSummary(
        id=rel,
        path=rel,
        title=title,
        section=section,
        size=stat.st_size,
        updated_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        excerpt=_excerpt(content),
    )


def _normalize_page_id(page_id: str) -> str:
    rel = page_id.strip().lstrip("/").replace("\\", "/")
    parts = [p for p in rel.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        return ""
    return "/".join(parts)


def _section_lines(content: str, heading: str) -> list[str]:
    lines = content.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == heading.lower():
            start = idx + 1
            break
    if start is None:
        return []
    out: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def _parse_concepts(content: str) -> dict[str, str]:
    concepts: dict[str, str] = {}
    for line in _section_lines(content, "## Concepts"):
        item = line.strip().lstrip("-* ").strip()
        if not item:
            continue
        if ":" in item:
            name, desc = item.split(":", 1)
        else:
            name, desc = item, ""
        name = name.strip()
        if name and name.lower() != "none":
            concepts[name] = desc.strip()
    return concepts


def _parse_open_questions(content: str) -> list[str]:
    questions = []
    for line in _section_lines(content, "## Open Questions"):
        item = line.strip().lstrip("-* ").strip()
        if item:
            questions.append(item)
    return questions


def _excerpt(content: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)).strip()
    return text[:limit]


def _render_index(state: WikiState, concept_map: dict[str, list[tuple[str, str]]], now: str) -> str:
    lines = [
        "# Vault Wiki Index",
        "",
        f"Generated at: {now}",
        "",
        "## Sources",
    ]
    if not state.sources:
        lines.append("- None")
    for source, item in sorted(state.sources.items()):
        lines.append(f"- [[{item.source_page}]] - {source}")
    lines.extend(["", "## Concepts"])
    if not concept_map:
        lines.append("- None")
    for concept, refs in sorted(concept_map.items()):
        lines.append(f"- [[concepts/{_slug(concept)}.md|{concept}]] ({len(refs)} sources)")
    lines.extend(["", "## Maintenance", "- [[open-questions.md]]", "- [[contradictions.md]]"])
    return "\n".join(lines)


def _render_concept(concept: str, refs: list[tuple[str, str]], now: str) -> str:
    lines = ["# " + concept, "", f"Generated at: {now}", "", "## Summary"]
    lines.append(f"- Appears in {len(refs)} source(s).")
    lines.extend(["", "## Source Notes"])
    for source, desc in refs:
        suffix = f": {desc}" if desc else ""
        lines.append(f"- {source}{suffix}")
    lines.extend(["", "## Verification", "- Treat this page as synthesized; verify final answers against raw source citations."])
    return "\n".join(lines)


def _render_open_questions(items: list[tuple[str, str]], now: str) -> str:
    lines = ["# Open Questions", "", f"Generated at: {now}", ""]
    if not items:
        lines.append("- None")
    for source, question in items:
        lines.append(f"- {source}: {question}")
    return "\n".join(lines)


def _render_contradictions(now: str) -> str:
    return "\n".join(
        [
            "# Contradictions",
            "",
            f"Generated at: {now}",
            "",
            "- No automated contradictions detected in this MVP.",
            "- If wiki notes disagree with raw source citations, prefer the raw Vault source.",
        ]
    )


def _append_log(store: WikiFileStore, state: WikiState, now: str, processed: int, written: int, skipped: int) -> None:
    path = store.root / "log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Wiki Build Log\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- {now}: processed={processed}, written={written}, skipped={skipped}, sources={len(state.sources)}\n")
