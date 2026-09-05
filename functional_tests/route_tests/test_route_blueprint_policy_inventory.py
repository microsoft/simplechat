#!/usr/bin/env python3
# test_route_blueprint_policy_inventory.py
"""
Functional test for route blueprint policy inventory.
Version: 0.250.055
Implemented in: 0.242.069

This test ensures every SimpleChat route is assigned to a Blueprint-based
security policy or an explicit reviewed route exemption.
"""

import ast
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = ROOT_DIR / "application" / "single_app"
CONFIG_FILE = APP_DIR / "config.py"

ROUTE_POLICY_BLUEPRINTS = {
    "bpa": ("login_required",),
    "bpap": ("login_required",),
    "bp_agent_templates": ("login_required",),
    "bp_migration": ("login_required", "user_required"),
    "bpdp": ("login_required", "admin_required"),
    "bpl": ("login_required",),
    "debug_admin_bp": ("login_required", "admin_required"),
    "plugin_validation_bp": ("login_required", "user_required"),
    "plugin_validation_admin_bp": ("login_required", "admin_required"),
    "public_app_bp": (),
    "session_api_bp": ("login_required",),
    "swagger_bp": ("login_required",),
}

REGISTERED_BLUEPRINT_POLICIES = {
    "backend_chats": ("login_required", "user_required"),
    "backend_collaboration": ("login_required", "user_required"),
    "backend_control_center": ("login_required",),
    "backend_conversation_export": ("login_required", "user_required"),
    "backend_conversations": ("login_required", "user_required"),
    "backend_data_management": ("login_required", "admin_required"),
    "backend_documents": ("login_required", "user_required"),
    "backend_feedback": ("login_required", "user_required"),
    "backend_file_sync": ("login_required",),
    "backend_governance": ("login_required", "admin_required"),
    "backend_group_documents": ("login_required", "user_required"),
    "backend_group_prompts": ("login_required", "user_required"),
    "backend_groups": ("login_required", "user_required"),
    "backend_models": ("login_required", "user_required"),
    "backend_msgraph_pending_actions": ("login_required", "user_required"),
    "backend_notifications": ("login_required", "user_required"),
    "backend_orchestration": ("login_required", "user_required"),
    "backend_prompts": ("login_required", "user_required"),
    "backend_public_documents": ("login_required", "user_required"),
    "backend_public_prompts": ("login_required", "user_required"),
    "backend_public_workspaces": ("login_required", "user_required"),
    "backend_retention_policy": ("login_required",),
    "backend_safety": ("login_required", "user_required"),
    "backend_search": ("login_required", "user_required"),
    "backend_settings": ("login_required",),
    "backend_speech": ("login_required", "user_required"),
    "backend_thoughts": ("login_required", "user_required"),
    "backend_tts": ("login_required", "user_required"),
    "backend_user_agreement": ("login_required", "user_required"),
    "backend_users": ("login_required", "user_required"),
    "backend_v2": ("login_required", "user_required"),
    "backend_v2_admin": ("login_required", "admin_required"),
    "backend_workflows": ("login_required", "user_required"),
    "backend_workspace_identities": ("login_required",),
    "custom_pages": ("login_required",),
    "enhanced_citations": ("login_required", "user_required"),
    "external_health": (),
    "external_no_auth_health": (),
    "frontend_admin_settings": ("login_required", "admin_required"),
    "frontend_agents": ("login_required", "user_required"),
    "frontend_terms_of_use": (),
    "frontend_authentication": (),
    "frontend_chats": ("login_required", "user_required"),
    "frontend_control_center": ("login_required",),
    "frontend_conversations": ("login_required", "user_required"),
    "frontend_feedback": ("login_required",),
    "frontend_group_workspaces": ("login_required", "user_required"),
    "frontend_groups": ("login_required", "user_required"),
    "frontend_notifications": ("login_required", "user_required"),
    "frontend_profile": ("login_required",),
    "frontend_public_workspaces": ("login_required", "user_required"),
    "frontend_safety": ("login_required",),
    "frontend_support": ("login_required", "user_required"),
    "frontend_v2": ("login_required", "user_required"),
    "frontend_workspace": ("login_required", "user_required"),
    "inbound_mcp": ("inbound_mcp_required",),
    "openapi": ("login_required", "user_required"),
}

EXPECTED_PUBLIC_PATHS = {
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
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/api/mcp",
    "/.well-known/oauth-protected-resource/mcp",
    "/.well-known/oauth-authorization-server",
    "/static/js/<path:filename>",
    "/acceptable_use_policy.html",
    "/external/healthcheck",
    "/external/healthcheckz",
}

