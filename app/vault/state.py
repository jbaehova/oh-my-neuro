"""Persistent vault state stored at ~/.oh-my-neuro/state.json."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_STATE_PATH = Path.home() / ".oh-my-neuro" / "state.json"
HISTORY_CAP = 20


class SyncHistoryEntry(BaseModel):
    at: str  # ISO 8601 UTC
    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    duration_s: float = 0.0


class VaultState(BaseModel):
    vault_path: str = ""
    onboarding_completed: bool = False
    last_sync_at: str | None = None
    sync_history: list[SyncHistoryEntry] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> VaultState:
        p = path or DEFAULT_STATE_PATH
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls.model_validate(data)

    def save(self, path: Path | None = None) -> None:
        p = path or DEFAULT_STATE_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump_json(indent=2)
        # atomic write: temp file + os.replace
        fd, tmp_name = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_name, p)
        except Exception:
            # cleanup tmp on failure
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    def record_sync(
        self,
        *,
        added: int,
        updated: int,
        deleted: int,
        skipped: int,
        duration_s: float,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.last_sync_at = now
        self.sync_history.insert(
            0,
            SyncHistoryEntry(
                at=now,
                added=added,
                updated=updated,
                deleted=deleted,
                skipped=skipped,
                duration_s=duration_s,
            ),
        )
        if len(self.sync_history) > HISTORY_CAP:
            self.sync_history = self.sync_history[:HISTORY_CAP]
