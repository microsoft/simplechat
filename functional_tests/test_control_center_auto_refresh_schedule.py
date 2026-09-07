# test_control_center_auto_refresh_schedule.py
#!/usr/bin/env python3
"""
Functional test for Control Center auto-refresh scheduling.
Version: 0.250.102
Implemented in: 0.241.026
Updated in: 0.250.102

This test validates the enabled 02:00 Eastern default, timezone normalization,
DST-aware UTC next-run timestamps, and scheduler/admin/status integration.
"""

import importlib.util
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from test_support.templates import read_admin_settings_template


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
SETTINGS_FILE = APP_DIR / "functions_settings.py"
CONTROL_CENTER_FUNCTIONS_FILE = APP_DIR / "functions_control_center.py"
BACKGROUND_TASKS_FILE = APP_DIR / "background_tasks.py"
ADMIN_SETTINGS_ROUTE_FILE = APP_DIR / "route_frontend_admin_settings.py"
CONTROL_CENTER_ROUTE_FILE = APP_DIR / "route_backend_control_center.py"
ADMIN_TEMPLATE_FILE = APP_DIR / "templates" / "admin_settings.html"
CONTROL_CENTER_JS_FILE = APP_DIR / "static" / "js" / "control-center.js"
CONFIG_FILE = APP_DIR / "config.py"


def load_control_center_module():
    """Load schedule helpers without initializing external application clients."""
    stub_modules = {
        "config": types.SimpleNamespace(
            cosmos_user_settings_container=None,
            cosmos_groups_container=None,
        ),
        "functions_debug": types.SimpleNamespace(debug_print=lambda *args, **kwargs: None),
        "functions_settings": types.SimpleNamespace(
            get_settings=lambda: {},
            update_settings=lambda settings: True,
        ),
        "functions_appinsights": types.SimpleNamespace(
            log_event=lambda *args, **kwargs: None,
        ),
    }
    original_modules = {}
    for module_name, module in stub_modules.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module

    try:
        spec = importlib.util.spec_from_file_location(
            "control_center_schedule_under_test",
            CONTROL_CENTER_FUNCTIONS_FILE,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module


def assert_contains(source, expected, description):
    """Assert that source contains expected text."""
    if expected not in source:
        raise AssertionError(f"Missing {description}: {expected}")


def test_default_schedule(schedule_module):
    """Validate the enabled 02:00 America/New_York default."""
    schedule = schedule_module.get_control_center_auto_refresh_schedule({})
    assert schedule == {
        "hour": 2,
        "minute": 0,
        "time": "02:00",
        "timezone": "America/New_York",
    }

    invalid_timezone_schedule = schedule_module.normalize_control_center_auto_refresh_time(
        "04:15",
        schedule_timezone="Not/A_Timezone",
    )
    assert invalid_timezone_schedule["time"] == "04:15"
    assert invalid_timezone_schedule["timezone"] == "America/New_York"


def test_dst_aware_utc_next_runs(schedule_module):
    """Validate 02:00 Eastern resolves to the correct UTC time in winter and summer."""
    settings = {
        "control_center_auto_refresh_time": "02:00",
        "control_center_auto_refresh_timezone": "America/New_York",
    }

    winter_now = datetime(2026, 1, 15, 6, 30, tzinfo=timezone.utc)
    winter_next_run = schedule_module.calculate_next_control_center_auto_refresh_run(
        settings,
        current_time=winter_now,
    )
    assert winter_next_run == datetime(2026, 1, 15, 7, 0, tzinfo=timezone.utc)

    summer_now = datetime(2026, 7, 15, 5, 30, tzinfo=timezone.utc)
    summer_next_run = schedule_module.calculate_next_control_center_auto_refresh_run(
        settings,
        current_time=summer_now,
    )
    assert summer_next_run == datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)


def test_dst_transition_days(schedule_module):
    """Validate deterministic UTC timestamps on Eastern DST transition days."""
    settings = {
        "control_center_auto_refresh_time": "02:00",
        "control_center_auto_refresh_timezone": "America/New_York",
    }

    spring_now = datetime(2026, 3, 8, 6, 30, tzinfo=timezone.utc)
    spring_next_run = schedule_module.calculate_next_control_center_auto_refresh_run(
        settings,
        current_time=spring_now,
    )
    assert spring_next_run == datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)

    fall_now = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
    fall_next_run = schedule_module.calculate_next_control_center_auto_refresh_run(
        settings,
        current_time=fall_now,
    )
    assert fall_next_run == datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)


