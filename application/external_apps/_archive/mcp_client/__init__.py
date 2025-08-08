"""
SimpleChat MCP Client Package

This package provides a client interface to the SimpleChat MCP (Model Context Protocol) server,
enabling integration with Semantic Kernel and other applications.
"""

from .simplechat_mcp_client import (
    SimpleChatMCPClient,
    SimpleChatMCPClientConfig,
    MCPClientError,
    MCPConnectionError,
    MCPToolError,
    create_mcp_client
)

from .mcp_client_plugin import (
    SimpleChatMCPPlugin,
    add_simplechat_plugin
)

__version__ = "1.0.0"
__author__ = "SimpleChat Team"

__all__ = [
    "SimpleChatMCPClient",
    "SimpleChatMCPClientConfig", 
    "MCPClientError",
    "MCPConnectionError",
    "MCPToolError",
    "create_mcp_client",
    "SimpleChatMCPPlugin",
    "add_simplechat_plugin"
]