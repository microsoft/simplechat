#!/usr/bin/env python3
# test_action_test_connection_endpoints.py
"""
Functional test for the action Test Connection endpoints.
Version: 0.250.217
Implemented in: 0.250.217

This test ensures the eight action connection test routes are registered on the
admin_plugins Blueprint with the required Swagger and authentication decorators,
that every route delegates to a dedicated tester in
functions_action_connection_tests, and that the MCP route keeps the same stdio
scope restriction and outbound destination policy as MCP tool discovery.

Refs microsoft/simplechat#1267
"""

import ast
import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

ROUTE_FILE = os.path.join(REPO_ROOT, "application", "single_app", "route_backend_plugins.py")
TESTER_FILE = os.path.join(REPO_ROOT, "application", "single_app", "functions_action_connection_tests.py")
KEYVAULT_FILE = os.path.join(REPO_ROOT, "application", "single_app", "functions_keyvault.py")

EXPECTED_ROUTES = {
    "/api/plugins/test-openapi-connection": "test_openapi_connection",
    "/api/plugins/test-azure-maps-connection": "test_azure_maps_connection",
    "/api/plugins/test-blob-storage-connection": "test_blob_storage_connection",
    "/api/plugins/test-databricks-connection": "test_databricks_connection",
    "/api/plugins/test-log-analytics-connection": "test_log_analytics_connection",
    "/api/plugins/test-mcp-connection": "test_mcp_connection",
    "/api/plugins/test-snowflake-connection": "test_snowflake_connection",
    "/api/plugins/test-tableau-connection": "test_tableau_connection",
}

REQUIRED_DECORATORS = ("swagger_route", "login_required", "user_required")


def _dotted_name(node):
    """Return a dotted attribute name for a decorator expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    return ""


def _parse_module(file_path):
    with open(file_path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=file_path)


def _iter_route_functions(tree):
    """Yield (path, methods, decorator_names, function_node) for every decorated route."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue

        decorator_names = tuple(
            _dotted_name(item.func if isinstance(item, ast.Call) else item)
            for item in node.decorator_list
        )

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not _dotted_name(decorator.func).endswith(".route"):
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue

            methods = []
            for keyword in decorator.keywords:
                if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                    methods = [
                        element.value
                        for element in keyword.value.elts
                        if isinstance(element, ast.Constant)
                    ]

            yield decorator.args[0].value, methods, decorator_names, node, _dotted_name(decorator.func)


