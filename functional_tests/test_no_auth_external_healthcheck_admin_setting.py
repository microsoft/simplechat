# test_no_auth_external_healthcheck_admin_setting.py
#!/usr/bin/env python3
"""
Functional test for no-auth external healthcheck admin wiring.
Version: 0.241.014
Implemented in: 0.241.014

This test ensures that the unauthenticated external healthcheck setting is wired
through defaults, admin save handling, and the admin settings template.
"""

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = ROOT / "application" / "single_app" / "functions_settings.py"
ADMIN_ROUTE_FILE = ROOT / "application" / "single_app" / "route_frontend_admin_settings.py"
ADMIN_TEMPLATE_FILE = ROOT / "application" / "single_app" / "templates" / "admin_settings.html"


def read_text(path: Path) -> str:
    """Return UTF-8 text for a repo file."""
    return path.read_text(encoding="utf-8")


def test_no_auth_healthcheck_setting_defaults_and_save_path() -> bool:
    """Validate defaults and admin form persistence for the no-auth healthcheck setting."""
    print("🔍 Testing no-auth healthcheck defaults and save handling...")

    try:
        settings_content = read_text(SETTINGS_FILE)
        route_content = read_text(ADMIN_ROUTE_FILE)

        if not re.search(r"['\"]enable_no_auth_external_healthcheck['\"]\s*:\s*False", settings_content):
            raise AssertionError("Missing default False value for enable_no_auth_external_healthcheck in functions_settings.py")

        required_route_snippets = [
            "if 'enable_no_auth_external_healthcheck' not in settings:",
            "settings['enable_no_auth_external_healthcheck'] = False",
            "'enable_no_auth_external_healthcheck': form_data.get('enable_no_auth_external_healthcheck') == 'on'",
        ]

        for snippet in required_route_snippets:
            if snippet not in route_content:
                raise AssertionError(f"Missing admin settings route wiring: {snippet}")

        print("✅ No-auth healthcheck defaults and save handling are wired correctly")
        return True
    except Exception as ex:
        print(f"❌ Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


def test_no_auth_healthcheck_admin_template() -> bool:
    """Validate admin template rendering for both authenticated and unauthenticated healthcheck toggles."""
    print("🔍 Testing no-auth healthcheck admin template...")

    try:
        template_content = read_text(ADMIN_TEMPLATE_FILE)

        required_template_snippets = [
            'id="enable_external_healthcheck"',
            'id="enable_no_auth_external_healthcheck"',
            'Enable /external/healthcheck',
            'Enable /external/healthcheckz',
            'Unauthenticated Endpoint',
            'Security note:',
        ]

        for snippet in required_template_snippets:
            if snippet not in template_content:
                raise AssertionError(f"Missing admin template content: {snippet}")

        unauth_occurrences = len(re.findall(r'id="enable_no_auth_external_healthcheck"', template_content))
        if unauth_occurrences != 1:
            raise AssertionError(
                f"Expected exactly one no-auth healthcheck toggle in the template, found {unauth_occurrences}"
            )

        print("✅ Admin template contains both healthcheck controls and the unauthenticated warning")
        return True
    except Exception as ex:
        print(f"❌ Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_no_auth_healthcheck_setting_defaults_and_save_path,
        test_no_auth_healthcheck_admin_template,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)