"""Vault file scanner — walk + filter + stat + hash."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.common.models import SkippedFile
from app.config.loader import VaultSection

HASH_PREFIX_CHARS = 16  # first 16 hex chars of sha256


@dataclass(slots=True, frozen=True)
class FileEntry:
    """Scan 결과. 해시는 lazy — `compute_hash`로 별도 계산."""

    relative_path: str  # POSIX-style path relative to vault root
    absolute_path: Path
    mtime_ns: int
    size: int


def compute_hash(path: Path) -> str:
    """sha256(file) 앞 16 hex chars."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:HASH_PREFIX_CHARS]


def _is_excluded_dir(name: str, excluded: list[str]) -> bool:
    if name.startswith("."):
        return True
    return name in excluded


def scan_vault(
    root: Path,
    cfg: VaultSection,
) -> tuple[list[FileEntry], list[SkippedFile]]:
    """Vault를 walk해서 (included_entries, skipped) 반환.

    - `cfg.recursive`가 False면 root 직계만.
    - 확장자 미지원 → 조용히 무시 (skipped에 포함 안 함).
    - 크기 초과 → skipped에 `too_large`.
    - 숨김 디렉토리(`.*`), cfg.excluded_dirs 에 있는 디렉토리는 walk에서 제외.
    """
    if not root.exists() or not root.is_dir():
        return [], []

    exts = {e.lower() for e in cfg.include_extensions}
    max_bytes = cfg.max_file_mb * 1024 * 1024
    entries: list[FileEntry] = []
    skipped: list[SkippedFile] = []

    def _process_file(abs_path: Path, rel: str) -> None:
        ext = abs_path.suffix.lower()
        if ext not in exts:
            return
        try:
            st = abs_path.stat()
        except OSError:
            skipped.append(SkippedFile(path=rel, reason="unreadable"))
            return
        if st.st_size > max_bytes:
            skipped.append(SkippedFile(path=rel, reason="too_large"))
            return
        entries.append(
            FileEntry(
                relative_path=rel,
                absolute_path=abs_path,
                mtime_ns=st.st_mtime_ns,
                size=st.st_size,
            )
        )

    if cfg.recursive:
        for dirpath, _dirnames, filenames in _walk(root, cfg.excluded_dirs):
            rel_dir = dirpath.relative_to(root).as_posix()
            for name in filenames:
                rel = f"{rel_dir}/{name}" if rel_dir != "." else name
                _process_file(dirpath / name, rel)
    else:
        for item in sorted(root.iterdir()):
            if item.is_file():
                _process_file(item, item.name)

    entries.sort(key=lambda e: e.relative_path)
    skipped.sort(key=lambda s: s.path)
    return entries, skipped


def _walk(root: Path, excluded: list[str]):
    """os.walk-like generator that honors excluded dirs and symlink safety."""
    import os

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # filter in-place to prune traversal
        dirnames[:] = [d for d in dirnames if not _is_excluded_dir(d, excluded)]
        yield Path(dirpath), dirnames, filenames
