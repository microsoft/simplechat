# test_getatoken_missing_code_redirect.py
"""
Functional test for direct getAToken callback visits without an OAuth code.
Version: 0.250.129
Implemented in: 0.250.129

This test ensures that users who reach /getAToken directly are redirected to
the home sign-in page instead of seeing an authorization-code error.
"""

import ast
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
AUTH_ROUTE_PATH = ROOT_DIR / "application" / "single_app" / "route_frontend_authentication.py"


def _find_authorized_function(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "authorized":
            return node
    raise AssertionError("Could not find the /getAToken authorized route function.")


def _is_missing_code_branch(node):
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Name)
        and node.test.operand.id == "code"
    )


def _returns_home_redirect(node):
    if not isinstance(node, ast.Return):
        return False
    value = node.value
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "redirect"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Call)
        and isinstance(value.args[0].func, ast.Name)
        and value.args[0].func.id == "url_for"
        and len(value.args[0].args) == 1
        and isinstance(value.args[0].args[0], ast.Constant)
        and value.args[0].args[0].value == "public_app.index"
    )


def _returns_authorization_code_error(node):
    if not isinstance(node, ast.Return):
        return False
    value = node.value
    if isinstance(value, ast.Constant):
        return value.value == "Authorization code not found"
    if isinstance(value, ast.Tuple):
        return any(
            isinstance(element, ast.Constant)
            and element.value == "Authorization code not found"
            for element in value.elts
        )
    return False


def test_getatoken_missing_code_redirects_home():
    """Validate that /getAToken without a code redirects to the sign-in entry point."""
    print("Testing /getAToken missing authorization-code redirect...")

    tree = ast.parse(AUTH_ROUTE_PATH.read_text(encoding="utf-8"))
    authorized_function = _find_authorized_function(tree)
    missing_code_branches = [
        node for node in ast.walk(authorized_function) if _is_missing_code_branch(node)
    ]

    if len(missing_code_branches) != 1:
        raise AssertionError(f"Expected exactly one missing-code branch, found {len(missing_code_branches)}.")

    missing_code_branch = missing_code_branches[0]
    if not any(_returns_home_redirect(node) for node in missing_code_branch.body):
        raise AssertionError("Expected missing-code branch to redirect to public_app.index.")

    if any(_returns_authorization_code_error(node) for node in missing_code_branch.body):
        raise AssertionError("Missing-code branch must not return the authorization-code error to users.")

    print("/getAToken missing-code requests redirect to the sign-in entry point.")


if __name__ == "__main__":
    try:
        test_getatoken_missing_code_redirects_home()
    except Exception as exc:
        print(f"Test failed: {exc}")
        sys.exit(1)

    print("All getAToken missing-code redirect tests passed")
