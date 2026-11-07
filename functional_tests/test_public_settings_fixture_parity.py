# test_public_settings_fixture_parity.py
"""
Per-route parity between the M10C public settings browser fixture and the real routes.
Version: 0.261.185
Implemented in: 0.261.185

The V2 public Settings, Activity and Statistics browser suite mocks the network with the closed HTTP
fixture `ui_tests/fixtures/public_settings.py`, so a fixture whose answers drift from the server would
let a passing browser test hide a real regression. This test drives the fixture's handlers through the
same `_dispatch` entry its Playwright route handler calls (a tiny fake page and route capture the
fulfilled status, JSON and headers), and the real native routes through the isolated backend harness
the public settings functional tests use (`test_support/public_settings_harness.py`: the real policy,
settings, insights, branding, stats-window and public workspace modules over an etag-enforcing fake
Cosmos), and requires them to agree.

For every native route the sections call -- the settings read; the profile, downloads, retention, logo
PUT and logo DELETE writes; and the activity, statistics and file-count reads -- it asserts that the
fixture never invents a key the server doesn't return, that the keys the sections read are present in
both, and that the status and `error_code` match. The reviewed texts the sections show verbatim are
compared by value: every refusal reason (owner, manager, member, locked and unrecognized status), the
404, the query refusal, the stale revision, the shared write conflict, the missing logo, the unreadable
image, the name, retention and downloads validation, the activity limit, the stats window refusals, and
the two insight 503s. Every answer carries `Cache-Control: no-store` on both sides.

The fixture's workspace `pub-a` is owned by the viewer in an active workspace with the administrator's
downloads and public retention on, which is the harness's `public-1` read by its owner under its base
settings.
"""

import sys
from io import BytesIO
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures import public_settings as fixture_module  # noqa: E402
from ui_tests.fixtures.public_settings import PublicSettingsFixture  # noqa: E402
from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN  # noqa: E402

from test_support.public_settings_harness import png_bytes, public_settings_environment  # noqa: E402


FIXTURE_WS = "pub-a"
REAL_WS = "public-1"
ROLE_USERS = {"Owner": "owner-1", "Admin": "admin-1", "DocumentManager": "manager-1", "User": "outsider-1"}

# The keys the native sections read off each envelope. The fixture may carry fewer keys than the
# server, but it must never drop one the sections rely on, nor invent one the server never returns.
SETTINGS_KEYS = {"schema_version", "workspace_id", "viewer_role", "status", "profile", "logo",
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
# Fixture driving: a fake page and route that capture the fulfilled response.
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
        self.headers = {}

    def fulfill(self, status=200, json=None, headers=None, **kwargs):
        self.status = status
        self.payload = json
        self.headers = dict(headers or {})


class Answer:
    """One fixture answer: status, JSON and headers."""

    def __init__(self, route):
        self.status = route.status
        self.payload = route.payload
        self.headers = route.headers


def drive(fixture, method, path, body=None, query=None, headers=None, post_data_buffer=None):
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}", method, headers, post_data_buffer)
    fixture._dispatch(route, entry)
    return Answer(route)


def new_fixture(role="Owner", status="active", **flags):
    fixture = PublicSettingsFixture(_FakePage())
    if (role, status, flags) != ("Owner", "active", {}):
        fixture.configure(FIXTURE_WS, role=role, status=status, **flags)
    return fixture


def fixture_path(section=None, family="settings"):
    base = f"/api/public-workspaces/{FIXTURE_WS}/{family}"
    return f"{base}/{section}" if section else base


def real_path(section=None, family="settings"):
    base = f"/api/public-workspaces/{REAL_WS}/{family}"
    return f"{base}/{section}" if section else base


def multipart_logo(revision, filename="logo.png", content=None):
    boundary = "----public-parity-logo-boundary"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="revision"\r\n\r\n'
        f"{revision}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="logo_file"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("ascii")
    body = prefix + (png_bytes() if content is None else content) + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, {"content-type": f"multipart/form-data; boundary={boundary}"}


