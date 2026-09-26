# test_public_directory_fixture_parity.py
"""
Per-route shape parity between the M9A public directory UI fixture and the real route.
Version: 0.261.186
Implemented in: 0.261.175 (request/cancel refusal-text parity added in 0.261.186)

The V2 public directory browser suite mocks the network with the closed HTTP fixture
`ui_tests/fixtures/public_directory.py`. A fixture whose response shape drifts from the server would
let a passing browser test hide a real regression, so this test pins the fixture's response keys and
codes against the real native directory route, driven by the isolated backend harness the directory
functional tests use (`test_support/public_directory_harness.py`, running the real policy and
directory modules against a fake Cosmos).

For the one route the directory page calls -- `GET /api/public_workspaces/directory` -- it asserts
the fixture never invents a top-level or row key the server does not return (`fixture keys <= server
keys`), that every key the page reads is present in both, and that a rejected query returns the same
status and machine-readable `error_code`. It covers a member-and-none listing and an invalid-query
400, so the run fails the moment the fixture drifts from the server.

The fixture handlers are the production browser-test code, exercised through the same `_dispatch`
entry the Playwright route handler calls, with a tiny fake page and route.

It also pins the fixture's self-service request/cancel refusals
(`POST`/`DELETE /api/public-workspaces/<id>/membership/requests`) against the real membership route,
driven by the isolated Flask harness `test_public_membership_apis.py` owns. The fixture answers a
refusal with a message the page renders verbatim, so a message that drifts from
`functions_public_membership`'s own words would silently mislead a reader; these cases assert the
status, the machine-readable `error_code` and the human `error` text all match the server for
success, `already_member`, `request_pending`, `no_pending_request`, an unknown workspace and a 400.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN
from ui_tests.fixtures.public_directory import (
    PublicDirectoryFixture,
    MEMBER_WORKSPACE,
    REQUESTABLE_WORKSPACE,
    PENDING_WORKSPACE,
)

from test_support.public_directory_harness import public_directory_environment

# The real request/cancel routes are driven by the membership API harness; importing its `environment`
# pytest fixture lets these parity cases exercise the same Flask app the membership suite pins. pytest
# resolves the fixture by name, so it is referenced below to keep it from being pruned as unused.
from test_public_membership_apis import (
    environment,
    login,
    OWNER,
    PENDING,
    OUTSIDER,
    REQUESTS_PATH,
)

_MEMBERSHIP_FIXTURES = (environment,)


DIRECTORY_PATH = "/api/public_workspaces/directory"

# The keys the directory page reads off every row, and the envelope and hint keys it reads.
ROW_KEYS = {
    "id", "name", "description", "heroColor", "hasLogo",
    "logoVersion", "userRole", "membership", "status",
}
LIST_KEYS = {"workspaces", "page", "page_size", "total_count", "public_directory"}
HINT_KEYS = {"schema_version", "can_create"}
ERROR_KEYS = {"error", "error_code"}


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
    return route.status, route.payload, route.headers


def new_fixture():
    return PublicDirectoryFixture(_FakePage())


# --------------------------------------------------------------------------
# Real route: the isolated backend harness.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def module_env():
    with public_directory_environment() as environment:
        yield environment


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


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
    # A member row for the caller (owner) and a discoverable none row they hold no role in.
    env.seed_workspace("mine-ws", name="Mine", owner="owner-1", admins=(), managers=())
    env.seed_workspace("other-ws", name="Other", owner="outsider-1", admins=(), managers=())
    env.as_user("owner-1")
    # A page size wide enough to hold the fixture's whole seeded set on one page, so its member row
    # is compared, not stranded on a later page behind the paging filler.
    real = env.directory(query_string={"view": "all", "page": "1", "page_size": "100"})

    fixture = new_fixture()
    status, payload, _ = drive_fixture(fixture, "GET", DIRECTORY_PATH,
                                       query={"view": ["all"], "page": ["1"], "page_size": ["100"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, LIST_KEYS)
    assert_shared_keys("list-hint", payload["public_directory"], real_payload["public_directory"], HINT_KEYS)

    real_union = row_key_union(real_payload["workspaces"])
    fixture_union = row_key_union(payload["workspaces"])
    invented = fixture_union - real_union
    assert not invented, f"list: the fixture row invents keys the server never returns: {sorted(invented)}"
    for key in ROW_KEYS:
        assert key in real_union and key in fixture_union, f"list: {key!r} missing from a row"
    # Both listings distinguish a member row from a discoverable one via membership.
    real_memberships = {row["membership"] for row in real_payload["workspaces"]}
    fixture_memberships = {row["membership"] for row in payload["workspaces"]}
    assert "member" in real_memberships and "member" in fixture_memberships
    assert "none" in real_memberships and "none" in fixture_memberships


def test_no_store_header_parity(env):
    """The directory list carries `Cache-Control: no-store`, as the server's `_no_store` wrapper does."""
    env.seed_workspace("mine-ws", name="Mine", owner="owner-1", admins=(), managers=())
    env.as_user("owner-1")
    real = env.directory(query_string={"view": "all", "page": "1", "page_size": "20"})

    fixture = new_fixture()
    _, _, headers = drive_fixture(fixture, "GET", DIRECTORY_PATH,
                                  query={"view": ["all"], "page": ["1"], "page_size": ["20"]})

    assert real.headers.get("Cache-Control") == "no-store", "The real directory list must not be cached."
    assert headers.get("Cache-Control") == "no-store", "The fixture must mark the directory list no-store too."


# --------------------------------------------------------------------------
# Invalid query.
# --------------------------------------------------------------------------

