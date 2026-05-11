"""Configuration loader for OH-MY-NEURO.

YAML과 환경 변수를 병합해 Pydantic 모델로 검증된 설정 객체를 반환한다.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except Exception:  # pragma: no cover - dotenv optional
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


class AppSection(BaseModel):
    name: str = "oh-my-neuro"
    environment: str = "local"
    log_level: str = "INFO"


class LLMSection(BaseModel):
    provider: str = "openai"
    chat_model: str = "gpt-5.4-mini"
    grader_model: str = "gpt-5.4-nano"
    rewriter_model: str = "gpt-5.4-nano"
    embedding_model: str = "text-embedding-3-large"
    temperature: float = 0.2
    request_timeout: int = 60


class RetrievalSection(BaseModel):
    top_k: int = 5
    fetch_k: int = 12
    chunk_size: int = 1000
    chunk_overlap: int = 150
    max_rewrites: int = 1
    relevance_threshold: float = 0.5

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_lt_size(cls, v: int, info: Any) -> int:
        size = info.data.get("chunk_size", 1000)
        if v >= size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return v


class StorageSection(BaseModel):
    chroma_path: str = "data/chroma"
    collection_name: str = "oh_my_neuro"
    distance: str = "cosine"

    @property
    def chroma_path_abs(self) -> Path:
        return _project_path(self.chroma_path)


class VaultSection(BaseModel):
    path: str = ""
    recursive: bool = True
    include_extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".docx", ".txt", ".md", ".markdown"]
    )
    max_file_mb: int = 50
    excluded_dirs: list[str] = Field(
        default_factory=lambda: [".git", "node_modules", ".obsidian", "__pycache__", ".venv", "venv"]
    )

    @property
    def path_abs(self) -> Path | None:
        if not self.path:
            return None
        return Path(self.path).expanduser().resolve()


class MCPSection(BaseModel):
    enabled: bool = True
    config_path: str = "configs/mcp_servers.yaml"
    law_server: str = "korean_law"
    law_keywords: list[str] = Field(default_factory=list)

    @property
    def config_path_abs(self) -> Path:
        return _project_path(self.config_path)


class UISection(BaseModel):
    title: str = "OH-MY-NEURO"
    description: str = "로컬 Vault 기반 RAG 문서 검색"
    host: str = "127.0.0.1"
    port: int = 7860
    dark: bool = False


class AppConfig(BaseModel):
    app: AppSection = Field(default_factory=AppSection)
    llm: LLMSection = Field(default_factory=LLMSection)
    retrieval: RetrievalSection = Field(default_factory=RetrievalSection)
    storage: StorageSection = Field(default_factory=StorageSection)
    vault: VaultSection = Field(default_factory=VaultSection)
    mcp: MCPSection = Field(default_factory=MCPSection)
    ui: UISection = Field(default_factory=UISection)

    openai_api_key: str = ""
    config_source: str = ""

    def ensure_dirs(self) -> None:
        self.storage.chroma_path_abs.mkdir(parents=True, exist_ok=True)

    def has_api_key(self) -> bool:
        return bool(self.openai_api_key)


class MCPServerSpec(BaseModel):
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    enabled: bool = True

    def to_adapter_spec(self) -> dict[str, Any]:
        if self.transport == "stdio":
            return {
                "command": self.command or "",
                "args": list(self.args),
                "transport": "stdio",
                "env": dict(self.env),
            }
        if self.transport in ("streamable_http", "http"):
            return {
                "url": self.url or "",
                "transport": "streamable_http",
            }
        if self.transport == "sse":
            return {
                "url": self.url or "",
                "transport": "sse",
            }
        raise ValueError(f"Unsupported MCP transport: {self.transport}")


class MCPConfig(BaseModel):
    servers: dict[str, MCPServerSpec] = Field(default_factory=dict)

    def enabled_servers(self) -> dict[str, MCPServerSpec]:
        return {k: v for k, v in self.servers.items() if v.enabled}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must be a mapping at top level")
    return data


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """YAML + 환경변수로부터 설정을 로드한다."""
    path = Path(config_path) if config_path else _project_path("configs/app.yaml")
    raw = _read_yaml(path)
    if "uploads" in raw:
        import logging

        logging.getLogger(__name__).warning(
            "configs/app.yaml의 'uploads:' 섹션은 v0.3.0에서 무시됩니다. 'vault:' 섹션으로 이전하세요."
        )
        raw.pop("uploads", None)
    try:
        cfg = AppConfig(**raw)
    except ValidationError as e:
        raise RuntimeError(f"Invalid configuration in {path}: {e}") from e

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    cfg = cfg.model_copy(update={"openai_api_key": api_key, "config_source": str(path)})

    log_level = os.getenv("OMN_LOG_LEVEL")
    if log_level:
        cfg.app.log_level = log_level

    return cfg


def load_mcp_config(path: str | Path | None = None) -> MCPConfig:
    p = Path(path) if path else _project_path("configs/mcp_servers.yaml")
    raw = _read_yaml(p)
    servers_raw = raw.get("servers", {}) or {}
    servers: dict[str, MCPServerSpec] = {}
    for name, spec in servers_raw.items():
        if not isinstance(spec, dict):
            continue
        servers[name] = MCPServerSpec(name=name, **spec)
    return MCPConfig(servers=servers)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()


def reset_config_cache() -> None:
    get_config.cache_clear()
