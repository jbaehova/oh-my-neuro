"""Filesystem and vector-store helpers for the generated wiki."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path

from app.common.models import Chunk
from app.config import AppConfig
from app.ingestion.chunking import chunk_pages
from app.ingestion.loaders import LoadedPage
from app.storage.chroma_store import ChromaStore
from app.wiki.models import WikiState

STATE_FILE = ".state.json"


def wiki_root(cfg: AppConfig) -> Path | None:
    root = cfg.vault.path_abs
    if root is None:
        return None
    return root / cfg.wiki.directory


def source_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def wiki_vector_store(cfg: AppConfig) -> ChromaStore:
    return ChromaStore(
        persist_path=cfg.storage.chroma_path_abs,
        collection_name=cfg.wiki.collection_name,
        embedding_model=cfg.llm.embedding_model,
        api_key=cfg.openai_api_key,
        distance=cfg.storage.distance,
    )


class WikiFileStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self) -> None:
        for rel in ("sources", "concepts"):
            (self.root / rel).mkdir(parents=True, exist_ok=True)

    def load_state(self) -> WikiState:
        path = self.root / STATE_FILE
        if not path.exists():
            return WikiState()
        try:
            return WikiState.model_validate_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return WikiState()

    def save_state(self, state: WikiState) -> None:
        self.write_text(STATE_FILE, state.model_dump_json(indent=2))

    def write_text(self, rel_path: str, text: str) -> None:
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text.rstrip() + "\n")
            os.replace(tmp_name, target)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    def read_text(self, rel_path: str) -> str:
        return (self.root / rel_path).read_text(encoding="utf-8")

    def delete(self, rel_path: str) -> None:
        with contextlib.suppress(OSError):
            (self.root / rel_path).unlink()

    def markdown_pages(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(p for p in self.root.rglob("*.md") if p.is_file())


def chunk_wiki_pages(cfg: AppConfig, root: Path) -> list[Chunk]:
    pages: list[LoadedPage] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        pages.append(
            LoadedPage(
                source=f"{cfg.wiki.directory}/{rel}",
                doc_type="md",
                page=None,
                location=rel,
                text=text,
            )
        )
    return chunk_pages(
        pages,
        chunk_size=cfg.retrieval.chunk_size,
        chunk_overlap=cfg.retrieval.chunk_overlap,
        extras={"kind": "wiki", "relative_path": cfg.wiki.directory},
    )
