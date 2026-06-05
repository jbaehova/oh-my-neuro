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
    WikiContradiction,
    WikiGraph,
    WikiGraphEdge,
    WikiGraphNode,
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
        state = WikiFileStore(root).load_state()
        linked = _linked_source_pages(state, content, rel)
        return WikiPageContent(**summary.model_dump(), content=content, linked_source_pages=linked)

    def rebuild(
        self,
        *,
        index: bool = True,
        force: bool = False,
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
        sources_regenerated = 0
        processed = 0
        skipped_count = len(skipped)
        total = max(1, len(entries))
        for idx, entry in enumerate(entries):
            _notify(progress, entry.relative_path, "wiki source scan", idx / total)
            try:
                changed, source_state = self._build_source_page(file_store, state, entry, now, force=force)
            except Exception as exc:
                log.warning("wiki source build failed for %s: %s", entry.relative_path, exc)
                skipped_count += 1
                continue
            state.sources[entry.relative_path] = source_state
            processed += 1
            if changed:
                pages_written += 1
                sources_regenerated += 1

        _notify(progress, "", "wiki aggregate pages", None)
        aggregate_written, concepts_regenerated = self._write_aggregate_pages(file_store, state, now)
        pages_written += aggregate_written
        state.last_built_at = now
        file_store.save_state(state)
        _append_log(
            file_store,
            state,
            now,
            processed,
            pages_written,
            skipped_count,
            sources_regenerated=sources_regenerated,
            concepts_regenerated=concepts_regenerated,
        )

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

    def build_graph(self) -> WikiGraph:
        root = wiki_root(self._cfg)
        if root is None:
            return WikiGraph()
        state = WikiFileStore(root).load_state()
        nodes: dict[str, WikiGraphNode] = {}
        edges: list[WikiGraphEdge] = []

        def add_node(node_id: str, label: str, kind: str, page_id: str) -> str:
            if node_id not in nodes:
                nodes[node_id] = WikiGraphNode(id=node_id, label=label, kind=kind, page_id=page_id)  # type: ignore[arg-type]
            return node_id

        for rel, page in [("index.md", "Vault Wiki Index"), ("open-questions.md", "Open Questions"), ("contradictions.md", "Contradictions")]:
            add_node(f"page:{rel}", page, "page", rel)

        for source, source_state in sorted(state.sources.items()):
            source_id = add_node(f"source:{source}", Path(source).name, "source", source_state.source_page)
            page_id = add_node(f"page:{source_state.source_page}", source_state.title, "page", source_state.source_page)
            edges.append(WikiGraphEdge(source=source_id, target=page_id, label="summarized"))
            for concept, desc in source_state.concepts.items():
                concept_page = f"concepts/{_slug(concept)}.md"
                concept_id = add_node(f"concept:{concept}", concept, "concept", concept_page)
                edges.append(WikiGraphEdge(source=concept_id, target=source_id, label=desc[:40] if desc else ""))

        return WikiGraph(nodes=list(nodes.values()), edges=edges)

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
            state = WikiFileStore(root).load_state()
            for item in state.contradictions:
                issues.append(
                    WikiLintIssue(
                        severity="warning",
                        code="contradiction",
                        message=f"{item.concept}: {item.summary}",
                        page=f"concepts/{_slug(item.concept)}.md",
                        metadata={"concept": item.concept, "source_a": item.source_a, "source_b": item.source_b},
                    )
                )
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
        *,
        force: bool = False,
    ) -> tuple[bool, WikiSourceState]:
        digest = source_hash(entry.absolute_path)
        existing = state.sources.get(entry.relative_path)
        if (
            not force
            and existing
            and existing.content_hash == digest
            and (store.root / existing.source_page).exists()
        ):
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

    def _write_aggregate_pages(self, store: WikiFileStore, state: WikiState, now: str) -> tuple[int, int]:
        concept_map: dict[str, list[tuple[str, str]]] = {}
        open_questions: list[tuple[str, str]] = []
        for source, source_state in sorted(state.sources.items()):
            for concept, desc in source_state.concepts.items():
                concept_map.setdefault(concept, []).append((source, desc))
            for question in source_state.open_questions:
                if question.lower() != "none":
                    open_questions.append((source, question))

        contradictions = self._detect_contradictions(concept_map)
        state.contradictions = contradictions

        pages = {
            "index.md": _render_index(state, concept_map, now),
            "open-questions.md": _render_open_questions(open_questions, now),
            "contradictions.md": _render_contradictions(contradictions, now),
        }
        written = 0
        concepts_regenerated = 0
        for rel, text in pages.items():
            store.write_text(rel, text)
            written += 1

        existing_concept_pages = {p.relative_to(store.root).as_posix() for p in (store.root / "concepts").glob("*.md")}
        next_concept_pages: set[str] = set()
        for concept, refs in sorted(concept_map.items()):
            rel = f"concepts/{_slug(concept)}.md"
            next_concept_pages.add(rel)
            store.write_text(rel, self._build_concept_page(store, concept, refs, now))
            written += 1
            concepts_regenerated += 1
        for rel in existing_concept_pages - next_concept_pages:
            store.delete(rel)
        return written, concepts_regenerated

    def _build_concept_page(
        self,
        store: WikiFileStore,
        concept: str,
        refs: list[tuple[str, str]],
        now: str,
    ) -> str:
        source_blocks = _collect_concept_source_blocks(store, refs)
        meta = f"<!-- generated-by: oh-my-neuro wiki -->\n<!-- updated-at: {now} -->\n\n"
        fallback = _render_concept(store, concept, refs, now)
        if self._cfg.has_api_key() or self._llm is not None:
            try:
                llm = self._ensure_llm()
                if hasattr(llm, "wiki_concept_page"):
                    content = llm.wiki_concept_page(concept=concept, source_blocks=source_blocks)
                    if content.strip() and not _concept_page_is_thin(content):
                        return meta + content.strip() + "\n"
                    if content.strip():
                        log.info("wiki concept page for %s was too thin; using merged fallback", concept)
            except Exception as exc:
                log.warning("wiki concept synthesis failed for %s: %s", concept, exc)
        return fallback

    def _detect_contradictions(self, concept_map: dict[str, list[tuple[str, str]]]) -> list[WikiContradiction]:
        llm = self._llm
        if llm is None and self._cfg.has_api_key():
            llm = self._ensure_llm()
        if llm is None or not hasattr(llm, "wiki_contradiction_check"):
            return []

        found: list[WikiContradiction] = []
        for concept, refs in concept_map.items():
            described = [(source, desc.strip()) for source, desc in refs if desc.strip()]
            if len(described) < 2:
                continue
            for i in range(len(described)):
                for j in range(i + 1, len(described)):
                    source_a, desc_a = described[i]
                    source_b, desc_b = described[j]
                    try:
                        if not llm.wiki_contradiction_check(
                            concept=concept,
                            source_a=source_a,
                            description_a=desc_a,
                            source_b=source_b,
                            description_b=desc_b,
                        ):
                            continue
                    except Exception:
                        log.debug("contradiction check failed for %s", concept, exc_info=True)
                        continue
                    found.append(
                        WikiContradiction(
                            concept=concept,
                            source_a=source_a,
                            source_b=source_b,
                            description_a=desc_a,
                            description_b=desc_b,
                            summary=f"{source_a} vs {source_b}",
                        )
                    )
        return found


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
    return _section_lines_any(content, [heading])


