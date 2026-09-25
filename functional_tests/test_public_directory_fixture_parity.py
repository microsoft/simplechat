# test_public_directory_fixture_parity.py
"""
Per-route shape parity between the M9A public directory UI fixture and the real route.
Version: 0.261.175
Implemented in: 0.261.175

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
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN
from ui_tests.fixtures.public_directory import PublicDirectoryFixture

from test_support.public_directory_harness import public_directory_environment


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
