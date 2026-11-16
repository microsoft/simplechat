# test_group_endpoint_fixture_parity.py
"""
Per-route shape parity between the M5C group endpoint UI fixture and the real routes.
Version: 0.261.160
Implemented in: 0.261.145

M5C contract Section 11, F5. The V2 group Endpoints browser suite mocks the network with the
closed HTTP fixture `ui_tests/fixtures/group_endpoints.py`, so a fixture whose response shape
drifts from the server would let a passing browser test hide a real regression. This test pins
the fixture's response keys against the real named-group routes, driven by the same isolated
backend harness the group endpoint functional tests use (`test_support/group_endpoint_harness.py`,
running the real policy, access, route, group-document, Key Vault and settings modules against an
etag-enforcing fake Cosmos and an in-memory vault).

For every named-group route the UI calls -- the list, read, create, update and delete of
`/api/groups/<g>/model-endpoints[...]`, and the `models/{fetch,test-model,foundry/agents}`
discovery and test routes -- it asserts that the fixture never invents a top-level, endpoint-item
or reference key the server does not return (`fixture keys <= server keys`), that the keys the UI
actually reads are present in both, and that the status code and the machine-readable
`error_code` match. It covers success, each 409 code (`endpoint_conflict`, `group_write_conflict`
and `endpoint_in_use`) and one reviewed 400, so the run fails the moment the fixture drifts.

The fixture handlers are the production browser-test code, exercised here through the same
`_dispatch` entry the Playwright route handler calls, with a tiny fake page and route that only
capture the fulfilled status and JSON.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN
from ui_tests.fixtures.group_endpoints import (
    GroupEndpointsFixture,
    EDITABLE_ENDPOINT_ID,
    FOUNDRY_ENDPOINT_ID,
    IN_USE_ENDPOINT_ID,
)

from test_support.group_endpoint_harness import (
    GROUP_A,
    ROLE_USERS,
    aoai_endpoint,
    foundry_endpoint,
    group_endpoint_environment,
)


LIST_PATH = f"/api/groups/{GROUP_A}/model-endpoints"

# The keys the shared ModelConnectionsManager reads off a projected endpoint. The fixture may carry
# fewer keys than the server (a subset is fine), but it must never drop one the editor relies on.
ENDPOINT_ITEM_KEYS = {"id", "name", "enabled", "provider", "models", "auth", "connection", "revision", "endpoint_actions"}
REFERENCE_KEYS = {"kind", "id", "name"}


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

    def fulfill(self, status=200, json=None, **kwargs):
        self.status = status
        self.payload = json


def drive_fixture(fixture, method, path, body=None, query=None):
    """Dispatch one request through the fixture exactly as its Playwright route handler would, and
    return the fulfilled (status, payload)."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}")
    fixture._dispatch(route, entry)
    return route.status, route.payload


def new_fixture():
    return GroupEndpointsFixture(_FakePage())


def fixture_item_path(endpoint_id):
    return f"{LIST_PATH}/{endpoint_id}"


# --------------------------------------------------------------------------
# Real routes: the isolated backend harness.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def real_item_path(endpoint_id):
    return f"{LIST_PATH}/{endpoint_id}"


def new_endpoint(**changes):
    payload = aoai_endpoint("", api_key="sk-new")
    payload.pop("id")
    payload["name"] = "New connection"
    payload.update(changes)
    return payload


def legacy_key_name(endpoint_id, field="api-key"):
    return f"{endpoint_id}--model-endpoint--group--model-endpoint-{field}"


def land_membership_change(env, user_id="late-member"):
    def concurrent():
        record = env.stored_group(GROUP_A)
        record["users"].append({"userId": user_id, "email": "", "displayName": "Late"})
        env.groups.seed(record)
    return concurrent


def seed_one_endpoint(env, endpoint_id="ep-a"):
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint(endpoint_id)])
    env.as_user(ROLE_USERS["Owner"])
    env.vault.writes.clear()


# --------------------------------------------------------------------------
# Parity assertions.
# --------------------------------------------------------------------------

def assert_no_invented_keys(scenario, fixture_payload, real_payload):
    fixture_keys, real_keys = set(fixture_payload), set(real_payload)
    invented = fixture_keys - real_keys
    assert not invented, (
        f"{scenario}: the fixture returns top-level keys the server never does: {sorted(invented)} "
        f"(server keys {sorted(real_keys)})"
    )


def assert_shared_keys(scenario, fixture_payload, real_payload, required):
    for key in required:
        assert key in real_payload, f"{scenario}: the server no longer returns {key!r}; the harness or contract drifted"
        assert key in fixture_payload, f"{scenario}: the fixture dropped {key!r}, which the editor reads"


def assert_item_parity(scenario, fixture_item, real_item):
    invented = set(fixture_item) - set(real_item)
    assert not invented, (
        f"{scenario}: the fixture endpoint item invents keys the server never returns: {sorted(invented)}"
    )
    for key in ENDPOINT_ITEM_KEYS:
        assert key in real_item, f"{scenario}: the server endpoint item no longer carries {key!r}"
        assert key in fixture_item, f"{scenario}: the fixture endpoint item dropped {key!r}"


