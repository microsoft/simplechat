#!/usr/bin/env python3
# test_route_unauthenticated_policy_contract.py
"""
Functional test for route unauthenticated access policy contract.
Version: 0.250.055
Implemented in: 0.242.069

This test ensures every SimpleChat route has an explicit expected unauthenticated
access behavior: public, browser-session authenticated, admin-only, or external
bearer-token protected.
"""

import ast
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = ROOT_DIR / "application" / "single_app"

PUBLIC_PATHS = {
    "/",
    "/login",
    "/getAToken",
    "/getATokenApi",
    "/logout",
    "/logout/local",
    "/terms-of-use",
    "/terms-of-use/accept",
    "/terms-of-use/decline",
    "/ci-auth/session",
    "/robots933456.txt",
    "/favicon.ico",
    "/.well-known/oauth-protected-resource/mcp",
    "/static/js/<path:filename>",
    "/acceptable_use_policy.html",
    "/auth/teams/token-exchange",
    "/external/healthcheck",
    "/external/healthcheckz",
}

EXTERNAL_BEARER_PATH_PREFIXES = (
    "/external/public_documents",
)

INBOUND_MCP_BEARER_PATH_PREFIXES = (
    "/api/mcp",
)

ADMIN_PATH_PREFIXES = (
    "/admin/",
    "/api/admin/",
    "/api/semantic-kernel/plugins",
)

LOGIN_ONLY_PATH_PREFIXES = (
    "/custom/",
    "/api/custom/",
    "/api/approvals",
    "/swagger",
    "/api/swagger/",
)

USER_SESSION_PATH_PREFIXES = (
    "/conversation/",
    "/feedback/submit",
    "/feedback/my",
    "/api/",
    "/agents",
    "/approvals",
    "/chats",
    "/conversations",
    "/group_workspaces",
    "/groups/",
    "/my_groups",
    "/my_feedback",
    "/my_public_workspaces",
    "/notifications",
    "/profile",
    "/public_workspaces",
    "/public_directory",
    "/safety_violations",
    "/set_active_group",
    "/set_active_public_workspace",
    "/support/",
    "/upload",
    "/view_document",
    "/view_pdf",
    "/workspace",
    "/workflow-activity",
)

SPECIALIZED_ADMIN_PATH_PREFIXES = (
    "/feedback/review",
    "/feedback/retest",
)


@dataclass(frozen=True)
class RouteFunction:
    file_name: str
    function_name: str
    route_target: str
    path: str
    decorator_names: tuple[str, ...]
    line_number: int


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding="utf-8")