SENSITIVE_ROUTE_POLICIES = {
    ("app.py", "session_heartbeat"): ("login_required",),
    ("app.py", "list_semantic_kernel_plugins"): ("login_required", "admin_required"),
    ("route_backend_plugins.py", "get_agent_action_targets"): ("login_required", "user_required"),
    ("route_backend_agents.py", "initiate_delegated_foundry_auth"): ("login_required", "user_required"),
    ("route_backend_agents.py", "update_personal_agent_action_bindings"): ("login_required", "user_required"),
    ("route_backend_agents.py", "update_group_agent_action_bindings"): ("login_required", "user_required"),
    ("route_backend_agents.py", "update_global_agent_action_bindings"): ("login_required", "admin_required"),
}


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


def read_config_version() -> str:
    """Extract the current application version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


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
                target = decorator_name.rsplit(".", 1)[0]
                routes.append(
                    RouteFunction(
                        file_name=file_path.name,
                        function_name=node.name,
                        route_target=target,
                        path=route_path(decorator),
                        decorator_names=tuple(dotted_name(item.func if isinstance(item, ast.Call) else item) for item in node.decorator_list),
                        line_number=node.lineno,
                    )
                )
    return routes


def test_route_policy_inventory_assets_and_version_are_current() -> None:
    """Verify the route policy test folder and config version reader are wired correctly."""
    version_parts = read_config_version().split(".")
    assert len(version_parts) == 3
    assert all(part.isdigit() for part in version_parts)
    assert Path(__file__).parent.name == "route_tests"


def test_no_new_direct_app_routes_outside_reviewed_exemptions() -> None:
    """Require new route modules to use Blueprint route registration."""
    unexpected_app_routes = [
        route for route in iter_route_functions()
        if route.route_target == "app"
    ]

    assert unexpected_app_routes == [], "Unexpected direct app routes: " + "; ".join(
        f"{route.file_name}:{route.line_number}:{route.function_name}:{route.path}"
        for route in unexpected_app_routes
    )


def test_blueprint_routes_have_registered_policy_classification() -> None:
    """Verify protected Blueprint routes use a declared route-policy Blueprint."""
    unclassified_routes = []
    for route in iter_route_functions():
        if route.route_target in {"app", "bp"}:
            continue
        if route.route_target in ROUTE_POLICY_BLUEPRINTS:
            continue
        if route.path in EXPECTED_PUBLIC_PATHS:
            continue
        unclassified_routes.append(route)

    assert unclassified_routes == [], "Blueprint routes missing policy classification: " + "; ".join(
        f"{route.file_name}:{route.line_number}:{route.route_target}.{route.function_name}:{route.path}"
        for route in unclassified_routes
    )


def test_registered_route_blueprints_have_policy_classification() -> None:
    """Verify every blueprint registered through app.py's helper has an explicit policy."""
    app_source = read_text(APP_DIR / "app.py")
    tree = ast.parse(app_source, filename="app.py")
    registered_names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if dotted_name(node.func) != "register_route_blueprint" or not node.args:
            continue
        name_arg = node.args[0]
        if isinstance(name_arg, ast.Constant):
            registered_names.add(str(name_arg.value))

    missing_policy = sorted(registered_names - set(REGISTERED_BLUEPRINT_POLICIES))
    stale_policy = sorted(set(REGISTERED_BLUEPRINT_POLICIES) - registered_names)
    assert missing_policy == [], f"Registered blueprints missing route policy: {missing_policy}"
    assert stale_policy == [], f"Route policy entries for unregistered blueprints: {stale_policy}"


def test_explicit_app_route_exemptions_have_expected_security() -> None:
    """Verify remaining direct app route exemptions keep their reviewed security posture."""
    routes = {(route.file_name, route.function_name): route for route in iter_route_functions()}
    for key, expected_decorators in SENSITIVE_ROUTE_POLICIES.items():
        route = routes[key]
        for expected_decorator in expected_decorators:
            assert expected_decorator in route.decorator_names, (
                f"{route.file_name}:{route.function_name} must keep @{expected_decorator}."
            )


def test_public_routes_are_explicitly_listed() -> None:
    """Verify public route decisions are explicit and reviewed."""
    routes_by_path = {route.path: route for route in iter_route_functions() if route.path}
    missing_public_paths = sorted(EXPECTED_PUBLIC_PATHS - set(routes_by_path))
    assert missing_public_paths == [], f"Expected public routes are missing: {missing_public_paths}"

    unlisted_public_candidates = [
        route for route in iter_route_functions()
        if route.path in EXPECTED_PUBLIC_PATHS
        and "login_required" in route.decorator_names
        and route.path not in {"/logout", "/logout/local"}
    ]
    assert unlisted_public_candidates == [], "Public routes unexpectedly require login: " + "; ".join(
        f"{route.path} ({route.file_name}:{route.function_name})" for route in unlisted_public_candidates
    )


if __name__ == "__main__":
    tests = [
        test_route_policy_inventory_assets_and_version_are_current,
        test_no_new_direct_app_routes_outside_reviewed_exemptions,
        test_blueprint_routes_have_registered_policy_classification,
        test_registered_route_blueprints_have_policy_classification,
        test_explicit_app_route_exemptions_have_expected_security,
        test_public_routes_are_explicitly_listed,
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
