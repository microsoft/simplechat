# test_group_settings_fixture_parity.py
"""
Per-route shape parity between the M7C group settings UI fixture and the real routes.
Version: 0.261.165
Implemented in: 0.261.165

M7C contract Section 8, F5. The V2 group Settings, Activity and Statistics browser suite mocks the
network with the closed HTTP fixture `ui_tests/fixtures/group_workspace.py`, so a fixture whose
response shape drifts from the server would let a passing browser test hide a real regression. This
test pins the fixture's response keys against the real native group settings and insights routes,
driven by the same isolated backend harness the group settings functional tests use
(`test_support/group_settings_harness.py`, running the real policy, access, settings, insight,
branding, stats-window, group-document and retention modules against an etag-enforcing fake Cosmos).

For every native route the UI calls -- the settings read; the profile, downloads, retention, logo
PUT and logo DELETE writes; and the activity, statistics and file-count insight reads -- it asserts
that the fixture never invents a top-level or nested key the server does not return
(`fixture keys <= server keys`), that the keys the UI reads are present in both, and that the status
code and, on an error, the machine-readable `error_code` match. It covers success, each 409 code
(`group_settings_changed`, `group_write_conflict`, `no_group_logo`), a reviewed 400 and the two 503
insight-unavailable codes, so the run fails the moment the fixture drifts from the server.

The fixture handlers are the production browser-test code, exercised here through the same
`_dispatch` entry the Playwright route handler calls, with a tiny fake page and route that only
capture the fulfilled status and JSON. The logo upload is driven with a real multipart body so the
fixture's own multipart parser runs, exactly as it does behind the browser.
"""

import ast
import sys
from io import BytesIO
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN
from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture, _settings_kwargs, group_context

from test_support.group_settings_harness import group_settings_environment, png_bytes


def _app_constant(file_name, name):
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    values = {}

    def evaluate(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "date":
            return date(*(evaluate(argument) for argument in node.args))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            value = evaluate(node.func.value)
            if node.func.attr == "isoformat" and not node.args and not node.keywords:
                return value.isoformat()
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.JoinedStr):
            parts = []
            for part in node.values:
                if isinstance(part, ast.Constant):
                    parts.append(str(part.value))
                elif isinstance(part, ast.FormattedValue):
                    parts.append(str(evaluate(part.value)))
            return "".join(parts)
        return ast.literal_eval(node)

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = evaluate(node.value)
            values[node.targets[0].id] = value
            if node.targets[0].id == name:
                return value
    raise LookupError(f"{file_name} defines no constant {name}")


# The group the fixture seeds as an Owner in an active group, matching the harness's owner-1 group.
FIXTURE_GROUP = "group-a"
REAL_GROUP = "group-1"
REAL_OWNER = "owner-1"
STATS_EARLIEST_CUSTOM_DATE = _app_constant("functions_stats_windows.py", "STATS_EARLIEST_CUSTOM_DATE")
STATS_LATEST_CUSTOM_DATE = _app_constant("functions_stats_windows.py", "STATS_LATEST_CUSTOM_DATE")
STATS_DATE_RANGE_MESSAGE = _app_constant("functions_stats_windows.py", "STATS_DATE_RANGE_MESSAGE")

SETTINGS_PATH = "/api/groups/{group}/settings"

# The keys the native Settings view reads off the settings envelope and each of its sections. The
# fixture may carry fewer keys than the server (a subset is fine), but it must never drop one the
# view relies on, nor invent one the server never returns.
SETTINGS_KEYS = {"schema_version", "group_id", "viewer_role", "status", "profile", "logo",
                 "settings_management"}
PROFILE_KEYS = {"name", "description", "hero_color", "revision"}
LOGO_KEYS = {"has_logo", "logo_version", "logo_url", "revision"}
MANAGEMENT_KEYS = {"schema_version", "operations", "reasons"}
DOWNLOADS_KEYS = {"disable_file_downloads", "file_downloads_enabled", "revision"}
RETENTION_KEYS = {"conversation_retention_days", "document_retention_days", "bounds",
                  "organization_defaults", "revision"}
