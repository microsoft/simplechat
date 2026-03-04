#!/usr/bin/env python3
"""
Functional test for idle session auto-logout.
Version: 0.238.026
Implemented in: 0.238.026

This test ensures that server-side idle timeout enforcement and
client-side warning/logout wiring are present for a 30-minute inactivity window.
"""

import os
import sys

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

    try:
        app_content = _read_file("application", "single_app", "app.py")
        config_content = _read_file("application", "single_app", "config.py")
        auth_route_content = _read_file("application", "single_app", "route_frontend_authentication.py")

        required_app_markers = [
            "def enforce_idle_session_timeout():",
            "last_activity_epoch",
            "IDLE_TIMEOUT_EXEMPT_PATHS",
            "'/logout/local'",
            "redirect(url_for('local_logout'))",
            "@app.route('/api/session/heartbeat', methods=['POST'])",
            "def session_heartbeat():"
        ]

        missing_app_markers = [marker for marker in required_app_markers if marker not in app_content]
        if missing_app_markers:
            print(f"❌ Missing backend markers in app.py: {missing_app_markers}")
            return False

        required_config_markers = [
            "IDLE_TIMEOUT_MINUTES",
            "IDLE_WARNING_MINUTES",
            "VERSION = \"0.238.026\""
        ]

        missing_config_markers = [marker for marker in required_config_markers if marker not in config_content]
        if missing_config_markers:
            print(f"❌ Missing config markers: {missing_config_markers}")
            return False

        required_auth_markers = [
            "session.pop(\"last_activity_epoch\", None)",
            "session[\"last_activity_epoch\"] = int(time.time())"
        ]

        missing_auth_markers = [marker for marker in required_auth_markers if marker not in auth_route_content]
        if missing_auth_markers:
            print(f"❌ Missing authentication flow markers: {missing_auth_markers}")
            return False

        print("✅ Server-side idle-timeout wiring is present")
        return True

    except Exception as error:
        print(f"❌ Error testing server-side wiring: {error}")
        import traceback
        traceback.print_exc()
        return False


def test_base_template_warning_modal_wiring():
    """Validate warning modal and JS config are wired in base template."""
    print("🔍 Testing base template warning modal wiring...")

    try:
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
            "session_heartbeat"
        ]

        missing_markers = [marker for marker in required_markers if marker not in base_html_content]
        if missing_markers:
            print(f"❌ Missing base template markers: {missing_markers}")
            return False

        print("✅ Base template warning modal wiring is present")
        return True

    except Exception as error:
        print(f"❌ Error testing template wiring: {error}")
        import traceback
        traceback.print_exc()
        return False


def test_idle_warning_javascript_wiring():
    """Validate client-side warning and heartbeat logic markers exist."""
    print("🔍 Testing idle warning JavaScript wiring...")

    try:
        js_content = _read_file("application", "single_app", "static", "js", "idle-logout-warning.js")

        required_markers = [
            "heartbeatUrl",
            "localLogoutUrl",
            "warningMinutes",
            "logoutNow",
            "scheduleIdleTimers",
            "idleTimeoutWarningModal",
            "idleStaySignedInButton",
            "fetch(mergedConfig.heartbeatUrl",
            "const logoutTarget = mergedConfig.localLogoutUrl || mergedConfig.logoutUrl",
            "window.location.href = logoutTarget"
        ]

        missing_markers = [marker for marker in required_markers if marker not in js_content]
        if missing_markers:
            print(f"❌ Missing JavaScript markers: {missing_markers}")
            return False

        print("✅ Client-side idle warning/logout wiring is present")
        return True

    except Exception as error:
        print(f"❌ Error testing JavaScript wiring: {error}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all idle-timeout functional checks."""
    print("🧪 Running Idle Timeout Functional Tests...\n")

    tests = [
        test_server_idle_timeout_wiring,
        test_base_template_warning_modal_wiring,
        test_idle_warning_javascript_wiring
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

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
