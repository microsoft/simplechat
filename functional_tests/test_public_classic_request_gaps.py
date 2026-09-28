# test_public_classic_request_gaps.py
"""
Functional test for two classic public-workspace request gaps (R5.3 and R5.6).
Version: 0.261.173
Implemented in: 0.261.173

- Classic ``GET /api/public_workspaces/<ws_id>/stats`` resolved its date window with
  the unbounded ``resolve_stats_time_window`` under only ``except ValueError``. A
  custom date whose UTC offset carried it past the calendar's edge raised
  ``OverflowError`` (a 500), and a date before 2000-01-01 or after 9998-12-31 was
  accepted. Like the classic group stats route, it now uses
  ``resolve_bounded_stats_time_window``. ``StatsDateRangeError`` subclasses
  ``ValueError``, so such a date is answered by the route's existing ``except`` as a
  400 carrying the shared ``Choose dates between 2000-01-01 and 9998-12-31.`` text.

- ``check_public_workspace_status_allows_operation`` gave an unrecognized status the
  ``active`` permissions, so a workspace whose status the code did not know allowed
  every operation and answered no reason. It now gives an unknown status the
  ``inactive`` permissions and the public workspace context's own words,
  ``This workspace's status is not recognized. Contact an administrator.`` The known
  statuses are unchanged. Its classic callers (public document upload and delete,
  chat, artifact publication, workflow inputs and the workspace context) therefore
  fail closed on an unknown status instead of open.

The stats route and the status helper run for real; only the workspace lookup, the
user lookup and Flask's request/jsonify are modeled for the route.
"""

import ast
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from test_support.agent_delegation import APP_ROOT
from test_support.app_source import definitions as source_definitions
from test_support.versioning import assert_app_version_at_least


APP_DIR = Path(APP_ROOT)
STATS_FILE = "route_backend_public_workspaces.py"
STATS_WINDOWS_FILE = "functions_stats_windows.py"
WORKSPACES_FILE = "functions_public_workspaces.py"
REGISTER = "register_route_backend_public_workspaces"
WS = "public-1"
UNKNOWN_STATUS_REASON = "This workspace's status is not recognized. Contact an administrator."
DATE_RANGE_MESSAGE = "Choose dates between 2000-01-01 and 9998-12-31."

STATS_WINDOWS_DEFINITIONS = {
    "DEFAULT_STATS_WINDOW_DAYS", "ALLOWED_STATS_WINDOW_DAYS",
    "STATS_EARLIEST_CUSTOM_DATE", "STATS_LATEST_CUSTOM_DATE",
    "STATS_DATE_RANGE_MESSAGE", "StatsDateRangeError",
    "_get_request_value", "_parse_date_value", "_normalize_days", "_format_display_date",
    "resolve_stats_time_window", "resolve_bounded_stats_time_window",
}


assert_app_version_at_least("0.261.132")


# --------------------------------------------------------------------------- #
# R5.3 — the classic public stats route uses the bounded window
# --------------------------------------------------------------------------- #

def _window_resolvers(file_name):
    tree = ast.parse((APP_DIR / file_name).read_text(encoding="utf-8"))
    return sorted({
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"resolve_stats_time_window", "resolve_bounded_stats_time_window"}
    })


def test_the_public_stats_route_uses_only_the_bounded_window():
    assert _window_resolvers(STATS_FILE) == ["resolve_bounded_stats_time_window"]


class _Request:
    def __init__(self, args):
        self.args = args


def _build_stats_route():
    class _Blueprint:
        def route(self, *args, **kwargs):
            return lambda function: function

    namespace = {
        "date": date, "datetime": datetime, "timedelta": timedelta, "timezone": timezone,
        "bp": _Blueprint(),
        "swagger_route": lambda **kwargs: (lambda function: function),
        "get_auth_security": lambda: [{"sessionAuth": []}],
        "login_required": lambda function: function,
        "user_required": lambda function: function,
        "enabled_required": lambda *args, **kwargs: (lambda function: function),
        "jsonify": lambda payload=None: payload,
        "request": None,
        "get_current_user_info": lambda: {"userId": "owner"},
        "find_public_workspace_by_id": lambda ws_id: {
            "id": ws_id, "owner": {"userId": "owner"}, "admins": [], "documentManagers": [],
        },
    }
    # The real bounded window resolver, run from its own source.
    exec(compile(source_definitions(STATS_WINDOWS_FILE, STATS_WINDOWS_DEFINITIONS),
                 STATS_WINDOWS_FILE, "exec"), namespace)
    exec(compile(source_definitions(STATS_FILE, {"is_user_in_admins", "_member_user_id"}),
                 STATS_FILE, "exec"), namespace)
    exec(compile(source_definitions(STATS_FILE, set(), register=REGISTER, nested={"api_public_workspace_stats"}),
                 STATS_FILE, "exec"), namespace)
    return namespace


def _call_stats(args):
    namespace = _build_stats_route()
    namespace["request"] = _Request(args)
    return namespace["api_public_workspace_stats"](WS)


def test_a_date_whose_offset_steps_past_the_calendar_is_a_reviewed_400():
    payload, code = _call_stats({"start_date": "9998-12-30", "end_date": "9998-12-31T23:00:00-05:00"})
    assert code == 400 and payload == {"error": DATE_RANGE_MESSAGE}


def test_a_date_before_the_supported_range_is_a_reviewed_400():
    payload, code = _call_stats({"start_date": "1999-12-31", "end_date": "2000-01-01"})
    assert code == 400 and payload == {"error": DATE_RANGE_MESSAGE}


# --------------------------------------------------------------------------- #
# R5.6 — an unknown status fails closed with the public context's reason
# --------------------------------------------------------------------------- #

def _status_helper():
    namespace = {}
    exec(compile(source_definitions(WORKSPACES_FILE, {"check_public_workspace_status_allows_operation"}),
                 WORKSPACES_FILE, "exec"), namespace)
    return namespace["check_public_workspace_status_allows_operation"]


@pytest.mark.parametrize("operation", ["upload", "delete", "chat", "view"])
def test_an_unknown_status_denies_every_operation_with_the_context_reason(operation):
    check = _status_helper()
    allowed, reason = check({"status": "mystery"}, operation)
    assert allowed is False
    assert reason == UNKNOWN_STATUS_REASON


@pytest.mark.parametrize("operation", ["upload", "delete", "chat", "view"])
def test_an_active_workspace_still_allows_every_operation(operation):
    check = _status_helper()
    allowed, reason = check({"status": "active"}, operation)
    assert allowed is True and reason == ""


def test_a_workspace_with_no_status_is_treated_as_active():
    check = _status_helper()
    allowed, _reason = check({"id": "x"}, "upload")
    assert allowed is True


@pytest.mark.parametrize("operation", ["upload", "delete", "chat", "view"])
def test_an_inactive_workspace_still_denies_with_its_own_reason(operation):
    check = _status_helper()
    allowed, reason = check({"status": "inactive"}, operation)
    assert allowed is False
    assert reason != UNKNOWN_STATUS_REASON
    assert "inactive" in reason.lower()


def test_a_locked_workspace_still_allows_view_and_chat_and_denies_writes():
    check = _status_helper()
    assert check({"status": "locked"}, "view")[0] is True
    assert check({"status": "locked"}, "chat")[0] is True
    assert check({"status": "locked"}, "upload")[0] is False
    assert check({"status": "locked"}, "delete")[0] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
