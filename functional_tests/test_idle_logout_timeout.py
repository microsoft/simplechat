#!/usr/bin/env python3
# test_idle_logout_timeout.py
"""
Functional test for idle session auto-logout.
Version: v0.240.002
Implemented in: v0.240.002

This test ensures that server-side idle timeout enforcement and
client-side warning/logout wiring are present and sourced from admin settings.
"""

import os
import sys
import ast
import traceback

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _read_file(*path_parts):
    file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        *path_parts
    )
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def _parse_python_file(*path_parts):
    """Read and parse a Python source file into AST."""
    source = _read_file(*path_parts)
    return source, ast.parse(source)


def _find_top_level_function(module_tree, function_name):
    """Find a top-level function definition by name."""
    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    return None


def _find_nested_function(parent_function, function_name):
    """Find a nested function definition by name in a parent function body."""
    for node in parent_function.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    return None


def _extract_constant_string_set(value_node):
    """Extract constant string values from supported AST set expressions."""
    if isinstance(value_node, ast.Set):
        return {
            element.value
            for element in value_node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }

    if (
        isinstance(value_node, ast.Call)
        and isinstance(value_node.func, ast.Name)
        and value_node.func.id == "set"
        and len(value_node.args) == 1
        and isinstance(value_node.args[0], (ast.Set, ast.List, ast.Tuple))
    ):
        return {
            element.value
            for element in value_node.args[0].elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }

    return set()


def _get_top_level_constant_string_set(module_tree, variable_name):
    """Return constant string values for a top-level set variable assignment."""
    for node in module_tree.body:
        if isinstance(node, ast.Assign):
            has_target = any(
                isinstance(target, ast.Name) and target.id == variable_name
                for target in node.targets
            )
            if has_target:
                return _extract_constant_string_set(node.value)

        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == variable_name
            and node.value is not None
        ):
            return _extract_constant_string_set(node.value)

    return set()


