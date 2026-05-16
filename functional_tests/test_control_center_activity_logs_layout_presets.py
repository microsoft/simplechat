# test_control_center_activity_logs_layout_presets.py
#!/usr/bin/env python3
"""
Functional test for Control Center activity log layout presets.
Version: 0.241.016
Implemented in: 0.241.016

This test ensures that the Activity Logs tab exposes preset-based layout
controls, persists the selected preset in localStorage, and keeps clear
guidance for reading full raw log details.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def read_text(relative_path: str) -> str:
    """Read a repository file as UTF-8 text."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_activity_logs_template_contains_layout_presets() -> bool:
    """Validate the template exposes layout preset controls and CSS preset rules."""
    print("Testing activity logs layout preset template hooks...")
    template_content = read_text("application/single_app/templates/control_center.html")

    required_snippets = [
        "activity-log-layout-presets",
        'name="activityLogsLayoutPreset"',
        'id="activityLogsLayoutPresetBalanced"',
        'id="activityLogsLayoutPresetDetailsFocus"',
        'id="activityLogsLayoutPresetCompact"',
        'id="activityLogsLayoutHint"',
        'data-layout-preset="balanced"',
        '--activity-log-details-width:',
        '.activity-logs-table[data-layout-preset="details-focus"]',
        '.activity-logs-table[data-layout-preset="compact"]'
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in template_content]
    if missing_snippets:
        print(f"Missing activity logs layout preset template snippets: {missing_snippets}")
        return False

    print("Activity logs layout preset template hooks found.")
    return True


def test_activity_logs_javascript_contains_layout_preset_logic() -> bool:
    """Validate the client stores and applies Activity Logs layout presets."""
    print("Testing activity logs layout preset JavaScript wiring...")
    js_content = read_text("application/single_app/static/js/control-center.js")

    required_snippets = [
        "const ACTIVITY_LOGS_LAYOUT_PRESET_STORAGE_KEY = 'simplechat_activityLogsLayoutPreset';",
        "const ACTIVITY_LOGS_LAYOUT_PRESETS = ['balanced', 'details-focus', 'compact'];",
        "loadActivityLogsLayoutPreset()",
        "saveActivityLogsLayoutPreset()",
        "applyActivityLogsLayoutPreset(preset)",
        "updateActivityLogsLayoutHint()",
        "handleActivityLogsLayoutPresetChange(event)",
        "activityLogsLayoutPreset = 'balanced';",
        "window.localStorage.setItem(ACTIVITY_LOGS_LAYOUT_PRESET_STORAGE_KEY, this.activityLogsLayoutPreset);",
        "activityLogsTable.setAttribute('data-layout-preset', resolvedPreset);"
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in js_content]
    if missing_snippets:
        print(f"Missing activity logs layout preset JavaScript snippets: {missing_snippets}")
        return False

    print("Activity logs layout preset JavaScript wiring found.")
    return True


def test_config_version_bumped_for_activity_logs_layout_presets() -> bool:
    """Validate the repository version bump for the Activity Logs preset feature."""
    print("Testing config version bump for activity log layout presets...")
    config_content = read_text("application/single_app/config.py")

    if 'VERSION = "0.241.016"' not in config_content:
        print("Config version was not bumped to 0.241.016")
        return False

    print("Config version bump found.")
    return True


if __name__ == "__main__":
    checks = [
        test_activity_logs_template_contains_layout_presets,
        test_activity_logs_javascript_contains_layout_preset_logic,
        test_config_version_bumped_for_activity_logs_layout_presets,
    ]

    results = []
    for check in checks:
        print(f"\nRunning {check.__name__}...")
        results.append(check())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} checks passed")
    raise SystemExit(0 if success else 1)