# --------------------------------------------------------------------------
# Success shapes.
# --------------------------------------------------------------------------

def test_list_shape_parity(env):
    """The list envelope and each endpoint item carry the same keys the UI reads."""
    seed_one_endpoint(env)
    real = env.client.get(LIST_PATH)
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", LIST_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, {"endpoints"})
    assert_item_parity("list", payload["endpoints"][0], real_payload["endpoints"][0])


def test_read_shape_parity(env):
    """A single read returns one `endpoint`, its item shape matching the list projection."""
    seed_one_endpoint(env)
    real = env.client.get(real_item_path("ep-a"))
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "GET", fixture_item_path(EDITABLE_ENDPOINT_ID))

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("read", payload, real_payload)
    assert_shared_keys("read", payload, real_payload, {"endpoint"})
    assert_item_parity("read", payload["endpoint"], real_payload["endpoint"])


def test_create_shape_parity(env):
    """A create returns the new `endpoint` with a 201, its item shape matching a read."""
    seed_one_endpoint(env)
    real = env.call("POST", LIST_PATH, new_endpoint())
    fixture = new_fixture()
    # The editor posts the full connection payload -- name, provider, connection, auth and models --
    # so the created item projects the same shape a read would; drive the fixture with that body.
    status, payload = drive_fixture(fixture, "POST", LIST_PATH, body=new_endpoint())

    assert (status, real.status_code) == (201, 201)
    real_payload = real.get_json()
    assert_no_invented_keys("create", payload, real_payload)
    assert_shared_keys("create", payload, real_payload, {"endpoint"})
    assert_item_parity("create", payload["endpoint"], real_payload["endpoint"])


