"""MCP client wrapper used to fetch external context (e.g., Korean Law)."""

from __future__ import annotations

import asyncio
import re
import threading
from typing import Any

from app.common.logging import get_logger
from app.common.models import MCPResult
from app.config import AppConfig, MCPConfig, get_config, load_user_mcp_config

log = get_logger(__name__)

_WEB_RESULT_RE = re.compile(
    r"^\s*\d+\.\s+(?P<title>.+?)\n\s*URL:\s*(?P<url>\S+)\n\s*Summary:\s*(?P<summary>.*?)(?=\n\s*\d+\.|\Z)",
    re.MULTILINE | re.DOTALL,
)


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


def _split_formatted_web_results(results: list[MCPResult]) -> list[MCPResult]:
    out: list[MCPResult] = []
    for item in results:
        matches = list(_WEB_RESULT_RE.finditer(item.content or ""))
        if not matches:
            out.append(item)
            continue
        for match in matches:
            summary = " ".join(match.group("summary").split())
            out.append(
                MCPResult(
                    tool=item.tool,
                    title=match.group("title").strip(),
                    url=match.group("url").strip(),
                    content=summary,
                    kind="web",
                    metadata=item.metadata,
                )
            )
    return out


class MCPClient:
    """langchain-mcp-adapters를 래핑한 간단한 클라이언트."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._mcp_config: MCPConfig | None = None
        self._client = None
        self._clients: list[Any] = []
        self._tools: list[Any] | None = None
        self._lock = threading.Lock()
        self._attempted = False
        self._error: str | None = None
        self._last_web_error: str = ""

    # --- lifecycle ---------------------------------------------------------
    def _load_mcp_config(self) -> MCPConfig:
        if self._mcp_config is None:
            try:
                self._mcp_config = load_user_mcp_config(
                    self._cfg.mcp.config_path_abs,
                    self._cfg.mcp.user_config_path_abs,
                )
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
            try:
                spec = {name: server.to_adapter_spec() for name, server in enabled.items()}
            except Exception as e:
                log.warning("MCP 서버 설정 변환 실패: %s", e)
                self._error = f"MCP 서버 설정 오류: {e}"
                return
            try:
                self._client = MultiServerMCPClient(
                    spec,
                    tool_name_prefix=self._cfg.mcp.tool_name_prefix,
                )
                self._tools = _run_async(self._client.get_tools())
                self._clients = [self._client]
                self._error = None
                log.info("MCP 도구 로드: %d개", len(self._tools or []))
            except Exception as e:
                log.warning("MCP 일괄 초기화 실패, 서버별 재시도: %s", e)
                tools: list[Any] = []
                clients: list[Any] = []
                failures: list[str] = []
                for name, server_spec in spec.items():
                    try:
                        client = MultiServerMCPClient(
                            {name: server_spec},
                            tool_name_prefix=self._cfg.mcp.tool_name_prefix,
                        )
                        server_tools = _run_async(client.get_tools())
                    except Exception as server_exc:
                        log.warning("MCP 서버 초기화 실패(%s): %s", name, server_exc)
                        failures.append(f"{name}: {server_exc}")
                        continue
                    clients.append(client)
                    tools.extend(server_tools)
                self._clients = clients
                self._client = clients[0] if clients else None
                self._tools = tools or None
                if tools:
                    self._error = "일부 MCP 서버 연결 실패: " + "; ".join(failures) if failures else None
                    log.info("MCP 도구 부분 로드: %d개", len(tools))
                else:
                    self._error = f"MCP 서버 연결 실패: {e}"

    # --- public API --------------------------------------------------------
    def status(self, *, connect: bool = True) -> dict[str, Any]:
        if connect:
            self._initialize()
        tools = [getattr(t, "name", "?") for t in (self._tools or [])]
        mcp_cfg = self._load_mcp_config()
        web_tool = self._pick_web_tool()
        web_search_configured = any(
            _looks_like_web_server(name, server)
            for name, server in mcp_cfg.enabled_servers().items()
        )
        return {
            "enabled": self._cfg.mcp.enabled,
            "available": self._tools is not None and bool(self._tools),
            "error": self._error,
            "connection_checked": self._attempted,
            "tools": tools,
            "web_search_configured": web_search_configured,
            "web_search_available": web_tool is not None,
            "web_search_tool": getattr(web_tool, "name", "") if web_tool is not None else "",
            "servers": list(mcp_cfg.servers.keys()),
            "enabled_servers": list(mcp_cfg.enabled_servers().keys()),
            "server": self._cfg.mcp.law_server,
        }

    def is_available(self) -> bool:
        self._initialize()
        return self._tools is not None and bool(self._tools)

    def _pick_law_tool(self):
        if not self._tools:
            return None
        law_server = self._cfg.mcp.law_server.lower()
        preferred = [
            "search_law",
            "search_korean_law",
            "korean_law_search",
            "search_precedent",
            "search_statute",
        ]
        named = {getattr(t, "name", ""): t for t in self._tools}
        for name in preferred:
            prefixed = f"{law_server}_{name}"
            if prefixed in named:
                return named[prefixed]
        for name in preferred:
            if name in named:
                return named[name]
        for tool in self._tools:
            name = getattr(tool, "name", "").lower()
            if (
                name.startswith(f"{law_server}_")
                or "law" in name
                or "법" in name
                or "statute" in name
                or "precedent" in name
            ):
                return tool
        return None

    def _pick_web_tool(self):
        if not self._tools:
            return None
        preferred_parts = (
            "web_search",
            "search_web",
            "internet_search",
            "brave",
            "tavily",
            "duckduckgo",
            "google",
            "bing",
            "perplexity",
            "serp",
        )
        excluded_parts = ("law", "statute", "precedent", "법", "판례", "조항")
        candidates: list[tuple[int, Any]] = []
        for tool in self._tools:
            name = getattr(tool, "name", "").lower()
            if any(part in name for part in excluded_parts):
                continue
            score = 0
            if name in ("search", "web_search_search", "duckduckgo_search"):
                score += 100
            if name.endswith("_search") or name.endswith(".search"):
                score += 90
            if "search_web" in name:
                score += 80
            if any(part in name for part in preferred_parts):
                score += 60
            if "search" in name:
                score += 40
            if any(part in name for part in ("fetch", "content", "page", "read")):
                score -= 50
            if score > 0:
                candidates.append((score, tool))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

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

    def search_web(self, query: str) -> list[MCPResult]:
        self._last_web_error = ""
        self._initialize()
        if not self.is_available():
            self._last_web_error = self._error or "MCP 도구를 사용할 수 없습니다."
            return []
        tool = self._pick_web_tool()
        if tool is None:
            self._last_web_error = "웹검색 MCP 도구를 찾을 수 없습니다."
            return []
        result = None
        payloads = (
            {"query": query, "max_results": 5, "region": "kr-kr"},
            {"query": query, "max_results": 5},
            {"query": query},
            {"q": query},
            {"search": query},
        )
        for payload in payloads:
            try:
                result = _run_async(tool.ainvoke(payload))
                break
            except Exception as e:
                log.debug("MCP web 도구 호출 실패(%s): %s", sorted(payload), e)
                self._last_web_error = str(e)
        if result is None:
            if not self._last_web_error:
                self._last_web_error = "웹검색 MCP 도구 호출에 실패했습니다."
            return []
        normalized = _normalize_tool_output(result)
        tool_name = getattr(tool, "name", "mcp_web")
        for item in normalized:
            item.tool = tool_name
            item.kind = "web"
        split = _split_formatted_web_results(normalized)[:5]
        if not split:
            self._last_web_error = "웹검색 결과가 없습니다."
        return split

    def last_web_error(self) -> str:
        return self._last_web_error


def _looks_like_web_server(name: str, server: Any) -> bool:
    haystack = " ".join(
        [
            name,
            str(getattr(server, "command", "") or ""),
            " ".join(str(arg) for arg in (getattr(server, "args", []) or [])),
        ]
    ).lower()
    return any(
        marker in haystack
        for marker in (
            "web",
            "search",
            "duckduckgo",
            "brave",
            "tavily",
            "google",
            "bing",
            "serp",
        )
    )


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