def test_enabled_and_due_checks(schedule_module):
    """Validate disabled, not-due, and due schedule decisions."""
    next_run = datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)
    settings = {
        "control_center_auto_refresh_enabled": True,
        "control_center_auto_refresh_next_run": next_run.isoformat(),
    }

    assert not schedule_module.is_control_center_auto_refresh_due(
        settings,
        current_time=datetime(2026, 7, 15, 5, 59, tzinfo=timezone.utc),
    )
    assert schedule_module.is_control_center_auto_refresh_due(
        settings,
        current_time=next_run,
    )

    settings["control_center_auto_refresh_enabled"] = False
    assert not schedule_module.is_control_center_auto_refresh_due(
        settings,
        current_time=datetime(2026, 7, 15, 6, 1, tzinfo=timezone.utc),
    )


def test_integration_wiring():
    """Validate defaults, persistence, scheduler, API, and browser-local rendering."""
    settings_source = SETTINGS_FILE.read_text(encoding="utf-8")
    background_source = BACKGROUND_TASKS_FILE.read_text(encoding="utf-8")
    admin_route_source = ADMIN_SETTINGS_ROUTE_FILE.read_text(encoding="utf-8")
    control_center_route_source = CONTROL_CENTER_ROUTE_FILE.read_text(encoding="utf-8")
    template_source = read_admin_settings_template()
    javascript_source = CONTROL_CENTER_JS_FILE.read_text(encoding="utf-8")

    expected_settings = [
        "'control_center_auto_refresh_enabled': True",
        "'control_center_auto_refresh_time': '02:00'",
        "'control_center_auto_refresh_timezone': 'America/New_York'",
        "legacy_control_center_schedule",
        "merged['control_center_auto_refresh_timezone'] = 'UTC'",
    ]
    for snippet in expected_settings:
        assert_contains(settings_source, snippet, "Control Center schedule default or migration")

    expected_background = [
        "def check_control_center_auto_refresh_once",
        "acquire_distributed_task_lock('control_center_auto_refresh'",
        "execute_control_center_refresh(manual_execution=False)",
        "'control_center_auto_refresh_timezone': schedule['timezone']",
        "run_control_center_auto_refresh_loop",
    ]
    for snippet in expected_background:
        assert_contains(background_source, snippet, "background scheduler integration")

    expected_admin = [
        "incoming_control_center_auto_refresh_timezone",
        "'control_center_auto_refresh_timezone': control_center_auto_refresh_schedule['timezone']",
        "calculate_next_control_center_auto_refresh_run",
    ]
    for snippet in expected_admin:
        assert_contains(admin_route_source, snippet, "admin schedule persistence")

    expected_status = [
        "'auto_refresh_enabled': auto_refresh_enabled",
        "'auto_refresh_time': auto_refresh_schedule['time']",
        "'auto_refresh_timezone': auto_refresh_schedule['timezone']",
        "'auto_refresh_next_run_utc':",
    ]
    for snippet in expected_status:
        assert_contains(control_center_route_source, snippet, "refresh status response")

    expected_ui = [
        'value="{{ settings.control_center_auto_refresh_time or \'02:00\' }}"',
        'id="control_center_auto_refresh_timezone"',
        'id="control-center-auto-refresh-viewer-timezone"',
        "displayControlCenterAutoRefreshLocalTime",
        "Intl.DateTimeFormat().resolvedOptions().timeZone",
    ]
    combined_ui_source = f"{template_source}\n{javascript_source}"
    for snippet in expected_ui:
        assert_contains(combined_ui_source, snippet, "browser-local schedule UI")


def test_version():
    """Validate the application version for this update."""
    config_source = CONFIG_FILE.read_text(encoding="utf-8")
    version_match = re.search(r'VERSION = "([^"]+)"', config_source)
    if not version_match:
        raise AssertionError("Could not find VERSION in config.py")
    assert version_match.group(1) == "0.250.102"


def run_all_tests():
    """Run all Control Center auto-refresh schedule checks."""
    schedule_module = load_control_center_module()
    tests = [
        lambda: test_default_schedule(schedule_module),
        lambda: test_dst_aware_utc_next_runs(schedule_module),
        lambda: test_dst_transition_days(schedule_module),
        lambda: test_enabled_and_due_checks(schedule_module),
        test_integration_wiring,
        test_version,
    ]
    for test in tests:
        test()

    print("All Control Center auto-refresh schedule checks passed")
    return True


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