def _section_lines_any(content: str, headings: list[str]) -> list[str]:
    normalized = {item.strip().lower() for item in headings}
    lines = content.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip().lower() in normalized:
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


def _section_bullets(content: str, *headings: str) -> list[str]:
    bullets: list[str] = []
    for line in _section_lines_any(content, [f"## {heading}" for heading in headings]):
        item = line.strip().lstrip("-* ").strip()
        if not item or item.lower() in {"none", "없음"}:
            continue
        bullets.append(item)
    return bullets


def _section_prose_text(content: str, *headings: str) -> str:
    lines: list[str] = []
    for line in _section_lines_any(content, [f"## {heading}" for heading in headings]):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            continue
        lines.append(stripped)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _concept_main_bullet_count(content: str) -> int:
    return len(
        _section_bullets(
            content,
            "핵심 내용",
            "주요 내용",
            "Key Facts",
            "Summary",
            "핵심 요약",
        )
    )


def _concept_page_is_thin(content: str, *, min_bullets: int = 3, min_chars: int = 180) -> bool:
    body = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    substantive = re.sub(r"\s+", " ", body).strip()
    return _concept_main_bullet_count(content) < min_bullets and len(substantive) < min_chars


def _linked_source_pages(state: WikiState, content: str, rel: str) -> list[str]:
    if not rel.startswith("concepts/"):
        source = _source_path_from_meta(content)
        return [rel] if source else []
    linked: list[str] = []
    seen: set[str] = set()
    for line in _section_lines(content, "## Source Notes"):
        item = line.strip().lstrip("-* ").strip()
        if not item:
            continue
        source = item.split(":", 1)[0].strip()
        page = state.sources.get(source)
        if page and page.source_page not in seen:
            seen.add(page.source_page)
            linked.append(page.source_page)
    for line in _section_lines(content, "## 근거 문서"):
        item = line.strip().lstrip("-* ").strip()
        page = state.sources.get(item)
        if page and page.source_page not in seen:
            seen.add(page.source_page)
            linked.append(page.source_page)
    return linked