def test_server_idle_timeout_wiring():
    """Validate idle-timeout and heartbeat backend wiring exists."""
    print("🔍 Testing server-side idle-timeout wiring...")

    app_content, app_tree = _parse_python_file("application", "single_app", "app.py")
    config_content = _read_file("application", "single_app", "config.py")
    _, auth_tree = _parse_python_file("application", "single_app", "route_frontend_authentication.py")
    _, config_tree = _parse_python_file("application", "single_app", "config.py")

    required_app_functions = [
        "get_idle_timeout_settings",
        "is_idle_timeout_enabled",
        "record_request_settings_source",
        "get_request_settings",
        "enforce_idle_session_timeout",
        "session_heartbeat"
    ]
    missing_app_functions = [
        function_name for function_name in required_app_functions
        if _find_top_level_function(app_tree, function_name) is None
    ]
    assert not missing_app_functions, f"Missing backend functions in app.py: {missing_app_functions}"

    removed_app_functions = [
        "load_request_settings_cache"
    ]
    unexpected_app_functions = [
        function_name for function_name in removed_app_functions
        if _find_top_level_function(app_tree, function_name) is not None
    ]
    assert not unexpected_app_functions, (
        f"Unexpected removed backend functions in app.py: {unexpected_app_functions}"
    )

    has_settings_source_counter_dict = any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "settings_source_counters" for target in node.targets)
        and isinstance(node.value, ast.Dict)
        and len(node.value.keys) == 0
        for node in app_tree.body
    )
    assert has_settings_source_counter_dict, "Missing settings_source_counters = {} assignment"

    required_settings_source_logging_markers = [
        "settings_source_last_observed = None",
        "settings_source_last_non_cache_log_epoch = 0",
        "settings_source_non_cache_log_interval_seconds = 60",
        "should_log_non_cache_info",
        "if should_log_non_cache_info:"
    ]
    missing_settings_source_logging_markers = [
        marker for marker in required_settings_source_logging_markers
        if marker not in app_content
    ]
    assert not missing_settings_source_logging_markers, (
        f"Missing settings-source logging throttling markers: {missing_settings_source_logging_markers}"
    )

    idle_settings_def = _find_top_level_function(app_tree, "get_idle_timeout_settings")
    has_idle_timeout_default_get = False
    has_idle_warning_default_get = False
    for node in ast.walk(idle_settings_def):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "settings"
            and node.func.attr == "get"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[1], ast.Constant)
        ):
            if node.args[0].value == "idle_timeout_minutes" and node.args[1].value == 30:
                has_idle_timeout_default_get = True
            if node.args[0].value == "idle_warning_minutes" and node.args[1].value == 28:
                has_idle_warning_default_get = True

    assert has_idle_timeout_default_get, "Missing settings.get('idle_timeout_minutes', 30) in get_idle_timeout_settings"
    assert has_idle_warning_default_get, "Missing settings.get('idle_warning_minutes', 28) in get_idle_timeout_settings"

    has_include_source_get_settings = False
    has_record_settings_source_call = False
    for node in ast.walk(app_tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "get_settings"
            and any(
                isinstance(keyword, ast.keyword)
                and keyword.arg == "include_source"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
        ):
            has_include_source_get_settings = True

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "record_request_settings_source"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "settings_source"
        ):
            has_record_settings_source_call = True

    assert has_include_source_get_settings, "Missing get_settings(include_source=True) wiring in app.py"
    assert has_record_settings_source_call, "Missing record_request_settings_source(settings_source) wiring in app.py"

    idle_timeout_exempt_paths = _get_top_level_constant_string_set(
        config_tree,
        "IDLE_TIMEOUT_EXEMPT_PATHS"
    )
    assert "/logout/local" in idle_timeout_exempt_paths, "Missing '/logout/local' in IDLE_TIMEOUT_EXEMPT_PATHS"

    enforce_idle_timeout_def = _find_top_level_function(app_tree, "enforce_idle_session_timeout")
    has_is_idle_timeout_enabled_guard = False
    has_local_logout_redirect = False
    for node in ast.walk(enforce_idle_timeout_def):
        if isinstance(node, ast.If):
            test_node = node.test
            if (
                isinstance(test_node, ast.UnaryOp)
                and isinstance(test_node.op, ast.Not)
                and isinstance(test_node.operand, ast.Call)
                and isinstance(test_node.operand.func, ast.Name)
                and test_node.operand.func.id == "is_idle_timeout_enabled"
                and len(test_node.operand.args) == 1
                and isinstance(test_node.operand.args[0], ast.Name)
                and test_node.operand.args[0].id == "request_settings"
            ):
                has_is_idle_timeout_enabled_guard = True

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "redirect"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == "url_for"
            and len(node.args[0].args) == 1
            and isinstance(node.args[0].args[0], ast.Constant)
            and node.args[0].args[0].value == "local_logout"
        ):
            has_local_logout_redirect = True

    has_api_activity_seed_assignment = False
    for node in ast.walk(enforce_idle_timeout_def):
        if not isinstance(node, ast.If):
            continue

        test_node = node.test
        is_api_path_check = (
            isinstance(test_node, ast.Call)
            and isinstance(test_node.func, ast.Attribute)
            and isinstance(test_node.func.value, ast.Attribute)
            and isinstance(test_node.func.value.value, ast.Name)
            and test_node.func.value.value.id == "request"
            and test_node.func.value.attr == "path"
            and test_node.func.attr == "startswith"
            and len(test_node.args) == 1
            and isinstance(test_node.args[0], ast.Constant)
            and test_node.args[0].value == "/api/"
        )
        if not is_api_path_check:
            continue

        has_seed_assign_in_api_block = any(
            isinstance(inner_node, ast.Assign)
            and len(inner_node.targets) == 1
            and isinstance(inner_node.targets[0], ast.Subscript)
            and isinstance(inner_node.targets[0].value, ast.Name)
            and inner_node.targets[0].value.id == "session"
            and isinstance(inner_node.targets[0].slice, ast.Constant)
            and inner_node.targets[0].slice.value == "last_activity_epoch"
            and isinstance(inner_node.value, ast.Name)
            and inner_node.value.id == "now_epoch"
            for inner_node in ast.walk(node)
        )
        if has_seed_assign_in_api_block:
            has_api_activity_seed_assignment = True
            break

    assert has_is_idle_timeout_enabled_guard, "Missing 'if not is_idle_timeout_enabled(request_settings)' guard"
    assert has_local_logout_redirect, "Missing redirect(url_for('local_logout')) in enforce_idle_session_timeout"
    assert has_api_activity_seed_assignment, "Missing API-path last_activity_epoch seeding in enforce_idle_session_timeout"

    session_heartbeat_def = _find_top_level_function(app_tree, "session_heartbeat")
    has_heartbeat_refresh_call = False
    for node in ast.walk(session_heartbeat_def):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "get_idle_timeout_settings"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == "get_request_settings"
        ):
            has_heartbeat_refresh_call = True
    assert has_heartbeat_refresh_call, "Missing get_idle_timeout_settings(get_request_settings()) in session_heartbeat"

    required_config_markers = [
        "VERSION = \"v0.240.002\""
    ]

    missing_config_markers = [marker for marker in required_config_markers if marker not in config_content]
    assert not missing_config_markers, f"Missing config markers: {missing_config_markers}"

    auth_register_def = _find_top_level_function(auth_tree, "register_route_frontend_authentication")
    assert auth_register_def is not None, "Missing register_route_frontend_authentication function"

    login_def = _find_nested_function(auth_register_def, "login")
    authorized_def = _find_nested_function(auth_register_def, "authorized")
    local_logout_def = _find_nested_function(auth_register_def, "local_logout")
    assert login_def is not None, "Missing login route function in authentication route"
    assert authorized_def is not None, "Missing authorized route function in authentication route"
    assert local_logout_def is not None, "Missing local_logout route function in authentication route"

    has_last_activity_pop = False
    for node in ast.walk(login_def):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "session"
            and node.func.attr == "pop"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "last_activity_epoch"
        ):
            has_last_activity_pop = True
    assert has_last_activity_pop, "Missing session.pop('last_activity_epoch', ...) in login flow"

    has_last_activity_assignment = False
    for node in ast.walk(authorized_def):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "session"
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "last_activity_epoch"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "int"
                and len(node.value.args) == 1
                and isinstance(node.value.args[0], ast.Call)
                and isinstance(node.value.args[0].func, ast.Attribute)
                and isinstance(node.value.args[0].func.value, ast.Name)
                and node.value.args[0].func.value.id == "time"
                and node.value.args[0].func.attr == "time"
            ):
                has_last_activity_assignment = True
    assert has_last_activity_assignment, "Missing session['last_activity_epoch'] = int(time.time()) in authorized flow"

    has_relative_index_url_for = False
    has_external_index_url_for = False
    for node in ast.walk(local_logout_def):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "url_for"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "index"
        ):
            if len(node.keywords) == 0:
                has_relative_index_url_for = True

            has_external_keyword = any(
                isinstance(keyword, ast.keyword)
                and keyword.arg == "_external"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
            if has_external_keyword:
                has_external_index_url_for = True

    assert has_relative_index_url_for, "Missing relative url_for('index') fallback in local_logout"
    assert not has_external_index_url_for, "Unexpected url_for('index', _external=True) in local_logout"

    print("✅ Server-side idle-timeout wiring is present")


def test_base_template_warning_modal_wiring():
    """Validate warning modal and JS config are wired in base template."""
    print("🔍 Testing base template warning modal wiring...")

    base_html_content = _read_file("application", "single_app", "templates", "base.html")

    required_markers = [
        "window.idleLogoutConfig",
        "idleTimeoutWarningModal",
        "idleTimeoutCountdown",
        "idleStaySignedInButton",
        "idleLogoutNowButton",
        "js/idle-logout-warning.js",
        "idle_warning_message",
        "app_settings.idle_warning_message",
        "localLogoutUrl",
        "fullSsoLogoutUrl",
        "'enabled': idle_timeout_enabled | default(false)",
        "| tojson | safe",
        "session_heartbeat"
    ]

    missing_markers = [marker for marker in required_markers if marker not in base_html_content]
    assert not missing_markers, f"Missing base template markers: {missing_markers}"

    print("✅ Base template warning modal wiring is present")


def test_idle_warning_javascript_wiring():
    """Validate client-side warning and heartbeat logic markers exist."""
    print("🔍 Testing idle warning JavaScript wiring...")

    js_content = _read_file("application", "single_app", "static", "js", "idle-logout-warning.js")

    required_markers = [
        "heartbeatUrl",
        "localLogoutUrl",
        "fullSsoLogoutUrl",
        "warningMinutes",
        "const warningDisabled = warningMinutes === timeoutMinutes",
        "if (!warningDisabled)",
        "logoutNow",
        "scheduleIdleTimers",
        "idleTimeoutWarningModal",
        "idleStaySignedInButton",
        "let lastServerHeartbeatAt = 0",
        "const HEARTBEAT_MIN_INTERVAL_MS = Math.min(60000, timeoutMs / 2)",
        "response.status === 401 || response.status === 403",
        "const responseBody = await response.clone().json()",
        "responseBody && responseBody.requires_reauth",
        "fetch(mergedConfig.heartbeatUrl",
        "const logoutTarget = mergedConfig.localLogoutUrl || mergedConfig.fullSsoLogoutUrl || mergedConfig.logoutUrl",
        "window.location.href = logoutTarget"
    ]

    missing_markers = [marker for marker in required_markers if marker not in js_content]
    assert not missing_markers, f"Missing JavaScript markers: {missing_markers}"

    print("✅ Client-side idle warning/logout wiring is present")


def test_admin_idle_settings_wiring():
    """Validate admin settings and Cosmos defaults for idle timeout are wired."""
    print("🔍 Testing admin idle settings wiring...")

    settings_content = _read_file("application", "single_app", "functions_settings.py")
    admin_route_content = _read_file("application", "single_app", "route_frontend_admin_settings.py")
    admin_template_content = _read_file("application", "single_app", "templates", "admin_settings.html")

    required_settings_markers = [
        "'enable_idle_timeout': False",
        "'idle_timeout_minutes': 30",
        "'idle_warning_minutes': 28",
        "'idle_warning_message': \"You've been inactive for a while.\""
    ]
    missing_settings_markers = [marker for marker in required_settings_markers if marker not in settings_content]
    assert not missing_settings_markers, f"Missing settings default markers: {missing_settings_markers}"

    required_route_markers = [
        "form_data.get('enable_idle_timeout')",
        "form_data.get('idle_timeout_minutes')",
        "form_data.get('idle_warning_minutes')",
        "max(10, parse_admin_int(form_data.get('idle_timeout_minutes')",
        "idle_warning_message',",
        "'enable_idle_timeout': enable_idle_timeout",
        "'idle_timeout_minutes': idle_timeout_minutes",
        "'idle_warning_minutes': idle_warning_minutes",
        "'idle_warning_message': idle_warning_message"
    ]
    missing_route_markers = [marker for marker in required_route_markers if marker not in admin_route_content]
    assert not missing_route_markers, f"Missing admin route markers: {missing_route_markers}"

    required_template_markers = [
        "id=\"enable_idle_timeout\"",
        "name=\"enable_idle_timeout\"",
        "id=\"idle_timeout_settings\"",
        "id=\"idle_timeout_minutes\"",
        "name=\"idle_timeout_minutes\"",
        "min=\"10\"",
        "id=\"idle_warning_minutes\"",
        "name=\"idle_warning_minutes\"",
        "id=\"idle_warning_message\"",
        "name=\"idle_warning_message\""
    ]
    missing_template_markers = [marker for marker in required_template_markers if marker not in admin_template_content]
    assert not missing_template_markers, f"Missing admin template markers: {missing_template_markers}"

    print("✅ Admin idle settings wiring is present")


def main():
    """Run all idle-timeout functional checks."""
    print("🧪 Running Idle Timeout Functional Tests...\n")

    tests = [
        test_server_idle_timeout_wiring,
        test_base_template_warning_modal_wiring,
        test_idle_warning_javascript_wiring,
        test_admin_idle_settings_wiring
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except AssertionError as error:
            print(f"❌ {test.__name__} failed: {error}")
            results.append(False)
        except Exception as error:
            print(f"❌ {test.__name__} error: {error}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")

    if success:
        print("✅ All idle-timeout functional tests passed!")
    else:
        print("❌ Some idle-timeout functional tests failed.")

    return success


if __name__ == "__main__":
    test_success = main()
    sys.exit(0 if test_success else 1)
