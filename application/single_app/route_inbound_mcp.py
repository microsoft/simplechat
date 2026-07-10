# route_inbound_mcp.py

import logging

from flask import g, jsonify, request

from config import (
    AUTHORITY,
    CLIENT_ID,
    ENABLE_INBOUND_MCP_SERVER,
    INBOUND_MCP_REQUIRED_SCOPE,
)
from functions_appinsights import log_event
from functions_mcp_server_governance import get_inbound_mcp_governance_baseline
from functions_mcp_server_registry import (
    get_enabled_inbound_mcp_tools,
    get_inbound_mcp_tool_registry,
)
from swagger_wrapper import swagger_route, get_auth_security


def _resource_identifier():
    if CLIENT_ID:
        return f"api://{CLIENT_ID}"
    return ""


def _authorization_server():
    return AUTHORITY.rstrip("/") if AUTHORITY else ""


def _get_auth_context():
    return getattr(g, "inbound_mcp_auth_context", None)


def build_inbound_mcp_protected_resource_metadata():
    """Build safe OAuth protected resource metadata for inbound MCP clients."""
    authorization_server = _authorization_server()
    scopes_supported = []
    if INBOUND_MCP_REQUIRED_SCOPE:
        scopes_supported.append(INBOUND_MCP_REQUIRED_SCOPE)

    metadata = {
        "resource": _resource_identifier(),
        "authorization_servers": [authorization_server] if authorization_server else [],
        "scopes_supported": scopes_supported,
        "bearer_methods_supported": ["header"],
        "resource_documentation": "https://aka.ms/simplechat-documentation",
        "mcp_endpoint": "/api/mcp",
    }
    return metadata


def register_route_inbound_mcp(bp):
    @bp.route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])
    @swagger_route(security=get_auth_security())
    def inbound_mcp_protected_resource_metadata():
        """Return safe OAuth Protected Resource Metadata for inbound MCP clients."""
        return jsonify(build_inbound_mcp_protected_resource_metadata()), 200

    @bp.route("/api/mcp/health", methods=["GET"])
    @swagger_route(security=get_auth_security())
    def inbound_mcp_health():
        """Return authenticated inbound MCP shell health information."""
        auth_context = _get_auth_context()
        enabled_tools = get_enabled_inbound_mcp_tools(auth_context)
        return jsonify({
            "status": "ok",
            "enabled": ENABLE_INBOUND_MCP_SERVER,
            "transport": "streamable_http",
            "enabled_tools": len(enabled_tools),
            "governance": get_inbound_mcp_governance_baseline(),
        }), 200

    @bp.route("/api/mcp", methods=["POST"])
    @swagger_route(security=get_auth_security())
    def inbound_mcp_endpoint():
        """Return the disabled-shell response until tools are explicitly enabled."""
        auth_context = _get_auth_context()
        planned_tools = get_inbound_mcp_tool_registry()
        enabled_tools = get_enabled_inbound_mcp_tools(auth_context)
        log_event(
            "[InboundMCP] Inbound MCP endpoint reached with no enabled tools.",
            extra={
                "method": request.method,
                "path": request.path,
                "caller_app_id": getattr(auth_context, "caller_app_id", ""),
                "tenant_id": getattr(auth_context, "tenant_id", ""),
                "enabled_tools": len(enabled_tools),
                "planned_tools": len(planned_tools),
            },
            level=logging.INFO,
            debug_only=True,
            category="InboundMCP",
        )
        return jsonify({
            "error": "inbound_mcp_no_tools_enabled",
            "message": "Inbound MCP is enabled, but no tools are exposed in this phase.",
            "enabled_tools": [],
            "planned_tool_count": len(planned_tools),
        }), 501
