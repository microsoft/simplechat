# test_group_picker_fixture_parity.py
"""
Per-route shape parity between the M8 group picker UI fixture and the real classic routes.
Version: 0.261.165
Implemented in: 0.261.161

The M8 group journeys reach every group through the workspace picker: J1 activates a group and
reconciles an activation made in another tab, and J2 pages and searches the picker's group list.
Every group suite mocks the network with the shared base fixture `ui_tests/fixtures/group_workspace.py`,
and the journeys with the composite `ui_tests/fixtures/group_journeys.py`, which inherits the base's
answers to the picker's two routes -- `GET /api/groups` (the paged, searchable list) and
`PATCH /api/groups/setActive` (the activation write). A fixture whose response drifts from the
server would let a passing browser test hide a real regression, so this test pins both fixtures'
responses against the real `route_backend_groups` picker routes, driven by the isolated
backend harness the classic group functional tests use (`test_support/group_directory_harness.py`,
running the real policy, group and settings modules against an etag-enforcing fake Cosmos).

It asserts, for every picker call and both fixtures:

* the fixture never invents a top-level or row key the server does not return
  (`fixture keys <= server keys`);
* the keys the picker reads -- the envelope `groups`, `page`, `page_size`, `total_count`, and each
  row's `id` and `name` -- are present on both sides, with an integer `total_count`;
* the requested `page_size` is honoured and the total is never capped, so a store of more than a
  thousand groups still reports the full count (the ">1000 groups not capped" contract check);
* `setActive`'s success and its 400 (missing id), 404 (unknown group) and 403 (not a member)
  refusals match by status, by text, and by the presence or absence of a machine-readable
  `error_code`.

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
from ui_tests.fixtures.group_journeys import GroupJourneyFixture
from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture, group_context

from test_support.group_directory_harness import group_directory_environment


LIST_PATH = "/api/groups"
SET_ACTIVE_PATH = "/api/groups/setActive"

# The envelope keys and row keys the picker adapter (`lib/workspaces.ts` / `GroupWorkspacePicker.tsx`)
# reads: the page walks `result.items` off `groups`, `result.totalCount` off `total_count`, and each
# summary's `id` and `name`. It never reads a per-row owner, hero colour, logo or status.
LIST_ENVELOPE_KEYS = {"groups", "page", "page_size", "total_count"}
UI_ROW_KEYS = {"id", "name"}

# A member id that exists in the harness's people table, used as the caller on both sides.
CALLER = "member-1"


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


def _make_fixture(fixture_class):
    """A picker fixture of `fixture_class` with an empty group store for the test to fill."""
    fixture = fixture_class(_FakePage())
    fixture.groups = {}
    fixture.denied_groups = set()
    fixture.active_group = None
    return fixture


# Both fixtures answer the picker's two routes: the shared base every group suite rides, and the
# journeys composite, which inherits the base's handlers. Each case runs against both.
PICKER_FIXTURES = {"base": GroupWorkspaceFixture, "journeys": GroupJourneyFixture}


@pytest.fixture(params=sorted(PICKER_FIXTURES))
def new_fixture(request):
    """A factory for the picker fixture under test, parametrized over the base and the composite."""
    return lambda: _make_fixture(PICKER_FIXTURES[request.param])


def seed_fixture_groups(fixture, specs, *, denied=(), active=None):
    """Replace the fixture's group store with `{group_id: group_context(...)}` from `specs`."""
    fixture.groups = {
        group_id: group_context(group_id, name, role=role, status="active")
        for group_id, name, role in specs
    }
    fixture.denied_groups = set(denied)
    fixture.active_group = active


