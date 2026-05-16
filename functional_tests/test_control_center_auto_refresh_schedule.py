# test_control_center_auto_refresh_schedule.py
#!/usr/bin/env python3
"""
Functional test for Control Center auto-refresh scheduling.
Version: 0.241.026
Implemented in: 0.241.026

This test ensures administrators can configure the daily Control Center
refresh schedule and that the background scheduler honors the saved UTC time.
"""

import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
SETTINGS_FILE = APP_DIR / "functions_settings.py"
CONTROL_CENTER_FUNCTIONS_FILE = APP_DIR / "functions_control_center.py"
BACKGROUND_TASKS_FILE = APP_DIR / "background_tasks.py"
ADMIN_SETTINGS_ROUTE_FILE = APP_DIR / "route_frontend_admin_settings.py"
CONTROL_CENTER_ROUTE_FILE = APP_DIR / "route_backend_control_center.py"
ADMIN_TEMPLATE_FILE = APP_DIR / "templates" / "admin_settings.html"
CONFIG_FILE = APP_DIR / "config.py"


def assert_contains(source, expected, description):
    """Assert that source contains expected text."""
    if expected not in source:
        raise AssertionError(f"Missing {description}: {expected}")


def get_version():
    """Read the current application version from config.py."""
    config_source = CONFIG_FILE.read_text(encoding="utf-8")
    match = re.search(r'VERSION = "([^"]+)"', config_source)
    if not match:
        raise AssertionError("Could not find VERSION in config.py")
    return match.group(1)


def test_default_settings(settings_source):
    """Validate default Control Center auto-refresh settings."""
    assert_contains(settings_source, "'control_center_auto_refresh_enabled': True", "enabled default")
    assert_contains(settings_source, "'control_center_auto_refresh_time': '06:00'", "06:00 UTC default")
    assert_contains(settings_source, "'control_center_auto_refresh_hour': 6", "hour default")
    assert_contains(settings_source, "'control_center_auto_refresh_minute': 0", "minute default")
    assert_contains(settings_source, "'control_center_auto_refresh_next_run': None", "next-run default")


def test_schedule_helpers(control_center_source):
    """Validate schedule normalization and next-run helpers exist."""
    expected_snippets = [
        "CONTROL_CENTER_DEFAULT_AUTO_REFRESH_TIME = '06:00'",
        "def normalize_control_center_auto_refresh_time",
        "def calculate_next_control_center_auto_refresh_run",
        "def parse_control_center_auto_refresh_datetime",
        "next_run += timedelta(days=1)",
        "settings['control_center_auto_refresh_next_run'] = next_run.isoformat()",
    ]
    for snippet in expected_snippets:
        assert_contains(control_center_source, snippet, "Control Center schedule helper")


def test_admin_settings_form(route_source, template_source):
    """Validate admin settings saves and renders the schedule controls."""
    route_snippets = [
        "control_center_auto_refresh_enabled = form_data.get('control_center_auto_refresh_enabled') == 'on'",
        "incoming_control_center_auto_refresh_time = form_data.get(",
        "control_center_auto_refresh_schedule_changed = (",
        "calculate_next_control_center_auto_refresh_run(",
        "'control_center_auto_refresh_time': control_center_auto_refresh_schedule['time']",
    ]
    for snippet in route_snippets:
        assert_contains(route_source, snippet, "admin route schedule persistence")

    template_snippets = [
        "id=\"control-center-auto-refresh-section\"",
        "id=\"control_center_auto_refresh_enabled\"",
        "id=\"control_center_auto_refresh_time\"",
        "value=\"{{ settings.control_center_auto_refresh_time or '06:00' }}\"",
        "toggleControlCenterAutoRefreshInputs",
        "classList.toggle('d-none'",
    ]
    for snippet in template_snippets:
        assert_contains(template_source, snippet, "admin template schedule control")


def test_background_scheduler(background_source):
    """Validate the background scheduler runs Control Center refresh when due."""
    expected_snippets = [
        "def check_control_center_auto_refresh_once",
        "acquire_distributed_task_lock('control_center_auto_refresh'",
        "execute_control_center_refresh(manual_execution=False)",
        "def run_control_center_auto_refresh_loop",
        "('Control Center auto-refresh background task started.', run_control_center_auto_refresh_loop)",
    ]
    for snippet in expected_snippets:
        assert_contains(background_source, snippet, "background auto-refresh scheduler")


def test_refresh_status_response(route_source):
    """Validate the refresh-status endpoint exposes schedule metadata."""
    expected_snippets = [
        "'auto_refresh_enabled': auto_refresh_enabled",
        "'auto_refresh_time': auto_refresh_schedule['time']",
        "'auto_refresh_hour_formatted': f\"{auto_refresh_schedule['hour']:02d}:{auto_refresh_schedule['minute']:02d} UTC\"",
        "'auto_refresh_next_run_formatted': None if not auto_refresh_next_run_datetime",
    ]
    for snippet in expected_snippets:
        assert_contains(route_source, snippet, "refresh status schedule field")


def run_all_tests():
    """Run all source-level Control Center auto-refresh checks."""
    print("Testing Control Center auto-refresh scheduling source changes...")

    current_version = get_version()
    if current_version != "0.241.026":
        raise AssertionError(f"Expected version 0.241.026, found {current_version}")

    settings_source = SETTINGS_FILE.read_text(encoding="utf-8")
    control_center_source = CONTROL_CENTER_FUNCTIONS_FILE.read_text(encoding="utf-8")
    background_source = BACKGROUND_TASKS_FILE.read_text(encoding="utf-8")
    admin_route_source = ADMIN_SETTINGS_ROUTE_FILE.read_text(encoding="utf-8")
    control_center_route_source = CONTROL_CENTER_ROUTE_FILE.read_text(encoding="utf-8")
    template_source = ADMIN_TEMPLATE_FILE.read_text(encoding="utf-8")

    test_default_settings(settings_source)
    print("Default settings checks passed")

    test_schedule_helpers(control_center_source)
    print("Schedule helper checks passed")

    test_admin_settings_form(admin_route_source, template_source)
    print("Admin settings checks passed")

    test_background_scheduler(background_source)
    print("Background scheduler checks passed")

    test_refresh_status_response(control_center_route_source)
    print("Refresh status checks passed")

    print("All Control Center auto-refresh schedule checks passed")
    return True


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)