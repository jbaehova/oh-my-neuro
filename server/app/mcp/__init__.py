"""MCP client integration."""

from app.mcp.client import (
    MCPClient,
    build_mcp_client,
    get_mcp_client,
    reset_mcp_client,
    search_law,
)

__all__ = [
    "MCPClient",
    "build_mcp_client",
    "get_mcp_client",
    "reset_mcp_client",
    "search_law",
]