def concurrently(env, change):
    """Land ``change`` on the stored workspace between the real writer's read and its write."""
    def land():
        stored = env.stored_workspace(REAL_WS)
        change(stored)
        env.public_workspaces.seed(stored)
    env.public_workspaces.before_replace.append(land)


# --------------------------------------------------------------------------
# Real routes: the isolated backend harness.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def module_env():
    with public_settings_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_workspace(REAL_WS, status="active")
    module_env.as_user("owner-1")
    yield module_env
    module_env.reset()


def reseed(env, **fields):
    env.public_workspaces.records.clear()
    return env.seed_workspace(REAL_WS, status=fields.pop("status", "active"), **fields)


# --------------------------------------------------------------------------
# Parity assertions.
# --------------------------------------------------------------------------

def assert_no_store(scenario, answer, real):
    assert answer.headers.get("Cache-Control") == "no-store", f"{scenario}: the fixture dropped no-store"
    assert real.headers.get("Cache-Control") == "no-store", f"{scenario}: the server dropped no-store"


def assert_no_invented_keys(scenario, fixture_payload, real_payload):
    invented = set(fixture_payload) - set(real_payload)
    assert not invented, f"{scenario}: the fixture returns keys the server never does: {sorted(invented)}"


def assert_shared_keys(scenario, fixture_payload, real_payload, required):
    for key in required:
        assert key in real_payload, f"{scenario}: the server no longer returns {key!r}"
        assert key in fixture_payload, f"{scenario}: the fixture dropped {key!r}, which the sections read"


def assert_section(scenario, fixture_settings, real_settings, section, keys):
    assert_no_invented_keys(f"{scenario}.{section}", fixture_settings[section], real_settings[section])
    assert_shared_keys(f"{scenario}.{section}", fixture_settings[section], real_settings[section], keys)


def assert_settings_parity(scenario, answer, real):
    assert (answer.status, real.status_code) == (200, 200), (scenario, answer.payload, real.get_json())
    assert_no_store(scenario, answer, real)
    fixture_payload, real_payload = answer.payload, real.get_json()
    assert set(fixture_payload) == set(real_payload) == {"settings"}
    fixture_settings, real_settings = fixture_payload["settings"], real_payload["settings"]
    assert_no_invented_keys(f"{scenario}.settings", fixture_settings, real_settings)
    assert_shared_keys(f"{scenario}.settings", fixture_settings, real_settings, SETTINGS_KEYS)
    for section, keys in (("profile", PROFILE_KEYS), ("logo", LOGO_KEYS), ("settings_management", MANAGEMENT_KEYS),
                          ("downloads", DOWNLOADS_KEYS), ("retention", RETENTION_KEYS)):
        assert_section(scenario, fixture_settings, real_settings, section, keys)
    # The decision is the same for the same role, status and deployment.
    assert fixture_settings["settings_management"] == real_settings["settings_management"]
    for section in ("bounds", "organization_defaults"):
        assert set(fixture_settings["retention"][section]) == set(real_settings["retention"][section])
    return fixture_settings, real_settings


def assert_error_parity(scenario, answer, real, status, code, message=None):
    real_payload = real.get_json()
    assert (answer.status, real.status_code) == (status, status), (scenario, answer.payload, real_payload)
    assert_no_store(scenario, answer, real)
    assert set(answer.payload) == set(real_payload) == {"error", "error_code"}, (scenario, answer.payload, real_payload)
    assert answer.payload["error_code"] == real_payload["error_code"] == code, (scenario, answer.payload, real_payload)
    assert answer.payload["error"] == real_payload["error"], (
        f"{scenario}: the fixture's text drifted\n  fixture: {answer.payload['error']!r}\n"
        f"  server:  {real_payload['error']!r}"
    )
    if message is not None:
        assert real_payload["error"] == message
    return real_payload


# --------------------------------------------------------------------------
# Success shapes.
# --------------------------------------------------------------------------

def test_settings_read_shape_parity(env):
    real = env.settings_read(REAL_WS)
    answer = drive(new_fixture(), "GET", fixture_path())
    fixture_settings, real_settings = assert_settings_parity("read", answer, real)
    assert fixture_settings["logo"]["logo_url"] is real_settings["logo"]["logo_url"] is None


