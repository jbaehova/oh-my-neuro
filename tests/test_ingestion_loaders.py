from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from app.config import IngestionSection
from app.ingestion import loaders
from app.ingestion.chunking import chunk_pages
from app.ingestion.loaders import LoadedPage, load_document


def test_pdf_auto_backend_falls_back_to_pypdf(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    def fail_pdf_monster(path: Path, ingestion: IngestionSection) -> list[LoadedPage]:
        raise RuntimeError("boom")

    def fake_pypdf(path: Path) -> list[LoadedPage]:
        return [
            LoadedPage(
                source=path.name,
                doc_type="pdf",
                page=1,
                location="page=1",
                text="fallback text",
                metadata={"parser_backend": "pypdf"},
            )
        ]

    monkeypatch.setattr(loaders, "_load_pdf_pdf_monster", fail_pdf_monster)
    monkeypatch.setattr(loaders, "_load_pdf_pypdf", fake_pypdf)

    pages = load_document(pdf_path, ingestion=IngestionSection(pdf_backend="auto"))

    assert pages[0].text == "fallback text"
    assert pages[0].metadata["parser_backend"] == "pypdf"


def test_pdf_monster_loader_uses_ocr_for_sparse_page(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    class FakePixmap:
        def save(self, target: str) -> None:
            Path(target).write_bytes(b"png")

    class FakePage:
        def get_text(self, kind: str, sort: bool = True) -> str:
            return ""

        def get_images(self, full: bool = True) -> list[tuple[int, int, int, int]]:
            return [(7, 0, 200, 200)]

        def get_pixmap(self, matrix: object, alpha: bool = False) -> FakePixmap:
            return FakePixmap()

    class FakeDoc:
        needs_pass = False
        page_count = 1

        def load_page(self, index: int) -> FakePage:
            return FakePage()

        def close(self) -> None:
            return None

    fake_fitz = SimpleNamespace(
        Matrix=lambda x, y: (x, y),
        open=lambda path: FakeDoc(),
    )
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    monkeypatch.setattr(loaders.shutil, "which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(
        loaders.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="scanned korean text\n",
            stderr="",
        ),
    )

    pages = loaders._load_pdf_pdf_monster(
        pdf_path,
        IngestionSection(pdf_backend="pdf_monster", pdf_ocr="auto"),
    )

    assert pages[0].text == "scanned korean text"
    assert pages[0].metadata["parser_backend"] == "pdf_monster"
    assert pages[0].metadata["ocr_attempted"] is True
    assert pages[0].metadata["ocr_used"] is True
    assert pages[0].metadata["needs_visual_review"] is True
    assert "new_significant_embedded_images:1" in str(pages[0].metadata["visual_review_reasons"])


def test_chunk_pages_merges_loaded_page_metadata() -> None:
    chunks = chunk_pages(
        [
            LoadedPage(
                source="doc.pdf",
                doc_type="pdf",
                page=1,
                location="page=1",
                text="alpha beta",
                metadata={"parser_backend": "pdf_monster", "ocr_used": True},
            )
        ],
        chunk_size=1000,
        chunk_overlap=0,
    )

    assert chunks[0].extras["parser_backend"] == "pdf_monster"
    assert chunks[0].to_metadata()["ocr_used"] is True
