"""Chunk generation from loaded document pages."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.common.models import Chunk
from app.ingestion.loaders import LoadedPage


def _slugify_source(source: str) -> str:
    safe = []
    for ch in source:
        if ch.isalnum() or ch in ("-", "_", ".", "/"):
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe)


def chunk_pages(
    pages: Sequence[LoadedPage],
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    extras: dict[str, object] | None = None,
) -> list[Chunk]:
    """LangChain의 RecursiveCharacterTextSplitter로 분할해 Chunk 리스트 반환.

    :param extras: 모든 생성된 Chunk 의 ``extras`` 에 머지될 메타
                   (vault metadata: mtime_ns/size/content_hash 등).
    """
    if not pages:
        return []

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("langchain-text-splitters가 필요합니다.") from e

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", ".", "?", "!", " ", ""],
        length_function=len,
    )

    uploaded_at = datetime.now(UTC).isoformat()
    base_extras = dict(extras or {})

    chunks: list[Chunk] = []
    per_source_index: dict[str, int] = {}

    for page in pages:
        parts = splitter.split_text(page.text)
        for part in parts:
            part_stripped = part.strip()
            if not part_stripped:
                continue
            idx = per_source_index.get(page.source, 0)
            per_source_index[page.source] = idx + 1
            page_tag = page.page if page.page is not None else 0
            source_slug = _slugify_source(page.source)
            chunk_id = f"{source_slug}::p{page_tag}::c{idx:04d}"
            chunk_extras = dict(base_extras)
            chunk_extras.update(page.metadata)
            chunk_extras["relative_path"] = page.source
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    content=part_stripped,
                    source=page.source,
                    page=page.page,
                    location=page.location or f"chunk={idx}",
                    doc_type=page.doc_type,
                    uploaded_at=uploaded_at,
                    extras=chunk_extras,
                )
            )
    return chunks