def test_profile_write_shape_parity(env):
    real = env.call("PATCH", real_path("profile"), {"revision": env.revision("profile", REAL_WS), "name": "Renamed"})
    fixture = new_fixture()
    answer = drive(fixture, "PATCH", fixture_path("profile"),
                   body={"revision": fixture._revision(FIXTURE_WS, "profile"), "name": "Renamed"})
    fixture_settings, real_settings = assert_settings_parity("profile", answer, real)
    assert fixture_settings["profile"]["name"] == real_settings["profile"]["name"] == "Renamed"


def test_downloads_write_shape_parity(env):
    real = env.call("PATCH", real_path("downloads"),
                    {"revision": env.revision("downloads", REAL_WS), "disable_file_downloads": True})
    fixture = new_fixture()
    answer = drive(fixture, "PATCH", fixture_path("downloads"),
                   body={"revision": fixture._revision(FIXTURE_WS, "downloads"), "disable_file_downloads": True})
    fixture_settings, real_settings = assert_settings_parity("downloads", answer, real)
    for key in ("disable_file_downloads", "file_downloads_enabled"):
        assert fixture_settings["downloads"][key] == real_settings["downloads"][key]


def test_retention_write_shape_parity(env):
    real = env.call("PATCH", real_path("retention"),
                    {"revision": env.revision("retention", REAL_WS), "conversation_retention_days": 30})
    fixture = new_fixture()
    answer = drive(fixture, "PATCH", fixture_path("retention"),
                   body={"revision": fixture._revision(FIXTURE_WS, "retention"), "conversation_retention_days": 30})
    fixture_settings, real_settings = assert_settings_parity("retention", answer, real)
    for key in ("conversation_retention_days", "document_retention_days"):
        assert fixture_settings["retention"][key] == real_settings["retention"][key]


def test_logo_put_and_delete_shape_parity(env):
    real = env.call("PUT", real_path("logo"), data={
        "revision": env.revision("logo", REAL_WS), "logo_file": (BytesIO(png_bytes()), "logo.png"),
    })
    fixture = new_fixture()
    body, headers = multipart_logo(fixture._revision(FIXTURE_WS, "logo"))
    answer = drive(fixture, "PUT", fixture_path("logo"), headers=headers, post_data_buffer=body)
    fixture_settings, real_settings = assert_settings_parity("logo-put", answer, real)
    assert fixture_settings["logo"]["has_logo"] is real_settings["logo"]["has_logo"] is True
    assert fixture_settings["logo"]["logo_version"] == real_settings["logo"]["logo_version"] == 2
    assert fixture_settings["logo"]["logo_url"] == f"/api/public_workspaces/{FIXTURE_WS}/logo?v=2"
    assert real_settings["logo"]["logo_url"] == f"/api/public_workspaces/{REAL_WS}/logo?v=2"

    real = env.call("DELETE", real_path("logo"), {"revision": env.revision("logo", REAL_WS)})
    answer = drive(fixture, "DELETE", fixture_path("logo"), body={"revision": fixture._revision(FIXTURE_WS, "logo")})
    fixture_settings, real_settings = assert_settings_parity("logo-delete", answer, real)
    assert fixture_settings["logo"]["has_logo"] is real_settings["logo"]["has_logo"] is False
    assert fixture_settings["logo"]["logo_version"] == real_settings["logo"]["logo_version"] == 3


# --------------------------------------------------------------------------
# Insight reads.
# --------------------------------------------------------------------------

