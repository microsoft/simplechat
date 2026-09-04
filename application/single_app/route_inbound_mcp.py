# route_inbound_mcp.py

import json
import logging
import time

from flask import Response, g, jsonify, request

from config import (
    AUTHORITY,
    CLIENT_ID,
    INBOUND_MCP_PRM_PATHS,
    VERSION,
)
from functions_appinsights import log_event
from functions_mcp_server_enterprise import (
    InboundMcpRateLimitStoreError,
    check_inbound_mcp_tool_rate_limit,
    log_inbound_mcp_event,
    resolve_inbound_mcp_request_id,
)
from functions_mcp_server_governance import evaluate_inbound_mcp_governance, get_inbound_mcp_governance_baseline
from functions_mcp_server_registry import (
    build_mcp_tool_descriptor,
    get_enabled_inbound_mcp_tools,
    get_inbound_mcp_tool,
    get_inbound_mcp_tool_registry,
)
from functions_mcp_server_config import build_inbound_mcp_public_base_url, get_inbound_mcp_runtime_config
from functions_mcp_server_tools import InboundMcpToolConflict, execute_inbound_mcp_tool
from functions_settings import get_rate_limit_message
from swagger_wrapper import swagger_route, get_auth_security


INBOUND_MCP_SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
)
INBOUND_MCP_DEFAULT_PROTOCOL_VERSION = INBOUND_MCP_SUPPORTED_PROTOCOL_VERSIONS[0]
INBOUND_MCP_PROTOCOL_HEADER = "MCP-Protocol-Version"


def _resource_identifier():
    if CLIENT_ID:
        return f"api://{CLIENT_ID}"
    return ""


def _authorization_server():
    authority = AUTHORITY.rstrip("/") if AUTHORITY else ""
    if authority.endswith("/v2.0"):
        return authority[:-5]
    return authority


def _public_base_url():
    return build_inbound_mcp_public_base_url(request)


def _qualified_scope(scope_name):
    normalized_scope = str(scope_name or "").strip()
    if not normalized_scope:
        return ""
    if "://" in normalized_scope or normalized_scope.startswith("https:"):
        return normalized_scope
    if CLIENT_ID:
        return f"api://{CLIENT_ID}/{normalized_scope}"
    return normalized_scope


def _entra_authorization_endpoint():
    authorization_server = _authorization_server()
    return f"{authorization_server}/oauth2/v2.0/authorize" if authorization_server else ""


def _entra_token_endpoint():
    authorization_server = _authorization_server()
    return f"{authorization_server}/oauth2/v2.0/token" if authorization_server else ""


def _entra_jwks_uri():
    authorization_server = _authorization_server()
    return f"{authorization_server}/discovery/v2.0/keys" if authorization_server else ""


def _get_auth_context():
    return getattr(g, "inbound_mcp_auth_context", None)


def _attach_inbound_mcp_headers(response, mcp_request_id):
    if mcp_request_id:
        response.headers["X-Correlation-ID"] = mcp_request_id
    return response


def _jsonrpc_response(request_id, result, status_code=200, mcp_request_id=""):
    response = jsonify({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    })
    response.status_code = status_code
    return _attach_inbound_mcp_headers(response, mcp_request_id)


def _jsonrpc_error(request_id, code, message, data=None, status_code=400, mcp_request_id=""):
    error_data = data
    if status_code != 200:
        if isinstance(error_data, dict):
            error_data = dict(error_data)
            error_data.setdefault("http_status", status_code)
        elif error_data is None:
            error_data = {"http_status": status_code}
        else:
            error_data = {
                "details": error_data,
                "http_status": status_code,
            }
    if mcp_request_id:
        if isinstance(error_data, dict):
            error_data = dict(error_data)
            error_data.setdefault("mcp_request_id", mcp_request_id)
        elif error_data is None:
            error_data = {"mcp_request_id": mcp_request_id}
    error = {
        "code": code,
        "message": message,
    }
    if error_data is not None:
        error["data"] = error_data
    response = jsonify({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error,
    })
    response.status_code = 200
    return _attach_inbound_mcp_headers(response, mcp_request_id)


def _json_text_content(value):
    return [{
        "type": "text",
        "text": json.dumps(value, ensure_ascii=True),
    }]


def _is_tool_result_error(tool_id, result):
    if str(tool_id or "").strip() != "execute_workflow":
        return False
    if not isinstance(result, dict):
        return False
    run = result.get("run")
    if not isinstance(run, dict):
        return False
    return run.get("success") is False


