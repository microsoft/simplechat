# test_stats_custom_window_cap.py
"""
Functional test for the shared custom-window span cap (follow-up item 4).
Version: 0.261.176
Implemented in: 0.261.176

A bounded stats window still let a custom range span the whole 2000-01-01..9998-12-31
calendar: 2.9 million days of CPU, memory and response body. The native group insights
already capped a custom span at 366 days; that cap now lives once in the shared
``resolve_bounded_stats_time_window`` as ``STATS_MAX_CUSTOM_DAYS``, and every route that
uses the bounded window inherits it.

This test pins, in one place:

- the shared constant and message, and that the resolver accepts 366 days, refuses 367
  with the span message, and still refuses an out-of-calendar window with the calendar
  message first (calendar bound before span cap);
- the classic group stats route reads a 366-day window and answers a 367-day window with
  a reviewed 400;
- the classic public stats route answers a 367-day window with a reviewed 400;
- the profile trends route, now on the bounded window, answers a 367-day window, an
  offset that steps past the calendar, and a pre-2000 date each with a reviewed 400
  (the offset case used to be a 500 on the unbounded resolver).

The resolver, the classic group route and the classic public and profile routes all run
for real; only each route's workspace/user lookup and Flask's request/jsonify are modeled.
"""

import ast
import importlib.util
import logging
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

from test_support.agent_delegation import APP_ROOT, module_stub
from test_support.app_source import definitions as source_definitions
from test_support.group_settings_harness import group_settings_environment
from test_support.versioning import assert_app_version_at_least


STATS_WINDOWS_FILE = "functions_stats_windows.py"
PUBLIC_STATS_FILE = "route_backend_public_workspaces.py"
PUBLIC_REGISTER = "register_route_backend_public_workspaces"
PROFILE_FILE = "route_frontend_profile.py"
PROFILE_REGISTER = "register_route_frontend_profile"

SPAN_MESSAGE = "Choose a date range of 366 days or fewer."
CALENDAR_MESSAGE = "Choose dates between 2000-01-01 and 9998-12-31."

# 2000 is a leap year, so 2000-01-01..2000-12-31 is exactly 366 days (the cap), and
# 2000-01-01..2001-01-01 is 367 (one past it).
WINDOW_366 = {"start_date": "2000-01-01", "end_date": "2000-12-31"}
WINDOW_367 = {"start_date": "2000-01-01", "end_date": "2001-01-01"}
OFFSET_PAST_CALENDAR = {"start_date": "9998-12-30", "end_date": "9998-12-31T23:00:00-05:00"}
BEFORE_THE_RANGE = {"start_date": "1999-12-31", "end_date": "2000-01-01"}

STATS_WINDOWS_DEFINITIONS = {
    "DEFAULT_STATS_WINDOW_DAYS", "ALLOWED_STATS_WINDOW_DAYS",
    "STATS_EARLIEST_CUSTOM_DATE", "STATS_LATEST_CUSTOM_DATE",
    "STATS_DATE_RANGE_MESSAGE", "STATS_MAX_CUSTOM_DAYS", "STATS_MAX_CUSTOM_DAYS_MESSAGE",
    "StatsDateRangeError",
    "_get_request_value", "_parse_date_value", "_normalize_days", "_format_display_date",
    "resolve_stats_time_window", "resolve_bounded_stats_time_window",
}


assert_app_version_at_least("0.261.132")