def test_activity_shape_and_actor_parity(env):
    for record_id, activity_type, user_id in (
        ("activity-1", "document_creation", "owner-1"),
        ("activity-2", "conversation_creation", "outsider-1"),
        ("activity-3", "token_usage", REAL_WS),
    ):
        env.activity_logs.seed_activity({
            "id": record_id, "user_id": user_id, "activity_type": activity_type,
            "timestamp": "2024-05-02T09:00:00", "created_at": "2024-05-02T09:00:00",
            "workspace_type": "public", "workspace_context": {"public_workspace_id": REAL_WS},
        })
    real = env.call("GET", real_path("activity", family="insights"), query_string={"limit": "10"})
    answer = drive(new_fixture(), "GET", fixture_path("activity", family="insights"), query={"limit": ["10"]})
    assert (answer.status, real.status_code) == (200, 200)
    assert_no_store("activity", answer, real)
    real_payload = real.get_json()
    assert set(answer.payload) == set(real_payload) == {"activity", "limit"}
    assert answer.payload["limit"] == real_payload["limit"] == 10
    for fixture_item in answer.payload["activity"]:
        assert set(fixture_item) == ACTIVITY_ITEM_KEYS == set(real_payload["activity"][0])
    # Every actor shape the fixture serves is one the server projects: a member by name, a signed-in
    # person who holds no role, and the system.
    real_actors = {item["actor"]["kind"]: set(item["actor"]) for item in real_payload["activity"]}
    fixture_actors = {item["actor"]["kind"]: set(item["actor"]) for item in answer.payload["activity"]}
    assert fixture_actors == real_actors == {
        "member": {"kind", "display_name"}, "non_member": {"kind"}, "system": {"kind"},
    }


def test_stats_shape_parity(env):
    real = env.call("GET", real_path("stats", family="insights"), query_string={"days": "30"})
    answer = drive(new_fixture(), "GET", fixture_path("stats", family="insights"), query={"days": ["30"]})
    assert (answer.status, real.status_code) == (200, 200)
    assert_no_store("stats", answer, real)
    real_payload = real.get_json()
    assert set(answer.payload) == set(real_payload) == {"stats"}
    assert_no_invented_keys("stats", answer.payload["stats"], real_payload["stats"])
    assert_shared_keys("stats", answer.payload["stats"], real_payload["stats"], STATS_KEYS)
    assert set(answer.payload["stats"]["window"]) == set(real_payload["stats"]["window"]) == WINDOW_KEYS
    assert "storageLimit" not in real_payload["stats"] and "storageLimit" not in answer.payload["stats"]


def test_custom_stats_window_value_parity(env):
    real = env.call("GET", real_path("stats", family="insights"),
                    query_string={"start_date": "2024-01-01", "end_date": "2024-01-31"})
    answer = drive(new_fixture(), "GET", fixture_path("stats", family="insights"),
                   query={"start_date": ["2024-01-01"], "end_date": ["2024-01-31"]})
    assert (answer.status, real.status_code) == (200, 200)
    assert answer.payload["stats"]["window"] == real.get_json()["stats"]["window"]
    assert answer.payload["stats"]["window"]["label"] == "1/1/2024 - 1/31/2024"


def test_file_count_shape_parity(env):
    real = env.call("GET", real_path("file-count", family="insights"))
    answer = drive(new_fixture(), "GET", fixture_path("file-count", family="insights"))
    assert (answer.status, real.status_code) == (200, 200)
    assert_no_store("file-count", answer, real)
    assert set(answer.payload) == set(real.get_json()) == {"file_count"}


# --------------------------------------------------------------------------
# Refusals: the reviewed texts the sections show verbatim.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role,method,section,family,code", [
    ("DocumentManager", "GET", None, "settings", "public_workspace_manager_required"),
    ("Admin", "PATCH", "profile", "settings", "public_workspace_owner_required"),
    ("DocumentManager", "GET", "activity", "insights", "public_workspace_manager_required"),
    ("User", "GET", "stats", "insights", "public_workspace_member_required"),
    ("Admin", "GET", "file-count", "insights", "public_workspace_owner_required"),
])
def test_role_refusal_value_parity(env, role, method, section, family, code):
    env.as_user(ROLE_USERS[role])
    body = {"revision": env.revision("profile", REAL_WS), "name": "Blocked"} if method == "PATCH" else None
    real = env.call(method, real_path(section, family=family), body)
    fixture = new_fixture(role=role)
    fixture_body = {"revision": fixture._revision(FIXTURE_WS, "profile"), "name": "Blocked"} if method == "PATCH" else None
    answer = drive(fixture, method, fixture_path(section, family=family), body=fixture_body)
    assert_error_parity(f"{role}-{section}", answer, real, 403, code,
                        fixture_module.PUBLIC_SETTINGS_REFUSAL_MESSAGES[code])


