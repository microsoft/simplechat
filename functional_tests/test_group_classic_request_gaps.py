# test_group_classic_request_gaps.py
"""
Functional test for three classic group request gaps (residuals R2).
Version: 0.261.156
Implemented in: 0.261.156

- ``PATCH /api/groups/<group_id>/download-settings`` read
  ``bool(data.get("disable_file_downloads", False))``: a body without the field, or
  one that wasn't JSON, turned downloads back on, the string ``"false"`` turned them
  off, and a JSON array answered 500. Anything but a boolean, after the route's
  existing refusals, is now a reviewed 400 that writes nothing. The classic page
  always sends the checkbox's boolean (``manage_group.js``).
- ``POST /api/retention-policy/group/<group_id>`` called ``request.get_json()``, so a
  body that wasn't JSON raised inside the route's ``try`` and answered 500, as did a
  JSON body that wasn't an object. After the role check, such a body is now a
  reviewed 400 in the route's existing style.
- Classic ``GET /api/groups/<group_id>/stats`` caught only ``ValueError``: a custom
  date whose UTC offset carried it past the calendar's edge raised ``OverflowError``,
  and a window ending near 9999-12-31 overflowed building its day-by-day series,
  both a 500. The bounds, message and checker the native statistics use now live in
  ``functions_stats_windows`` (``resolve_bounded_stats_time_window``), and both
  routes use them, so such a date is a 400 with the native text. Classic windows keep
  no length cap. Public workspace statistics and profile trends still use the
  unbounded window, unchanged.

The routes run for real in ``test_support/group_settings_harness.py``.
"""

import ast
import importlib.util
import logging

import pytest

from test_support.agent_delegation import APP_ROOT
from test_support.group_settings_harness import group_settings_environment


GROUP = "group-1"
DOWNLOADS_PATH = f"/api/groups/{GROUP}/download-settings"
RETENTION_PATH = f"/api/retention-policy/group/{GROUP}"
STATS_PATH = f"/api/groups/{GROUP}/stats"
SET_A_BOOLEAN = {"error": "Set disable_file_downloads to true or false."}
JSON_OBJECT_REQUIRED = {"success": False, "error": "A JSON object is required for this request."}
DATE_RANGE = {"error": "Choose dates between 2000-01-01 and 9998-12-31."}


@pytest.fixture(scope="module")
def module_env():
    with group_settings_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group(GROUP, status="active", disable_file_downloads=True)
    module_env.as_user("owner-1")
    yield module_env
    module_env.reset()


def outcome(response):
    return response.status_code, response.get_json()


def error_logs(env):
    return [entry for entry in env.logs if entry[1] == logging.ERROR]


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [True, False])
def test_a_boolean_is_saved_as_before(env, value):
    assert outcome(env.call("PATCH", DOWNLOADS_PATH, {"disable_file_downloads": value})) == (200, {
        "success": True, "message": "Download settings updated", "disable_file_downloads": value,
    })
    assert env.stored_group(GROUP)["disable_file_downloads"] is value


@pytest.mark.parametrize("request_body", [
    {"body": {}},
    {"body": {"disable_file_downloads": "false"}},
    {"body": {"disable_file_downloads": "true"}},
    {"body": {"disable_file_downloads": 0}},
    {"body": {"disable_file_downloads": None}},
    {"body": []},
    {"body": ["disable_file_downloads"]},
    {"body": "disable_file_downloads"},
    {"raw": "not json"},
    {"raw": '{"disable_file_downloads": false}', "content_type": "text/plain"},
], ids=repr)
def test_anything_but_a_boolean_changes_nothing(env, request_body):
    body = request_body.get("body")
    kwargs = {key: value for key, value in request_body.items() if key != "body"}
    response = env.call("PATCH", DOWNLOADS_PATH, body, **kwargs)
    assert outcome(response) == (400, SET_A_BOOLEAN)
    assert env.stored_group(GROUP)["disable_file_downloads"] is True
    assert env.write_calls() == [] and error_logs(env) == []


