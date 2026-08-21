# server.py
"""Local MCP server for SimpleChat outbound MCP action validation."""

import argparse
import asyncio
import base64
import json
from typing import Any, Dict, List, Optional

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse


SERVER_NAME = "simplechat-local-mcp"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MCP_PATH = "/mcp"
MAX_DELAY_SECONDS = 10
SENSITIVE_HEADER_TOKENS = (
    "authorization",
    "cookie",
    "key",
    "password",
    "secret",
    "token",
)
REDACTED_VALUE = "***REDACTED***"


def parse_header_values(raw_values: Optional[List[str]]) -> Dict[str, str]:
    """Parse repeated NAME=VALUE CLI values into a header expectation map."""
    parsed_values: Dict[str, str] = {}
    for raw_value in raw_values or []:
        name, separator, value = raw_value.partition("=")
        header_name = name.strip()
        if not separator or not header_name:
            raise ValueError("--require-header-value entries must use NAME=VALUE syntax")
        parsed_values[header_name] = value.strip()
    return parsed_values


def normalize_header_map(headers: Dict[str, str]) -> Dict[str, str]:
    """Return a lowercase lookup map for case-insensitive header access."""
    return {str(name).lower(): str(value) for name, value in headers.items()}


def get_context_headers(ctx: Optional[Context]) -> Dict[str, str]:
    """Read HTTP headers from the MCP request context."""
    if ctx is None:
        return {}

    try:
        request = ctx.request_context.request
    except ValueError:
        return {}

    if request is None or not hasattr(request, "headers"):
        return {}

    return {str(name): str(value) for name, value in request.headers.items()}


def is_sensitive_header(header_name: str) -> bool:
    """Return whether a header value should be redacted by default."""
    normalized_name = str(header_name or "").lower()
    return any(token in normalized_name for token in SENSITIVE_HEADER_TOKENS)


def redact_header_value(header_name: str, header_value: str, include_sensitive: bool = False) -> str:
    """Redact sensitive header values unless explicitly requested."""
    if is_sensitive_header(header_name) and not include_sensitive:
        return REDACTED_VALUE
    return header_value


def parse_basic_authorization(value: str) -> Dict[str, str]:
    """Parse a Basic authorization header into username and password fields."""
    scheme, _, encoded_value = str(value or "").partition(" ")
    if scheme.lower() != "basic" or not encoded_value:
        return {}

    try:
        decoded = base64.b64decode(encoded_value).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return {}

    username, separator, password = decoded.partition(":")
    if not separator:
        return {}
    return {
        "username": username,
        "password": password,
    }


