from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.routes import vault
from app.config import AppConfig


def test_browse_rejects_request_without_app_header() -> None:
    client = TestClient(create_app())

    response = client.post("/api/vault/browse")

    assert response.status_code == 403


def test_browse_cancel_returns_no_content(monkeypatch) -> None:
    monkeypatch.setattr(vault.platform, "system", lambda: "Windows")
    monkeypatch.setattr(vault, "_tkinter_browse", lambda: "")
    client = TestClient(create_app())

    response = client.post("/api/vault/browse", headers={"X-Requested-With": "oh-my-neuro"})

    assert response.status_code == 204
    assert response.content == b""


def test_validate_scan_truncates_document_preview(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(vault, "VAULT_VALIDATION_MAX_DOCUMENTS", 2)
    for index in range(3):
        (tmp_path / f"note-{index}.md").write_text("memo", encoding="utf-8")
    cfg = AppConfig(vault={"path": str(tmp_path), "include_extensions": [".md"]})

    doc_count, extensions, truncated = vault._scan_vault_validation(tmp_path, cfg.vault)

    assert doc_count == 2
    assert extensions == [".md"]
    assert truncated is True