@pytest.mark.parametrize("setup,expected", [
    ("member", (403, {"error": "Only group owners and admins can update download settings"})),
    ("missing", (404, {"error": "Group not found"})),
    ("not_enabled", (403, {"error": "File downloads have not been enabled for this group by an administrator"})),
])
def test_the_existing_refusals_come_before_the_body(env, setup, expected):
    path = DOWNLOADS_PATH
    if setup == "member":
        env.as_user("member-1")
    elif setup == "missing":
        path = "/api/groups/group-9/download-settings"
    else:
        env.settings["allow_group_workspace_file_downloads"] = False
    assert outcome(env.call("PATCH", path, raw="not json")) == expected
    assert env.write_calls() == []


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("request_body", [
    {"raw": "not json"},
    {"raw": "[]"},
    {"raw": '["conversation_retention_days"]'},
    {"raw": '"conversation_retention_days"'},
    {"raw": "5"},
    {"raw": "null"},
    {"raw": '{"conversation_retention_days": 30}', "content_type": "text/plain"},
], ids=repr)
def test_a_body_that_is_not_a_json_object_is_a_reviewed_400(env, request_body):
    before = env.stored_group(GROUP)
    assert outcome(env.call("POST", RETENTION_PATH, **request_body)) == (400, JSON_OBJECT_REQUIRED)
    assert env.stored_group(GROUP) == before
    assert env.write_calls() == [] and error_logs(env) == []


@pytest.mark.parametrize("caller,path,expected", [
    ("member-1", RETENTION_PATH,
     (403, {"success": False, "error": "Insufficient permissions. Must be group owner or admin."})),
    ("outsider-1", RETENTION_PATH,
     (403, {"success": False, "error": "Insufficient permissions. Must be group owner or admin."})),
    ("owner-1", "/api/retention-policy/group/group-9", (404, {"success": False, "error": "Group not found"})),
])
def test_the_body_is_answered_after_the_group_and_role_checks(env, caller, path, expected):
    env.as_user(caller)
    assert outcome(env.call("POST", path, raw="not json")) == expected
    assert env.write_calls() == []


def test_a_json_object_is_still_saved(env):
    response = env.call("POST", RETENTION_PATH, {"conversation_retention_days": 30})
    assert outcome(response) == (200, {"success": True, "message": "Group retention settings updated successfully"})
    assert env.stored_group(GROUP)["retention_policy"]["conversation_retention_days"] == 30


# ---------------------------------------------------------------------------
# Classic statistics
# ---------------------------------------------------------------------------

OUT_OF_RANGE_WINDOWS = {
    # Was a 500: the shared parser overflowed converting the offset to UTC.
    "offset_before_the_calendar": {"start_date": "0001-01-01T00:00:00+01:00", "end_date": "0001-01-02"},
    "offset_after_the_calendar": {"start_date": "9998-12-01", "end_date": "9999-12-31T23:59:59-23:59"},
    # Was a 500: the day-by-day series stepped past 9999-12-31.
    "series_past_the_calendar": {"start_date": "9999-12-01", "end_date": "9999-12-31"},
    "before_the_earliest_date": {"start_date": "1999-12-31", "end_date": "2000-01-01"},
    "after_the_latest_date": {"start_date": "9998-12-31", "end_date": "9999-01-01"},
    "offset_moves_the_start_before_it": {"start_date": "2000-01-01T00:30:00+01:00", "end_date": "2000-01-02"},
    "offset_moves_the_end_after_it": {"start_date": "9998-12-30", "end_date": "9998-12-31T23:00:00-05:00"},
}


@pytest.mark.parametrize("window", OUT_OF_RANGE_WINDOWS)
def test_dates_outside_the_supported_range_are_a_reviewed_400(env, window):
    response = env.call("GET", STATS_PATH, query_string=OUT_OF_RANGE_WINDOWS[window])
    assert outcome(response) == (400, DATE_RANGE)
    assert env.activity_logs.queries == [] and error_logs(env) == []