STATS_KEYS = {"totalDocuments", "storageUsed", "totalTokens", "totalMembers", "storage",
              "documentActivity", "tokenUsage", "dateRange", "window"}
WINDOW_KEYS = {"type", "days", "label", "startDate", "endDate"}
ACTIVITY_ITEM_KEYS = {"id", "occurred_at", "type", "summary", "actor"}


# --------------------------------------------------------------------------
# Fixture driving: a fake page and route that only capture the fulfilled response.
# --------------------------------------------------------------------------

class _FakeContext:
    def route(self, *args, **kwargs):
        pass

    def on(self, *args, **kwargs):
        pass


class _FakePage:
    def __init__(self):
        self.context = _FakeContext()
        self.url = "about:blank"

    def on(self, *args, **kwargs):
        pass


class _FakeRequest:
    def __init__(self, url, method, headers=None, post_data_buffer=None):
        self.url = url
        self.method = method
        self.headers = headers or {}
        self.post_data_buffer = post_data_buffer


class _FakeRoute:
    def __init__(self, url, method, headers=None, post_data_buffer=None):
        self.request = _FakeRequest(url, method, headers, post_data_buffer)
        self.status = 200
        self.payload = None

    def fulfill(self, status=200, json=None, **kwargs):
        self.status = status
        self.payload = json


