"""MCP client wrapper used to fetch external context (e.g., Korean Law)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from app.common.logging import get_logger
from app.common.models import MCPResult
from app.config import AppConfig, MCPConfig, get_config, load_mcp_config

log = get_logger(__name__)


def _run_async(coro):
    """동기 컨텍스트에서 async 함수를 안전하게 실행한다."""
    running = False
    try:
        asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False
    if running:
        result_box: dict[str, Any] = {}

        def _runner() -> None:
            try:
                result_box["value"] = asyncio.run(coro)
            except Exception as e:  # pragma: no cover
                result_box["error"] = e

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join()
        if "error" in result_box:
            raise result_box["error"]
        return result_box.get("value")
    return asyncio.run(coro)


def _normalize_tool_output(raw: Any) -> list[MCPResult]:
    """MCP 도구 호출 결과를 MCPResult 리스트로 정규화."""
    if raw is None:
        return []
    results: list[MCPResult] = []

    def _push(content: str, title: str = "", url: str | None = None, meta: dict | None = None) -> None:
        content = (content or "").strip()
        if not content and not title:
            return
        results.append(
            MCPResult(
                tool="mcp",
                title=title,
                content=content,
                url=url,
                metadata=dict(meta or {}),
            )
        )

    if isinstance(raw, str):
        _push(raw)
        return results
    if isinstance(raw, list):
        for item in raw:
            results.extend(_normalize_tool_output(item))
        return results
    if isinstance(raw, dict):
        title = str(raw.get("title") or raw.get("name") or "")
        url = raw.get("url") or raw.get("link")
        text = raw.get("content") or raw.get("text") or raw.get("body") or raw.get("summary")
        if isinstance(text, list):
            collected: list[str] = []
            for t in text:
                if isinstance(t, dict):
                    t_type = t.get("type")
                    if t_type in ("text", "output_text") or "text" in t:
                        collected.append(str(t.get("text", "")))
                    # tool_use / image 등은 건너뜀
                else:
                    collected.append(str(t))
            text = "\n".join(s for s in collected if s)
        if text or title:
            _push(str(text or ""), title=title, url=url, meta=raw)
        else:
            _push(str(raw))
        return results
    _push(str(raw))
    return results


class MCPClient:
    """langchain-mcp-adapters를 래핑한 간단한 클라이언트."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._mcp_config: MCPConfig | None = None
        self._client = None
        self._tools: list[Any] | None = None
        self._lock = threading.Lock()
        self._attempted = False
        self._error: str | None = None

    # --- lifecycle ---------------------------------------------------------
    def _load_mcp_config(self) -> MCPConfig:
        if self._mcp_config is None:
            try:
                self._mcp_config = load_mcp_config(self._cfg.mcp.config_path_abs)
            except Exception as e:  # pragma: no cover
                log.warning("MCP 설정 로드 실패: %s", e)
                self._mcp_config = MCPConfig()
        return self._mcp_config

    def _initialize(self) -> None:
        if self._attempted:
            return
        with self._lock:
            if self._attempted:
                return
            self._attempted = True
            if not self._cfg.mcp.enabled:
                self._error = "MCP가 설정에서 비활성화되어 있습니다."
                return
            mcp_cfg = self._load_mcp_config()
            enabled = mcp_cfg.enabled_servers()
            if not enabled:
                self._error = "활성화된 MCP 서버가 없습니다."
                return
            try:
                from langchain_mcp_adapters.client import MultiServerMCPClient
            except ImportError as e:
                self._error = f"langchain-mcp-adapters 미설치: {e}"
                return
            spec = {name: server.to_adapter_spec() for name, server in enabled.items()}
            try:
                self._client = MultiServerMCPClient(spec)
                self._tools = _run_async(self._client.get_tools())
                log.info("MCP 도구 로드: %d개", len(self._tools or []))
            except Exception as e:
                log.warning("MCP 초기화 실패: %s", e)
                self._error = f"MCP 서버 연결 실패: {e}"
                self._client = None
                self._tools = None

    # --- public API --------------------------------------------------------
    def status(self) -> dict[str, Any]:
        self._initialize()
        tools = [getattr(t, "name", "?") for t in (self._tools or [])]
        return {
            "enabled": self._cfg.mcp.enabled,
            "available": self._tools is not None and bool(self._tools),
            "error": self._error,
            "tools": tools,
            "server": self._cfg.mcp.law_server,
        }

    def is_available(self) -> bool:
        self._initialize()
        return self._tools is not None and bool(self._tools)

    def _pick_law_tool(self):
        if not self._tools:
            return None
        preferred = [
            "search_law",
            "search_korean_law",
            "korean_law_search",
            "search_precedent",
            "search_statute",
        ]
        named = {getattr(t, "name", ""): t for t in self._tools}
        for name in preferred:
            if name in named:
                return named[name]
        for tool in self._tools:
            name = getattr(tool, "name", "").lower()
            if "law" in name or "법" in name or "statute" in name or "precedent" in name:
                return tool
        return self._tools[0] if self._tools else None

    def search_law(self, query: str) -> list[MCPResult]:
        self._initialize()
        if not self.is_available():
            return []
        tool = self._pick_law_tool()
        if tool is None:
            return []
        try:
            payload = {"query": query}
            result = _run_async(tool.ainvoke(payload))
        except Exception as e:
            log.warning("MCP law 도구 호출 실패: %s", e)
            try:
                result = _run_async(tool.ainvoke({"q": query}))
            except Exception as e2:  # pragma: no cover
                log.warning("MCP 재시도도 실패: %s", e2)
                return []
        normalized = _normalize_tool_output(result)
        tool_name = getattr(tool, "name", "mcp")
        for item in normalized:
            item.tool = tool_name
        return normalized[:5]


_DEFAULT_CLIENT: MCPClient | None = None


def get_mcp_client(cfg: AppConfig | None = None) -> MCPClient:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = MCPClient(cfg or get_config())
    return _DEFAULT_CLIENT


def reset_mcp_client() -> None:
    global _DEFAULT_CLIENT
    _DEFAULT_CLIENT = None


def build_mcp_client() -> MCPClient:
    return get_mcp_client()


def search_law(query: str) -> list[dict]:
    results = get_mcp_client().search_law(query)
    return [r.model_dump() for r in results]