@pytest.mark.parametrize("query,days", [
    ({"start_date": "2000-01-01", "end_date": "2000-01-31"}, 31),
    ({"start_date": "9998-12-01", "end_date": "9998-12-31"}, 31),
    # Classic windows keep no length cap.
    ({"start_date": "2000-01-01", "end_date": "2003-12-31"}, 1461),
])
def test_windows_inside_the_range_are_read(env, query, days):
    response = env.call("GET", STATS_PATH, query_string=query)
    assert response.status_code == 200
    body = response.get_json()
    assert (body["window"]["type"], body["window"]["days"], len(body["dateRange"])) == ("custom", days, days)


@pytest.mark.parametrize("query,message", [
    ({"start_date": "yesterday", "end_date": "2026-09-01"}, "start_date must use YYYY-MM-DD format."),
    ({"start_date": "2026-09-05", "end_date": "2026-09-01"}, "start_date must be before or equal to end_date."),
    ({"start_date": "2026-09-01"}, "end_date is required."),
])
def test_the_classic_window_refusals_are_unchanged(env, query, message):
    assert outcome(env.call("GET", STATS_PATH, query_string=query)) == (400, {"error": message})


@pytest.mark.parametrize("caller,path,expected", [
    ("member-1", STATS_PATH, (403, {"error": "Forbidden"})),
    ("owner-1", "/api/groups/group-9/stats", (404, {"error": "Not found"})),
])
def test_the_classic_access_checks_still_come_first(env, caller, path, expected):
    env.as_user(caller)
    assert outcome(env.call("GET", path, query_string=OUT_OF_RANGE_WINDOWS["series_past_the_calendar"])) == expected


# ---------------------------------------------------------------------------
# The shared checker
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def windows():
    spec = importlib.util.spec_from_file_location("functions_stats_windows_under_test", APP_ROOT / "functions_stats_windows.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_bounded_window_refuses_only_custom_dates_outside_the_range(windows):
    assert windows.resolve_bounded_stats_time_window({"days": "7"})["days"] == 7
    inside = windows.resolve_bounded_stats_time_window({"start_date": "2000-01-01", "end_date": "9998-12-31"})
    assert (inside["type"], inside["start_date_iso"], inside["end_date_iso"]) == (
        "custom", "2000-01-01T00:00:00", "9998-12-31T23:59:59.999999",
    )
    for query in OUT_OF_RANGE_WINDOWS.values():
        with pytest.raises(windows.StatsDateRangeError) as refused:
            windows.resolve_bounded_stats_time_window(query)
        assert isinstance(refused.value, ValueError)
        assert str(refused.value) == windows.STATS_DATE_RANGE_MESSAGE == DATE_RANGE["error"]
    with pytest.raises(ValueError, match="^start_date must use YYYY-MM-DD format.$"):
        windows.resolve_bounded_stats_time_window({"start_date": "soon", "end_date": "2026-09-01"})


def test_the_unbounded_window_is_unchanged(windows):
    """Public workspace statistics and profile trends still use it, recorded rather than changed."""
    window = windows.resolve_stats_time_window({"start_date": "1999-12-31", "end_date": "2000-01-01"})
    assert window["days"] == 2
    with pytest.raises(OverflowError):
        windows.resolve_stats_time_window(OUT_OF_RANGE_WINDOWS["offset_before_the_calendar"])


def _window_resolvers(file_name):
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    return sorted({
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"resolve_stats_time_window", "resolve_bounded_stats_time_window"}
    })


@pytest.mark.parametrize("file_name,expected", [
    ("route_backend_groups.py", ["resolve_bounded_stats_time_window"]),
    ("functions_group_insights.py", ["resolve_bounded_stats_time_window"]),
    ("route_backend_public_workspaces.py", ["resolve_stats_time_window"]),
    ("route_frontend_profile.py", ["resolve_stats_time_window"]),
])
def test_each_stats_route_uses_its_window(file_name, expected):
    assert _window_resolvers(file_name) == expected
