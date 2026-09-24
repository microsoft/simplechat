# test_group_directory_fixture_parity.py
"""
Per-route shape parity between the M7A group directory UI fixture and the real routes.
Version: 0.261.150
Implemented in: 0.261.150

The V2 group directory browser suite mocks the network with the closed HTTP fixture
`ui_tests/fixtures/group_directory.py`. A fixture whose response shape drifts from the server
would let a passing browser test hide a real regression, so this test pins the fixture's response
keys and codes against the real native directory routes, driven by the isolated backend harness the
directory functional tests use (`test_support/group_directory_harness.py`, running the real policy,
directory, group and settings modules against an etag-enforcing fake Cosmos).

For every route the directory page calls -- `GET`/`POST /api/groups/directory` and
`POST`/`DELETE /api/groups/<g>/join-request` -- it asserts the fixture never invents a top-level
or row key the server does not return (`fixture keys <= server keys`), that the keys the page reads
are present in both, and that the status and machine-readable `error_code` match. It covers a
member-and-none listing, a create success and both create 403s and a reviewed 400, a join success,
`already_member` and `request_pending`, a cancel success and `no_pending_request`, a
`group_not_found` 404 and a `group_write_conflict` 409, so the run fails the moment the fixture
drifts.

The fixture handlers are the production browser-test code, exercised through the same `_dispatch`
entry the Playwright route handler calls, with a tiny fake page and route.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN
from ui_tests.fixtures.group_directory import (
    GroupDirectoryFixture,
    MEMBER_GROUP,
    PENDING_GROUP,
    JOINABLE_GROUP,
)

from test_support.group_directory_harness import group_directory_environment


DIRECTORY_PATH = "/api/groups/directory"

# The keys the directory page reads off every row; a member row adds userRole.
ROW_KEYS = {"id", "name", "description", "owner", "member_count", "heroColor", "hasLogo", "logoVersion", "membership"}
LIST_KEYS = {"groups", "page", "page_size", "total_count", "group_directory"}
HINT_KEYS = {"schema_version", "can_create", "can_request_to_join"}


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
    def __init__(self, url):
        self.url = url


class _FakeRoute:
    def __init__(self, url):
        self.request = _FakeRequest(url)
        self.status = 200
        self.payload = None
        self.headers = {}

    def fulfill(self, status=200, json=None, **kwargs):
        self.status = status
        self.payload = json
        self.headers = kwargs.get("headers") or {}


def drive_fixture(fixture, method, path, body=None, query=None):
    """Dispatch one request through the fixture exactly as its Playwright route handler would."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}")
    fixture._dispatch(route, entry)
    return route.status, route.payload


def drive_fixture_with_headers(fixture, method, path, body=None, query=None):
    """Like `drive_fixture`, but also returns the fulfilled response headers for header parity."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}")
    fixture._dispatch(route, entry)
    return route.status, route.payload, route.headers


def new_fixture():
    return GroupDirectoryFixture(_FakePage())


def join_path(group_id):
    return f"/api/groups/{group_id}/join-request"


# --------------------------------------------------------------------------
# Real routes: the isolated backend harness.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def land_membership_change(env, group_id):
    """A concurrent write that bumps the stored group's etag between a read and a replace."""
    def concurrent():
        env.seed_document(env.stored_group(group_id))
    return concurrent


# --------------------------------------------------------------------------
# Parity assertions.
# --------------------------------------------------------------------------

def assert_no_invented_keys(scenario, fixture_payload, real_payload):
    invented = set(fixture_payload) - set(real_payload)
    assert not invented, (
        f"{scenario}: the fixture returns top-level keys the server never does: {sorted(invented)} "
        f"(server keys {sorted(real_payload)})"
    )


def assert_shared_keys(scenario, fixture_payload, real_payload, required):
    for key in required:
        assert key in real_payload, f"{scenario}: the server no longer returns {key!r}; the harness or contract drifted"
        assert key in fixture_payload, f"{scenario}: the fixture dropped {key!r}, which the page reads"


def row_key_union(rows):
    union = set()
    for row in rows:
        union |= set(row)
    return union


# --------------------------------------------------------------------------
# Listing.
# --------------------------------------------------------------------------

