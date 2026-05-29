from datetime import timedelta

from app.config.loader import MCPServerSpec, VaultSection, WikiSection


def test_blank_vault_path_is_unset() -> None:
    assert VaultSection(path="   ").path_abs is None


def test_wiki_directory_is_normalized() -> None:
    assert WikiSection(directory="/_omn_wiki/").directory == "_omn_wiki"
    assert "_omn_wiki" in VaultSection().excluded_dirs


def test_stdio_mcp_spec_expands_environment(monkeypatch) -> None:
    monkeypatch.setenv("OMN_MCP_BIN", "uvx")
    monkeypatch.setenv("OMN_MCP_TOKEN", "secret")

    spec = MCPServerSpec(
        name="law",
        transport="stdio",
        command="$OMN_MCP_BIN",
        args=["server", "$OMN_MCP_TOKEN"],
        cwd="$HOME",
        env={"TOKEN": "$OMN_MCP_TOKEN"},
    ).to_adapter_spec()

    assert spec["transport"] == "stdio"
    assert spec["command"] == "uvx"
    assert spec["args"] == ["server", "secret"]
    assert spec["env"] == {"TOKEN": "secret"}
    assert "$HOME" not in spec["cwd"]


def test_http_mcp_spec_maps_to_streamable_http(monkeypatch) -> None:
    monkeypatch.setenv("OMN_MCP_TOKEN", "secret")

    spec = MCPServerSpec(
        name="remote",
        transport="http",
        url="https://example.test/mcp",
        headers={"Authorization": "Bearer $OMN_MCP_TOKEN"},
        timeout=5,
        sse_read_timeout=30,
        terminate_on_close=True,
    ).to_adapter_spec()

    assert spec["transport"] == "streamable_http"
    assert spec["url"] == "https://example.test/mcp"
    assert spec["headers"] == {"Authorization": "Bearer secret"}
    assert spec["timeout"] == timedelta(seconds=5)
    assert spec["sse_read_timeout"] == timedelta(seconds=30)
    assert spec["terminate_on_close"] is True