def drive_fixture(fixture, method, path, body=None, query=None):
    """Dispatch one request through the fixture exactly as its Playwright route handler would."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}")
    fixture._dispatch(route, entry)
    return route.status, route.payload


# --------------------------------------------------------------------------
# Real routes: the isolated classic-routes backend harness.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.as_user(CALLER)
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
        assert key in fixture_payload, f"{scenario}: the fixture dropped {key!r}, which the picker reads"


def row_key_union(rows):
    union = set()
    for row in rows:
        union |= set(row)
    return union


def assert_error_code_parity(scenario, fixture_payload, real_payload):
    assert fixture_payload.get("error_code") == real_payload.get("error_code"), (
        f"{scenario}: error_code drifted "
        f"(fixture {fixture_payload.get('error_code')!r}, server {real_payload.get('error_code')!r})"
    )


# --------------------------------------------------------------------------
# Listing: envelope and row shape.
# --------------------------------------------------------------------------

def test_list_envelope_and_row_shape_parity(env, new_fixture):
    """The picker list envelope and every row carry the keys the picker reads, and no invented ones."""
    env.seed_group("group-a", "Group A", members=(CALLER,))
    env.seed_group("group-b", "Group B", members=(CALLER,))
    real = env.call("GET", LIST_PATH, query_string={"page": "1", "page_size": "25"})

    fixture = new_fixture()
    seed_fixture_groups(fixture, [("group-a", "Group A", "User"), ("group-b", "Group B", "User")])
    status, payload = drive_fixture(fixture, "GET", LIST_PATH, query={"page": ["1"], "page_size": ["25"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, LIST_ENVELOPE_KEYS)
    assert isinstance(payload["total_count"], int) and isinstance(real_payload["total_count"], int)

    real_union = row_key_union(real_payload["groups"])
    fixture_union = row_key_union(payload["groups"])
    invented = fixture_union - real_union
    assert not invented, f"list: the fixture row invents keys the server never returns: {sorted(invented)}"
    for key in UI_ROW_KEYS:
        assert key in real_union, f"list: the server row no longer carries {key!r}"
        assert key in fixture_union, f"list: the fixture row dropped {key!r}, which the picker reads"


# --------------------------------------------------------------------------
# Listing: page size honoured and total never capped.
# --------------------------------------------------------------------------

def test_list_page_size_and_no_cap_parity(env, new_fixture):
    """A store of more than a thousand groups is paged at the requested size with the full count."""
    total = 1001
    for index in range(total):
        env.seed_group(f"group-{index:04d}", f"Group {index:04d}", members=(CALLER,))
    real = env.call("GET", LIST_PATH, query_string={"page": "1", "page_size": "25"})
    real_page_two = env.call("GET", LIST_PATH, query_string={"page": "2", "page_size": "25"})

    fixture = new_fixture()
    seed_fixture_groups(
        fixture,
        [(f"group-{index:04d}", f"Group {index:04d}", "User") for index in range(total)],
    )
    status, payload = drive_fixture(fixture, "GET", LIST_PATH, query={"page": ["1"], "page_size": ["25"]})
    status_two, payload_two = drive_fixture(fixture, "GET", LIST_PATH, query={"page": ["2"], "page_size": ["25"]})

    real_payload = real.get_json()
    real_payload_two = real_page_two.get_json()
    assert (status, status_two) == (200, 200)
    assert (real.status_code, real_page_two.status_code) == (200, 200)
    # The requested page size is honoured, never widened or capped, on both sides.
    assert len(payload["groups"]) == 25, f"fixture page 1 returned {len(payload['groups'])} rows, expected 25"
    assert len(real_payload["groups"]) == 25, f"server page 1 returned {len(real_payload['groups'])} rows, expected 25"
    assert len(payload_two["groups"]) == 25 and len(real_payload_two["groups"]) == 25
    # The total is the full store on both sides -- the fixture must not cap it below the server.
    assert payload["total_count"] == total, f"fixture capped the total at {payload['total_count']}"
    assert real_payload["total_count"] == total, f"server total drifted to {real_payload['total_count']}"
    # The page-1 and page-2 id lists agree between fixture and server, not merely their counts: J2's
    # "off-page" claim rests on the same group landing on the same page, so a paging-order drift in
    # the fixture (a different sort, or a reversed store) must fail here.
    assert [row["id"] for row in payload["groups"]] == [row["id"] for row in real_payload["groups"]], (
        "fixture page 1 ids drifted from the server's"
    )
    assert [row["id"] for row in payload_two["groups"]] == [row["id"] for row in real_payload_two["groups"]], (
        "fixture page 2 ids drifted from the server's"
    )
    # And the two pages are disjoint, so paging really advances rather than repeating page 1.
    assert not (set(row["id"] for row in payload["groups"]) & set(row["id"] for row in payload_two["groups"]))


# --------------------------------------------------------------------------
# Listing: search.
# --------------------------------------------------------------------------

def test_list_search_shape_parity(env, new_fixture):
    """A picker search returns the same envelope and, for a name-only term, the same single match."""
    env.seed_group("group-alpha", "Alpha Team", members=(CALLER,))
    env.seed_group("group-beta", "Beta Team", members=(CALLER,))
    real = env.call("GET", LIST_PATH, query_string={"search": "Alpha", "page": "1", "page_size": "25"})

    fixture = new_fixture()
    seed_fixture_groups(fixture, [("group-alpha", "Alpha Team", "User"), ("group-beta", "Beta Team", "User")])
    status, payload = drive_fixture(
        fixture, "GET", LIST_PATH, query={"search": ["Alpha"], "page": ["1"], "page_size": ["25"]}
    )

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list-search", payload, real_payload)
    assert_shared_keys("list-search", payload, real_payload, LIST_ENVELOPE_KEYS)
    # `Alpha` matches one name only (and neither description), so the server's casefolded name-or-
    # description filter and the fixture agree on the single match and its count.
    assert payload["total_count"] == 1 and real_payload["total_count"] == 1
    assert [row["id"] for row in payload["groups"]] == ["group-alpha"]
    assert [row["id"] for row in real_payload["groups"]] == ["group-alpha"]


def _search(fixture, env, term):
    """Both sides' rows for one search term, as (fixture_ids, server_ids)."""
    real = env.call("GET", LIST_PATH, query_string={"search": term, "page": "1", "page_size": "25"})
    _, payload = drive_fixture(fixture, "GET", LIST_PATH, query={"search": [term], "page": ["1"], "page_size": ["25"]})
    return [row["id"] for row in payload["groups"]], [row["id"] for row in real.get_json()["groups"]]


