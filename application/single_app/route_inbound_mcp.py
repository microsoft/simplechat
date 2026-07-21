# route_inbound_mcp.py

import json
import logging

from flask import g, jsonify, request

from config import (
    AUTHORITY,
    CLIENT_ID,
    VERSION,
)
from functions_appinsights import log_event
from functions_mcp_server_governance import evaluate_inbound_mcp_governance, get_inbound_mcp_governance_baseline
from functions_mcp_server_registry import (
    build_mcp_tool_descriptor,
    get_enabled_inbound_mcp_tools,
    get_inbound_mcp_tool,
    get_inbound_mcp_tool_registry,
)
from functions_mcp_server_config import get_inbound_mcp_runtime_config
from functions_mcp_server_tools import execute_inbound_mcp_tool
from swagger_wrapper import swagger_route, get_auth_security


def _resource_identifier():
    if CLIENT_ID:
        return f"api://{CLIENT_ID}"
    return ""


def _authorization_server():
    return AUTHORITY.rstrip("/") if AUTHORITY else ""


def _get_auth_context():
    return getattr(g, "inbound_mcp_auth_context", None)


def _jsonrpc_response(request_id, result, status_code=200):
    return jsonify({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }), status_code


def _jsonrpc_error(request_id, code, message, data=None, status_code=400):
    error = {
        "code": code,
        "message": message,
    }
    if data is not None:
        error["data"] = data
    return jsonify({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error,
    }), status_code


def _json_text_content(value):
    return [{
        "type": "text",
        "text": json.dumps(value, ensure_ascii=True),
    }]


def build_inbound_mcp_protected_resource_metadata():
    """Build safe OAuth protected resource metadata for inbound MCP clients."""
    runtime_config = get_inbound_mcp_runtime_config()
    authorization_server = _authorization_server()
    scopes_supported = []
    required_scope = str(runtime_config.get("inbound_mcp_required_scope") or "").strip()
    if required_scope:
        scopes_supported.append(required_scope)

    metadata = {
        "resource": _resource_identifier(),
        "authorization_servers": [authorization_server] if authorization_server else [],
        "scopes_supported": scopes_supported,
        "bearer_methods_supported": ["header"],
        "resource_documentation": "https://aka.ms/simplechat-documentation",
        "mcp_endpoint": runtime_config.get("inbound_mcp_resource_path", "/api/mcp"),
    }
    return metadata


def _build_initialize_result():
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {
                "listChanged": False,
            },
        },
        "serverInfo": {
            "name": "simplechat-inbound-mcp",
            "version": VERSION,
        },
    }


def _build_tools_list_result(auth_context):
    enabled_tools = get_enabled_inbound_mcp_tools(auth_context)
    return {
        "tools": [
            build_mcp_tool_descriptor(tool)
            for tool in enabled_tools
        ],
    }


def _call_tool(auth_context, request_id, params):
    params = params if isinstance(params, dict) else {}
    tool_name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    if not tool_name:
        return _jsonrpc_error(request_id, -32602, "Tool name is required.", status_code=400)

    tool = get_inbound_mcp_tool(tool_name)
    if not tool or not bool(tool.get("implemented", False)):
        return _jsonrpc_error(request_id, -32601, "Inbound MCP tool is not available.", status_code=404)

    decision = evaluate_inbound_mcp_governance(
        auth_context=auth_context,
        tool_id=tool.get("id", ""),
        resource_family=tool.get("resource_family", ""),
        operation=tool.get("operation", ""),
        scope=tool.get("scope", ""),
        target_scope_id=getattr(auth_context, "delegated_user_id", ""),
        identity_type=tool.get("identity_type", "delegated"),
    )
    if not decision.allowed:
        log_event(
            "[InboundMCP] Inbound MCP tool call denied by governance.",
            extra={
                "tool_id": tool.get("id", ""),
                "caller_app_id": getattr(auth_context, "caller_app_id", ""),
                "delegated_user_id": getattr(auth_context, "delegated_user_id", ""),
                "error": decision.error,
            },
            level=logging.WARNING,
            debug_only=True,
            category="InboundMCP",
        )
        return _jsonrpc_error(
            request_id,
            -32001,
            "Inbound MCP governance denied the tool call.",
            data=decision.to_dict(),
            status_code=403,
        )

    try:
        result = execute_inbound_mcp_tool(tool.get("id", ""), auth_context, arguments)
    except ValueError as exc:
        return _jsonrpc_error(request_id, -32602, str(exc), status_code=400)
    except PermissionError:
        log_event(
            "[InboundMCP] Inbound MCP tool call denied by object authorization.",
            extra={
                "tool_id": tool.get("id", ""),
                "caller_app_id": getattr(auth_context, "caller_app_id", ""),
                "delegated_user_id": getattr(auth_context, "delegated_user_id", ""),
            },
            level=logging.WARNING,
            debug_only=True,
            category="InboundMCP",
        )
        return _jsonrpc_error(
            request_id,
            -32003,
            "Inbound MCP tool access denied.",
            status_code=403,
        )
    except LookupError:
        return _jsonrpc_error(
            request_id,
            -32004,
            "Inbound MCP resource not found.",
            status_code=404,
        )
    log_event(
        "[InboundMCP] Inbound MCP tool call completed.",
        extra={
            "tool_id": tool.get("id", ""),
            "caller_app_id": getattr(auth_context, "caller_app_id", ""),
            "delegated_user_id": getattr(auth_context, "delegated_user_id", ""),
            "audit_event": tool.get("audit_event", ""),
        },
        level=logging.INFO,
        debug_only=True,
        category="InboundMCP",
    )
    return _jsonrpc_response(request_id, {
        "content": _json_text_content(result),
        "structuredContent": result,
        "isError": False,
    })


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
        runtime_config = get_inbound_mcp_runtime_config()
        enabled_tools = get_enabled_inbound_mcp_tools(auth_context)
        return jsonify({
            "status": "ok",
            "enabled": bool(runtime_config.get("enable_inbound_mcp_server")),
            "transport": "streamable_http",
            "enabled_tools": len(enabled_tools),
            "governance": get_inbound_mcp_governance_baseline(),
        }), 200

    @bp.route("/api/mcp", methods=["POST"])
    @swagger_route(security=get_auth_security())
    def inbound_mcp_endpoint():
        """Handle streamable HTTP JSON-RPC requests for governed inbound MCP tools."""
        auth_context = _get_auth_context()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({
                "error": "invalid_mcp_request",
                "message": "Inbound MCP requests must be JSON-RPC objects.",
            }), 400

        request_id = payload.get("id")
        method = str(payload.get("method") or "").strip()
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

        if method == "notifications/initialized" and request_id is None:
            return "", 204

        if method == "initialize":
            return _jsonrpc_response(request_id, _build_initialize_result())

        if method == "tools/list":
            return _jsonrpc_response(request_id, _build_tools_list_result(auth_context))

        if method == "tools/call":
            return _call_tool(auth_context, request_id, params)

        log_event(
            "[InboundMCP] Unsupported inbound MCP method.",
            extra={
                "method": request.method,
                "path": request.path,
                "mcp_method": method,
                "caller_app_id": getattr(auth_context, "caller_app_id", ""),
                "tenant_id": getattr(auth_context, "tenant_id", ""),
                "planned_tools": len(get_inbound_mcp_tool_registry()),
            },
            level=logging.INFO,
            debug_only=True,
            category="InboundMCP",
        )
        return _jsonrpc_error(request_id, -32601, "Unsupported inbound MCP method.", status_code=404)
