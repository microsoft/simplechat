# functions_mcp_operations.py
"""Helpers for Model Context Protocol action configuration."""

import re
from urllib.parse import urlparse

from functions_mcp_presets import (
    MCP_DEFAULT_SERVER_PRESET_ID,
    mcp_server_preset_exists,
    normalize_mcp_preset_id,
)


MCP_PLUGIN_TYPE = "mcp"
MCP_DEFAULT_SERVER_PROFILE = MCP_DEFAULT_SERVER_PRESET_ID
MCP_DEFAULT_TRANSPORT = "streamable_http"
MCP_DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
MCP_DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
MCP_DEFAULT_SSE_READ_TIMEOUT_SECONDS = 300
MCP_DEFAULT_RETRY_COUNT = 0
MCP_DEFAULT_RETRY_BACKOFF_SECONDS = 1
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
MCP_MAX_RETRY_COUNT = 3
MCP_MAX_RETRY_BACKOFF_SECONDS = 30
MCP_MAX_TOOL_COUNT = 100
MCP_MAX_TOOL_RESULT_TEXT_LENGTH = 120000
MCP_MAX_CUSTOM_HEADER_COUNT = 20
MCP_MAX_HEADER_NAME_LENGTH = 128
MCP_MAX_HEADER_VALUE_LENGTH = 4096
MCP_CUSTOM_HEADERS_FIELD = "custom_headers"
MCP_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
MCP_RESERVED_CUSTOM_HEADERS = {
    "connection",
    "content-length",
    "cookie",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "set-cookie",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
MCP_REDACTED_VALUE = "***REDACTED***"
MCP_ERROR_DETAIL_MAX_LENGTH = 500
MCP_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[-_]?key|access[-_]?token|authorization|client[-_]?secret|password|secret|token)=([^&\s,;]+)"
)
MCP_AUTHORIZATION_VALUE_RE = re.compile(r"(?i)\b(Bearer|Basic|Splunk)\s+[A-Za-z0-9._~+/=-]+")


class McpRuntimeError(RuntimeError):
    """MCP runtime error with a safe public category and message."""

    def __init__(self, message, category="unknown", operation="mcp", detail=None, retryable=False):
        super().__init__(message)
        self.category = category
        self.operation = operation
        self.detail = detail or message
        self.retryable = retryable


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


def normalize_mcp_server_profile(value):
    """Normalize a server preset/profile value using the validated preset catalog."""
    normalized_value = normalize_mcp_preset_id(value)
    if mcp_server_preset_exists(normalized_value):
        return normalized_value
    return MCP_DEFAULT_SERVER_PROFILE


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


def coerce_mcp_integer(value, default_value, minimum_value, maximum_value):
    """Coerce an integer into a supported range."""
    try:
        integer_value = int(value)
    except (TypeError, ValueError):
        integer_value = default_value

    return min(max(integer_value, minimum_value), maximum_value)


def coerce_mcp_timeout(value, default_value):
    """Coerce a timeout value into the supported MCP timeout range."""
    return coerce_mcp_integer(value, default_value, 1, MCP_MAX_TIMEOUT_SECONDS)


def coerce_mcp_retry_count(value):
    """Coerce an MCP retry count into the supported retry range."""
    return coerce_mcp_integer(value, MCP_DEFAULT_RETRY_COUNT, 0, MCP_MAX_RETRY_COUNT)


def coerce_mcp_retry_backoff(value):
    """Coerce retry backoff into the supported MCP backoff range."""
    return coerce_mcp_integer(value, MCP_DEFAULT_RETRY_BACKOFF_SECONDS, 1, MCP_MAX_RETRY_BACKOFF_SECONDS)


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


def normalize_mcp_custom_headers(value):
    """Return a case-deduplicated custom header mapping with string names and values."""
    if isinstance(value, dict):
        raw_items = value.items()
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            if not isinstance(item, dict):
                continue
            header_name = item.get("name") or item.get("header") or item.get("key")
            header_value = item.get("value")
            raw_items.append((header_name, header_value))
    else:
        return {}

    normalized_headers = {}
    seen_header_names = {}
    for raw_name, raw_value in raw_items:
        header_name = str(raw_name or "").strip()
        if not header_name:
            continue

        header_value = "" if raw_value is None else str(raw_value).strip()
        if not header_value:
            continue

        normalized_name = header_name.lower()
        previous_name = seen_header_names.get(normalized_name)
        if previous_name:
            normalized_headers.pop(previous_name, None)
        normalized_headers[header_name] = header_value
        seen_header_names[normalized_name] = header_name

    return normalized_headers


def is_valid_mcp_header_name(header_name):
    """Return whether a custom MCP header name is syntactically safe."""
    normalized_name = str(header_name or "").strip()
    if not normalized_name or len(normalized_name) > MCP_MAX_HEADER_NAME_LENGTH:
        return False
    if normalized_name.lower() in MCP_RESERVED_CUSTOM_HEADERS:
        return False
    return MCP_HEADER_NAME_PATTERN.fullmatch(normalized_name) is not None


