#!/usr/bin/env python3
"""
Functional test for V2 API security posture.

Version: 0.261.003
Implemented in: 0.261.003

This test ensures that the V2 bootstrap endpoint never returns raw settings to the
browser, that every V2 route carries the required swagger security decorator, and that the
V2 admin settings endpoints are restricted to the Admin role.

The bootstrap endpoint hands a settings document to an authenticated but non-admin user,
so sending get_settings() output directly would leak API keys, connection strings and
endpoint configuration. The check is performed with AST analysis because importing the
route module requires live Azure configuration.
"""

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
BACKEND_V2 = APP_DIR / "route_backend_v2.py"
FRONTEND_V2 = APP_DIR / "route_frontend_v2.py"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _iter_route_functions(tree):
    """Yield (function_node, decorator_names) for every decorated route handler."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        decorator_names = []
        is_route = False
        for decorator in node.decorator_list:
            call = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(call, ast.Attribute):
                decorator_names.append(call.attr)
                if call.attr == "route":
                    is_route = True
            elif isinstance(call, ast.Name):
                decorator_names.append(call.id)

        if is_route:
            yield node, decorator_names


def test_bootstrap_sanitizes_settings():
    """The bootstrap payload's settings come from sanitize_settings_for_user, not get_settings."""
    print("Testing bootstrap settings sanitization...")

    source = BACKEND_V2.read_text(encoding="utf-8")
    tree = _parse(BACKEND_V2)

    assert "sanitize_settings_for_user" in source, (
        "route_backend_v2.py must import and use sanitize_settings_for_user"
    )

    bootstrap = None
    for node, _ in _iter_route_functions(tree):
        if node.name == "v2_bootstrap":
            bootstrap = node
            break

    assert bootstrap is not None, "v2_bootstrap route function was not found"

    # Locate the name the sanitized settings were bound to.
    sanitized_names = set()
    for node in ast.walk(bootstrap):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "sanitize_settings_for_user"
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    sanitized_names.add(target.id)

    assert sanitized_names, "v2_bootstrap must assign the result of sanitize_settings_for_user"

    # The payload's "settings" entry must reference that sanitized name.
    settings_values = []
    for node in ast.walk(bootstrap):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "settings":
                    settings_values.append(value)

    assert settings_values, "v2_bootstrap payload must include a 'settings' key"

    for value in settings_values:
        assert isinstance(value, ast.Name) and value.id in sanitized_names, (
            "The bootstrap payload's 'settings' must be the sanitized settings, "
            f"got {ast.dump(value)[:120]}"
        )

    print("Bootstrap sanitization test passed!")
    return True


def test_all_v2_routes_declare_swagger_security():
    """Every V2 route carries @swagger_route, per the repository route convention."""
    print("Testing swagger security decorators...")

    for path in (BACKEND_V2, FRONTEND_V2):
        for node, decorators in _iter_route_functions(_parse(path)):
            assert "swagger_route" in decorators, (
                f"{path.name}:{node.name} is missing @swagger_route(security=get_auth_security())"
            )
            assert "login_required" in decorators, (
                f"{path.name}:{node.name} is missing @login_required"
            )

    print("Swagger security decorator test passed!")
    return True


def test_admin_endpoints_require_admin_role():
    """The V2 admin settings endpoints are gated on the Admin role."""
    print("Testing admin endpoint authorization...")

    admin_routes = []
    for node, decorators in _iter_route_functions(_parse(BACKEND_V2)):
        if node.name.startswith("v2_admin_"):
            admin_routes.append((node.name, decorators))

    assert admin_routes, "No V2 admin routes were found"

    for name, decorators in admin_routes:
        assert "admin_required" in decorators, (
            f"{name} exposes admin settings but is missing @admin_required"
        )

    # Both the read and the partial-update endpoints must exist and be protected.
    route_names = {name for name, _ in admin_routes}
    assert "v2_admin_get_settings" in route_names, "Admin settings read endpoint is missing"
    assert "v2_admin_patch_settings" in route_names, "Admin settings update endpoint is missing"

    print("Admin endpoint authorization test passed!")
    return True


def test_admin_nav_is_withheld_from_non_admins():
    """Non-admin callers do not receive the admin navigation structure."""
    print("Testing admin navigation exposure...")

    source = BACKEND_V2.read_text(encoding="utf-8")
    assert '"admin_nav": ADMIN_NAV if "Admin" in current_user_roles else []' in source, (
        "The bootstrap payload must only include ADMIN_NAV for users holding the Admin role"
    )

    print("Admin navigation exposure test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that introduced the V2 UI."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.003")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_bootstrap_sanitizes_settings,
        test_all_v2_routes_declare_swagger_security,
        test_admin_endpoints_require_admin_role,
        test_admin_nav_is_withheld_from_non_admins,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
