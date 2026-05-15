"""ChromaDB-backed vector store with OpenAI embeddings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.common.logging import get_logger
from app.common.models import Chunk, RetrievedChunk
from app.config import AppConfig, get_config

log = get_logger(__name__)


@dataclass(slots=True)
class _CollectionHandle:
    collection: Any
    client: Any


class ChromaStore:
    """로컬 ChromaDB 컬렉션을 감싼다."""

    def __init__(
        self,
        persist_path: str | Path,
        collection_name: str,
        embedding_model: str,
        api_key: str,
        distance: str = "cosine",
    ) -> None:
        self.persist_path = Path(persist_path)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.api_key = api_key
        self.distance = distance
        self._handle: _CollectionHandle | None = None

    @classmethod
    def from_config(cls, cfg: AppConfig | None = None) -> ChromaStore:
        cfg = cfg or get_config()
        return cls(
            persist_path=cfg.storage.chroma_path_abs,
            collection_name=cfg.storage.collection_name,
            embedding_model=cfg.llm.embedding_model,
            api_key=cfg.openai_api_key,
            distance=cfg.storage.distance,
        )

    def _ensure_handle(self, require_embeddings: bool = False) -> _CollectionHandle:
        if self._handle is not None:
            if require_embeddings and not self.api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY가 설정되어 있지 않아 임베딩 생성/검색을 수행할 수 없습니다."
                )
            return self._handle
        try:
            import chromadb
            from chromadb.config import Settings
            from chromadb.utils.embedding_functions.openai_embedding_function import (
                OpenAIEmbeddingFunction,
            )
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("chromadb가 설치되어야 합니다.") from e

        if require_embeddings and not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY가 설정되어 있지 않아 임베딩 생성/검색을 수행할 수 없습니다."
            )

        client = chromadb.PersistentClient(
            path=str(self.persist_path),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        embedder = None
        if self.api_key:
            embedder = OpenAIEmbeddingFunction(
                api_key=self.api_key,
                model_name=self.embedding_model,
            )
        collection = client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=embedder,
            metadata={"hnsw:space": self.distance},
        )
        self._handle = _CollectionHandle(collection=collection, client=client)
        return self._handle

    def close(self) -> None:
        self._handle = None

    def count(self) -> int:
        handle = self._ensure_handle()
        try:
            return int(handle.collection.count())
        except Exception:  # pragma: no cover
            return 0

    def delete_by_source(self, source: str) -> int:
        handle = self._ensure_handle()
        try:
            before = self._count_by_source(source)
            handle.collection.delete(where={"source": source})
            return before
        except Exception as e:
            log.warning("source=%s 삭제 실패: %s", source, e)
            return 0

    def _count_by_source(self, source: str) -> int:
        handle = self._ensure_handle()
        try:
            # chromadb 1.x 는 ``include=[]`` 에 경고를 낸다. metadatas 를 포함해도 len만 사용.
            res = handle.collection.get(where={"source": source}, include=["metadatas"])
            ids = res.get("ids") or []
            return len(ids)
        except Exception:
            return 0

    def clear(self) -> int:
        handle = self._ensure_handle()
        try:
            n = self.count()
            handle.client.delete_collection(self.collection_name)
        except Exception as e:  # pragma: no cover
            log.warning("컬렉션 삭제 실패: %s", e)
            n = 0
        self._handle = None
        self._ensure_handle()
        return n

    def upsert_chunks(self, chunks: Sequence[Chunk], source: str | None = None) -> int:
        if not chunks:
            return 0
        handle = self._ensure_handle(require_embeddings=True)

        if source:
            self.delete_by_source(source)

        ids = [c.chunk_id for c in chunks]
        docs = [c.content for c in chunks]
        metas = [c.to_metadata() for c in chunks]

        batch = 128
        for start in range(0, len(ids), batch):
            handle.collection.upsert(
                ids=ids[start : start + batch],
                documents=docs[start : start + batch],
                metadatas=metas[start : start + batch],
            )
        return len(ids)

    def search(
        self,
        query: str,
        top_k: int = 5,
        fetch_k: int | None = None,
        where: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        handle = self._ensure_handle(require_embeddings=True)
        n_results = max(top_k, fetch_k or top_k)
        try:
            raw = handle.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            log.exception("벡터 검색 실패: %s", e)
            return []

        ids = (raw.get("ids") or [[]])[0]
        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        dists = (raw.get("distances") or [[]])[0]

        chunks: list[RetrievedChunk] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, dists, strict=False):
            if not doc:
                continue
            score = max(0.0, 1.0 - float(dist)) if dist is not None else 0.0
            chunks.append(
                RetrievedChunk(
                    chunk_id=cid,
                    content=doc,
                    metadata=dict(meta or {}),
                    score=score,
                )
            )
        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks[:top_k]

    def list_sources(self) -> list[dict[str, Any]]:
        handle = self._ensure_handle()
        try:
            res = handle.collection.get(include=["metadatas"])
        except Exception as e:  # pragma: no cover
            log.warning("소스 목록 조회 실패: %s", e)
            return []
        metas = res.get("metadatas") or []
        grouped: dict[str, dict[str, Any]] = {}
        for m in metas:
            source = str((m or {}).get("source", "")) or "unknown"
            entry = grouped.setdefault(
                source,
                {
                    "source": source,
                    "chunks": 0,
                    "doc_type": (m or {}).get("doc_type", ""),
                    "uploaded_at": (m or {}).get("uploaded_at", ""),
                },
            )
            entry["chunks"] += 1
            if (m or {}).get("uploaded_at"):
                entry["uploaded_at"] = (m or {}).get("uploaded_at")
        return sorted(grouped.values(), key=lambda x: x["source"].lower())

    def list_indexed_files(self) -> dict[str, dict[str, Any]]:
        """relative_path -> {mtime_ns, size, content_hash, doc_type, synced_at} 집계.

        같은 relative_path 의 여러 청크는 동일 파일 메타를 공유하므로 첫 번째 값만 사용.
        """
        handle = self._ensure_handle()
        try:
            res = handle.collection.get(include=["metadatas"])
        except Exception as e:
            log.warning("인덱스 파일 목록 조회 실패: %s", e)
            return {}
        metas = res.get("metadatas") or []
        out: dict[str, dict[str, Any]] = {}
        for m in metas:
            rel = (m or {}).get("relative_path") or (m or {}).get("source")
            if not rel or rel in out:
                continue
            out[rel] = {
                "mtime_ns": (m or {}).get("mtime_ns"),
                "size": (m or {}).get("size"),
                "content_hash": (m or {}).get("content_hash"),
                "doc_type": (m or {}).get("doc_type"),
                "synced_at": (m or {}).get("synced_at") or (m or {}).get("uploaded_at"),
            }
        return out


_DEFAULT_STORE: ChromaStore | None = None


def get_vector_store(cfg: AppConfig | None = None) -> ChromaStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = ChromaStore.from_config(cfg or get_config())
    return _DEFAULT_STORE


def reset_vector_store() -> None:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is not None:
        _DEFAULT_STORE.close()
    _DEFAULT_STORE = None


def upsert_chunks(chunks: Sequence[Chunk], source: str | None = None) -> int:
    return get_vector_store().upsert_chunks(chunks, source=source)


def search(query: str, top_k: int = 5) -> list[RetrievedChunk]:
    return get_vector_store().search(query, top_k=top_k)