def drive_fixture(fixture, method, path, body=None, query=None, headers=None, post_data_buffer=None):
    """Dispatch one request through the fixture exactly as its Playwright route handler would, and
    return the fulfilled (status, payload)."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}", method, headers, post_data_buffer)
    fixture._dispatch(route, entry)
    return route.status, route.payload


def new_fixture():
    # BASE_SETTINGS on the real side models a deployment with group downloads and retention both on.
    # The base fixture keeps retention off (the deployment the context parity test pins), so group-a
    # opts in here to match the modelled deployment this parity test compares against.
    fixture = GroupWorkspaceFixture(_FakePage())
    fixture.apply_group_settings_flags(FIXTURE_GROUP, downloads_admin=True, retention_enabled=True)
    return fixture


def fixture_revision(fixture, section):
    return fixture._settings_revision(FIXTURE_GROUP, section)


def configure_fixture_status(fixture, status, role="Owner"):
    current = fixture.groups[FIXTURE_GROUP]
    fixture.groups[FIXTURE_GROUP] = group_context(
        FIXTURE_GROUP, current["workspace"]["name"], role=role, status=status, viewer=fixture.viewer_id,
        **_settings_kwargs(fixture.group_settings_flags_by_id.get(FIXTURE_GROUP, {})),
    )


def multipart_logo(revision, filename="logo.png", content=None):
    """A real multipart/form-data body carrying a logo_file and the revision, for the fixture's own
    parser to read, plus the content-type header its boundary lives in."""
    boundary = "----parity-logo-boundary"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="revision"\r\n\r\n'
        f"{revision}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="logo_file"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("ascii")
    body = prefix + (png_bytes() if content is None else content) + f"\r\n--{boundary}--\r\n".encode("ascii")
    headers = {"content-type": f"multipart/form-data; boundary={boundary}"}
    return body, headers


# --------------------------------------------------------------------------
# Real routes: the isolated backend harness.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def module_env():
    with group_settings_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group(REAL_GROUP)
    module_env.as_user(REAL_OWNER, roles=("User",))
    yield module_env
    module_env.reset()


def real_revision(env, section):
    return env.revision(section, REAL_GROUP)


def real_settings_path(section=None):
    base = SETTINGS_PATH.format(group=REAL_GROUP)
    return f"{base}/{section}" if section else base


def fixture_settings_path(section=None):
    base = SETTINGS_PATH.format(group=FIXTURE_GROUP)
    return f"{base}/{section}" if section else base


# --------------------------------------------------------------------------
# Parity assertions.
# --------------------------------------------------------------------------

def assert_no_invented_keys(scenario, fixture_payload, real_payload):
    invented = set(fixture_payload) - set(real_payload)
    assert not invented, (
        f"{scenario}: the fixture returns keys the server never does: {sorted(invented)} "
        f"(server keys {sorted(set(real_payload))})"
    )


def assert_shared_keys(scenario, fixture_payload, real_payload, required):
    for key in required:
        assert key in real_payload, f"{scenario}: the server no longer returns {key!r}; the harness or contract drifted"
        assert key in fixture_payload, f"{scenario}: the fixture dropped {key!r}, which the view reads"


def assert_section_parity(scenario, fixture_settings, real_settings, section, keys):
    assert section in real_settings, f"{scenario}: the server no longer returns the {section!r} section"
    assert section in fixture_settings, f"{scenario}: the fixture dropped the {section!r} section"
    assert_no_invented_keys(f"{scenario}.{section}", fixture_settings[section], real_settings[section])
    assert_shared_keys(f"{scenario}.{section}", fixture_settings[section], real_settings[section], keys)


def assert_settings_parity(scenario, fixture_payload, real_payload):
    """Every settings envelope the writes and the read return has the same shape the UI reads."""
    assert_no_invented_keys(scenario, fixture_payload, real_payload)
    assert_shared_keys(scenario, fixture_payload, real_payload, {"settings"})
    fixture_settings, real_settings = fixture_payload["settings"], real_payload["settings"]
    assert_no_invented_keys(f"{scenario}.settings", fixture_settings, real_settings)
    assert_shared_keys(f"{scenario}.settings", fixture_settings, real_settings, SETTINGS_KEYS)
    assert_section_parity(scenario, fixture_settings, real_settings, "profile", PROFILE_KEYS)
    assert_section_parity(scenario, fixture_settings, real_settings, "logo", LOGO_KEYS)
    assert_section_parity(scenario, fixture_settings, real_settings, "settings_management", MANAGEMENT_KEYS)
    # BASE_SETTINGS enables both file downloads and group retention, so both sections are present.
    assert_section_parity(scenario, fixture_settings, real_settings, "downloads", DOWNLOADS_KEYS)
    assert_section_parity(scenario, fixture_settings, real_settings, "retention", RETENTION_KEYS)


def assert_error_parity(scenario, fixture_status, real, expected_status, expected_code=None):
    assert (fixture_status, real.status_code) == (expected_status, expected_status), (
        f"{scenario}: status codes diverged (fixture {fixture_status}, server {real.status_code})"
    )
    real_payload = real.get_json()
    fixture_payload = scenario_payload_holder[scenario]
    assert_no_invented_keys(scenario, fixture_payload, real_payload)
    assert_shared_keys(scenario, fixture_payload, real_payload, {"error"})
    if expected_code is not None:
        assert_shared_keys(scenario, fixture_payload, real_payload, {"error_code"})
        assert fixture_payload["error_code"] == real_payload["error_code"] == expected_code, (
            f"{scenario}: error_code diverged (fixture {fixture_payload.get('error_code')!r}, "
            f"server {real_payload.get('error_code')!r})"
        )
    return real_payload


# A tiny holder so the error helper can read the fixture payload the test just captured.
scenario_payload_holder = {}


def record(scenario, payload):
    scenario_payload_holder[scenario] = payload
    return payload


# --------------------------------------------------------------------------
# Success shapes.
# --------------------------------------------------------------------------

def test_settings_read_shape_parity(env):
    """The settings read envelope and each of its sections carry the keys the view reads."""
    real = env.settings_read(REAL_GROUP)
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", fixture_settings_path())

    assert (status, real.status_code) == (200, 200)
    assert_settings_parity("read", payload, real.get_json())


def test_profile_write_shape_parity(env):
    """A profile PATCH returns the settings envelope, its shape matching a read."""
    real = env.call("PATCH", real_settings_path("profile"),
                    {"revision": real_revision(env, "profile"), "name": "Renamed group"})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_settings_path("profile"),
                                    body={"revision": fixture_revision(fixture, "profile"), "name": "Renamed group"})

    assert (status, real.status_code) == (200, 200)
    assert_settings_parity("profile", payload, real.get_json())


def test_downloads_write_shape_parity(env):
    """A downloads PATCH returns the settings envelope."""
    real = env.call("PATCH", real_settings_path("downloads"),
                    {"revision": real_revision(env, "downloads"), "disable_file_downloads": True})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_settings_path("downloads"),
                                    body={"revision": fixture_revision(fixture, "downloads"),
                                          "disable_file_downloads": True})

    assert (status, real.status_code) == (200, 200)
    assert_settings_parity("downloads", payload, real.get_json())


def test_retention_write_shape_parity(env):
    """A retention PATCH returns the settings envelope, including the bounds and defaults."""
    real = env.call("PATCH", real_settings_path("retention"),
                    {"revision": real_revision(env, "retention"), "conversation_retention_days": 30})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_settings_path("retention"),
                                    body={"revision": fixture_revision(fixture, "retention"),
                                          "conversation_retention_days": 30})

    assert (status, real.status_code) == (200, 200)
    assert_settings_parity("retention", payload, real.get_json())


def test_logo_put_shape_parity(env):
    """A logo PUT (multipart) returns the settings envelope, its logo section matching a read."""
    body, headers = multipart_logo(real_revision(env, "logo"))
    real = env.call("PUT", real_settings_path("logo"), data={
        "revision": real_revision(env, "logo"),
        "logo_file": (BytesIO(png_bytes()), "logo.png"),
    }, content_type="multipart/form-data")

    fixture = new_fixture()
    fixture_body, fixture_headers = multipart_logo(fixture_revision(fixture, "logo"))
    status, payload = drive_fixture(fixture, "PUT", fixture_settings_path("logo"),
                                    headers=fixture_headers, post_data_buffer=fixture_body)

    assert (status, real.status_code) == (200, 200)
    assert_settings_parity("logo", payload, real.get_json())
    assert payload["settings"]["logo"]["logo_version"] >= 1


def test_unreadable_logo_upload_value_parity(env):
    """A .png name with non-image bytes is the same reviewed 400 as the server."""
    real = env.call("PUT", real_settings_path("logo"), data={
        "revision": real_revision(env, "logo"),
        "logo_file": (BytesIO(b"not image bytes"), "logo.png"),
    }, content_type="multipart/form-data")

    fixture = new_fixture()
    fixture_body, fixture_headers = multipart_logo(
        fixture_revision(fixture, "logo"), content=b"not image bytes",
    )
    status, payload = drive_fixture(fixture, "PUT", fixture_settings_path("logo"),
                                    headers=fixture_headers, post_data_buffer=fixture_body)

    record("unreadable_logo_upload", payload)
    real_payload = assert_error_parity("unreadable_logo_upload", status, real, 400, "invalid_request")
    assert payload["error"] == real_payload["error"] == (
        "The logo image could not be read. Upload a PNG or JPEG image."
    )


# --------------------------------------------------------------------------
# Insight reads.
# --------------------------------------------------------------------------

def test_activity_shape_parity(env):
    """The activity read returns `{activity, limit}`, each item matching the view's shape."""
    real = env.call("GET", f"/api/groups/{REAL_GROUP}/insights/activity", query_string={"limit": "10"})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", f"/api/groups/{FIXTURE_GROUP}/insights/activity",
                                    query={"limit": ["10"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("activity", payload, real_payload)
    assert_shared_keys("activity", payload, real_payload, {"activity", "limit"})
    if real_payload["activity"] and payload["activity"]:
        fixture_item, real_item = payload["activity"][0], real_payload["activity"][0]
        assert_no_invented_keys("activity.item", fixture_item, real_item)
        assert_shared_keys("activity.item", fixture_item, real_item, ACTIVITY_ITEM_KEYS)


def test_stats_shape_parity(env):
    """The statistics read returns `{stats}`, its figures and window matching the view's shape."""
    real = env.call("GET", f"/api/groups/{REAL_GROUP}/insights/stats", query_string={"days": "30"})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", f"/api/groups/{FIXTURE_GROUP}/insights/stats",
                                    query={"days": ["30"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("stats", payload, real_payload)
    assert_shared_keys("stats", payload, real_payload, {"stats"})
    assert_no_invented_keys("stats.stats", payload["stats"], real_payload["stats"])
    assert_shared_keys("stats.stats", payload["stats"], real_payload["stats"], STATS_KEYS)
    assert_no_invented_keys("stats.window", payload["stats"]["window"], real_payload["stats"]["window"])
    assert_shared_keys("stats.window", payload["stats"]["window"], real_payload["stats"]["window"], WINDOW_KEYS)


def test_custom_stats_window_value_parity(env):
    """A custom window reports the same values, including the classic short-date label."""
    query = {"start_date": ["2024-01-01"], "end_date": ["2024-01-31"]}
    real = env.call("GET", f"/api/groups/{REAL_GROUP}/insights/stats",
                    query_string={"start_date": "2024-01-01", "end_date": "2024-01-31"})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", f"/api/groups/{FIXTURE_GROUP}/insights/stats", query=query)

    assert (status, real.status_code) == (200, 200)
    real_window = real.get_json()["stats"]["window"]
    fixture_window = payload["stats"]["window"]
    assert fixture_window == real_window
    assert fixture_window["label"] == "1/1/2024 - 1/31/2024"


@pytest.mark.parametrize("scenario,query,expected_message", [
    (
        "range_over_366_days",
        {"start_date": "2024-01-01", "end_date": "2025-01-01"},
        "Choose a date range of 366 days or fewer.",
    ),
    (
        "out_of_bounds_range",
        {
            "start_date": (STATS_EARLIEST_CUSTOM_DATE - timedelta(days=1)).isoformat(),
            "end_date": STATS_EARLIEST_CUSTOM_DATE.isoformat(),
        },
        STATS_DATE_RANGE_MESSAGE,
    ),
    (
        "after_latest_range",
        {
            "start_date": STATS_LATEST_CUSTOM_DATE.isoformat(),
            "end_date": (STATS_LATEST_CUSTOM_DATE + timedelta(days=1)).isoformat(),
        },
        STATS_DATE_RANGE_MESSAGE,
    ),
    (
        "malformed_date",
        {"start_date": "not-a-date", "end_date": "2024-01-31"},
        "start_date must use YYYY-MM-DD format.",
    ),
])
def test_stats_window_refusal_value_parity(env, scenario, query, expected_message):
    real = env.call("GET", f"/api/groups/{REAL_GROUP}/insights/stats", query_string=query)
    fixture = new_fixture()
    fixture_query = {key: [value] for key, value in query.items()}
    status, payload = drive_fixture(
        fixture, "GET", f"/api/groups/{FIXTURE_GROUP}/insights/stats", query=fixture_query,
    )

    record(scenario, payload)
    real_payload = assert_error_parity(scenario, status, real, 400, "invalid_request")
    assert payload["error"] == real_payload["error"] == expected_message


def test_file_count_shape_parity(env):
    """The file-count read returns `{file_count}` from both."""
    real = env.call("GET", f"/api/groups/{REAL_GROUP}/insights/file-count")
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", f"/api/groups/{FIXTURE_GROUP}/insights/file-count")

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("file-count", payload, real_payload)
    assert_shared_keys("file-count", payload, real_payload, {"file_count"})


# --------------------------------------------------------------------------
# Conflict codes.
# --------------------------------------------------------------------------

def test_settings_changed_shape_parity(env):
    """A stale revision returns `{error, error_code: "group_settings_changed"}` from both."""
    real = env.call("PATCH", real_settings_path("profile"),
                    {"revision": "profile-does-not-match", "name": "Renamed"})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_settings_path("profile"),
                                    body={"revision": "profile-does-not-match", "name": "Renamed"})

    record("group_settings_changed", payload)
    assert_error_parity("group_settings_changed", status, real, 409, "group_settings_changed")


def test_write_conflict_shape_parity(env):
    """A never-settling concurrent group write returns `{error, error_code: "group_write_conflict"}`."""
    revision = real_revision(env, "profile")
    attempts = env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS

    def bump(index):
        def concurrent():
            stored = env.stored_group(REAL_GROUP)
            stored.setdefault("users", []).append(
                {"userId": f"late-{index}", "email": "", "displayName": "Late"})
            env.groups.seed(stored)
        return concurrent

    env.groups.before_replace.extend(bump(index) for index in range(attempts))
    real = env.call("PATCH", real_settings_path("profile"), {"revision": revision, "name": "Busy"})

    fixture = new_fixture()
    fixture.settings_force_write_conflict.add(FIXTURE_GROUP)
    status, payload = drive_fixture(fixture, "PATCH", fixture_settings_path("profile"),
                                    body={"revision": fixture_revision(fixture, "profile"), "name": "Busy"})

    record("group_write_conflict", payload)
    real_payload = assert_error_parity("group_write_conflict", status, real, 409, "group_write_conflict")
    assert payload["error"] == real_payload["error"] == "The group changed while your request was being saved. Try again."


def test_no_group_logo_shape_parity(env):
    """Removing a logo the group does not have returns `{error, error_code: "no_group_logo"}`."""
    real = env.call("DELETE", real_settings_path("logo"), {"revision": real_revision(env, "logo")})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", fixture_settings_path("logo"),
                                    body={"revision": fixture_revision(fixture, "logo")})

    record("no_group_logo", payload)
    assert_error_parity("no_group_logo", status, real, 409, "no_group_logo")


# --------------------------------------------------------------------------
# One reviewed 400 and the insight 503s.
# --------------------------------------------------------------------------

def test_reviewed_400_shape_parity(env):
    """A profile PATCH naming an unknown field returns the server's reviewed 400 text, verbatim."""
    real = env.call("PATCH", real_settings_path("profile"),
                    {"revision": real_revision(env, "profile"), "color": "purple"})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_settings_path("profile"),
                                    body={"revision": fixture_revision(fixture, "profile"), "color": "purple"})

    record("reviewed_400", payload)
    real_payload = assert_error_parity("reviewed_400", status, real, 400)
    # The editor renders the server's own text; a drift in the fixture's copy would mislead a user.
    assert payload["error"] == real_payload["error"]


@pytest.mark.parametrize("stored_status,expected_text", [
    ("locked", "This group is locked or inactive, so its name, description, color and logo can't be changed."),
    ("archived", "This group's status isn't recognized, so its name, description, color and logo can't be changed."),
])
def test_status_refusal_text_value_parity(env, stored_status, expected_text):
    """Profile writes carry the same reviewed locked/unknown status text as the real route."""
    env.groups.records.clear()
    env.seed_group(REAL_GROUP, status=stored_status)
    env.as_user(REAL_OWNER, roles=("User",))
    real = env.call("PATCH", real_settings_path("profile"),
                    {"revision": real_revision(env, "profile"), "name": "Blocked"})

    fixture = new_fixture()
    configure_fixture_status(fixture, stored_status)
    status, payload = drive_fixture(fixture, "PATCH", fixture_settings_path("profile"),
                                    body={"revision": fixture_revision(fixture, "profile"), "name": "Blocked"})

    scenario = f"{stored_status}_status_refusal"
    record(scenario, payload)
    real_payload = assert_error_parity(scenario, status, real, 403, "group_status_unavailable")
    assert payload["error"] == real_payload["error"] == expected_text


def test_activity_unavailable_shape_parity(env):
    """A failing activity query returns `{error, error_code: "group_activity_unavailable"}` (503)."""
    env.activity_logs.fail_queries = 1
    real = env.call("GET", f"/api/groups/{REAL_GROUP}/insights/activity")
    fixture = new_fixture()
    fixture.activity_unavailable.add(FIXTURE_GROUP)
    status, payload = drive_fixture(fixture, "GET", f"/api/groups/{FIXTURE_GROUP}/insights/activity")

    record("group_activity_unavailable", payload)
    assert_error_parity("group_activity_unavailable", status, real, 503, "group_activity_unavailable")


def test_stats_unavailable_shape_parity(env):
    """A failing statistics query returns `{error, error_code: "group_stats_unavailable"}` (503)."""
    env.activity_logs.fail_queries = 1
    real = env.call("GET", f"/api/groups/{REAL_GROUP}/insights/stats")
    fixture = new_fixture()
    fixture.stats_unavailable.add(FIXTURE_GROUP)
    status, payload = drive_fixture(fixture, "GET", f"/api/groups/{FIXTURE_GROUP}/insights/stats")

    record("group_stats_unavailable", payload)
    assert_error_parity("group_stats_unavailable", status, real, 503, "group_stats_unavailable")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
