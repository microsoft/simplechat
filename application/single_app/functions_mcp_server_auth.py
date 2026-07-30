# functions_mcp_server_auth.py

import logging
import re
from dataclasses import asdict, dataclass
from functools import wraps

from flask import g, jsonify, request

from functions_appinsights import log_event
from functions_authentication import validate_bearer_token
from functions_mcp_server_config import build_inbound_mcp_public_base_url, get_inbound_mcp_runtime_config
from functions_mcp_server_enterprise import normalize_inbound_mcp_correlation_id


AUTH_CATEGORY = "InboundMCP"


@dataclass(frozen=True)
class InboundMcpAuthContext:
    tenant_id: str
    audience: str
    issuer: str
    caller_app_id: str
    source_id: str
    source_signal_type: str
    source_trust_level: str
    token_type: str
    roles: tuple[str, ...]
    scopes: tuple[str, ...]
    delegated_user_id: str
    delegated_username: str
    correlation_id: str

    def to_public_dict(self):
        """Return non-secret context metadata for diagnostics and tests."""
        return asdict(self)


class InboundMcpAuthError(Exception):
    """Raised when an inbound MCP request fails auth or source checks."""

    def __init__(self, status_code, public_error, public_message):
        super().__init__(public_error)
        self.status_code = status_code
        self.public_error = public_error
        self.public_message = public_message


def _normalize_claim_values(value):
    items = []
    if isinstance(value, str):
        items = [item for item in re.split(r"[\s,]+", value.strip()) if item]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
    elif value is not None:
        item = str(value).strip()
        if item:
            items = [item]
    return tuple(items)


def _extract_bearer_token(flask_request):
    auth_header = flask_request.headers.get("Authorization", "")
    if not auth_header:
        raise InboundMcpAuthError(
            401,
            "bearer_token_required",
            "A bearer token is required for inbound MCP requests.",
        )
    if not auth_header.startswith("Bearer "):
        raise InboundMcpAuthError(
            401,
            "invalid_token",
            "The Authorization header must use the Bearer scheme.",
        )

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise InboundMcpAuthError(
            401,
            "bearer_token_required",
            "A bearer token is required for inbound MCP requests.",
        )
    return token


def _resolve_source_signal(flask_request, caller_app_id, runtime_config):
    source_header_name = str(runtime_config.get("inbound_mcp_source_header") or "").strip()
    if source_header_name:
        source_header_value = flask_request.headers.get(source_header_name, "").strip()
        if source_header_value:
            return source_header_value, "configured_header", "advisory_header"

    origin = flask_request.headers.get("Origin", "").strip()
    if origin:
        return origin, "origin", "origin"

    referer = flask_request.headers.get("Referer", "").strip()
    if referer:
        return referer, "referer", "origin"

    if caller_app_id:
        return caller_app_id, "token_client", "token_client"

    return "unknown", "unknown", "unknown"


def _source_is_allowed(source_id, runtime_config):
    allowed_sources = tuple(runtime_config.get("inbound_mcp_allowed_source_ids") or ("*",))
    return "*" in allowed_sources or source_id in allowed_sources


def _tenant_is_allowed(tenant_id, runtime_config):
    allowed_tenants = tuple(runtime_config.get("inbound_mcp_allowed_tenant_ids") or ())
    return not allowed_tenants or tenant_id in allowed_tenants


def _client_is_allowed(caller_app_id, runtime_config):
    allowed_clients = tuple(runtime_config.get("inbound_mcp_allowed_client_app_ids") or ())
    return bool(caller_app_id and allowed_clients and caller_app_id.lower() in allowed_clients)


def _runtime_list(runtime_config, key):
    values = runtime_config.get(key)
    items = []
    if isinstance(values, (list, tuple, set)):
        items = [str(value or "").strip() for value in values if str(value or "").strip()]
    else:
        value = str(values or "").strip()
        if value:
            items = [value]
    return tuple(items)


def _has_required_delegated_scope(scopes, runtime_config):
    required_scope = str(runtime_config.get("inbound_mcp_required_scope") or "").strip()
    return bool(required_scope and required_scope in scopes)


def _has_required_delegated_user_role(roles, runtime_config):
    required_roles = _runtime_list(runtime_config, "inbound_mcp_required_user_roles")
    return bool(required_roles and set(required_roles).intersection(set(roles or ())))


def _has_required_app_role(roles, runtime_config):
    required_roles = _runtime_list(runtime_config, "inbound_mcp_required_app_roles")
    return bool(required_roles and set(required_roles).intersection(set(roles or ())))


def _correlation_id(flask_request):
    raw_value = (
        flask_request.headers.get("x-ms-client-request-id")
        or flask_request.headers.get("x-correlation-id")
        or flask_request.headers.get("x-request-id")
        or ""
    )
    return normalize_inbound_mcp_correlation_id(raw_value)


