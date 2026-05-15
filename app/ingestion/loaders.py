"""Document loaders for PDF, DOCX, TXT, Markdown."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.common.logging import get_logger

log = get_logger(__name__)

SUPPORTED_EXTS = {"pdf", "docx", "txt", "md", "markdown"}


@dataclass(slots=True)
class LoadedPage:
    """로더가 반환하는 문서의 한 단위 (페이지 또는 청크 이전의 텍스트)."""

    source: str
    doc_type: str
    page: int | None
    location: str
    text: str


def detect_doc_type(path: str | Path) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix == "markdown":
        return "md"
    return suffix


def is_supported(path: str | Path) -> bool:
    return detect_doc_type(path) in SUPPORTED_EXTS


def _load_pdf(path: Path) -> list[LoadedPage]:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("pypdf가 설치되어 있지 않습니다. 'pip install pypdf'") from e

    reader = PdfReader(str(path))
    pages: list[LoadedPage] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            log.warning("PDF 페이지 추출 실패 (%s p.%d): %s", path.name, idx, e)
            text = ""
        text = text.strip()
        if not text:
            continue
        pages.append(
            LoadedPage(
                source=path.name,
                doc_type="pdf",
                page=idx,
                location=f"page={idx}",
                text=text,
            )
        )
    return pages


def _load_docx(path: Path) -> list[LoadedPage]:
    try:
        from docx import Document
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("python-docx가 설치되어 있지 않습니다.") from e

    doc = Document(str(path))
    paragraphs: list[str] = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            paragraphs.append(t)
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                paragraphs.append(" | ".join(cells))
    body = "\n".join(paragraphs).strip()
    if not body:
        return []
    return [
        LoadedPage(
            source=path.name,
            doc_type="docx",
            page=None,
            location="section=body",
            text=body,
        )
    ]


def _load_text(path: Path, doc_type: str) -> list[LoadedPage]:
    for encoding in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        text = path.read_text(encoding="utf-8", errors="replace")
    text = text.strip()
    if not text:
        return []
    return [
        LoadedPage(
            source=path.name,
            doc_type=doc_type,
            page=None,
            location="section=body",
            text=text,
        )
    ]


def load_document(path: str | Path, relative_path: str | None = None) -> list[LoadedPage]:
    """지원 형식의 파일에서 페이지 단위 텍스트를 추출한다.

    :param relative_path: 지정 시 LoadedPage.source 를 이 값으로 덮어쓴다.
                          Vault 모드에서 vault 루트 기준 상대 경로를 전달.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {p}")
    doc_type = detect_doc_type(p)
    if doc_type not in SUPPORTED_EXTS:
        raise ValueError(f"지원하지 않는 형식: .{doc_type} (파일: {p.name})")

    if doc_type == "pdf":
        pages = _load_pdf(p)
    elif doc_type == "docx":
        pages = _load_docx(p)
    elif doc_type in ("md", "markdown"):
        pages = _load_text(p, "md")
    else:
        pages = _load_text(p, "txt")

    if relative_path is not None:
        pages = [
            LoadedPage(
                source=relative_path,
                doc_type=pg.doc_type,
                page=pg.page,
                location=pg.location,
                text=pg.text,
            )
            for pg in pages
        ]
    return pages


def load_documents(paths: Iterable[str | Path]) -> list[LoadedPage]:
    pages: list[LoadedPage] = []
    for p in paths:
        pages.extend(load_document(p))
    return pages