def create_server(mcp_path: str = DEFAULT_MCP_PATH) -> FastMCP:
    """Create the reusable local MCP server instance."""
    server = FastMCP(
        SERVER_NAME,
        instructions=(
            "SimpleChat local MCP validation server. Use this server to test "
            "streamable HTTP discovery, custom headers, auth precedence, mock "
            "responses, latency, and controlled tool failures."
        ),
        streamable_http_path=mcp_path,
    )

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "server": SERVER_NAME,
            "mcp_path": mcp_path,
        })

    @server.tool()
    def server_info(ctx: Context) -> Dict[str, Any]:
        """Return local MCP server capabilities and observed request metadata."""
        headers = get_context_headers(ctx)
        return {
            "success": True,
            "server": SERVER_NAME,
            "transport": "streamable_http",
            "mcp_path": mcp_path,
            "tool_names": [
                "server_info",
                "ping",
                "inspect_headers",
                "require_headers",
                "require_auth",
                "echo_payload",
                "mock_search",
                "slow_response",
                "always_fail",
            ],
            "observed_header_names": sorted(headers.keys()),
        }

    @server.tool()
    def ping(message: str = "pong") -> Dict[str, Any]:
        """Return a simple success response for smoke testing."""
        return {
            "success": True,
            "message": message,
            "server": SERVER_NAME,
        }

    @server.tool()
    def inspect_headers(
        header_names: Optional[List[str]] = None,
        include_sensitive: bool = False,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Inspect selected HTTP headers received by the MCP server."""
        headers = get_context_headers(ctx)
        header_lookup = normalize_header_map(headers)
        requested_names = header_names or sorted(headers.keys())
        inspected_headers = {}

        for header_name in requested_names:
            normalized_name = str(header_name or "").strip().lower()
            if not normalized_name:
                continue
            observed_value = header_lookup.get(normalized_name)
            inspected_headers[str(header_name)] = {
                "present": observed_value is not None,
                "value": (
                    redact_header_value(str(header_name), observed_value, include_sensitive)
                    if observed_value is not None
                    else None
                ),
            }

        return {
            "success": True,
            "headers": inspected_headers,
            "header_count": len(headers),
        }

    @server.tool()
    def require_headers(
        required_headers: Optional[List[str]] = None,
        expected_headers: Optional[Dict[str, str]] = None,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Validate that required headers exist and expected values match."""
        headers = get_context_headers(ctx)
        header_lookup = normalize_header_map(headers)
        required_names = [str(name).strip() for name in required_headers or [] if str(name).strip()]
        expected_values = expected_headers or {}

        missing_headers = [
            header_name
            for header_name in required_names
            if header_name.lower() not in header_lookup
        ]
        mismatched_headers = {}
        matched_headers = []

        for header_name, expected_value in expected_values.items():
            normalized_name = str(header_name or "").strip().lower()
            if not normalized_name:
                continue
            observed_value = header_lookup.get(normalized_name)
            if observed_value is None:
                missing_headers.append(str(header_name))
            elif observed_value != str(expected_value):
                mismatched_headers[str(header_name)] = {
                    "present": True,
                    "matched": False,
                    "observed": redact_header_value(str(header_name), observed_value),
                }
            else:
                matched_headers.append(str(header_name))

        missing_headers = sorted(set(missing_headers))
        success = not missing_headers and not mismatched_headers
        return {
            "success": success,
            "matched_headers": sorted(set(matched_headers)),
            "missing_headers": missing_headers,
            "mismatched_headers": mismatched_headers,
        }

    @server.tool()
    def require_auth(
        auth_type: str = "bearer",
        expected_token: str = "",
        api_key_header_name: str = "X-API-Key",
        expected_api_key: str = "",
        expected_username: str = "",
        expected_password: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Validate bearer, API key, or basic auth headers without echoing secrets."""
        headers = get_context_headers(ctx)
        header_lookup = normalize_header_map(headers)
        normalized_auth_type = str(auth_type or "bearer").strip().lower().replace("-", "_")
        authorization_value = header_lookup.get("authorization", "")

        if normalized_auth_type in {"bearer", "bearer_token"}:
            expected_value = f"Bearer {expected_token}" if expected_token else ""
            matched = bool(expected_value and authorization_value == expected_value)
            return {
                "success": matched,
                "auth_type": "bearer",
                "authorization_present": bool(authorization_value),
                "scheme": authorization_value.partition(" ")[0] if authorization_value else "",
                "matched": matched,
            }

        if normalized_auth_type in {"api_key", "apikey"}:
            observed_api_key = header_lookup.get(str(api_key_header_name or "").strip().lower(), "")
            matched = bool(expected_api_key and observed_api_key == expected_api_key)
            return {
                "success": matched,
                "auth_type": "api_key",
                "header_name": api_key_header_name,
                "header_present": bool(observed_api_key),
                "matched": matched,
            }

        if normalized_auth_type == "basic":
            parsed_credentials = parse_basic_authorization(authorization_value)
            matched = (
                bool(parsed_credentials)
                and parsed_credentials.get("username") == expected_username
                and parsed_credentials.get("password") == expected_password
            )
            return {
                "success": matched,
                "auth_type": "basic",
                "authorization_present": bool(authorization_value),
                "username_present": bool(parsed_credentials.get("username")),
                "matched": matched,
            }

        return {
            "success": False,
            "auth_type": normalized_auth_type,
            "error": "Unsupported auth_type. Use bearer, api_key, or basic.",
        }

    @server.tool()
    def echo_payload(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Echo a JSON payload for argument-shape testing."""
        return {
            "success": True,
            "payload": payload or {},
        }

    @server.tool()
    def mock_search(query: str, max_results: int = 3) -> Dict[str, Any]:
        """Return deterministic mock search results for agent tests."""
        bounded_count = min(max(int(max_results or 1), 1), 10)
        results = [
            {
                "id": f"mock-result-{index}",
                "title": f"Mock result {index} for {query}",
                "summary": (
                    "This deterministic local MCP response is safe for testing "
                    "SimpleChat action invocation and citation-style handling."
                ),
            }
            for index in range(1, bounded_count + 1)
        ]
        return {
            "success": True,
            "query": query,
            "results": results,
        }

    @server.tool()
    async def slow_response(delay_seconds: int = 1) -> Dict[str, Any]:
        """Delay for a bounded number of seconds before returning."""
        bounded_delay = min(max(int(delay_seconds or 0), 0), MAX_DELAY_SECONDS)
        await asyncio.sleep(bounded_delay)
        return {
            "success": True,
            "delay_seconds": bounded_delay,
        }

    @server.tool()
    def always_fail(message: str = "Intentional local MCP failure") -> Dict[str, Any]:
        """Raise a deterministic failure for error handling tests."""
        raise RuntimeError(message)

    return server


class HeaderGateMiddleware:
    """Small ASGI gate for optional local ingress header/auth scenarios."""

    def __init__(
        self,
        app,
        mcp_path: str,
        required_headers: Dict[str, str],
        bearer_token: str,
        api_key_header_name: str,
        api_key_value: str,
    ):
        self.app = app
        self.mcp_path = mcp_path
        self.required_headers = normalize_header_map(required_headers)
        self.bearer_token = bearer_token
        self.api_key_header_name = api_key_header_name
        self.api_key_value = api_key_value

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != self.mcp_path:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        errors = []

        for header_name, expected_value in self.required_headers.items():
            observed_value = headers.get(header_name)
            if observed_value is None:
                errors.append(f"Missing required header '{header_name}'")
            elif expected_value and observed_value != expected_value:
                errors.append(f"Header '{header_name}' did not match expected value")

        if self.bearer_token:
            expected_authorization = f"Bearer {self.bearer_token}"
            if headers.get("authorization") != expected_authorization:
                errors.append("Bearer authorization did not match expected token")

        if self.api_key_value:
            api_key_header = str(self.api_key_header_name or "X-API-Key").strip().lower()
            if headers.get(api_key_header) != self.api_key_value:
                errors.append(f"API key header '{api_key_header}' did not match expected value")

        if errors:
            response = JSONResponse(
                {
                    "error": "Local MCP header gate rejected the request.",
                    "details": errors,
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def build_app(args):
    """Build the Starlette app used by uvicorn."""
    server = create_server(args.path)
    server.settings.host = args.host
    server.settings.port = args.port
    server.settings.log_level = args.log_level.upper()
    server.settings.stateless_http = args.stateless_http
    server.settings.json_response = args.json_response

    app = server.streamable_http_app()
    required_headers = parse_header_values(args.require_header_value)
    for header_name in args.require_header or []:
        required_headers.setdefault(header_name, "")

    if required_headers or args.require_bearer_token or args.require_api_key:
        return HeaderGateMiddleware(
            app,
            args.path,
            required_headers,
            args.require_bearer_token or "",
            args.require_api_key_header,
            args.require_api_key or "",
        )

    return app


def parse_args(argv: Optional[List[str]] = None):
    """Parse local MCP server command-line arguments."""
    parser = argparse.ArgumentParser(description="Run the SimpleChat local MCP validation server.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host interface to bind. Defaults to 127.0.0.1.")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Port to bind. Defaults to 8765.")
    parser.add_argument("--path", default=DEFAULT_MCP_PATH, help="MCP streamable HTTP path. Defaults to /mcp.")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error", "critical"])
    parser.add_argument("--json-response", action="store_true", help="Use JSON responses instead of SSE streams.")
    parser.add_argument("--stateless-http", action="store_true", help="Run streamable HTTP in stateless mode.")
    parser.add_argument(
        "--require-header",
        action="append",
        help="Require a header by name for all /mcp requests. May be repeated.",
    )
    parser.add_argument(
        "--require-header-value",
        action="append",
        help="Require a header and exact value using NAME=VALUE syntax. May be repeated.",
    )
    parser.add_argument(
        "--require-bearer-token",
        default="",
        help="Require Authorization: Bearer <token> for all /mcp requests.",
    )
    parser.add_argument(
        "--require-api-key-header",
        default="X-API-Key",
        help="Header name to use with --require-api-key. Defaults to X-API-Key.",
    )
    parser.add_argument(
        "--require-api-key",
        default="",
        help="Require a specific API key value for all /mcp requests.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    """Run the local MCP server."""
    args = parse_args(argv)
    app = build_app(args)
    print(json.dumps({
        "server": SERVER_NAME,
        "url": f"http://{args.host}:{args.port}{args.path}",
        "healthz": f"http://{args.host}:{args.port}/healthz",
    }))
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