def _source_path_from_meta(content: str) -> str:
    match = re.search(r"<!--\s*source:\s*([^-]+?)\s*-->", content)
    return match.group(1).strip() if match else ""


def _unique_bullets(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = re.sub(r"\s+", " ", item.strip()).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
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
    questions: list[str] = []
    for heading in ("## 확인해야 할 질문", "## Open Questions"):
        for line in _section_lines(content, heading):
            item = line.strip().lstrip("-* ").strip()
            if item and item.lower() not in {"none", "없음"}:
                questions.append(item)
    return _unique_bullets(questions)


def _excerpt(content: str, limit: int = 220) -> str:
    for heading in ("주제 정리", "핵심 요약", "Summary", "주요 내용", "Key Facts", "관련 배경"):
        bullets = _section_bullets(content, heading)
        if bullets:
            text = re.sub(r"\s+", " ", " ".join(bullets)).strip()
            return text[:limit]
    text = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    parts: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^Generated at:", stripped, re.I):
            continue
        if stripped.startswith("## "):
            continue
        item = stripped.lstrip("-* ").strip()
        if item and item.lower() not in {"none", "없음"}:
            parts.append(item)
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    text = re.sub(r"Generated at:\s*\S+", "", text, flags=re.I).strip()
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


def _collect_concept_source_blocks(store: WikiFileStore, refs: list[tuple[str, str]]) -> str:
    blocks: list[str] = []
    for source, desc in refs:
        lines = [f"Source path: {source}"]
        if desc.strip():
            lines.append(f"Concept note: {desc.strip()}")
        rel_page = f"sources/{_slug(source)}.md"
        page_path = store.root / rel_page
        if page_path.exists():
            source_content = page_path.read_text(encoding="utf-8", errors="replace")
            for heading in (
                "주제 정리",
                "핵심 요약",
                "관련 배경",
                "주요 내용",
                "핵심 내용",
                "실무상 주의할 점",
                "확인해야 할 질문",
                "Summary",
                "Key Facts",
                "Open Questions",
            ):
                bullets = _section_bullets(source_content, heading)
                if bullets:
                    lines.append(f"{heading} bullets: " + " / ".join(bullets[:6]))
                prose = _section_prose_text(source_content, heading)
                if prose:
                    lines.append(f"{heading} prose: {prose[:500]}")
            raw_excerpt = _excerpt(source_content, limit=900)
            if raw_excerpt:
                lines.append(f"Source excerpt: {raw_excerpt}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_concept(store: WikiFileStore, concept: str, refs: list[tuple[str, str]], now: str) -> str:
    summaries: list[str] = []
    backgrounds: list[str] = []
    main_points: list[str] = []
    practical: list[str] = []
    questions: list[str] = []
    source_docs: list[str] = []

    for source, desc in refs:
        source_docs.append(source)
        rel_page = f"sources/{_slug(source)}.md"
        source_content = ""
        page_path = store.root / rel_page
        if page_path.exists():
            source_content = page_path.read_text(encoding="utf-8", errors="replace")

        summaries.extend(_section_bullets(source_content, "핵심 요약", "Summary"))
        if desc.strip():
            summaries.append(desc.strip())
        backgrounds.extend(_section_bullets(source_content, "관련 배경"))
        main_points.extend(_section_bullets(source_content, "주요 내용", "핵심 내용", "Key Facts"))
        practical.extend(_section_bullets(source_content, "실무상 주의할 점"))
        questions.extend(_section_bullets(source_content, "확인해야 할 질문", "Open Questions"))

    summaries = _unique_bullets(summaries)
    backgrounds = _unique_bullets(backgrounds)
    main_points = _unique_bullets(main_points)
    practical = _unique_bullets(practical)
    questions = _unique_bullets(questions)
    source_docs = _unique_bullets(source_docs)

    intro_parts = backgrounds[:1] + summaries[:2] + main_points[:2]
    intro = " ".join(intro_parts[:3]).strip()
    if not intro and summaries:
        intro = summaries[0]
    if not intro:
        intro = f"{concept}은(는) Vault 문서 {len(refs)}건에서 다루는 주제입니다."

    meta = f"<!-- generated-by: oh-my-neuro wiki -->\n<!-- updated-at: {now} -->\n\n"
    lines = [meta.strip(), f"# {concept}", "", "## 주제 정리", intro, ""]

    lines.extend(["## 관련 배경"])
    if backgrounds:
        for item in backgrounds[:5]:
            lines.append(f"- {item}")
    else:
        lines.append(f"- {concept}은(는) Vault 문서 {len(refs)}건에서 공통으로 등장합니다.")

    merged_main = _unique_bullets([*summaries, *main_points])
    lines.extend(["", "## 핵심 내용"])
    if merged_main:
        for item in merged_main[:12]:
            lines.append(f"- {item}")
    else:
        for source, desc in refs[:5]:
            if desc.strip():
                lines.append(f"- {desc.strip()} ({source})")

    lines.extend(["", "## 실무상 주의할 점"])
    if practical:
        for item in practical[:6]:
            lines.append(f"- {item}")
    else:
        lines.append("- 원본 문서와 이 합성 노트를 반드시 대조하세요.")

    lines.extend(["", "## 확인해야 할 질문"])
    if questions:
        for item in questions[:5]:
            lines.append(f"- {item}")
    else:
        lines.append("- 각 소스 문서에서 이 개념이 동일한 의미로 쓰이는지 확인하세요.")

    lines.extend(["", "## 근거 문서"])
    for source in source_docs:
        lines.append(f"- {source}")

    lines.extend(["", "## Source Notes"])
    for source, desc in refs:
        suffix = f": {desc}" if desc else ""
        lines.append(f"- {source}{suffix}")

    lines.extend(
        [
            "",
            "## Verification",
            "- 자동 합성 노트입니다. 최종 판단은 원본 Vault 인용으로 확인하세요.",
        ]
    )
    return "\n".join(lines)


def _render_open_questions(items: list[tuple[str, str]], now: str) -> str:
    lines = ["# Open Questions", "", f"Generated at: {now}", ""]
    if not items:
        lines.append("- None")
    for source, question in items:
        lines.append(f"- {source}: {question}")
    return "\n".join(lines)


def _render_contradictions(contradictions: list[WikiContradiction], now: str) -> str:
    lines = ["# Contradictions", "", f"Generated at: {now}", "", "## Detected Contradictions"]
    if not contradictions:
        lines.append("- No automated contradictions detected.")
    else:
        for item in contradictions:
            lines.append(
                f"- **{item.concept}**: {item.source_a} vs {item.source_b} — "
                f"'{item.description_a}' vs '{item.description_b}'"
            )
    lines.extend(
        [
            "",
            "## Verification",
            "- If wiki notes disagree with raw source citations, prefer the raw Vault source.",
        ]
    )
    return "\n".join(lines)


def _append_log(
    store: WikiFileStore,
    state: WikiState,
    now: str,
    processed: int,
    written: int,
    skipped: int,
    *,
    sources_regenerated: int = 0,
    concepts_regenerated: int = 0,
) -> None:
    path = store.root / "log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Wiki Build Log\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(
            f"- {now}: processed={processed}, written={written}, skipped={skipped}, "
            f"sources={len(state.sources)}, sources_regenerated={sources_regenerated}, "
            f"concepts_regenerated={concepts_regenerated}\n"
        )