@pytest.mark.parametrize("stored_status,expected", [
    ("locked", "This workspace is locked or inactive, so its name, description, color and logo can't be changed."),
    ("archived", "This workspace's status isn't recognized, so its name, description, color and logo can't be changed."),
])
def test_status_refusal_value_parity(env, stored_status, expected):
    reseed(env, status=stored_status)
    real = env.call("PATCH", real_path("profile"), {"revision": env.revision("profile", REAL_WS), "name": "Blocked"})
    fixture = new_fixture(status=stored_status)
    answer = drive(fixture, "PATCH", fixture_path("profile"),
                   body={"revision": fixture._revision(FIXTURE_WS, "profile"), "name": "Blocked"})
    assert_error_parity(f"{stored_status}-status", answer, real, 403, "public_workspace_status_unavailable", expected)


def test_downloads_not_enabled_refusal_value_parity(env):
    env.settings["allow_public_workspace_file_downloads"] = False
    real = env.call("PATCH", real_path("downloads"),
                    {"revision": env.revision("downloads", REAL_WS), "disable_file_downloads": True})
    fixture = new_fixture(downloads_admin=False)
    answer = drive(fixture, "PATCH", fixture_path("downloads"),
                   body={"revision": fixture._revision(FIXTURE_WS, "downloads"), "disable_file_downloads": True})
    assert_error_parity("downloads-off", answer, real, 403, "public_workspace_downloads_not_enabled")
    # And the read leaves the downloads card out on both sides.
    real_read = env.settings_read(REAL_WS).get_json()["settings"]
    fixture_read = drive(fixture, "GET", fixture_path()).payload["settings"]
    assert "downloads" not in real_read and "downloads" not in fixture_read


def test_retention_disabled_refusal_value_parity(env):
    env.settings["enable_retention_policy_public"] = False
    real = env.call("PATCH", real_path("retention"),
                    {"revision": env.revision("retention", REAL_WS), "document_retention_days": 30})
    fixture = new_fixture(retention_enabled=False)
    answer = drive(fixture, "PATCH", fixture_path("retention"),
                   body={"revision": fixture._revision(FIXTURE_WS, "retention"), "document_retention_days": 30})
    assert_error_parity("retention-off", answer, real, 403, "public_workspace_retention_disabled")
    real_read = env.settings_read(REAL_WS).get_json()["settings"]
    fixture_read = drive(fixture, "GET", fixture_path()).payload["settings"]
    assert "retention" not in real_read and "retention" not in fixture_read


def test_missing_workspace_value_parity(env):
    real = env.call("GET", "/api/public-workspaces/public-missing/settings")
    answer = drive(new_fixture(), "GET", "/api/public-workspaces/pub-missing/settings")
    assert_error_parity("missing", answer, real, 404, "public_workspace_not_found",
                        "The selected public workspace was not found.")


def test_query_refusal_value_parity(env):
    real = env.call("GET", real_path(), query_string={"view": "all"})
    answer = drive(new_fixture(), "GET", fixture_path(), query={"view": ["all"]})
    assert_error_parity("query", answer, real, 400, "invalid_request", "This request does not accept query parameters.")


def test_stale_revision_value_parity(env):
    real = env.call("PATCH", real_path("profile"), {"revision": "profile-does-not-match", "name": "Renamed"})
    answer = drive(new_fixture(), "PATCH", fixture_path("profile"),
                   body={"revision": "profile-does-not-match", "name": "Renamed"})
    assert_error_parity("stale", answer, real, 409, "public_workspace_settings_changed")


def test_write_conflict_value_parity(env):
    revision = env.revision("profile", REAL_WS)
    for _ in range(3):
        concurrently(env, lambda workspace: workspace["documentManagers"].append("reader-1"))
    real = env.call("PATCH", real_path("profile"), {"revision": revision, "name": "Busy"})
    fixture = new_fixture()
    fixture.force_write_conflict(FIXTURE_WS)
    answer = drive(fixture, "PATCH", fixture_path("profile"),
                   body={"revision": fixture._revision(FIXTURE_WS, "profile"), "name": "Busy"})
    assert_error_parity("conflict", answer, real, 409, "public_workspace_write_conflict",
                        "The public workspace changed while your request was being saved. Try again.")