def test_update_shape_parity(env):
    """A conditional update returns the updated `endpoint`."""
    seed_one_endpoint(env)
    real = env.call("PATCH", real_item_path("ep-a"), {
        "expected_revision": env.revision_of(GROUP_A, "ep-a"),
        "name": "Renamed connection",
    })
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_item_path(EDITABLE_ENDPOINT_ID), body={
        "expected_revision": fixture._endpoint_revision(GROUP_A, EDITABLE_ENDPOINT_ID),
        "name": "Renamed connection",
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("update", payload, real_payload)
    assert_shared_keys("update", payload, real_payload, {"endpoint"})
    assert_item_parity("update", payload["endpoint"], real_payload["endpoint"])


def test_delete_shape_parity(env):
    """A delete returns exactly `{success: true}`."""
    seed_one_endpoint(env)
    real = env.call("DELETE", real_item_path("ep-a"), {"expected_revision": env.revision_of(GROUP_A, "ep-a")})
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(EDITABLE_ENDPOINT_ID), body={
        "expected_revision": fixture._endpoint_revision(GROUP_A, EDITABLE_ENDPOINT_ID),
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("delete", payload, real_payload)
    assert_shared_keys("delete", payload, real_payload, {"success"})
    assert payload["success"] is True and real_payload["success"] is True


# --------------------------------------------------------------------------
# Conflict codes.
# --------------------------------------------------------------------------

def test_endpoint_conflict_shape_parity(env):
    """A stale revision returns `{error, error_code: "endpoint_conflict"}` from both."""
    seed_one_endpoint(env)
    stale = env.revision_of(GROUP_A, "ep-a")
    assert env.call("PATCH", real_item_path("ep-a"), {"expected_revision": stale, "name": "First"}).status_code == 200
    real = env.call("PATCH", real_item_path("ep-a"), {"expected_revision": stale, "name": "Second"})

    fixture = new_fixture()
    fixture.touch_endpoint(GROUP_A, EDITABLE_ENDPOINT_ID)
    status, payload = drive_fixture(fixture, "PATCH", fixture_item_path(EDITABLE_ENDPOINT_ID), body={
        "expected_revision": stale,
        "name": "Second",
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("endpoint_conflict", payload, real_payload)
    assert_shared_keys("endpoint_conflict", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "endpoint_conflict"


def test_group_write_conflict_shape_parity(env):
    """An unrelated concurrent group write returns `{error, error_code: "group_write_conflict"}`."""
    seed_one_endpoint(env)
    revision = env.revision_of(GROUP_A, "ep-a")
    attempts = env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS
    env.groups.before_replace.extend(
        land_membership_change(env, user_id=f"late-{index}") for index in range(attempts)
    )
    real = env.call("PATCH", real_item_path("ep-a"), {"expected_revision": revision, "auth": {"api_key": "sk-busy"}})

    fixture = new_fixture()
    fixture.endpoint_write_conflicts.add(GROUP_A)
    status, payload = drive_fixture(fixture, "PATCH", fixture_item_path(EDITABLE_ENDPOINT_ID), body={
        "expected_revision": fixture._endpoint_revision(GROUP_A, EDITABLE_ENDPOINT_ID),
        "auth": {"api_key": "sk-busy"},
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("group_write_conflict", payload, real_payload)
    assert_shared_keys("group_write_conflict", payload, real_payload, {"error", "error_code"})
    assert payload["error_code"] == real_payload["error_code"] == "group_write_conflict"
    assert payload["error"] == real_payload["error"] == env.modules.group.GROUP_WRITE_CONFLICT_MESSAGE


def test_endpoint_in_use_shape_parity(env):
    """A delete refused because the endpoint is in use returns references with `{kind, id, name}`."""
    seed_one_endpoint(env)
    env.agents.seed({
        "id": "a1", "group_id": GROUP_A, "name": "agent_a1", "display_name": "Agent a1",
        "agent_type": "local", "other_settings": {}, "model_endpoint_id": "ep-a",
    })
    real = env.call("DELETE", real_item_path("ep-a"), {"expected_revision": env.revision_of(GROUP_A, "ep-a")})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(IN_USE_ENDPOINT_ID), body={
        "expected_revision": fixture._endpoint_revision(GROUP_A, IN_USE_ENDPOINT_ID),
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("endpoint_in_use", payload, real_payload)
    assert_shared_keys("endpoint_in_use", payload, real_payload, {"error", "error_code", "references"})
    assert payload["error_code"] == real_payload["error_code"] == "endpoint_in_use"
    fixture_ref, real_ref = payload["references"][0], real_payload["references"][0]
    invented = set(fixture_ref) - set(real_ref)
    assert not invented, f"endpoint_in_use: the fixture reference invents keys the server never returns: {sorted(invented)}"
    for key in REFERENCE_KEYS:
        assert key in real_ref, f"endpoint_in_use: the server reference no longer carries {key!r}"
        assert key in fixture_ref, f"endpoint_in_use: the fixture reference dropped {key!r}"


# --------------------------------------------------------------------------
# One reviewed 400.
# --------------------------------------------------------------------------

def test_reviewed_400_shape_parity(env):
    """A client-supplied Key Vault reference returns the server's reviewed 400 text, verbatim."""
    seed_one_endpoint(env)
    real = env.call("PATCH", real_item_path("ep-a"), {
        "expected_revision": env.revision_of(GROUP_A, "ep-a"),
        "auth": {"api_key": legacy_key_name("ep-a")},
    })

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_item_path(EDITABLE_ENDPOINT_ID), body={
        "expected_revision": fixture._endpoint_revision(GROUP_A, EDITABLE_ENDPOINT_ID),
        "auth": {"api_key": legacy_key_name(EDITABLE_ENDPOINT_ID)},
    })

    assert (status, real.status_code) == (400, 400)
    real_payload = real.get_json()
    assert_no_invented_keys("reviewed_400", payload, real_payload)
    assert_shared_keys("reviewed_400", payload, real_payload, {"error"})
    # The editor renders the server's own text; a drift in the fixture's copy would mislead a user.
    assert payload["error"] == real_payload["error"]


# --------------------------------------------------------------------------
# Discovery and test routes.
# --------------------------------------------------------------------------

def test_models_fetch_shape_parity(env):
    """The group model discovery route returns `{models}` from both."""
    env.seed_group_with_legacy_endpoints(GROUP_A, [foundry_endpoint("fa")])
    env.as_user(ROLE_USERS["Owner"])
    real = env.call("POST", f"/api/groups/{GROUP_A}/models/fetch", {"endpoint_id": "fa"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "POST", f"/api/groups/{GROUP_A}/models/fetch",
                                    body={"endpoint_id": FOUNDRY_ENDPOINT_ID})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("models/fetch", payload, real_payload)
    assert_shared_keys("models/fetch", payload, real_payload, {"models"})


def test_models_test_model_shape_parity(env):
    """The group single-model test route returns `{success}` from both."""
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("aa")])
    env.as_user(ROLE_USERS["Owner"])
    real = env.call("POST", f"/api/groups/{GROUP_A}/models/test-model", {"endpoint_id": "aa", "model": {"id": "chat"}})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "POST", f"/api/groups/{GROUP_A}/models/test-model",
                                    body={"endpoint_id": EDITABLE_ENDPOINT_ID, "model": {"id": "chat"}})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("models/test-model", payload, real_payload)
    assert_shared_keys("models/test-model", payload, real_payload, {"success"})
    assert payload["success"] is True and real_payload["success"] is True


def test_models_foundry_agents_shape_parity(env):
    """The named-group Foundry discovery route returns `{agents, responses_api_version}` from both."""
    env.seed_group_with_legacy_endpoints(GROUP_A, [foundry_endpoint("fa")])
    env.as_user(ROLE_USERS["Owner"])
    real = env.call("POST", f"/api/groups/{GROUP_A}/models/foundry/agents", {"endpoint_id": "fa"})

    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "POST", f"/api/groups/{GROUP_A}/models/foundry/agents",
                                    body={"endpoint_id": FOUNDRY_ENDPOINT_ID})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("models/foundry/agents", payload, real_payload)
    assert_shared_keys("models/foundry/agents", payload, real_payload, {"agents", "responses_api_version"})


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