def get_mcp_custom_header_validation_errors(headers):
    """Return validation errors for normalized custom MCP headers."""
    if not isinstance(headers, dict):
        return ["MCP custom_headers must be an object when provided"]

    errors = []
    if len(headers) > MCP_MAX_CUSTOM_HEADER_COUNT:
        errors.append(f"MCP custom_headers supports at most {MCP_MAX_CUSTOM_HEADER_COUNT} headers")

    for header_name, header_value in headers.items():
        if not is_valid_mcp_header_name(header_name):
            errors.append(f"MCP custom header '{header_name}' has an invalid or reserved header name")
        value_text = str(header_value or "")
        if "\r" in value_text or "\n" in value_text:
            errors.append(f"MCP custom header '{header_name}' must not contain line breaks")
        if len(value_text) > MCP_MAX_HEADER_VALUE_LENGTH:
            errors.append(
                f"MCP custom header '{header_name}' must be {MCP_MAX_HEADER_VALUE_LENGTH} characters or fewer"
            )

    return errors


def validate_mcp_endpoint_for_transport(endpoint, transport):
    """Return validation errors for an MCP endpoint and transport combination."""
    normalized_transport = normalize_mcp_transport(transport)
    if normalized_transport not in MCP_REMOTE_TRANSPORTS:
        return []

    endpoint_text = str(endpoint or "").strip()
    if not endpoint_text:
        return ["MCP plugin requires an endpoint for remote transports"]
    if "\r" in endpoint_text or "\n" in endpoint_text:
        return ["MCP endpoint must not contain line breaks"]

    parsed_endpoint = urlparse(endpoint_text)
    allowed_schemes = {"ws", "wss"} if normalized_transport == "websocket" else {"http", "https"}
    if parsed_endpoint.scheme not in allowed_schemes or not parsed_endpoint.netloc:
        return [f"MCP {normalized_transport} transport requires a valid {'/'.join(sorted(allowed_schemes))} endpoint"]
    if parsed_endpoint.username or parsed_endpoint.password:
        return ["MCP endpoint must not include embedded credentials"]
    return []


def redact_mcp_error_detail(value):
    """Return MCP diagnostic text with credential-looking values removed."""
    detail = str(value or "")
    detail = MCP_SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}={MCP_REDACTED_VALUE}", detail)
    detail = MCP_AUTHORIZATION_VALUE_RE.sub(lambda match: f"{match.group(1)} {MCP_REDACTED_VALUE}", detail)
    if len(detail) > MCP_ERROR_DETAIL_MAX_LENGTH:
        return f"{detail[:MCP_ERROR_DETAIL_MAX_LENGTH]}... [truncated]"
    return detail


def classify_mcp_exception(exc, operation="mcp"):
    """Classify MCP exceptions into safe, actionable categories."""
    detail = redact_mcp_error_detail(str(exc))
    detail_lower = detail.lower()
    operation_text = str(operation or "mcp").strip() or "mcp"

    category = "unknown"
    message = "MCP operation failed. Check the server endpoint, transport, authentication, and server logs."
    retryable = True

    if isinstance(exc, TimeoutError) or "timeout" in detail_lower or "timed out" in detail_lower:
        category = "timeout"
        message = "MCP operation timed out. Check timeout settings and server responsiveness."
    elif any(term in detail_lower for term in ("certificate", "ssl", "tls", "handshake failure")):
        category = "tls"
        message = "MCP TLS negotiation failed. Check the server certificate and endpoint scheme."
        retryable = False
    elif any(term in detail_lower for term in ("name resolution", "getaddrinfo", "nodename", "dns")):
        category = "dns_resolution"
        message = "MCP server name could not be resolved. Check the endpoint host name."
    elif any(term in detail_lower for term in ("401", "403", "unauthorized", "forbidden", "invalid token")):
        category = "authentication"
        message = "MCP server rejected authentication. Check credentials, headers, and allowed tools."
        retryable = False
    elif any(term in detail_lower for term in ("connection refused", "connect call failed", "connection reset", "network is unreachable")):
        category = "connection"
        message = "MCP server connection failed. Check network access, firewall rules, and transport."
    elif any(term in detail_lower for term in ("initialize", "initialise", "session", "did not create a session")):
        category = "initialization"
        message = "MCP server initialization failed. Check server compatibility and transport settings."
    elif operation_text == "tool_discovery" or "list_tools" in detail_lower:
        category = "discovery"
        message = "MCP tool discovery failed. Check that the server supports tool listing."
    elif operation_text == "tool_call" or "call_tool" in detail_lower:
        category = "tool_execution"
        message = "MCP tool execution failed. Check the tool name, arguments, and server logs."

    return {
        "category": category,
        "message": message,
        "detail": detail,
        "operation": operation_text,
        "retryable": retryable,
    }


def get_mcp_error_http_status(category):
    """Map an MCP error category to an HTTP status suitable for discovery responses."""
    if category == "authentication":
        return 401
    if category == "timeout":
        return 504
    if category in {"connection", "dns_resolution", "tls", "initialization", "discovery", "tool_execution"}:
        return 502
    return 500


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
    normalized_fields["server_profile"] = normalize_mcp_server_profile(normalized_fields.get("server_profile"))
    normalized_fields["transport"] = normalize_mcp_transport(normalized_fields.get("transport"))
    normalized_fields["auth_method"] = normalize_mcp_auth_method(normalized_fields.get("auth_method"))
    normalized_fields["api_key_header_name"] = str(normalized_fields.get("api_key_header_name") or "X-API-Key").strip() or "X-API-Key"
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
    normalized_fields["retry_count"] = coerce_mcp_retry_count(normalized_fields.get("retry_count"))
    normalized_fields["retry_backoff_seconds"] = coerce_mcp_retry_backoff(
        normalized_fields.get("retry_backoff_seconds")
    )
    normalized_fields[MCP_CUSTOM_HEADERS_FIELD] = normalize_mcp_custom_headers(
        normalized_fields.get(MCP_CUSTOM_HEADERS_FIELD)
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