def test_routes_are_registered_with_required_security_decorators():
    """Verify each connection test route exists on bpap with the full decorator stack."""
    print("Testing action connection test route registration...")

    try:
        assert_app_version_at_least(
            "0.250.217",
            reason="Action Test Connection endpoints were added in 0.250.217.",
        )

        tree = _parse_module(ROUTE_FILE)
        discovered = {}
        for path, methods, decorator_names, node, route_target in _iter_route_functions(tree):
            if path in EXPECTED_ROUTES:
                discovered[path] = {
                    "methods": methods,
                    "decorators": decorator_names,
                    "function_name": node.name,
                    "route_target": route_target,
                }

        missing_routes = sorted(set(EXPECTED_ROUTES) - set(discovered))
        assert not missing_routes, f"Missing action connection test routes: {missing_routes}"

        for path, details in sorted(discovered.items()):
            assert details["route_target"] == "bpap.route", (
                f"{path} must be registered on the admin_plugins Blueprint, found {details['route_target']}."
            )
            assert details["methods"] == ["POST"], (
                f"{path} must only accept POST, found {details['methods']}."
            )
            for required_decorator in REQUIRED_DECORATORS:
                assert required_decorator in details["decorators"], (
                    f"{path} is missing the @{required_decorator} decorator."
                )

        print(f"Verified {len(discovered)} routes with required decorators.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_every_route_delegates_to_a_dedicated_tester():
    """Verify each route calls _run_action_connection_test with its matching tester."""
    print("Testing action connection test route delegation...")

    try:
        route_source = open(ROUTE_FILE, "r", encoding="utf-8").read()
        tester_tree = _parse_module(TESTER_FILE)

        exported_testers = {
            node.name
            for node in tester_tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        }

        missing_testers = sorted(set(EXPECTED_ROUTES.values()) - exported_testers)
        assert not missing_testers, (
            f"functions_action_connection_tests is missing testers: {missing_testers}"
        )

        assert "_prepare_action_test_manifest" in route_source, (
            "route_backend_plugins.py must define the shared _prepare_action_test_manifest helper."
        )
        assert "_run_action_connection_test" in route_source, (
            "route_backend_plugins.py must define the shared _run_action_connection_test helper."
        )

        for tester_name in sorted(EXPECTED_ROUTES.values()):
            assert f"_run_action_connection_test(" in route_source, (
                "Routes must delegate through _run_action_connection_test."
            )
            assert tester_name in route_source, (
                f"route_backend_plugins.py must reference the {tester_name} tester."
            )

        print(f"Verified {len(EXPECTED_ROUTES)} route-to-tester delegations.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_mcp_route_keeps_discovery_security_parity():
    """Verify the MCP test route enforces stdio scope limits and destination policy."""
    print("Testing MCP connection test security parity...")

    try:
        tree = _parse_module(ROUTE_FILE)

        mcp_route_node = None
        for path, _methods, _decorators, node, _route_target in _iter_route_functions(tree):
            if path == "/api/plugins/test-mcp-connection":
                mcp_route_node = node
                break

        assert mcp_route_node is not None, "The MCP connection test route was not found."

        mcp_route_source = ast.unparse(mcp_route_node)
        assert "_reject_non_admin_mcp_stdio" in mcp_route_source, (
            "The MCP connection test route must reject stdio transport outside global scope."
        )
        assert "_enforce_mcp_destination_policy" in mcp_route_source, (
            "The MCP connection test route must enforce the outbound destination policy."
        )
        assert "mcp_connection_test" in mcp_route_source, (
            "The MCP destination policy call must pass a distinct operation label."
        )

        print("MCP connection test route matches discovery security guarantees.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_secret_references_are_resolved_within_the_action_scope():
    """Verify caller-supplied Key Vault references cannot be resolved across scopes.

    A reference name arrives in the request body, so resolving it without a scope check
    would let any authenticated user read another user's, group's, or global action's
    secret and forward it to a caller-controlled endpoint.
    """
    print("Testing action test secret scope enforcement...")

    try:
        route_source = open(ROUTE_FILE, "r", encoding="utf-8").read()
        tree = _parse_module(ROUTE_FILE)

        scoped_helper = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_resolve_secret_value_for_action_test":
                scoped_helper = node
                break

        assert scoped_helper is not None, (
            "route_backend_plugins.py must define the scoped _resolve_secret_value_for_action_test helper."
        )

        helper_source = ast.unparse(scoped_helper)
        assert "resolve_secret_reference_for_context" in helper_source, (
            "The action test secret helper must resolve through the scope-checked Key Vault resolver."
        )

        helper_argument_names = [argument.arg for argument in scoped_helper.args.args]
        for required_argument in ("scope_value", "scope", "allowed_sources"):
            assert required_argument in helper_argument_names, (
                f"The action test secret helper must require an explicit {required_argument} argument."
            )
        assert scoped_helper.args.defaults == [], (
            "The action test secret helper must not default its scope or source arguments."
        )
        assert "if not scope_value or not scope" in helper_source, (
            "The action test secret helper must fail closed when the scope cannot be determined."
        )

        # The source constants must match how keyvault_plugin_get_helper stored each field,
        # otherwise editing an action and testing it without retyping the secret breaks.
        keyvault_source = open(KEYVAULT_FILE, "r", encoding="utf-8").read()
        auth_read_source = re.search(
            r"for auth_field in \('key',.*?allowed_sources=\{(\"|')([a-z-]+)(\"|')\}",
            keyvault_source,
            re.DOTALL,
        )
        assert auth_read_source, "Unable to locate the auth field Key Vault source in functions_keyvault.py."
        expected_auth_source = auth_read_source.group(2)

        route_source_normalized = route_source.replace('"', "'")
        assert f"ACTION_AUTH_SECRET_SOURCES = {{'{expected_auth_source}'}}" in route_source_normalized, (
            f"auth.* references are stored with source '{expected_auth_source}', "
            "so ACTION_AUTH_SECRET_SOURCES must match or edit-mode connection tests will fail."
        )
        assert "ACTION_ADDITIONAL_SECRET_SOURCES = {'action-addset'}" in route_source_normalized, (
            "additionalFields.* and MCP custom header references are stored with source 'action-addset'."
        )
        assert expected_auth_source != "action-addset", (
            "auth.* and additionalFields.* must not share a source; the distinction is what this test guards."
        )

        prepare_node = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_prepare_action_test_manifest":
                prepare_node = node
                break

        assert prepare_node is not None, "_prepare_action_test_manifest was not found."

        prepare_source = ast.unparse(prepare_node)
        assert "_resolve_plugin_secret_context(existing_plugin, user_id)" in prepare_source, (
            "The action test manifest must derive the Key Vault scope from the loaded action, not the request body."
        )
        assert "ACTION_AUTH_SECRET_SOURCES" in prepare_source, (
            "auth.key must be resolved with the auth secret source."
        )
        assert "ACTION_ADDITIONAL_SECRET_SOURCES" in prepare_source, (
            "additionalFields secrets must be resolved with the additional-field secret source."
        )
        assert "_resolve_secret_value_for_plugin_test" not in prepare_source, (
            "The action test manifest must not use the unscoped Key Vault resolver."
        )

        # No connection test route may fall back to the unscoped resolver.
        unscoped_uses = re.findall(r"_resolve_secret_value_for_plugin_test\b", route_source)
        assert not unscoped_uses, (
            f"The unscoped Key Vault resolver must not be used, found {len(unscoped_uses)} references."
        )

        # The scoped helper must be the single chokepoint for resolving a reference to a value,
        # so every path inherits the scope, source, and fail-closed checks.
        resolver_call_sites = re.findall(r"^\s+return resolve_secret_reference_for_context\(", route_source, re.MULTILINE)
        assert len(resolver_call_sites) == 1, (
            "resolve_secret_reference_for_context must only be called from _resolve_secret_value_for_action_test, "
            f"found {len(resolver_call_sites)} call sites."
        )

        # Global actions are admin-managed, so the shared loader must gate them for every route.
        loader_node = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_load_existing_plugin_for_test":
                loader_node = node
                break

        assert loader_node is not None, "_load_existing_plugin_for_test was not found."
        loader_source = ast.unparse(loader_node)
        assert "get_global_action" in loader_source, "The loader must handle the global action scope."
        assert "PermissionError" in loader_source and "Admin" in loader_source, (
            "Loading a global action for testing must require the Admin role, so routes that do not "
            "resolve an action identity scope still inherit the check."
        )

        print("Action test secrets resolve only within the owning action's scope and source.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_routes_are_registered_with_required_security_decorators,
        test_every_route_delegates_to_a_dedicated_tester,
        test_mcp_route_keeps_discovery_security_parity,
        test_secret_references_are_resolved_within_the_action_scope,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
