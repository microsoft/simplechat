# test_control_center_left_nav_endpoint.py
#!/usr/bin/env python3
"""
Functional test for Control Center left nav endpoint matching.
Version: 0.250.052
Implemented in: 0.250.052

This test ensures the Control Center sidebar section uses the blueprint-qualified
endpoint so admins see the left nav when ControlCenterAdmin enforcement is disabled.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    """Read a repository file as UTF-8 text."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_control_center_sidebar_uses_blueprint_endpoint() -> bool:
    """Validate the Control Center sidebar section matches the registered endpoint."""
    print("Testing Control Center sidebar endpoint match...")
    sidebar_template = read_text("application/single_app/templates/_sidebar_nav.html")

    expected_endpoint_check = "request.endpoint == 'frontend_control_center.control_center'"
    stale_endpoint_check = "request.endpoint == 'control_center'"

    if expected_endpoint_check not in sidebar_template:
        print("Control Center sidebar does not use the blueprint-qualified endpoint.")
        return False

    if stale_endpoint_check in sidebar_template:
        print("Control Center sidebar still contains the stale unqualified endpoint check.")
        return False

    print("Control Center sidebar endpoint match found.")
    return True


def test_control_center_regular_admin_fallback_preserved() -> bool:
    """Validate regular admins still get Control Center nav when app-role enforcement is disabled."""
    print("Testing Control Center regular Admin fallback...")
    sidebar_template = read_text("application/single_app/templates/_sidebar_nav.html")

    required_snippets = [
        "not app_settings.require_member_of_control_center_admin and 'Admin' in session['user']['roles']",
        "app_settings.require_member_of_control_center_dashboard_reader",
        "ControlCenterDashboardReader",
        "ControlCenterAdmin",
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in sidebar_template]
    if missing_snippets:
        print(f"Missing Control Center role fallback snippets: {missing_snippets}")
        return False

    print("Control Center regular Admin fallback preserved.")
    return True


def test_config_version_bumped_for_control_center_left_nav_fix() -> bool:
    """Validate the repository version bump for the Control Center left nav fix."""
    print("Testing config version bump for Control Center left nav fix...")
    config_content = read_text("application/single_app/config.py")

    if 'VERSION = "0.250.052"' not in config_content:
        print("Config version was not bumped to 0.250.052")
        return False

    print("Config version bump found.")
    return True


if __name__ == "__main__":
    checks = [
        test_control_center_sidebar_uses_blueprint_endpoint,
        test_control_center_regular_admin_fallback_preserved,
        test_config_version_bumped_for_control_center_left_nav_fix,
    ]

    results = []
    for check in checks:
        print(f"\nRunning {check.__name__}...")
        results.append(check())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} checks passed")
    raise SystemExit(0 if success else 1)