def test_list_shape_parity(env):
    """The list envelope, the hint and every row carry the same keys the page reads."""
    env.seed_group("mine-group", members=("member-1",))
    env.seed_group("other-group", members=("owner-1",))
    env.as_user("member-1")
    real = env.directory(query_string={"view": "all", "page": "1", "page_size": "20"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", DIRECTORY_PATH,
                                    query={"view": ["all"], "page": ["1"], "page_size": ["20"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, LIST_KEYS)
    assert_shared_keys("list-hint", payload["group_directory"], real_payload["group_directory"], HINT_KEYS)

    real_union = row_key_union(real_payload["groups"])
    fixture_union = row_key_union(payload["groups"])
    invented = fixture_union - real_union
    assert not invented, f"list: the fixture row invents keys the server never returns: {sorted(invented)}"
    for key in ROW_KEYS:
        assert key in real_union and key in fixture_union, f"list: {key!r} missing from a row"
    # Both listings carry a member row (userRole) and a discoverable row (no userRole).
    assert "userRole" in real_union and "userRole" in fixture_union


# --------------------------------------------------------------------------
# Create.
# --------------------------------------------------------------------------

def test_create_success_shape_parity(env):
    """A create returns `{group}` with a 201, its row shape matching a listing row."""
    env.as_user("outsider-1")
    real = env.create({"name": "New parity group", "description": "Made for parity."})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "POST", DIRECTORY_PATH,
                                    body={"name": "New parity group", "description": "Made for parity."})

    assert (status, real.status_code) == (201, 201)
    real_payload = real.get_json()
    assert_no_invented_keys("create", payload, real_payload)
    assert_shared_keys("create", payload, real_payload, {"group"})
    invented = set(payload["group"]) - set(real_payload["group"])
    assert not invented, f"create: the fixture row invents keys: {sorted(invented)}"
    for key in ROW_KEYS:
        assert key in real_payload["group"] and key in payload["group"]


def test_create_disabled_shape_parity(env):
    """Creation switched off returns `{error, error_code: 'group_creation_disabled'}` (403)."""
    env.settings["enable_group_creation"] = False
    env.as_user("outsider-1")
    real = env.create({"name": "Blocked"})

    fixture = new_fixture()
    fixture.create_refusal = "group_creation_disabled"
    status, payload = drive_fixture(fixture, "POST", DIRECTORY_PATH, body={"name": "Blocked"})

    assert (status, real.status_code) == (403, 403)
    real_payload = real.get_json()
    assert_no_invented_keys("create_disabled", payload, real_payload)
    assert_shared_keys("create_disabled", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "group_creation_disabled"


def test_create_role_required_shape_parity(env):
    """Creation narrowed to a role returns `{error, error_code: 'create_groups_role_required'}` (403)."""
    env.settings["require_member_of_create_group"] = True
    env.as_user("outsider-1", roles=("User",))
    real = env.create({"name": "Blocked"})

    fixture = new_fixture()
    fixture.create_refusal = "create_groups_role_required"
    status, payload = drive_fixture(fixture, "POST", DIRECTORY_PATH, body={"name": "Blocked"})

    assert (status, real.status_code) == (403, 403)
    real_payload = real.get_json()
    assert_no_invented_keys("create_role", payload, real_payload)
    assert_shared_keys("create_role", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "create_groups_role_required"


def test_create_reviewed_400_shape_parity(env):
    """An extra field returns the server's reviewed 400 text, verbatim."""
    env.as_user("outsider-1")
    real = env.create({"name": "Fine", "colour": "red"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "POST", DIRECTORY_PATH, body={"name": "Fine", "colour": "red"})

    assert (status, real.status_code) == (400, 400)
    real_payload = real.get_json()
    assert_no_invented_keys("create_400", payload, real_payload)
    assert_shared_keys("create_400", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "invalid_request"
    # The dialog renders the server's own text; a drift in the fixture's copy would mislead a user.
    assert payload["error"] == real_payload["error"]


# --------------------------------------------------------------------------
# Join and cancel.
# --------------------------------------------------------------------------

def test_join_success_shape_parity(env):
    """A join returns `{group}` with a 201, its row shape matching a listing row."""
    env.seed_group("open-group")
    env.as_user("outsider-1")
    real = env.join("open-group")

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "POST", join_path(JOINABLE_GROUP))

    assert (status, real.status_code) == (201, 201)
    real_payload = real.get_json()
    assert_no_invented_keys("join", payload, real_payload)
    assert_shared_keys("join", payload, real_payload, {"group"})
    for key in ROW_KEYS:
        assert key in real_payload["group"] and key in payload["group"]


def test_join_already_member_shape_parity(env):
    """Joining a group you belong to returns `{error, error_code: 'already_member'}` (409)."""
    env.seed_group("member-group", members=("member-1",))
    env.as_user("member-1")
    real = env.join("member-group")

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "POST", join_path(MEMBER_GROUP))

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("already_member", payload, real_payload)
    assert_shared_keys("already_member", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "already_member"


def test_join_request_pending_shape_parity(env):
    """Joining again while pending returns `{error, error_code: 'request_pending'}` (409)."""
    env.seed_group("pending-group", pending=("applicant-1",))
    env.as_user("applicant-1")
    real = env.join("pending-group")

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "POST", join_path(PENDING_GROUP))

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("request_pending", payload, real_payload)
    assert_shared_keys("request_pending", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "request_pending"


def test_cancel_success_shape_parity(env):
    """A cancel returns `{group}` with a 200."""
    env.seed_group("pending-group", pending=("applicant-1",))
    env.as_user("applicant-1")
    real = env.cancel("pending-group")

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", join_path(PENDING_GROUP))

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("cancel", payload, real_payload)
    assert_shared_keys("cancel", payload, real_payload, {"group"})
    for key in ROW_KEYS:
        assert key in real_payload["group"] and key in payload["group"]


def test_cancel_no_pending_shape_parity(env):
    """Cancelling with no request returns `{error, error_code: 'no_pending_request'}` (409)."""
    env.seed_group("open-group")
    env.as_user("outsider-1")
    real = env.cancel("open-group")

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", join_path(JOINABLE_GROUP))

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("no_pending", payload, real_payload)
    assert_shared_keys("no_pending", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "no_pending_request"


def test_join_group_not_found_shape_parity(env):
    """Joining a missing group returns `{error, error_code: 'group_not_found'}` (404)."""
    env.as_user("outsider-1")
    real = env.join("absent-group")

    fixture = new_fixture()
    fixture.forced_conflicts["dir-absent"] = "group_not_found"
    status, payload = drive_fixture(fixture, "POST", join_path("dir-absent"))

    assert (status, real.status_code) == (404, 404)
    real_payload = real.get_json()
    assert_no_invented_keys("group_not_found", payload, real_payload)
    assert_shared_keys("group_not_found", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "group_not_found"


def test_join_group_write_conflict_shape_parity(env):
    """A concurrent group write returns `{error, error_code: 'group_write_conflict'}` (409)."""
    env.seed_group("busy-group")
    env.as_user("outsider-1")
    attempts = env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS
    env.groups.before_replace.extend(land_membership_change(env, "busy-group") for _ in range(attempts))
    real = env.join("busy-group")

    fixture = new_fixture()
    fixture.forced_conflicts[JOINABLE_GROUP] = "group_write_conflict"
    status, payload = drive_fixture(fixture, "POST", join_path(JOINABLE_GROUP))

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("group_write_conflict", payload, real_payload)
    assert_shared_keys("group_write_conflict", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "group_write_conflict"


def assert_list_parity(scenario, fixture_payload, real_payload):
    """The shared list-shape checks: no invented keys, the read keys present, rows and hint aligned."""
    assert_no_invented_keys(scenario, fixture_payload, real_payload)
    assert_shared_keys(scenario, fixture_payload, real_payload, LIST_KEYS)
    assert_shared_keys(f"{scenario}-hint", fixture_payload["group_directory"],
                       real_payload["group_directory"], HINT_KEYS)
    real_union = row_key_union(real_payload["groups"])
    fixture_union = row_key_union(fixture_payload["groups"])
    invented = fixture_union - real_union
    assert not invented, f"{scenario}: the fixture row invents keys the server never returns: {sorted(invented)}"


def test_list_view_mine_shape_parity(env):
    """`view=mine` returns only member rows in both, with the same envelope and row keys."""
    env.seed_group("mine-group", members=("member-1",))
    env.seed_group("other-group", members=("owner-1",))
    env.as_user("member-1")
    real = env.directory(query_string={"view": "mine"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", DIRECTORY_PATH, query={"view": ["mine"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_list_parity("view_mine", payload, real_payload)
    assert real_payload["groups"] and payload["groups"]
    assert all(row["membership"] == "member" for row in real_payload["groups"])
    assert all(row["membership"] == "member" for row in payload["groups"])


def test_list_view_discover_shape_parity(env):
    """`view=discover` returns only non-member rows in both, with the same keys."""
    env.seed_group("mine-group", members=("member-1",))
    env.seed_group("other-group", members=("owner-1",))
    env.as_user("member-1")
    real = env.directory(query_string={"view": "discover"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", DIRECTORY_PATH, query={"view": ["discover"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_list_parity("view_discover", payload, real_payload)
    assert real_payload["groups"] and payload["groups"]
    assert all(row["membership"] != "member" for row in real_payload["groups"])
    assert all(row["membership"] != "member" for row in payload["groups"])


def test_list_search_shape_parity(env):
    """A search narrows both listings and keeps the same envelope and row keys."""
    env.seed_group("beacon-group", name="Zephyr parity beacon", members=("member-1",))
    env.seed_group("other-group", name="Unrelated crew", members=("owner-1",))
    env.as_user("member-1")
    real = env.directory(query_string={"view": "all", "search": "Zephyr parity beacon"})

    fixture = new_fixture()
    # "Marketing circle" is a seeded fixture row; searching its name must narrow the list too.
    status, payload = drive_fixture(fixture, "GET", DIRECTORY_PATH,
                                    query={"view": ["all"], "search": ["Marketing circle"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_list_parity("search", payload, real_payload)
    assert real_payload["total_count"] == 1
    assert payload["total_count"] == 1


def test_list_later_page_shape_parity(env):
    """A later page echoes `page`/`page_size` and keeps the row keys the page reads."""
    for index in range(5):
        env.seed_group(f"page-group-{index}", name=f"Paging group {index}", members=("member-1",))
    env.as_user("member-1")
    real = env.directory(query_string={"view": "all", "page": "2", "page_size": "2"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", DIRECTORY_PATH,
                                    query={"view": ["all"], "page": ["2"], "page_size": ["2"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_list_parity("later_page", payload, real_payload)
    assert (payload["page"], payload["page_size"]) == (2, 2)
    assert (real_payload["page"], real_payload["page_size"]) == (2, 2)


def test_list_strict_parameter_400_shape_parity(env):
    """An unknown query parameter is a reviewed `invalid_request` 400 with the same verbatim text."""
    env.as_user("member-1")
    real = env.directory(query_string={"view": "all", "bogus": "x"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", DIRECTORY_PATH,
                                    query={"view": ["all"], "bogus": ["x"]})

    assert (status, real.status_code) == (400, 400)
    real_payload = real.get_json()
    assert_no_invented_keys("list_400", payload, real_payload)
    assert_shared_keys("list_400", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "invalid_request"
    assert payload["error"] == real_payload["error"]


def test_list_owner_nested_keys_parity(env):
    """Each row's `owner` object carries exactly the nested keys the server returns."""
    env.seed_group("mine-group", members=("member-1",))
    env.as_user("member-1")
    real = env.directory(query_string={"view": "all"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", DIRECTORY_PATH, query={"view": ["all"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    real_owner_keys = set().union(*(set(row["owner"]) for row in real_payload["groups"]))
    fixture_owner_keys = set().union(*(set(row["owner"]) for row in payload["groups"]))
    invented = fixture_owner_keys - real_owner_keys
    assert not invented, f"owner: the fixture invents nested owner keys: {sorted(invented)}"
    assert "displayName" in real_owner_keys and "displayName" in fixture_owner_keys


def test_cache_control_no_store_on_every_route_parity(env):
    """Every directory response -- list, create, join and cancel -- carries `Cache-Control: no-store`."""
    env.seed_group("open-group")
    env.seed_group("pending-group", pending=("applicant-1",))

    def real_header(response):
        return response.headers.get("Cache-Control")

    env.as_user("member-1")
    real_list = env.directory(query_string={"view": "all"})
    env.as_user("outsider-1")
    real_create = env.create({"name": "Header parity group"})
    env.seed_group("join-group")
    real_join = env.join("join-group")
    env.as_user("applicant-1")
    real_cancel = env.cancel("pending-group")

    fixture = new_fixture()
    _, _, list_headers = drive_fixture_with_headers(fixture, "GET", DIRECTORY_PATH, query={"view": ["all"]})
    _, _, create_headers = drive_fixture_with_headers(fixture, "POST", DIRECTORY_PATH, body={"name": "Header parity group"})
    _, _, join_headers = drive_fixture_with_headers(fixture, "POST", join_path(JOINABLE_GROUP))
    _, _, cancel_headers = drive_fixture_with_headers(fixture, "DELETE", join_path(PENDING_GROUP))

    for scenario, real_response, fixture_headers in (
        ("list", real_list, list_headers),
        ("create", real_create, create_headers),
        ("join", real_join, join_headers),
        ("cancel", real_cancel, cancel_headers),
    ):
        assert real_header(real_response) == "no-store", f"{scenario}: the server no longer sets no-store"
        assert fixture_headers.get("Cache-Control") == "no-store", f"{scenario}: the fixture dropped no-store"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