def test_no_logo_value_parity(env):
    real = env.call("DELETE", real_path("logo"), {"revision": env.revision("logo", REAL_WS)})
    fixture = new_fixture()
    answer = drive(fixture, "DELETE", fixture_path("logo"), body={"revision": fixture._revision(FIXTURE_WS, "logo")})
    assert_error_parity("no-logo", answer, real, 409, "no_public_workspace_logo", "This workspace has no logo to remove.")


def test_unreadable_logo_value_parity(env):
    real = env.call("PUT", real_path("logo"), data={
        "revision": env.revision("logo", REAL_WS), "logo_file": (BytesIO(b"not image bytes"), "logo.png"),
    })
    fixture = new_fixture()
    body, headers = multipart_logo(fixture._revision(FIXTURE_WS, "logo"), content=b"not image bytes")
    answer = drive(fixture, "PUT", fixture_path("logo"), headers=headers, post_data_buffer=body)
    assert_error_parity("unreadable-logo", answer, real, 400, "invalid_request",
                        "The logo image could not be read. Upload a PNG or JPEG image.")


@pytest.mark.parametrize("scenario,section,fields", [
    ("unknown-field", "profile", {"color": "purple"}),
    ("no-profile-field", "profile", {}),
    ("blank-name", "profile", {"name": "   "}),
    ("long-name", "profile", {"name": "n" * 81}),
    ("control-name", "profile", {"name": "Bad\u0007name"}),
    ("long-description", "profile", {"description": "d" * 501}),
    ("hero-not-text", "profile", {"hero_color": 5}),
    ("downloads-not-bool", "downloads", {"disable_file_downloads": "yes"}),
    ("retention-out-of-bounds", "retention", {"conversation_retention_days": 0}),
    ("retention-not-days", "retention", {"document_retention_days": "forever"}),
    ("retention-empty", "retention", {}),
])
def test_reviewed_400_value_parity(env, scenario, section, fields):
    real = env.call("PATCH", real_path(section), {"revision": env.revision(section, REAL_WS), **fields})
    fixture = new_fixture()
    answer = drive(fixture, "PATCH", fixture_path(section),
                   body={"revision": fixture._revision(FIXTURE_WS, section), **fields})
    assert_error_parity(scenario, answer, real, 400, "invalid_request")


def test_missing_revision_value_parity(env):
    real = env.call("PATCH", real_path("profile"), {"name": "No revision"})
    answer = drive(new_fixture(), "PATCH", fixture_path("profile"), body={"name": "No revision"})
    assert_error_parity("no-revision", answer, real, 400, "invalid_request",
                        "Include the revision of the settings you loaded.")


@pytest.mark.parametrize("scenario,query", [
    ("bad-limit", {"limit": "5"}),
    ("extra-parameter", {"page": "2"}),
])
def test_activity_limit_refusal_value_parity(env, scenario, query):
    real = env.call("GET", real_path("activity", family="insights"), query_string=query)
    answer = drive(new_fixture(), "GET", fixture_path("activity", family="insights"),
                   query={key: [value] for key, value in query.items()})
    assert_error_parity(scenario, answer, real, 400, "invalid_request")


@pytest.mark.parametrize("scenario,query", [
    ("range-over-366-days", {"start_date": "2024-01-01", "end_date": "2025-01-01"}),
    ("before-earliest", {
        "start_date": (fixture_module.STATS_EARLIEST_CUSTOM_DATE - timedelta(days=1)).isoformat(),
        "end_date": fixture_module.STATS_EARLIEST_CUSTOM_DATE.isoformat(),
    }),
    ("after-latest", {
        "start_date": fixture_module.STATS_LATEST_CUSTOM_DATE.isoformat(),
        "end_date": (fixture_module.STATS_LATEST_CUSTOM_DATE + timedelta(days=1)).isoformat(),
    }),
    ("malformed-date", {"start_date": "not-a-date", "end_date": "2024-01-31"}),
    ("days-and-dates", {"days": "7", "start_date": "2024-01-01", "end_date": "2024-01-31"}),
    ("unlisted-days", {"days": "14"}),
    ("missing-end", {"start_date": "2024-01-01"}),
])
def test_stats_window_refusal_value_parity(env, scenario, query):
    real = env.call("GET", real_path("stats", family="insights"), query_string=query)
    answer = drive(new_fixture(), "GET", fixture_path("stats", family="insights"),
                   query={key: [value] for key, value in query.items()})
    assert_error_parity(scenario, answer, real, 400, "invalid_request")


