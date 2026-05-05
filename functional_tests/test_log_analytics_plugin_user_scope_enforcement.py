# test_log_analytics_plugin_user_scope_enforcement.py
"""
Functional test for Log Analytics plugin user-scope enforcement.
Version: 0.241.022
Implemented in: 0.241.012; 0.241.022

This test ensures the Log Analytics plugin no longer exposes a caller-controlled
`user_id` parameter, query history binds to the authenticated user on the
server, shared user-settings helpers deny cross-user access by default, and
the reviewed Control Center admin flows opt into an explicit cross-user bypass.
"""

import ast
import logging
import os
import sys
import types


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_ANALYTICS_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "semantic_kernel_plugins",
    "log_analytics_plugin.py",
)
SETTINGS_FILE = os.path.join(ROOT_DIR, "application", "single_app", "functions_settings.py")
CONTROL_CENTER_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_backend_control_center.py")
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
FIX_DOC = os.path.join(
    ROOT_DIR,
    "docs",
    "explanation",
    "fixes",
    "v0.241.012",
    "LOG_ANALYTICS_PLUGIN_USER_SCOPE_ENFORCEMENT_FIX.md",
)


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8-sig") as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def load_functions(file_path, function_names, namespace=None):
    source = read_file_text(file_path)
    parsed = ast.parse(source, filename=file_path)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert len(selected_nodes) == len(function_names), (
        f"Expected functions {sorted(function_names)} in {file_path}, "
        f"found {[node.name for node in selected_nodes]}"
    )
    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec_namespace = dict(namespace or {})
    exec(compile(module, file_path, "exec"), exec_namespace)
    return exec_namespace, source


def get_method_arg_names(file_path, method_name):
    source = read_file_text(file_path)
    parsed = ast.parse(source, filename=file_path)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            return [argument.arg for argument in node.args.args]
    raise AssertionError(f"Method {method_name} not found in {file_path}")


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f"Function {function_name} not found")


def test_log_analytics_plugin_no_longer_exposes_user_id():
    """Verify the tool surface and runtime logic bind query history to the authenticated user."""
    print("🔍 Testing Log Analytics plugin user-scope binding...")

    source = read_file_text(LOG_ANALYTICS_FILE)
    metadata_source = extract_function_source(source, "_generate_metadata")
    run_query_source = extract_function_source(source, "run_query")
    history_source = extract_function_source(source, "get_query_history")

    assert "User ID for query history tracking" not in metadata_source
    assert get_method_arg_names(LOG_ANALYTICS_FILE, "run_query") == ["self", "query", "timespan"]
    assert get_method_arg_names(LOG_ANALYTICS_FILE, "get_query_history") == ["self", "limit"]
    assert "history_user_id = self._get_authenticated_history_user_id()" in run_query_source
    assert "self._save_query_history_to_cosmos(history_user_id, query)" in run_query_source
    assert "user_id = self._get_authenticated_history_user_id()" in history_source

    print("✅ Log Analytics plugin user-scope binding passed")


def test_user_settings_helpers_deny_cross_user_access_without_bypass():
    """Verify shared settings helpers default-deny cross-user access during request context."""
    print("🔍 Testing shared user-settings access control...")

    fake_auth_module = types.ModuleType("functions_authentication")
    fake_auth_module.get_current_user_id = lambda: "actor-user"
    original_auth_module = sys.modules.get("functions_authentication")
    sys.modules["functions_authentication"] = fake_auth_module

    try:
        namespace, source = load_functions(
            SETTINGS_FILE,
            {"_authorize_user_settings_access", "_should_sync_session_profile"},
            {
                "has_request_context": lambda: True,
                "log_event": lambda *args, **kwargs: None,
                "logging": logging,
            },
        )

        authorize_access = namespace["_authorize_user_settings_access"]
        should_sync_profile = namespace["_should_sync_session_profile"]

        assert authorize_access("actor-user", "read") == "actor-user"

        try:
            authorize_access("target-user", "update")
        except PermissionError as exc:
            assert "another user" in str(exc)
        else:
            raise AssertionError("Expected cross-user settings update to raise PermissionError")

        assert authorize_access("target-user", "update", allow_cross_user=True) is None
        assert should_sync_profile("actor-user", "actor-user") is True
        assert should_sync_profile("target-user", "actor-user") is False
        assert should_sync_profile("target-user", "actor-user", allow_cross_user=True) is False

        assert "def get_user_settings(user_id, allow_cross_user=False):" in source
        assert "def update_user_settings(user_id, settings_to_update, allow_cross_user=False):" in source
    finally:
        if original_auth_module is None:
            sys.modules.pop("functions_authentication", None)
        else:
            sys.modules["functions_authentication"] = original_auth_module

    print("✅ Shared user-settings access control passed")


def test_control_center_cross_user_updates_opt_into_bypass():
    """Verify the reviewed admin routes explicitly opt into cross-user settings writes."""
    print("🔍 Testing Control Center admin bypass call sites...")

    source = read_file_text(CONTROL_CENTER_FILE)

    required_snippets = [
        "update_user_settings(user.get('id'), settings_update, allow_cross_user=True)",
        "update_user_settings(user_id, access_settings, allow_cross_user=True)",
        "update_user_settings(user_id, file_upload_settings, allow_cross_user=True)",
        "update_user_settings(user_id, update_settings, allow_cross_user=True)",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing explicit Control Center bypass snippets: {missing}"

    print("✅ Control Center admin bypass call sites passed")


def test_fix_documentation_and_version_exist():
    """Verify the config version bump and fix document landed for the f016 pass."""
    print("🔍 Testing f016 documentation and version...")

    assert read_config_version() == "0.241.022"
    assert os.path.exists(FIX_DOC), f"Expected fix documentation at {FIX_DOC}"

    print("✅ f016 documentation and version passed")


if __name__ == "__main__":
    tests = [
        test_log_analytics_plugin_no_longer_exposes_user_id,
        test_user_settings_helpers_deny_cross_user_access_without_bypass,
        test_control_center_cross_user_updates_opt_into_bypass,
        test_fix_documentation_and_version_exist,
    ]

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        test()

    print(f"\n📊 Results: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)