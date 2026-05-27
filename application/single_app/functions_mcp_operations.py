# functions_mcp_operations.py
"""Helpers for Model Context Protocol action configuration."""

import re

MCP_PLUGIN_TYPE = "mcp"
MCP_DEFAULT_TRANSPORT = "streamable_http"
MCP_DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
MCP_DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
MCP_DEFAULT_SSE_READ_TIMEOUT_SECONDS = 300
MCP_STDIO_ENDPOINT = "stdio://local"
MCP_SUPPORTED_TRANSPORTS = {
    "streamable_http",
    "sse",
    "websocket",
    "stdio",
}
MCP_REMOTE_TRANSPORTS = {
    "streamable_http",
    "sse",
    "websocket",
}
MCP_SUPPORTED_AUTH_METHODS = {
    "none",
    "bearer",
    "api_key",
    "basic",
    "identity",
}
MCP_MAX_TIMEOUT_SECONDS = 300
MCP_MAX_TOOL_COUNT = 100
MCP_MAX_TOOL_RESULT_TEXT_LENGTH = 120000


def normalize_mcp_transport(value):
    """Normalize supported MCP transport aliases."""
    normalized_value = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "http": "streamable_http",
        "streamablehttp": "streamable_http",
        "streamable_http": "streamable_http",
        "server_sent_events": "sse",
        "eventsource": "sse",
        "ws": "websocket",
        "wss": "websocket",
        "websocket": "websocket",
        "stdio": "stdio",
    }
    return aliases.get(normalized_value, MCP_DEFAULT_TRANSPORT)


def normalize_mcp_auth_method(value):
    """Normalize MCP auth method aliases stored in additionalFields."""
    normalized_value = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "": "none",
        "noauth": "none",
        "no_auth": "none",
        "none": "none",
        "bearer": "bearer",
        "bearer_token": "bearer",
        "token": "bearer",
        "api_key": "api_key",
        "apikey": "api_key",
        "key": "api_key",
        "basic": "basic",
        "username_password": "basic",
        "identity": "identity",
        "managed_identity": "identity",
    }
    return aliases.get(normalized_value, "none")


def coerce_mcp_timeout(value, default_value):
    """Coerce a timeout value into the supported MCP timeout range."""
    try:
        timeout_value = int(value)
    except (TypeError, ValueError):
        timeout_value = default_value

    return min(max(timeout_value, 1), MCP_MAX_TIMEOUT_SECONDS)


def normalize_mcp_string_list(value, max_items=MCP_MAX_TOOL_COUNT):
    """Return a clean list of non-empty strings."""
    if isinstance(value, str):
        raw_values = value.replace(",", "\n").splitlines()
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []

    normalized_values = []
    seen_values = set()
    for raw_value in raw_values:
        normalized_value = str(raw_value or "").strip()
        if not normalized_value or normalized_value in seen_values:
            continue
        normalized_values.append(normalized_value)
        seen_values.add(normalized_value)
        if len(normalized_values) >= max_items:
            break
    return normalized_values


def normalize_mcp_function_name(value, fallback_prefix="tool"):
    """Normalize an MCP tool name into a Semantic Kernel-safe function name."""
    normalized_value = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip())
    normalized_value = re.sub(r"_+", "_", normalized_value).strip("_")
    normalized_value = normalized_value or fallback_prefix
    if normalized_value[0].isdigit():
        normalized_value = f"{fallback_prefix}_{normalized_value}"
    return normalized_value[:120]


def normalize_mcp_tool_metadata(value):
    """Return normalized MCP tool metadata entries."""
    if not isinstance(value, list):
        return []

    normalized_tools = []
    used_function_names = set()
    for tool in value[:MCP_MAX_TOOL_COUNT]:
        if not isinstance(tool, dict):
            continue

        original_name = str(tool.get("original_name") or tool.get("name") or "").strip()
        if not original_name:
            continue

        preferred_function_name = tool.get("function_name") or original_name
        function_name = normalize_mcp_function_name(preferred_function_name)
        base_function_name = function_name
        suffix = 2
        while function_name in used_function_names:
            function_name = f"{base_function_name}_{suffix}"
            suffix += 1
        used_function_names.add(function_name)

        normalized_tools.append({
            "original_name": original_name,
            "function_name": function_name,
            "description": str(tool.get("description") or "").strip(),
            "input_schema": tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {},
        })
    return normalized_tools


def normalize_mcp_additional_fields(additional_fields):
    """Normalize MCP additionalFields while preserving unknown future fields."""
    normalized_fields = dict(additional_fields) if isinstance(additional_fields, dict) else {}
    normalized_fields["transport"] = normalize_mcp_transport(normalized_fields.get("transport"))
    normalized_fields["auth_method"] = normalize_mcp_auth_method(normalized_fields.get("auth_method"))
    normalized_fields["load_tools"] = bool(normalized_fields.get("load_tools", True))
    normalized_fields["load_prompts"] = bool(normalized_fields.get("load_prompts", False))
    normalized_fields["request_timeout"] = coerce_mcp_timeout(
        normalized_fields.get("request_timeout"),
        MCP_DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    normalized_fields["connect_timeout"] = coerce_mcp_timeout(
        normalized_fields.get("connect_timeout"),
        MCP_DEFAULT_CONNECT_TIMEOUT_SECONDS,
    )
    normalized_fields["sse_read_timeout"] = coerce_mcp_timeout(
        normalized_fields.get("sse_read_timeout"),
        MCP_DEFAULT_SSE_READ_TIMEOUT_SECONDS,
    )
    normalized_fields["allowed_tool_names"] = normalize_mcp_string_list(
        normalized_fields.get("allowed_tool_names")
    )
    normalized_fields["mcp_tools"] = normalize_mcp_tool_metadata(normalized_fields.get("mcp_tools"))

    if not isinstance(normalized_fields.get("args"), list):
        normalized_fields["args"] = normalize_mcp_string_list(normalized_fields.get("args"), max_items=50)
    if not isinstance(normalized_fields.get("env"), dict):
        normalized_fields["env"] = {}

    return normalized_fields