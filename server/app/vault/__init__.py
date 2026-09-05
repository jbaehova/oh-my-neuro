"""Vault management — scan, delta, sync, persistence."""

from __future__ import annotations

from app.vault.state import SyncHistoryEntry, VaultState

__all__ = ["VaultState", "SyncHistoryEntry"]