def build_inbound_mcp_protected_resource_metadata(public_base_url=None):
    """Build safe OAuth protected resource metadata for inbound MCP clients."""
    runtime_config = get_inbound_mcp_runtime_config()
    authorization_server = str(public_base_url or "").strip().rstrip("/")
    scopes_supported = []
    required_scope = str(runtime_config.get("inbound_mcp_required_scope") or "").strip()
    qualified_scope = _qualified_scope(required_scope)
    if qualified_scope:
        scopes_supported.append(qualified_scope)

    metadata = {
        "resource": _resource_identifier(),
        "authorization_servers": [authorization_server] if authorization_server else [],
        "scopes_supported": scopes_supported,
        "bearer_methods_supported": ["header"],
        "resource_documentation": "https://aka.ms/simplechat-documentation",
        "mcp_endpoint": runtime_config.get("inbound_mcp_resource_path", "/api/mcp"),
        "metadata_aliases": list(INBOUND_MCP_PRM_PATHS),
    }
    return metadata


def build_inbound_mcp_authorization_server_metadata(public_base_url=None):
    """Build OAuth authorization server metadata for MCP clients that expect RFC8414 discovery."""
    issuer = str(public_base_url or "").strip().rstrip("/")
    runtime_config = get_inbound_mcp_runtime_config()
    required_scope = str(runtime_config.get("inbound_mcp_required_scope") or "").strip()
    scopes_supported = [
        scope
        for scope in (
            "openid",
            "profile",
            "offline_access",
            _qualified_scope(required_scope),
        )
        if scope
    ]
    return {
        "issuer": issuer,
        "authorization_endpoint": _entra_authorization_endpoint(),
        "token_endpoint": _entra_token_endpoint(),
        "jwks_uri": _entra_jwks_uri(),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": scopes_supported,
        "resource": _resource_identifier(),
    }


def _requested_initialize_protocol_version(params):
    params = params if isinstance(params, dict) else {}
    return str(params.get("protocolVersion") or "").strip()


def _select_initialize_protocol_version(params):
    requested_protocol_version = _requested_initialize_protocol_version(params)
    if requested_protocol_version in INBOUND_MCP_SUPPORTED_PROTOCOL_VERSIONS:
        return requested_protocol_version
    return INBOUND_MCP_DEFAULT_PROTOCOL_VERSION


def _build_initialize_result(params=None):
    protocol_version = _select_initialize_protocol_version(params)
    return {
        "protocolVersion": protocol_version,
        "capabilities": {
            "tools": {
                "listChanged": False,
            },
        },
        "serverInfo": {
            "name": "simplechat-inbound-mcp",
            "title": "SimpleChat Inbound MCP",
            "version": VERSION,
        },
    }


def _duration_ms(started_at):
    return int((time.perf_counter() - started_at) * 1000)


def _log_initialize_request(auth_context, params, selected_protocol_version, mcp_request_id):
    params = params if isinstance(params, dict) else {}
    client_info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
    requested_protocol_version = _requested_initialize_protocol_version(params)
    log_event(
        "[INBOUND_MCP] Inbound MCP initialize negotiated.",
        extra={
            "mcp_request_id": mcp_request_id,
            "requested_protocol_version": requested_protocol_version,
            "selected_protocol_version": selected_protocol_version,
            "supported_protocol_versions": ",".join(INBOUND_MCP_SUPPORTED_PROTOCOL_VERSIONS),
            "protocol_version_defaulted": selected_protocol_version != requested_protocol_version,
            "client_name": str(client_info.get("name") or ""),
            "client_version": str(client_info.get("version") or ""),
            "accept_header": request.headers.get("Accept", ""),
            "mcp_protocol_header": request.headers.get(INBOUND_MCP_PROTOCOL_HEADER, ""),
            "caller_app_id": getattr(auth_context, "caller_app_id", ""),
            "tenant_id": getattr(auth_context, "tenant_id", ""),
        },
        level=logging.INFO,
        debug_only=True,
        category="InboundMCP",
    )


def _build_tools_list_result(auth_context):
    enabled_tools = get_enabled_inbound_mcp_tools(auth_context)
    return {
        "tools": [
            build_mcp_tool_descriptor(tool)
            for tool in enabled_tools
        ],
    }