def test_list_search_ignores_case_and_matches_descriptions_like_the_server(env, new_fixture):
    """The fixture's search must model the server exactly: casefolded, over the name or the description.

    From 0.261.162 the server searches through `functions_group.search_groups` with
    `CONTAINS(LOWER(c.name), @search) OR (IS_DEFINED(c.description) AND
    CONTAINS(LOWER(c.description), @search))` over a lowercased term, as the group directory and the
    admin search do. A fixture that kept the old case-sensitive, name-only match would strand a
    browser journey on a search the server answers. These terms agree only when the fixture models
    the server.
    """
    # group_context gives every fixture group the description "Shared knowledge for <name>.", so the
    # server-side group gets the same description, making `knowledge` a description-only term.
    env.seed_group(
        "group-research", "Research Group", members=(CALLER,),
        description="Shared knowledge for Research Group.",
    )
    env.seed_group("group-finance", "Finance Group", members=(CALLER,), description="Budgets and forecasts.")
    fixture = new_fixture()
    seed_fixture_groups(
        fixture, [("group-research", "Research Group", "User"), ("group-finance", "Finance Group", "User")]
    )
    fixture.groups["group-finance"]["workspace"]["description"] = "Budgets and forecasts."

    # A lowercase fragment of a name finds the group on both sides.
    fixture_lower, server_lower = _search(fixture, env, "research")
    assert fixture_lower == server_lower == ["group-research"], (
        f"case drift: fixture {fixture_lower}, server {server_lower}"
    )
    # A description-only term finds it too.
    fixture_desc, server_desc = _search(fixture, env, "KNOWLEDGE")
    assert fixture_desc == server_desc == ["group-research"], (
        f"description drift: fixture {fixture_desc}, server {server_desc}"
    )
    # Surrounding spaces are ignored, and a term in neither field matches nothing, so the fixture
    # isn't simply answering every search.
    fixture_spaced, server_spaced = _search(fixture, env, "  forecasts  ")
    assert fixture_spaced == server_spaced == ["group-finance"]
    fixture_none, server_none = _search(fixture, env, "marketing")
    assert fixture_none == server_none == []


# --------------------------------------------------------------------------
# setActive: success and refusals.
# --------------------------------------------------------------------------

def test_set_active_success_parity(env, new_fixture):
    """Activating a reachable group is a 200 carrying `message` on both sides."""
    env.seed_group("group-ok", "Group OK", members=(CALLER,))
    real = env.call("PATCH", SET_ACTIVE_PATH, body={"groupId": "group-ok"})

    fixture = new_fixture()
    seed_fixture_groups(fixture, [("group-ok", "Group OK", "User")])
    status, payload = drive_fixture(fixture, "PATCH", SET_ACTIVE_PATH, body={"groupId": "group-ok"})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert "message" in payload and "message" in real_payload
    assert payload["message"] == real_payload["message"]
    assert_error_code_parity("set-active-success", payload, real_payload)


def test_set_active_missing_group_id_parity(env, new_fixture):
    """A missing groupId is a 400 carrying `error` and no `error_code` on both sides."""
    real = env.call("PATCH", SET_ACTIVE_PATH, body={})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", SET_ACTIVE_PATH, body={})

    assert (status, real.status_code) == (400, 400)
    real_payload = real.get_json()
    assert "error" in payload and "error" in real_payload
    assert payload["error"] == real_payload["error"]
    assert_error_code_parity("set-active-missing", payload, real_payload)


def test_set_active_unknown_group_parity(env, new_fixture):
    """An unknown group is a 404 carrying `error` and no `error_code` on both sides."""
    real = env.call("PATCH", SET_ACTIVE_PATH, body={"groupId": "ghost-group"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", SET_ACTIVE_PATH, body={"groupId": "ghost-group"})

    assert (status, real.status_code) == (404, 404)
    real_payload = real.get_json()
    assert "error" in payload and "error" in real_payload
    assert payload["error"] == real_payload["error"]
    assert_error_code_parity("set-active-unknown", payload, real_payload)


def test_set_active_forbidden_parity(env, new_fixture):
    """Activating a group the caller cannot reach is a 403 carrying `error` on both sides."""
    # The caller is not among this group's owner, admins, managers or members.
    env.seed_group("group-foreign", "Foreign Group", owner="owner-1", members=())
    real = env.call("PATCH", SET_ACTIVE_PATH, body={"groupId": "group-foreign"})

    fixture = new_fixture()
    seed_fixture_groups(
        fixture, [("group-foreign", "Foreign Group", "User")], denied=("group-foreign",)
    )
    status, payload = drive_fixture(fixture, "PATCH", SET_ACTIVE_PATH, body={"groupId": "group-foreign"})

    assert (status, real.status_code) == (403, 403)
    real_payload = real.get_json()
    assert "error" in payload and "error" in real_payload
    assert payload["error"] == real_payload["error"]
    assert_error_code_parity("set-active-forbidden", payload, real_payload)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