def test_invalid_query_shape_parity(env):
    """An unknown query parameter returns `{error, error_code: 'invalid_request'}` (400) in both."""
    env.as_user("owner-1")
    real = env.directory(query_string={"bogus": "1"})

    fixture = new_fixture()
    status, payload, _ = drive_fixture(fixture, "GET", DIRECTORY_PATH, query={"bogus": ["1"]})

    assert (status, real.status_code) == (400, 400)
    real_payload = real.get_json()
    assert_no_invented_keys("invalid-query", payload, real_payload)
    assert_shared_keys("invalid-query", payload, real_payload, ERROR_KEYS)
    assert payload["error_code"] == real_payload["error_code"] == "invalid_request"


# --------------------------------------------------------------------------
# Self-service request and cancel: the refusal text the page renders must be the server's own.
#
# The real routes are driven through the membership harness's `environment` (a real Flask app over a
# fake Cosmos), the fixture through its own `_dispatch`. The two sides seed different workspace ids,
# so these compare the workspace-independent contract -- status, `error_code` and the human `error`
# text -- not the row payload, whose shape the listing parity above already pins.
# --------------------------------------------------------------------------

def _requests_path(workspace_id):
    return f"/api/public-workspaces/{workspace_id}/membership/requests"


def assert_refusal_parity(scenario, real_response, fixture_answer, expected_code):
    """The fixture and the server refuse with the same status, error_code and human text."""
    fixture_status, fixture_payload, _ = fixture_answer
    real_payload = real_response.get_json()
    assert real_response.status_code == fixture_status, (
        f"{scenario}: status {fixture_status} (fixture) != {real_response.status_code} (server)")
    assert real_payload.get("error_code") == fixture_payload.get("error_code") == expected_code, (
        f"{scenario}: error_code drift (server {real_payload.get('error_code')!r}, "
        f"fixture {fixture_payload.get('error_code')!r}, expected {expected_code!r})")
    assert fixture_payload.get("error") == real_payload.get("error"), (
        f"{scenario}: the fixture's text is not the server's "
        f"(server {real_payload.get('error')!r}, fixture {fixture_payload.get('error')!r})")


def assert_success_parity(scenario, real_response, fixture_answer, expected_status):
    """Both commit with the same status and answer with the server's own `{workspace}` row."""
    fixture_status, fixture_payload, _ = fixture_answer
    real_payload = real_response.get_json()
    assert (fixture_status, real_response.status_code) == (expected_status, expected_status), (
        f"{scenario}: status {fixture_status} (fixture) / {real_response.status_code} (server) "
        f"!= {expected_status}")
    assert_no_invented_keys(scenario, fixture_payload, real_payload)
    assert "workspace" in real_payload and "workspace" in fixture_payload, (
        f"{scenario}: both must return the committed {{workspace}} row")


def test_request_success_shape_parity(environment):
    """A reader with no role asks to manage: both commit a 201 carrying the fresh `{workspace}` row."""
    login(environment, OUTSIDER)
    real = environment.client.post(REQUESTS_PATH)
    answer = drive_fixture(new_fixture(), "POST", _requests_path(REQUESTABLE_WORKSPACE))
    assert_success_parity("request success", real, answer, 201)


def test_cancel_success_shape_parity(environment):
    """A pending requester cancels: both answer 200 with the reconciled `{workspace}` row."""
    login(environment, PENDING)
    real = environment.client.delete(REQUESTS_PATH)
    answer = drive_fixture(new_fixture(), "DELETE", _requests_path(PENDING_WORKSPACE))
    assert_success_parity("cancel success", real, answer, 200)


def test_request_already_member_text_parity(environment):
    """Asking to manage a workspace you already manage refuses with the server's `already_member` text."""
    login(environment, OWNER)
    real = environment.client.post(REQUESTS_PATH)
    answer = drive_fixture(new_fixture(), "POST", _requests_path(MEMBER_WORKSPACE))
    assert_refusal_parity("already a manager", real, answer, "already_member")


def test_request_pending_text_parity(environment):
    """A second request while one is pending refuses with the server's `request_pending` text."""
    login(environment, PENDING)
    real = environment.client.post(REQUESTS_PATH)
    answer = drive_fixture(new_fixture(), "POST", _requests_path(PENDING_WORKSPACE))
    assert_refusal_parity("already requested", real, answer, "request_pending")


def test_cancel_no_pending_request_text_parity(environment):
    """Cancelling with nothing pending refuses with the server's `no_pending_request` text."""
    login(environment, OUTSIDER)
    real = environment.client.delete(REQUESTS_PATH)
    answer = drive_fixture(new_fixture(), "DELETE", _requests_path(REQUESTABLE_WORKSPACE))
    assert_refusal_parity("cancel with no pending request", real, answer, "no_pending_request")


def test_request_unknown_workspace_text_parity(environment):
    """A request against an unknown workspace 404s with the server's `workspace_not_found` text."""
    login(environment, OUTSIDER)
    real = environment.client.post("/api/public-workspaces/ghost-ws/membership/requests")
    answer = drive_fixture(new_fixture(), "POST", _requests_path("ghost-ws"))
    assert_refusal_parity("unknown workspace", real, answer, "workspace_not_found")


def test_request_rejects_a_query_shape_parity(environment):
    """A query string on the request route is a 400 `invalid_request` with the same text in both."""
    login(environment, OUTSIDER)
    real = environment.client.post(REQUESTS_PATH, query_string={"role": "DocumentManager"})
    answer = drive_fixture(new_fixture(), "POST", _requests_path(REQUESTABLE_WORKSPACE),
                           query={"role": ["DocumentManager"]})
    assert_refusal_parity("request rejects a query", real, answer, "invalid_request")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