def _call_tool(auth_context, request_id, params, mcp_request_id, runtime_config):
    tool_started_at = time.perf_counter()
    params = params if isinstance(params, dict) else {}
    tool_name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    if not tool_name:
        return _jsonrpc_error(
            request_id,
            -32602,
            "Tool name is required.",
            status_code=400,
            mcp_request_id=mcp_request_id,
        )

    tool = get_inbound_mcp_tool(tool_name)
    if not tool or not bool(tool.get("implemented", False)):
        log_inbound_mcp_event(
            "[InboundMCP] Inbound MCP tool call rejected because the tool is unavailable.",
            auth_context,
            mcp_request_id,
            level=logging.WARNING,
            tool_id=tool_name,
            error_type="tool_unavailable",
            duration_ms=_duration_ms(tool_started_at),
        )
        return _jsonrpc_error(
            request_id,
            -32601,
            "Inbound MCP tool is not available.",
            status_code=404,
            mcp_request_id=mcp_request_id,
        )

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
        log_inbound_mcp_event(
            "[InboundMCP] Inbound MCP tool call denied by governance.",
            auth_context,
            mcp_request_id,
            level=logging.WARNING,
            tool_id=tool.get("id", ""),
            error_type="governance_denied",
            error=decision.error,
            duration_ms=_duration_ms(tool_started_at),
        )
        return _jsonrpc_error(
            request_id,
            -32001,
            "Inbound MCP governance denied the tool call.",
            data=decision.to_dict(),
            status_code=403,
            mcp_request_id=mcp_request_id,
        )

    try:
        rate_limit = check_inbound_mcp_tool_rate_limit(auth_context, tool, runtime_config=runtime_config)
    except InboundMcpRateLimitStoreError as exc:
        log_inbound_mcp_event(
            "[InboundMCP] Inbound MCP tool call could not update the rate-limit counter.",
            auth_context,
            mcp_request_id,
            level=logging.ERROR,
            tool_id=tool.get("id", ""),
            error_type="rate_limit_store_error",
            error_type_detail=type(exc).__name__,
            duration_ms=_duration_ms(tool_started_at),
        )
        return _jsonrpc_error(
            request_id,
            -32050,
            "Inbound MCP rate-limit state is unavailable.",
            status_code=503,
            mcp_request_id=mcp_request_id,
        )
    if not rate_limit.allowed:
        log_inbound_mcp_event(
            "[InboundMCP] Inbound MCP tool call denied by rate limit.",
            auth_context,
            mcp_request_id,
            level=logging.WARNING,
            tool_id=tool.get("id", ""),
            error_type="rate_limited",
            duration_ms=_duration_ms(tool_started_at),
            rate_limit_category=rate_limit.category,
            rate_limit=rate_limit.limit,
            rate_limit_window_seconds=rate_limit.window_seconds,
            rate_limit_reset_after_seconds=rate_limit.reset_after_seconds,
        )
        return _jsonrpc_error(
            request_id,
            -32029,
            get_rate_limit_message(),
            data=rate_limit.to_public_dict(),
            status_code=429,
            mcp_request_id=mcp_request_id,
        )

    log_inbound_mcp_event(
        "[InboundMCP] Inbound MCP tool call started.",
        auth_context,
        mcp_request_id,
        level=logging.INFO,
        tool_id=tool.get("id", ""),
        audit_event=tool.get("audit_event", ""),
        rate_limit_category=rate_limit.category,
        rate_limit_remaining=rate_limit.remaining,
    )
    try:
        result = execute_inbound_mcp_tool(tool.get("id", ""), auth_context, arguments)
    except ValueError as exc:
        log_inbound_mcp_event(
            "[InboundMCP] Inbound MCP tool call failed validation.",
            auth_context,
            mcp_request_id,
            level=logging.WARNING,
            tool_id=tool.get("id", ""),
            error_type="invalid_params",
            duration_ms=_duration_ms(tool_started_at),
        )
        return _jsonrpc_error(
            request_id,
            -32602,
            "Inbound MCP tool parameters are invalid.",
            status_code=400,
            mcp_request_id=mcp_request_id,
        )
    except InboundMcpToolConflict as exc:
        log_inbound_mcp_event(
            "[InboundMCP] Inbound MCP tool call hit an execution conflict.",
            auth_context,
            mcp_request_id,
            level=logging.WARNING,
            tool_id=tool.get("id", ""),
            error_type="conflict",
            duration_ms=_duration_ms(tool_started_at),
        )
        return _jsonrpc_error(
            request_id,
            -32009,
            "Inbound MCP tool execution conflict.",
            status_code=409,
            mcp_request_id=mcp_request_id,
        )
    except PermissionError:
        log_inbound_mcp_event(
            "[InboundMCP] Inbound MCP tool call denied by object authorization.",
            auth_context,
            mcp_request_id,
            level=logging.WARNING,
            tool_id=tool.get("id", ""),
            error_type="object_authorization_denied",
            duration_ms=_duration_ms(tool_started_at),
        )
        return _jsonrpc_error(
            request_id,
            -32003,
            "Inbound MCP tool access denied.",
            status_code=403,
            mcp_request_id=mcp_request_id,
        )
    except LookupError as exc:
        log_inbound_mcp_event(
            "[InboundMCP] Inbound MCP tool call target was not found.",
            auth_context,
            mcp_request_id,
            level=logging.WARNING,
            tool_id=tool.get("id", ""),
            error_type="not_found",
            duration_ms=_duration_ms(tool_started_at),
        )
        return _jsonrpc_error(
            request_id,
            -32004,
            "Inbound MCP resource not found.",
            status_code=404,
            mcp_request_id=mcp_request_id,
        )
    is_error_result = _is_tool_result_error(tool.get("id", ""), result)
    log_inbound_mcp_event(
        "[InboundMCP] Inbound MCP tool call completed.",
        auth_context,
        mcp_request_id,
        level=logging.INFO,
        tool_id=tool.get("id", ""),
        audit_event=tool.get("audit_event", ""),
        duration_ms=_duration_ms(tool_started_at),
        result_status="tool_error" if is_error_result else "success",
        is_error_result=is_error_result,
        rate_limit_category=rate_limit.category,
        rate_limit_remaining=rate_limit.remaining,
    )
    return _jsonrpc_response(request_id, {
        "content": _json_text_content(result),
        "structuredContent": result,
        "isError": is_error_result,
    }, mcp_request_id=mcp_request_id)


