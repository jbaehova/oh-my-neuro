"""Vault manager — orchestrates scan → delta → sync."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import AppConfig, get_config
from app.vault.scanner import FileEntry


@dataclass
class Delta:
    add: list[FileEntry] = field(default_factory=list)
    update: list[FileEntry] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)  # relative paths

    @property
    def is_empty(self) -> bool:
        return not (self.add or self.update or self.delete)


class VaultManager:
    def __init__(self, cfg: AppConfig | None = None) -> None:
        self.cfg = cfg or get_config()

    @staticmethod
    def compute_delta(
        current: list[FileEntry],
        indexed: dict[str, dict[str, Any]],
        hash_check: Callable[[FileEntry], str] | None = None,
    ) -> Delta:
        """현재 스캔 결과와 인덱스 상태를 비교해 Delta 생성.

        `indexed`: {relative_path: {mtime_ns, size, content_hash}}
        `hash_check`: 선택적 콜백. (mtime_ns, size)가 달라 보일 때 content_hash 재계산을 위해 호출.
                      해시가 저장된 것과 같으면 UPDATE에서 제외(touched but unchanged).
        """
        current_map = {e.relative_path: e for e in current}
        d = Delta()

        for rel, entry in current_map.items():
            if rel not in indexed:
                d.add.append(entry)
                continue
            prev = indexed[rel]
            if entry.mtime_ns == prev.get("mtime_ns") and entry.size == prev.get("size"):
                continue  # unchanged
            # mtime 또는 size 변경 — 해시 확인 가능하면 검사
            prev_hash = prev.get("content_hash")
            if hash_check is not None and prev_hash:
                try:
                    cur_hash = hash_check(entry)
                except Exception:
                    cur_hash = None
                if cur_hash and cur_hash == prev_hash:
                    continue  # content unchanged — touched only
            d.update.append(entry)

        for rel in indexed:
            if rel not in current_map:
                d.delete.append(rel)

        d.add.sort(key=lambda e: e.relative_path)
        d.update.sort(key=lambda e: e.relative_path)
        d.delete.sort()
        return d
