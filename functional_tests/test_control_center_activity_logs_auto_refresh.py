# test_control_center_activity_logs_auto_refresh.py
#!/usr/bin/env python3
"""
Functional test for Control Center Activity Logs auto-refresh.
Version: 0.261.491
Implemented in: 0.241.028; restored in 0.261.491

This test ensures that the Activity Logs tab exposes browser-side auto-refresh
controls, persists refresh settings, and guards the polling loop from running
while the page is hidden or repeatedly failing.
"""

import sys
from pathlib import Path
from test_support.versioning import app_version_is_at_least  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
CURRENT_VERSION = "0.261.491"
IMPLEMENTED_VERSION = "0.241.028"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def read_text(relative_path: str) -> str:
    """Read a repository file as UTF-8 text."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_activity_logs_template_contains_auto_refresh_controls() -> None:
    """Validate the template exposes the auto-refresh toolbar and controls."""
    print("Testing activity logs auto-refresh template hooks...")
    template_content = read_text("application/single_app/templates/control_center.html")

    required_snippets = [
        "activity-log-auto-refresh-toolbar",
        'id="activityLogsAutoRefreshToggle"',
        'id="activityLogsAutoRefreshStatus"',
        'id="activityLogsAutoRefreshIntervalRange"',
        'id="activityLogsAutoRefreshIntervalInput"',
        'id="activityLogsAutoRefreshIntervalValue"',
        'data-activity-logs-refresh-preset="1"',
        'data-activity-logs-refresh-preset="300"',
        "activity-log-refresh-interval-controls",
        "activity-log-refresh-presets",
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in template_content]
    assert not missing_snippets, f"Missing activity logs auto-refresh template snippets: {missing_snippets}"

    print("Activity logs auto-refresh template hooks found.")


def test_activity_logs_javascript_contains_auto_refresh_logic() -> None:
    """Validate the client stores, schedules, and pauses auto-refresh."""
    print("Testing activity logs auto-refresh JavaScript wiring...")
    js_content = read_text("application/single_app/static/js/control-center.js")

    required_snippets = [
        "const ACTIVITY_LOGS_AUTO_REFRESH_ENABLED_STORAGE_KEY = 'simplechat_activityLogsAutoRefreshEnabled';",
        "const ACTIVITY_LOGS_AUTO_REFRESH_INTERVAL_STORAGE_KEY = 'simplechat_activityLogsAutoRefreshIntervalSeconds';",
        "const ACTIVITY_LOGS_AUTO_REFRESH_MIN_SECONDS = 1;",
        "const ACTIVITY_LOGS_AUTO_REFRESH_MAX_SECONDS = 300;",
        "loadActivityLogsAutoRefreshSettings()",
        "saveActivityLogsAutoRefreshSettings()",
        "syncActivityLogsAutoRefreshControls()",
        "handleActivityLogsAutoRefreshToggle(event)",
        "handleActivityLogsAutoRefreshIntervalChange(value)",
        "scheduleActivityLogsAutoRefresh()",
        "clearActivityLogsAutoRefreshTimer()",
        "handleActivityLogsVisibilityChange()",
        "pauseActivityLogsAutoRefresh('Auto-refresh paused because access changed.')",
        "pauseActivityLogsAutoRefresh('Auto-refresh paused after repeated refresh errors.')",
        "window.setTimeout(() => {",
        "document.hidden",
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in js_content]
    assert not missing_snippets, f"Missing activity logs auto-refresh JavaScript snippets: {missing_snippets}"

    print("Activity logs auto-refresh JavaScript wiring found.")


def test_activity_logs_auto_refresh_documentation_and_version() -> None:
    """Validate feature documentation and config version are aligned."""
    print("Testing activity logs auto-refresh documentation and version...")
    documentation_content = read_text("docs/explanation/features/CONTROL_CENTER_ACTIVITY_LOG_AUTO_REFRESH.md")

    assert app_version_is_at_least(CURRENT_VERSION), f"Config version is older than {CURRENT_VERSION}"

    required_documentation_snippets = [
        f"Fixed/Implemented in version: **{IMPLEMENTED_VERSION}**",
        "Minimum interval: 1 second",
        "Maximum interval: 300 seconds",
        "Default interval: 30 seconds",
        "`functional_tests/test_control_center_activity_logs_auto_refresh.py`",
        "`ui_tests/test_control_center_activity_logs_auto_refresh.py`",
        f"`application/single_app/config.py` - version updated to {IMPLEMENTED_VERSION}",
    ]

    missing_snippets = [snippet for snippet in required_documentation_snippets if snippet not in documentation_content]
    assert not missing_snippets, f"Missing activity logs auto-refresh documentation snippets: {missing_snippets}"

    print("Activity logs auto-refresh documentation and version are aligned.")


if __name__ == "__main__":
    test_activity_logs_template_contains_auto_refresh_controls()
    test_activity_logs_javascript_contains_auto_refresh_logic()
    test_activity_logs_auto_refresh_documentation_and_version()
