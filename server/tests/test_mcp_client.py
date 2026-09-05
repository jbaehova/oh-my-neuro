from app.common.models import MCPResult
from app.config.loader import AppConfig, MCPConfig, MCPServerSpec
from app.mcp.client import MCPClient, _split_formatted_web_results


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def test_web_tool_prefers_search_over_fetch_content() -> None:
    client = MCPClient(AppConfig(openai_api_key="test"))
    client._tools = [
        FakeTool("web_search_fetch_content"),
        FakeTool("web_search_search"),
    ]

    tool = client._pick_web_tool()

    assert tool is not None
    assert tool.name == "web_search_search"


def test_law_tool_does_not_fall_back_to_web_search() -> None:
    client = MCPClient(AppConfig(openai_api_key="test"))
    client._tools = [FakeTool("web_search_search")]

    assert client._pick_law_tool() is None


def test_split_formatted_web_results_extracts_clickable_urls() -> None:
    content = """Found 2 search results:

1. First result
   URL: https://example.test/one
   Summary: First summary.

2. Second result
   URL: https://example.test/two
   Summary: Second summary.
"""

    results = _split_formatted_web_results([MCPResult(tool="web_search_search", content=content, kind="web")])

    assert [(item.title, item.url) for item in results] == [
        ("First result", "https://example.test/one"),
        ("Second result", "https://example.test/two"),
    ]


def test_status_without_connect_does_not_initialize_mcp() -> None:
    client = MCPClient(AppConfig(openai_api_key="test", mcp={"enabled": True}))
    client._mcp_config = MCPConfig(
        servers={
            "web_search": MCPServerSpec(
                name="web_search",
                transport="stdio",
                command="uvx",
                args=["duckduckgo-mcp-server"],
            )
        }
    )

    status = client.status(connect=False)

    assert client._attempted is False
    assert status["connection_checked"] is False
    assert status["available"] is False
    assert status["web_search_configured"] is True
