# test_user_settings_allowlist_keys.py
"""
Functional test for user settings allowlist synchronization.
Version: 0.242.051
Implemented in: 0.241.077
Updated in: 0.242.051

This test ensures that the backend user settings route accepts the
user-setting keys currently managed by microphone, retention policy,
personal model endpoint, tag, and chat preference workflows.
"""

import os
import sys


def test_user_settings_allowlist_contains_known_keys():
    """Verify that known user settings keys are accepted by the backend route."""
    print("🔍 Checking user settings allowlist keys...")

    try:
        route_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_backend_users.py'
        )

        with open(route_file, 'r', encoding='utf-8') as file_handle:
            content = file_handle.read()

        required_keys = [
            'microphonePermissionPreference',
            'microphonePermissionState',
            'retention_policy',
            'retention_policy_enabled',
            'retention_policy_days',
            'personal_model_endpoints',
            'tag_definitions',
            'deepResearchDefaultEnabled',
        ]

        missing_keys = [
            key for key in required_keys
            if f"'{key}'" not in content and f'"{key}"' not in content
        ]

        if missing_keys:
            raise Exception(f"Missing allowed_keys entries: {', '.join(missing_keys)}")

        print("✅ User settings allowlist contains the expected keys")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        return False


if __name__ == "__main__":
    success = test_user_settings_allowlist_contains_known_keys()
    sys.exit(0 if success else 1)