def test_activity_unavailable_value_parity(env):
    env.activity_logs.fail_queries = 1
    real = env.call("GET", real_path("activity", family="insights"))
    fixture = new_fixture()
    fixture.make_activity_unavailable(FIXTURE_WS)
    answer = drive(fixture, "GET", fixture_path("activity", family="insights"))
    assert_error_parity("activity-503", answer, real, 503, "public_workspace_activity_unavailable",
                        "Workspace activity is unavailable right now. Try again.")


def test_stats_unavailable_value_parity(env):
    env.activity_logs.fail_queries = 1
    real = env.call("GET", real_path("stats", family="insights"))
    fixture = new_fixture()
    fixture.make_stats_unavailable(FIXTURE_WS)
    answer = drive(fixture, "GET", fixture_path("stats", family="insights"))
    assert_error_parity("stats-503", answer, real, 503, "public_workspace_stats_unavailable",
                        "Workspace statistics are unavailable right now. Try again.")


# --------------------------------------------------------------------------
# The fixture's own context stays the server's after every write it serves.
# --------------------------------------------------------------------------

def test_a_downloads_write_rebuilds_the_served_context():
    fixture = new_fixture()
    drive(fixture, "PATCH", fixture_path("downloads"),
          body={"revision": fixture._revision(FIXTURE_WS, "downloads"), "disable_file_downloads": True})
    context = fixture.workspaces[FIXTURE_WS]
    assert context["document_permissions"]["can_download"] is False
    assert "download" not in context["document_management"]["operations"]
    # A later role or status change never reverts the written switch.
    fixture.configure(FIXTURE_WS, role="Owner", status="upload_disabled")
    assert fixture.workspaces[FIXTURE_WS]["document_permissions"]["can_download"] is False


def test_a_profile_and_logo_write_rebuild_the_served_header():
    fixture = new_fixture()
    drive(fixture, "PATCH", fixture_path("profile"),
          body={"revision": fixture._revision(FIXTURE_WS, "profile"), "name": "Frontier library",
                "hero_color": "#123456"})
    body, headers = multipart_logo(fixture._revision(FIXTURE_WS, "logo"))
    drive(fixture, "PUT", fixture_path("logo"), headers=headers, post_data_buffer=body)
    workspace = fixture.workspaces[FIXTURE_WS]["workspace"]
    assert (workspace["name"], workspace["hero_color"]) == ("Frontier library", "#123456")
    assert workspace["logo_url"] == f"/api/public_workspaces/{FIXTURE_WS}/logo?v=2"


def test_the_classic_settings_routes_are_trapped():
    fixture = new_fixture()
    for method, path in (
        ("PATCH", f"/api/public_workspaces/{FIXTURE_WS}"),
        ("POST", f"/api/public_workspaces/{FIXTURE_WS}/logo"),
        ("PATCH", f"/api/public_workspaces/{FIXTURE_WS}/download-settings"),
        ("POST", f"/api/retention-policy/public/{FIXTURE_WS}"),
        ("GET", f"/api/public_workspaces/{FIXTURE_WS}/activity"),
        ("GET", f"/api/public_workspaces/{FIXTURE_WS}/stats"),
        ("GET", f"/api/public_workspaces/{FIXTURE_WS}/fileCount"),
    ):
        answer = drive(fixture, method, path, body={} if method != "GET" else None)
        assert answer.status == 500, (method, path)
    assert len(fixture.unexpected_requests) == 7
    # setActive stays the shell's courtesy write, never a trapped settings route.
    answer = drive(fixture, "PATCH", "/api/public_workspaces/setActive", body={"workspaceId": FIXTURE_WS})
    assert answer.status == 200 and len(fixture.unexpected_requests) == 7


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