# --------------------------------------------------------------------------- #
# The shared resolver
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def windows():
    spec = importlib.util.spec_from_file_location(
        "functions_stats_windows_cap", APP_ROOT / STATS_WINDOWS_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shared_constant_and_message(windows):
    assert windows.STATS_MAX_CUSTOM_DAYS == 366
    assert windows.STATS_MAX_CUSTOM_DAYS_MESSAGE == SPAN_MESSAGE


def test_the_cap_accepts_366_and_refuses_367(windows):
    inside = windows.resolve_bounded_stats_time_window(WINDOW_366)
    assert (inside["type"], inside["days"]) == ("custom", 366)

    with pytest.raises(windows.StatsDateRangeError) as refused:
        windows.resolve_bounded_stats_time_window(WINDOW_367)
    assert isinstance(refused.value, ValueError)
    assert str(refused.value) == SPAN_MESSAGE


def test_the_calendar_bound_is_checked_before_the_span_cap(windows):
    # A window both out of the calendar and longer than the cap is refused for the
    # calendar first, so the caller sees the range message, not the span message.
    with pytest.raises(windows.StatsDateRangeError) as refused:
        windows.resolve_bounded_stats_time_window({"start_date": "1999-12-31", "end_date": "2001-06-01"})
    assert str(refused.value) == CALENDAR_MESSAGE


# --------------------------------------------------------------------------- #
# The classic group stats route
# --------------------------------------------------------------------------- #

GROUP = "group-1"
GROUP_STATS_PATH = f"/api/groups/{GROUP}/stats"


@pytest.fixture(scope="module")
def group_module_env():
    with group_settings_environment() as env:
        yield env


@pytest.fixture
def group_env(group_module_env):
    group_module_env.reset()
    group_module_env.seed_group(GROUP, status="active", disable_file_downloads=True)
    group_module_env.as_user("owner-1")
    yield group_module_env


def test_the_group_route_reads_a_366_day_window(group_env):
    response = group_env.call("GET", GROUP_STATS_PATH, query_string=WINDOW_366)
    assert response.status_code == 200
    assert response.get_json()["window"]["days"] == 366


def test_the_group_route_refuses_a_367_day_window(group_env):
    response = group_env.call("GET", GROUP_STATS_PATH, query_string=WINDOW_367)
    assert (response.status_code, response.get_json()) == (400, {"error": SPAN_MESSAGE})
    error_logs = [entry for entry in group_env.logs if entry[1] == logging.ERROR]
    assert group_env.activity_logs.queries == [] and error_logs == []


# --------------------------------------------------------------------------- #
# The classic public stats route
# --------------------------------------------------------------------------- #

PUBLIC_WS = "public-1"


class _Request:
    def __init__(self, args):
        self.args = args


class _Blueprint:
    def route(self, *args, **kwargs):
        return lambda function: function


def _decorator_namespace():
    return {
        "date": date, "datetime": datetime, "timedelta": timedelta, "timezone": timezone,
        "bp": _Blueprint(),
        "swagger_route": lambda **kwargs: (lambda function: function),
        "get_auth_security": lambda: [{"sessionAuth": []}],
        "login_required": lambda function: function,
        "user_required": lambda function: function,
        "enabled_required": lambda *args, **kwargs: (lambda function: function),
        "jsonify": lambda payload=None: payload,
        "request": None,
    }


def _build_public_stats_route():
    namespace = _decorator_namespace()
    namespace.update({
        "get_current_user_info": lambda: {"userId": "owner"},
        "find_public_workspace_by_id": lambda ws_id: {
            "id": ws_id, "owner": {"userId": "owner"}, "admins": [], "documentManagers": [],
        },
    })
    exec(compile(source_definitions(STATS_WINDOWS_FILE, STATS_WINDOWS_DEFINITIONS),
                 STATS_WINDOWS_FILE, "exec"), namespace)
    exec(compile(source_definitions(PUBLIC_STATS_FILE, {"is_user_in_admins", "_member_user_id"}),
                 PUBLIC_STATS_FILE, "exec"), namespace)
    exec(compile(source_definitions(PUBLIC_STATS_FILE, set(), register=PUBLIC_REGISTER,
                                    nested={"api_public_workspace_stats"}),
                 PUBLIC_STATS_FILE, "exec"), namespace)
    return namespace


def _call_public_stats(args):
    namespace = _build_public_stats_route()
    namespace["request"] = _Request(args)
    return namespace["api_public_workspace_stats"](PUBLIC_WS)


def test_the_public_route_refuses_a_367_day_window():
    payload, code = _call_public_stats(WINDOW_367)
    assert code == 400 and payload == {"error": SPAN_MESSAGE}


# --------------------------------------------------------------------------- #
# The profile trends route
# --------------------------------------------------------------------------- #

def _build_profile_route():
    namespace = _decorator_namespace()
    namespace["get_current_user_id"] = lambda: "user-1"
    exec(compile(source_definitions(STATS_WINDOWS_FILE, STATS_WINDOWS_DEFINITIONS),
                 STATS_WINDOWS_FILE, "exec"), namespace)
    exec(compile(source_definitions(PROFILE_FILE, set(), register=PROFILE_REGISTER,
                                    nested={"get_user_activity_trends"}),
                 PROFILE_FILE, "exec"), namespace)
    return namespace


def _call_profile(args):
    # The route imports ``cosmos_activity_logs_container`` from ``config`` before it
    # resolves the window; on the 400 path it never touches the container, so a stub
    # module carries the import without importing the real config.
    previous = sys.modules.get("config")
    sys.modules["config"] = module_stub("config", cosmos_activity_logs_container=object())
    try:
        namespace = _build_profile_route()
        namespace["request"] = _Request(args)
        return namespace["get_user_activity_trends"]()
    finally:
        if previous is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = previous


@pytest.mark.parametrize("query,message", [
    (WINDOW_367, SPAN_MESSAGE),
    (OFFSET_PAST_CALENDAR, CALENDAR_MESSAGE),
    (BEFORE_THE_RANGE, CALENDAR_MESSAGE),
])
def test_the_profile_route_refuses_out_of_bounds_windows(query, message):
    payload, code = _call_profile(query)
    assert code == 400 and payload == {"error": message}


def test_the_profile_route_uses_only_the_bounded_window():
    tree = ast.parse((APP_ROOT / PROFILE_FILE).read_text(encoding="utf-8"))
    resolvers = sorted({
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"resolve_stats_time_window", "resolve_bounded_stats_time_window"}
    })
    assert resolvers == ["resolve_bounded_stats_time_window"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