def validate_inbound_mcp_request(flask_request, token_validator=None):
    """Validate bearer auth and source policy for an inbound MCP request."""
    runtime_config = get_inbound_mcp_runtime_config()
    token_validator = token_validator or validate_bearer_token
    token = _extract_bearer_token(flask_request)
    is_valid, token_claims = token_validator(token)
    if not is_valid or not isinstance(token_claims, dict):
        log_event(
            "[InboundMCP] Inbound MCP bearer token validation failed.",
            extra={"reason": str(token_claims)},
            level=logging.WARNING,
            debug_only=True,
            category=AUTH_CATEGORY,
        )
        raise InboundMcpAuthError(401, "invalid_token", "The bearer token is invalid.")

    tenant_id = str(token_claims.get("tid") or "").strip()
    if not _tenant_is_allowed(tenant_id, runtime_config):
        raise InboundMcpAuthError(401, "invalid_token", "The bearer token is invalid.")

    caller_app_id = str(token_claims.get("azp") or token_claims.get("appid") or "").strip().lower()
    if not _client_is_allowed(caller_app_id, runtime_config):
        raise InboundMcpAuthError(403, "mcp_client_not_allowed", "The MCP client is not allowed.")

    delegated_user_id = str(token_claims.get("oid") or token_claims.get("sub") or "").strip()
    delegated_username = str(
        token_claims.get("preferred_username")
        or token_claims.get("upn")
        or token_claims.get("name")
        or ""
    ).strip()
    roles = _normalize_claim_values(token_claims.get("roles"))
    scopes = _normalize_claim_values(token_claims.get("scp"))
    token_type = "delegated" if delegated_user_id and scopes else "app_only"

    if token_type == "delegated":
        if not _has_required_delegated_scope(scopes, runtime_config):
            raise InboundMcpAuthError(
                403,
                "insufficient_mcp_permissions",
                "The bearer token does not include the required delegated MCP scope.",
            )
        if not _has_required_delegated_user_role(roles, runtime_config):
            raise InboundMcpAuthError(
                403,
                "insufficient_mcp_permissions",
                "The bearer token does not include the required delegated MCP user role.",
            )
    elif not _has_required_app_role(roles, runtime_config):
        raise InboundMcpAuthError(
            403,
            "insufficient_mcp_permissions",
            "The bearer token does not include the required app-only MCP role.",
        )

    source_id, source_signal_type, source_trust_level = _resolve_source_signal(
        flask_request,
        caller_app_id,
        runtime_config,
    )
    if not _source_is_allowed(source_id, runtime_config):
        raise InboundMcpAuthError(
            403,
            "mcp_source_not_allowed",
            "The MCP source is not allowed.",
        )

    return InboundMcpAuthContext(
        tenant_id=tenant_id,
        audience=str(token_claims.get("aud") or "").strip(),
        issuer=str(token_claims.get("iss") or "").strip(),
        caller_app_id=caller_app_id,
        source_id=source_id,
        source_signal_type=source_signal_type,
        source_trust_level=source_trust_level,
        token_type=token_type,
        roles=roles,
        scopes=scopes,
        delegated_user_id=delegated_user_id,
        delegated_username=delegated_username,
        correlation_id=_correlation_id(flask_request),
    )


def is_inbound_mcp_metadata_request(flask_request):
    runtime_config = get_inbound_mcp_runtime_config()
    metadata_paths = {
        runtime_config.get("inbound_mcp_authorization_server_metadata_path"),
    }
    metadata_paths.update(runtime_config.get("inbound_mcp_prm_paths") or ())
    return (
        flask_request.method == "GET"
        and flask_request.path in metadata_paths
    )


def _build_resource_metadata_url(flask_request):
    runtime_config = get_inbound_mcp_runtime_config()
    metadata_path = str(runtime_config.get("inbound_mcp_prm_path") or "").strip()
    if not metadata_path.startswith("/"):
        metadata_path = "/.well-known/oauth-protected-resource/api/mcp"
    if not flask_request:
        return metadata_path
    base_url = build_inbound_mcp_public_base_url(flask_request)
    if not base_url:
        return metadata_path
    return f"{base_url}{metadata_path}".replace("\r", "").replace("\n", "")


def build_inbound_mcp_auth_error_response(auth_error, flask_request=None):
    response = jsonify({
        "error": auth_error.public_error,
        "message": auth_error.public_message,
    })
    correlation_id = _correlation_id(flask_request) if flask_request else ""
    if correlation_id:
        response.headers["X-Correlation-ID"] = correlation_id
    if auth_error.status_code == 401:
        metadata_url = _build_resource_metadata_url(flask_request)
        response.headers["WWW-Authenticate"] = f'Bearer resource_metadata="{metadata_url}"'
    return response, auth_error.status_code


def inbound_mcp_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            g.inbound_mcp_auth_context = validate_inbound_mcp_request(request)
        except InboundMcpAuthError as auth_error:
            return build_inbound_mcp_auth_error_response(auth_error, request)
        return f(*args, **kwargs)
    return decorated_function


def inbound_mcp_required_blueprint():
    """Return a Blueprint guard for inbound MCP bearer-token requests."""
    def guard():
        if request.method == "OPTIONS":
            return None
        if is_inbound_mcp_metadata_request(request):
            return None
        runtime_config = get_inbound_mcp_runtime_config()
        if not runtime_config.get("enable_inbound_mcp_server"):
            log_event(
                "[InboundMCP] Inbound MCP request rejected because the server is disabled.",
                extra={
                    "path": request.path,
                    "method": request.method,
                    "mcp_request_id": _correlation_id(request),
                    "error_type": "server_disabled",
                },
                level=logging.INFO,
                category=AUTH_CATEGORY,
            )
            response = jsonify({
                "error": "inbound_mcp_disabled",
                "message": "Inbound MCP server is disabled.",
            })
            correlation_id = _correlation_id(request)
            if correlation_id:
                response.headers["X-Correlation-ID"] = correlation_id
            return response, 404

        try:
            g.inbound_mcp_auth_context = validate_inbound_mcp_request(request)
        except InboundMcpAuthError as auth_error:
            log_event(
                "[InboundMCP] Inbound MCP request rejected by auth guard.",
                extra={
                    "path": request.path,
                    "method": request.method,
                    "mcp_request_id": _correlation_id(request),
                    "error_type": auth_error.public_error,
                    "status_code": auth_error.status_code,
                },
                level=logging.WARNING,
                category=AUTH_CATEGORY,
            )
            return build_inbound_mcp_auth_error_response(auth_error, request)

        return None

    guard._simplechat_auth_policy = ("inbound_mcp_required",)
    return guard
