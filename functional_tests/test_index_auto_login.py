#!/usr/bin/env python3
# test_index_auto_login.py
"""
Functional test for index-page auto-login configuration.
Version: 0.250.209
Implemented in: 0.250.209

This test ensures SimpleChat can redirect unauthenticated index-page requests
to the existing Microsoft Entra sign-in flow when auto-login is enabled.
"""

import ast
from pathlib import Path
from test_support.versioning import assert_app_version_at_least


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_FILE = ROOT_DIR / "application" / "single_app" / "app.py"
CONFIG_FILE = ROOT_DIR / "application" / "single_app" / "config.py"
IMPLEMENTED_VERSION = "0.250.209"


def _read_source(path):
    """Read a UTF-8 source file from the repository."""
    return path.read_text(encoding="utf-8")


def _find_function(tree, function_name):
    """Find a top-level function definition by name."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"Function {function_name} not found")


def _call_name(node):
    """Return the simple function name for a call node."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_auto_login_condition(node):
    """Return True when the AST node matches the configured unauthenticated redirect guard."""
    if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.And):
        return False

    has_flag_check = any(
        isinstance(value, ast.Name) and value.id == "ENABLE_AUTO_LOGIN_ON_INDEX"
        for value in node.values
    )
    has_missing_user_check = any(
        isinstance(value, ast.Compare)
        and isinstance(value.left, ast.Constant)
        and value.left.value == "user"
        and any(isinstance(operator, ast.NotIn) for operator in value.ops)
        and any(isinstance(comparator, ast.Name) and comparator.id == "session" for comparator in value.comparators)
        for value in node.values
    )

    return has_flag_check and has_missing_user_check


def test_auto_login_config_defaults_to_off():
    """Verify the opt-in auto-login setting is present and disabled by default."""
    print("Testing index auto-login config default...")

    config_source = _read_source(CONFIG_FILE)

    assert_app_version_at_least(IMPLEMENTED_VERSION)
    assert (
        'ENABLE_AUTO_LOGIN_ON_INDEX = os.getenv("ENABLE_AUTO_LOGIN_ON_INDEX", "false").lower() == "true"'
        in config_source
    ), "Expected ENABLE_AUTO_LOGIN_ON_INDEX to default off and opt in through the environment"

    print("Index auto-login config defaults off")


def test_index_redirects_unauthenticated_users_when_enabled():
    """Verify the index route uses the existing Entra login route for auto sign-in."""
    print("Testing index auto-login redirect contract...")

    app_tree = ast.parse(_read_source(APP_FILE), filename=str(APP_FILE))
    index_function = _find_function(app_tree, "index")
    first_statement = index_function.body[0]

    assert isinstance(first_statement, ast.If), "Expected index route to begin with the auto-login guard"
    assert _is_auto_login_condition(first_statement.test), "Expected auto-login guard to require flag and no user session"
    assert len(first_statement.body) == 1 and isinstance(first_statement.body[0], ast.Return), (
        "Expected auto-login guard to return a redirect immediately"
    )

    redirect_call = first_statement.body[0].value
    assert _call_name(redirect_call) == "redirect", "Expected auto-login guard to call redirect(...)"
    assert redirect_call.args and _call_name(redirect_call.args[0]) == "url_for", (
        "Expected auto-login guard to redirect through url_for(...)"
    )
    url_for_call = redirect_call.args[0]
    assert url_for_call.args and isinstance(url_for_call.args[0], ast.Constant), (
        "Expected url_for target to be a static endpoint name"
    )
    assert url_for_call.args[0].value == "frontend_authentication.login", (
        "Expected index auto-login to reuse the existing Microsoft Entra login route"
    )

    print("Index auto-login redirects unauthenticated users through the login route")


if __name__ == "__main__":
    tests = [
        test_auto_login_config_defaults_to_off,
        test_index_redirects_unauthenticated_users_when_enabled,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except AssertionError as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(tests)} tests passed")
    raise SystemExit(0 if success else 1)
