#!/usr/bin/env python3
"""
Functional test for idle session auto-logout.
Version: 0.239.008
Implemented in: 0.239.008

This test ensures that server-side idle timeout enforcement and
client-side warning/logout wiring are present and sourced from admin settings.
"""

import os
import sys
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


def test_server_idle_timeout_wiring():
    """Validate idle-timeout and heartbeat backend wiring exists."""
    print("🔍 Testing server-side idle-timeout wiring...")

    app_content = _read_file("application", "single_app", "app.py")
    config_content = _read_file("application", "single_app", "config.py")
    auth_route_content = _read_file("application", "single_app", "route_frontend_authentication.py")

    required_app_markers = [
        "def get_idle_timeout_settings(settings=None):",
        "def is_idle_timeout_enabled(settings=None):",
        "settings.get('idle_timeout_minutes', 30)",
        "settings.get('idle_warning_minutes', 28)",
        "def enforce_idle_session_timeout():",
        "if not is_idle_timeout_enabled(request_settings):",
        "last_activity_epoch",
        "IDLE_TIMEOUT_EXEMPT_PATHS",
        "'/logout/local'",
        "redirect(url_for('local_logout'))",
        "@app.route('/api/session/heartbeat', methods=['POST'])",
        "def session_heartbeat():",
        "idle_timeout_minutes, _ = get_idle_timeout_settings(request_settings)"
    ]

    missing_app_markers = [marker for marker in required_app_markers if marker not in app_content]
    assert not missing_app_markers, f"Missing backend markers in app.py: {missing_app_markers}"

    required_config_markers = [
        "VERSION = \"0.239.008\""
    ]

    missing_config_markers = [marker for marker in required_config_markers if marker not in config_content]
    assert not missing_config_markers, f"Missing config markers: {missing_config_markers}"

    required_auth_markers = [
        "session.pop(\"last_activity_epoch\", None)",
        "session[\"last_activity_epoch\"] = int(time.time())"
    ]

    missing_auth_markers = [marker for marker in required_auth_markers if marker not in auth_route_content]
    assert not missing_auth_markers, f"Missing authentication flow markers: {missing_auth_markers}"

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
        "localLogoutUrl",
        "fullSsoLogoutUrl",
        "enabled: {{ idle_timeout_enabled | default(true) | tojson }}",
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
        "logoutNow",
        "scheduleIdleTimers",
        "idleTimeoutWarningModal",
        "idleStaySignedInButton",
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
        "'enable_idle_timeout': True",
        "'idle_timeout_minutes': 30",
        "'idle_warning_minutes': 28"
    ]
    missing_settings_markers = [marker for marker in required_settings_markers if marker not in settings_content]
    assert not missing_settings_markers, f"Missing settings default markers: {missing_settings_markers}"

    required_route_markers = [
        "form_data.get('enable_idle_timeout')",
        "form_data.get('idle_timeout_minutes')",
        "form_data.get('idle_warning_minutes')",
        "'enable_idle_timeout': enable_idle_timeout",
        "'idle_timeout_minutes': idle_timeout_minutes",
        "'idle_warning_minutes': idle_warning_minutes"
    ]
    missing_route_markers = [marker for marker in required_route_markers if marker not in admin_route_content]
    assert not missing_route_markers, f"Missing admin route markers: {missing_route_markers}"

    required_template_markers = [
        "id=\"enable_idle_timeout\"",
        "name=\"enable_idle_timeout\"",
        "id=\"idle_timeout_settings\"",
        "id=\"idle_timeout_minutes\"",
        "name=\"idle_timeout_minutes\"",
        "id=\"idle_warning_minutes\"",
        "name=\"idle_warning_minutes\""
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
