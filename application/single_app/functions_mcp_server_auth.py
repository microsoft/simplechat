# functions_mcp_server_auth.py

import logging
import re
from dataclasses import asdict, dataclass
from functools import wraps

from flask import g, jsonify, request

from config import (
    ENABLE_INBOUND_MCP_SERVER,
    INBOUND_MCP_ALLOWED_CLIENT_APP_IDS,
    INBOUND_MCP_ALLOWED_SOURCE_IDS,
    INBOUND_MCP_ALLOWED_TENANT_IDS,
    INBOUND_MCP_PRM_PATH,
    INBOUND_MCP_REQUIRED_ROLE,
    INBOUND_MCP_REQUIRED_SCOPE,
    INBOUND_MCP_SOURCE_HEADER,
    TENANT_ID,
)
from functions_appinsights import log_event
from functions_authentication import validate_bearer_token


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
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item for item in re.split(r"[\s,]+", value.strip()) if item)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


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


def _resolve_source_signal(flask_request, caller_app_id):
    source_header_name = (INBOUND_MCP_SOURCE_HEADER or "").strip()
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


def _source_is_allowed(source_id):
    allowed_sources = tuple(INBOUND_MCP_ALLOWED_SOURCE_IDS or ("*",))
    return "*" in allowed_sources or source_id in allowed_sources


def _tenant_is_allowed(tenant_id):
    allowed_tenants = tuple(INBOUND_MCP_ALLOWED_TENANT_IDS or ())
    if not allowed_tenants and TENANT_ID:
        allowed_tenants = (TENANT_ID,)
    return not allowed_tenants or tenant_id in allowed_tenants


def _client_is_allowed(caller_app_id):
    allowed_clients = tuple(INBOUND_MCP_ALLOWED_CLIENT_APP_IDS or ())
    return bool(caller_app_id and allowed_clients and caller_app_id.lower() in allowed_clients)


def _has_required_role_or_scope(roles, scopes):
    required_role = (INBOUND_MCP_REQUIRED_ROLE or "").strip()
    required_scope = (INBOUND_MCP_REQUIRED_SCOPE or "").strip()
    has_role = bool(required_role and required_role in roles)
    has_scope = bool(required_scope and required_scope in scopes)
    return has_role or has_scope


def _correlation_id(flask_request):
    return (
        flask_request.headers.get("x-ms-client-request-id")
        or flask_request.headers.get("x-correlation-id")
        or flask_request.headers.get("x-request-id")
        or ""
    )


def validate_inbound_mcp_request(flask_request, token_validator=None):
    """Validate bearer auth and source policy for an inbound MCP request."""
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
    if not _tenant_is_allowed(tenant_id):
        raise InboundMcpAuthError(401, "invalid_token", "The bearer token is invalid.")

    caller_app_id = str(token_claims.get("azp") or token_claims.get("appid") or "").strip().lower()
    if not _client_is_allowed(caller_app_id):
        raise InboundMcpAuthError(403, "mcp_client_not_allowed", "The MCP client is not allowed.")

    roles = _normalize_claim_values(token_claims.get("roles"))
    scopes = _normalize_claim_values(token_claims.get("scp"))
    if not _has_required_role_or_scope(roles, scopes):
        raise InboundMcpAuthError(
            403,
            "insufficient_mcp_permissions",
            "The bearer token does not include the required MCP role or scope.",
        )

    source_id, source_signal_type, source_trust_level = _resolve_source_signal(
        flask_request,
        caller_app_id,
    )
    if not _source_is_allowed(source_id):
        raise InboundMcpAuthError(
            403,
            "mcp_source_not_allowed",
            "The MCP source is not allowed.",
        )

    delegated_user_id = str(token_claims.get("oid") or token_claims.get("sub") or "").strip()
    delegated_username = str(
        token_claims.get("preferred_username")
        or token_claims.get("upn")
        or token_claims.get("name")
        or ""
    ).strip()
    token_type = "delegated" if delegated_user_id and scopes else "app_only"

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
    return flask_request.method == "GET" and flask_request.path == INBOUND_MCP_PRM_PATH


def build_inbound_mcp_auth_error_response(auth_error):
    return jsonify({
        "error": auth_error.public_error,
        "message": auth_error.public_message,
    }), auth_error.status_code


def inbound_mcp_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            g.inbound_mcp_auth_context = validate_inbound_mcp_request(request)
        except InboundMcpAuthError as auth_error:
            return build_inbound_mcp_auth_error_response(auth_error)
        return f(*args, **kwargs)
    return decorated_function


def inbound_mcp_required_blueprint():
    """Return a Blueprint guard for inbound MCP bearer-token requests."""
    def guard():
        if request.method == "OPTIONS":
            return None
        if is_inbound_mcp_metadata_request(request):
            return None
        if not ENABLE_INBOUND_MCP_SERVER:
            log_event(
                "[InboundMCP] Inbound MCP request rejected because the server is disabled.",
                extra={"path": request.path, "method": request.method},
                level=logging.INFO,
                debug_only=True,
                category=AUTH_CATEGORY,
            )
            return jsonify({
                "error": "inbound_mcp_disabled",
                "message": "Inbound MCP server is disabled.",
            }), 404

        try:
            g.inbound_mcp_auth_context = validate_inbound_mcp_request(request)
        except InboundMcpAuthError as auth_error:
            log_event(
                "[InboundMCP] Inbound MCP request rejected by auth guard.",
                extra={
                    "path": request.path,
                    "method": request.method,
                    "error": auth_error.public_error,
                    "status_code": auth_error.status_code,
                },
                level=logging.WARNING,
                debug_only=True,
                category=AUTH_CATEGORY,
            )
            return build_inbound_mcp_auth_error_response(auth_error)

        return None

    guard._simplechat_auth_policy = ("inbound_mcp_required",)
    return guard