def register_route_inbound_mcp(bp):
    @bp.route("/.well-known/oauth-protected-resource", methods=["GET"], strict_slashes=False)
    @bp.route("/.well-known/oauth-protected-resource/api/mcp", methods=["GET"])
    @bp.route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])
    @swagger_route(security=get_auth_security())
    def inbound_mcp_protected_resource_metadata():
        """Return safe OAuth Protected Resource Metadata for inbound MCP clients."""
        return jsonify(build_inbound_mcp_protected_resource_metadata(_public_base_url())), 200

    @bp.route("/.well-known/oauth-authorization-server", methods=["GET"])
    @swagger_route(security=get_auth_security())
    def inbound_mcp_authorization_server_metadata():
        """Return OAuth Authorization Server Metadata for clients that require RFC8414 discovery."""
        return jsonify(build_inbound_mcp_authorization_server_metadata(_public_base_url())), 200

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

    @bp.route("/api/mcp", methods=["GET"])
    @swagger_route(security=get_auth_security())
    def inbound_mcp_sse_stream_not_supported():
        """Return the streamable HTTP GET contract when SSE streams are not enabled."""
        return jsonify({
            "error": "mcp_sse_stream_not_supported",
            "message": "Inbound MCP does not offer a server-initiated SSE stream; use POST /api/mcp.",
        }), 405, {"Allow": "POST"}

    @bp.route("/api/mcp", methods=["POST"])
    @swagger_route(security=get_auth_security())
    def inbound_mcp_endpoint():
        """Handle streamable HTTP JSON-RPC requests for governed inbound MCP tools."""
        request_started_at = time.perf_counter()
        auth_context = _get_auth_context()
        runtime_config = get_inbound_mcp_runtime_config()
        mcp_request_id = resolve_inbound_mcp_request_id(auth_context, request)
        max_request_bytes = int(runtime_config.get("inbound_mcp_max_request_bytes") or 65536)
        content_length = int(request.content_length or 0)
        raw_request_body = b""
        if content_length and content_length <= max_request_bytes:
            raw_request_body = request.get_data(cache=True)
            content_length = len(raw_request_body or b"")
        if content_length and content_length > max_request_bytes:
            log_inbound_mcp_event(
                "[InboundMCP] Inbound MCP request rejected because the payload is too large.",
                auth_context,
                mcp_request_id,
                level=logging.WARNING,
                http_method=request.method,
                path=request.path,
                content_length=content_length,
                max_request_bytes=max_request_bytes,
                error_type="payload_too_large",
                duration_ms=_duration_ms(request_started_at),
            )
            return _jsonrpc_error(
                None,
                -32013,
                "Inbound MCP request payload is too large.",
                data={
                    "content_length": content_length,
                    "max_request_bytes": max_request_bytes,
                },
                status_code=413,
                mcp_request_id=mcp_request_id,
            )
        if not raw_request_body:
            raw_request_body = request.get_data(cache=True)
            content_length = len(raw_request_body or b"")
            if content_length > max_request_bytes:
                log_inbound_mcp_event(
                    "[InboundMCP] Inbound MCP request rejected because the payload is too large.",
                    auth_context,
                    mcp_request_id,
                    level=logging.WARNING,
                    http_method=request.method,
                    path=request.path,
                    content_length=content_length,
                    max_request_bytes=max_request_bytes,
                    error_type="payload_too_large",
                    duration_ms=_duration_ms(request_started_at),
                )
                return _jsonrpc_error(
                    None,
                    -32013,
                    "Inbound MCP request payload is too large.",
                    data={
                        "content_length": content_length,
                        "max_request_bytes": max_request_bytes,
                    },
                    status_code=413,
                    mcp_request_id=mcp_request_id,
                )

        log_inbound_mcp_event(
            "[InboundMCP] Inbound MCP request started.",
            auth_context,
            mcp_request_id,
            level=logging.INFO,
            http_method=request.method,
            path=request.path,
            content_length=content_length,
            max_request_bytes=max_request_bytes,
        )
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            log_inbound_mcp_event(
                "[InboundMCP] Inbound MCP request rejected because the payload is not a JSON-RPC object.",
                auth_context,
                mcp_request_id,
                level=logging.WARNING,
                error_type="invalid_jsonrpc_payload",
                duration_ms=_duration_ms(request_started_at),
            )
            response = jsonify({
                "error": "invalid_mcp_request",
                "message": "Inbound MCP requests must be JSON-RPC objects.",
            })
            return _attach_inbound_mcp_headers(response, mcp_request_id), 400

        request_id = payload.get("id")
        method = str(payload.get("method") or "").strip()
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

        if method == "notifications/initialized" and request_id is None:
            log_inbound_mcp_event(
                "[InboundMCP] Inbound MCP notification accepted.",
                auth_context,
                mcp_request_id,
                level=logging.INFO,
                mcp_method=method,
                duration_ms=_duration_ms(request_started_at),
                result_status="accepted",
                jsonrpc_id_present=False,
            )
            response = Response("", status=202)
            return _attach_inbound_mcp_headers(response, mcp_request_id)

        if method == "initialize":
            initialize_result = _build_initialize_result(params)
            _log_initialize_request(auth_context, params, initialize_result["protocolVersion"], mcp_request_id)
            log_inbound_mcp_event(
                "[InboundMCP] Inbound MCP request completed.",
                auth_context,
                mcp_request_id,
                level=logging.INFO,
                mcp_method=method,
                duration_ms=_duration_ms(request_started_at),
                result_status="success",
                jsonrpc_id_present=request_id is not None,
            )
            return _jsonrpc_response(request_id, initialize_result, mcp_request_id=mcp_request_id)

        if method == "tools/list":
            tools_list_result = _build_tools_list_result(auth_context)
            log_inbound_mcp_event(
                "[InboundMCP] Inbound MCP request completed.",
                auth_context,
                mcp_request_id,
                level=logging.INFO,
                mcp_method=method,
                duration_ms=_duration_ms(request_started_at),
                result_status="success",
                jsonrpc_id_present=request_id is not None,
                enabled_tools=len(tools_list_result.get("tools") or []),
            )
            return _jsonrpc_response(request_id, tools_list_result, mcp_request_id=mcp_request_id)

        if method == "tools/call":
            return _call_tool(auth_context, request_id, params, mcp_request_id, runtime_config)

        log_inbound_mcp_event(
            "[InboundMCP] Unsupported inbound MCP method.",
            auth_context,
            mcp_request_id,
            level=logging.INFO,
            http_method=request.method,
            path=request.path,
            mcp_method=method,
            planned_tools=len(get_inbound_mcp_tool_registry()),
            error_type="unsupported_method",
            duration_ms=_duration_ms(request_started_at),
        )
        return _jsonrpc_error(
            request_id,
            -32601,
            "Unsupported inbound MCP method.",
            status_code=404,
            mcp_request_id=mcp_request_id,
        )
