# test_control_center_activity_logs_hardening.py
#!/usr/bin/env python3
"""
Functional test for Control Center activity logs hardening.
Version: 0.241.021
Implemented in: 0.241.021

This test ensures that the Control Center activity logs flow validates
interactive pagination, uses a dedicated export endpoint, and keeps the
responsive table layout hooks needed for narrower viewports while safely
normalizing malformed legacy user_id values.
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


def test_activity_logs_backend_hardening_present() -> bool:
    """Validate the backend route includes paging validation and export support."""
    print("Testing activity logs backend hardening...")
    backend_content = read_text("application/single_app/route_backend_control_center.py")

    required_snippets = [
        "ACTIVITY_LOGS_MAX_PER_PAGE = 200",
        "def validate_activity_logs_pagination(request_args):",
        "def build_activity_logs_query_context(activity_type_filter='all', search_term=''):",
        "def normalize_activity_log_record(log_record):",
        "coerce_activity_log_user_id(normalized_record.get(field_name))",
        "(log_record.get('admin') or {}).get('user_id')",
        "def create_activity_log_csv_response(csv_content):",
        "/api/admin/control-center/activity-logs/export",
        "return jsonify({'error': str(ex)}), 400",
        "COUNT(1) FROM c",
        "normalize_activity_log_record(log_record)",
        "format_activity_log_details_for_csv(normalized_log)"
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in backend_content]
    if missing_snippets:
        print(f"Missing backend activity logs hardening snippets: {missing_snippets}")
        return False

    if "Apply search filter in Python (after fetching from Cosmos)" in backend_content:
        print("Backend still contains the old post-pagination search comment")
        return False

    print("Backend activity logs hardening found.")
    return True


def test_control_center_template_contains_activity_log_layout_hooks() -> bool:
    """Validate the template includes responsive Activity Logs table rules."""
    print("Testing control center activity logs template layout hooks...")
    template_content = read_text("application/single_app/templates/control_center.html")

    required_snippets = [
        "activity-logs-table",
        "min-width: 940px;",
        "table-layout: fixed;",
        ".activity-log-cell-text,",
        ".activity-log-details {",
        ".activity-log-row:hover {",
        "id=\"activityLogsTable\""
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in template_content]
    if missing_snippets:
        print(f"Missing template activity logs layout snippets: {missing_snippets}")
        return False

    print("Control center activity logs layout hooks found.")
    return True


def test_control_center_javascript_uses_dedicated_export_route() -> bool:
    """Validate the client uses the dedicated export path and clears stale paging on errors."""
    print("Testing control center activity logs JavaScript wiring...")
    js_content = read_text("application/single_app/static/js/control-center.js")

    required_snippets = [
        "renderActivityLogs(logs, userMap = {})",
        "formatActivityLogTimestamp(timestamp)",
        "/api/admin/control-center/activity-logs/export?",
        "paginationInfo.textContent = message;",
        "paginationNav.innerHTML = '';",
        "this.loadActivityLogs();",
        "return this.escapeHtml(log.description || 'N/A');"
    ]

    missing_snippets = [snippet for snippet in required_snippets if snippet not in js_content]
    if missing_snippets:
        print(f"Missing JavaScript activity logs snippets: {missing_snippets}")
        return False

    forbidden_snippets = [
        "per_page: 10000",
        "console.log('=== loadActivityLogs CALLED ===')",
        "console.log('Activity Logs tab clicked!')"
    ]

    remaining_forbidden = [snippet for snippet in forbidden_snippets if snippet in js_content]
    if remaining_forbidden:
        print(f"Old activity logs debug/export snippets still present: {remaining_forbidden}")
        return False

    print("Control center activity logs JavaScript wiring found.")
    return True


def test_config_version_bumped_for_activity_log_fix() -> bool:
    """Validate the repository version bump for the activity log fix."""
    print("Testing config version bump...")
    config_content = read_text("application/single_app/config.py")

    if 'VERSION = "0.241.021"' not in config_content:
        print("Config version was not bumped to 0.241.021")
        return False

    print("Config version bump found.")
    return True


if __name__ == "__main__":
    checks = [
        test_activity_logs_backend_hardening_present,
        test_control_center_template_contains_activity_log_layout_hooks,
        test_control_center_javascript_uses_dedicated_export_route,
        test_config_version_bumped_for_activity_log_fix,
    ]

    results = []
    for check in checks:
        print(f"\nRunning {check.__name__}...")
        results.append(check())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} checks passed")
    raise SystemExit(0 if success else 1)