"""Document loading, chunking, and indexing."""

from app.ingestion.chunking import chunk_pages
from app.ingestion.loaders import (
    SUPPORTED_EXTS,
    LoadedPage,
    detect_doc_type,
    is_supported,
    load_document,
    load_documents,
)
from app.ingestion.pipeline import (
    clear_all,
    index_vault_delta,
    list_indexed_sources,
)

__all__ = [
    "LoadedPage",
    "SUPPORTED_EXTS",
    "chunk_pages",
    "clear_all",
    "detect_doc_type",
    "index_vault_delta",
    "is_supported",
    "list_indexed_sources",
    "load_document",
    "load_documents",
]