def dotted_name(node: ast.AST) -> str:
    """Return a dotted name for supported AST node types."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    return ""


def route_path(route_decorator: ast.Call) -> str:
    """Return the literal path from a Flask route decorator."""
    if route_decorator.args and isinstance(route_decorator.args[0], ast.Constant):
        return str(route_decorator.args[0].value)
    return ""


def iter_route_functions() -> list[RouteFunction]:
    """Return first-party route functions from application/single_app Python files."""
    routes = []
    for file_path in sorted(APP_DIR.glob("*.py")):
        if file_path.name == "swagger_wrapper.py":
            source = "\n".join(
                line for index, line in enumerate(read_text(file_path).splitlines(), start=1)
                if index >= 100
            )
        else:
            source = read_text(file_path)
        tree = ast.parse(source, filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                decorator_name = dotted_name(decorator.func)
                if not decorator_name.endswith(".route"):
                    continue
                routes.append(
                    RouteFunction(
                        file_name=file_path.name,
                        function_name=node.name,
                        route_target=decorator_name.rsplit(".", 1)[0],
                        path=route_path(decorator),
                        decorator_names=tuple(dotted_name(item.func if isinstance(item, ast.Call) else item) for item in node.decorator_list),
                        line_number=node.lineno,
                    )
                )
    return routes


def matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    """Return True when a route path starts with any policy prefix."""
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in prefixes)


def expected_policy(path: str) -> str:
    """Return the expected unauthenticated behavior category for one path."""
    if path in PUBLIC_PATHS:
        return "public"
    if matches_prefix(path, EXTERNAL_BEARER_PATH_PREFIXES):
        return "external_bearer_401"
    if matches_prefix(path, INBOUND_MCP_BEARER_PATH_PREFIXES):
        return "inbound_mcp_bearer_401_or_404"
    if matches_prefix(path, ADMIN_PATH_PREFIXES):
        return "session_admin_401_or_redirect"
    if matches_prefix(path, SPECIALIZED_ADMIN_PATH_PREFIXES):
        return "session_specialized_admin_401_or_redirect"
    if matches_prefix(path, LOGIN_ONLY_PATH_PREFIXES):
        return "session_login_401_or_redirect"
    if matches_prefix(path, USER_SESSION_PATH_PREFIXES):
        return "session_user_401_or_redirect"
    return "unclassified"


def test_every_route_has_unauthenticated_access_policy() -> None:
    """Verify every route path has an explicit unauthenticated access policy."""
    unclassified = [route for route in iter_route_functions() if expected_policy(route.path) == "unclassified"]
    assert unclassified == [], "Routes without unauthenticated policy: " + "; ".join(
        f"{route.file_name}:{route.line_number}:{route.function_name}:{route.path}"
        for route in unclassified
    )


def test_public_routes_do_not_use_session_or_bearer_auth_decorators() -> None:
    """Verify public routes are intentionally public in the source contract."""
    guarded_public = []
    for route in iter_route_functions():
        if expected_policy(route.path) != "public":
            continue
        forbidden_decorators = {
            "login_required",
            "user_required",
            "admin_required",
            "accesstoken_required",
            "control_center_required",
            "feedback_admin_required",
            "safety_violation_admin_required",
        }
        if forbidden_decorators.intersection(route.decorator_names):
            guarded_public.append(route)

    assert guarded_public == [], "Public routes have auth decorators: " + "; ".join(
        f"{route.file_name}:{route.line_number}:{route.function_name}:{route.path}"
        for route in guarded_public
    )


def test_external_routes_use_bearer_auth_decorator() -> None:
    """Verify external API routes keep bearer-token runtime auth."""
    missing_bearer = []
    for route in iter_route_functions():
        if expected_policy(route.path) != "external_bearer_401":
            continue
        if "accesstoken_required" not in route.decorator_names:
            missing_bearer.append(route)

    assert missing_bearer == [], "External bearer routes missing @accesstoken_required: " + "; ".join(
        f"{route.file_name}:{route.line_number}:{route.function_name}:{route.path}"
        for route in missing_bearer
    )


def test_sensitive_admin_routes_have_admin_or_specialized_route_decorator() -> None:
    """Verify admin routes keep route-specific admin or specialized role checks."""
    missing_admin = []
    accepted_admin_decorators = {
        "admin_required",
        "control_center_required",
        "feedback_admin_required",
        "safety_violation_admin_required",
    }
    for route in iter_route_functions():
        if expected_policy(route.path) not in {
            "session_admin_401_or_redirect",
            "session_specialized_admin_401_or_redirect",
        }:
            continue
        if not accepted_admin_decorators.intersection(route.decorator_names):
            missing_admin.append(route)

    assert missing_admin == [], "Admin routes missing admin/specialized route decorators: " + "; ".join(
        f"{route.file_name}:{route.line_number}:{route.function_name}:{route.path}"
        for route in missing_admin
    )


if __name__ == "__main__":
    tests = [
        test_every_route_has_unauthenticated_access_policy,
        test_public_routes_do_not_use_session_or_bearer_auth_decorators,
        test_external_routes_use_bearer_auth_decorator,
        test_sensitive_admin_routes_have_admin_or_specialized_route_decorator,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    passed = sum(results)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    raise SystemExit(0 if all(results) else 1)
