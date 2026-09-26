# test_public_prompt_fixture_parity.py
"""
Per-route shape parity between the M9C public prompt UI fixture and the real routes.
Version: 0.261.177
Implemented in: 0.261.177

The V2 public Prompts section mocks the network with the closed HTTP fixture
``ui_tests/fixtures/public_prompts.py`` (its base dispatch lives in the shared
``ui_tests/fixtures/public_workspace.py``). A fixture whose response shape drifts from the server
would let a passing browser suite hide a real regression -- the M5B F1/F2 class, where a fixture
invented keys the server never sends.

For every route the prompt workbench (``lib/promptWorkbench.ts``) calls -- list, create, update,
delete, plus the stale-etag conflict, the not-found refusal and the unreadable-status refusal -- it
asserts that the fixture never invents a top-level or item key the server does not return
(``fixture keys <= server keys``), that the keys the workbench reads are present in both, and that
the status code and the machine-readable ``error_code`` match, including its absence.

The workbench calls list/create/update/delete only: it never reads a single prompt (the list uses
``page_size=500``), so no read-single route is a workbench subject. Public reads are open to every
authenticated caller of a browsable workspace, so there is no non-member refusal here; the public
analogue is the status refusal a workspace outside the browsable allowlist returns. Write refusals
and malformed input are gated client-side and asserted by the fixture, never returned, so they are
not parity subjects.

The real routes run through the same isolated backend harness the prompt API suite uses
(``test_support/public_prompt_harness.py``). The fixture handlers are the production browser-test
code, exercised through the same ``_dispatch`` entry the Playwright route handler calls.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN
from ui_tests.fixtures.public_prompts import PublicPromptsFixture

from test_support.public_prompt_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    as_user,
    environment,
    seed_prompt,
)


# The fixture and the real harness seed different workspace ids; parity compares shapes, not ids.
FIXTURE_WORKSPACE = "pub-a"
FIXTURE_LIST_PATH = f"/api/public-workspaces/{FIXTURE_WORKSPACE}/prompts"
FIXTURE_PROMPT_ID = "weekly-status"

# The keys the prompt workbench reads off a public prompt. id/public_id are the scope proof
# (`assertPublicPromptScope`), etag is the conditional-write marker, prompt_actions is the per-row
# gate, and name/content/description are the editor draft. The server may carry more (a subset is
# fine), but it must never drop one of these, and the fixture must never invent one it omits.
PROMPT_ITEM_UI_KEYS = {"id", "public_id", "etag", "prompt_actions", "name", "content", "description"}


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
    """Dispatch one request through the fixture exactly as its Playwright route handler would."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}")
    fixture._dispatch(route, entry)
    return route.status, route.payload


def new_fixture():
    return PublicPromptsFixture(_FakePage())


def fixture_item_path(prompt_id):
    return f"{FIXTURE_LIST_PATH}/{prompt_id}"


def real_item_path(prompt_id):
    return f"{LIST_PATH}/{prompt_id}"


def fixture_prompt_etag(fixture, prompt_id=FIXTURE_PROMPT_ID):
    return fixture.record(FIXTURE_WORKSPACE, prompt_id)["etag"]


def real_prompt_etag(environment, prompt_id):
    as_user(environment, "owner")
    payload = environment.client.get(LIST_PATH).get_json()
    return next(item["etag"] for item in payload["prompts"] if item["id"] == prompt_id)


# --------------------------------------------------------------------------
# Parity assertions (top-level and nested).
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
        assert key in fixture_payload, f"{scenario}: the fixture dropped {key!r}, which the UI reads"


def assert_nested_parity(scenario, fixture_obj, real_obj, ui_keys):
    invented = set(fixture_obj) - set(real_obj)
    assert not invented, (
        f"{scenario}: the fixture object invents keys the server never returns: {sorted(invented)}"
    )
    for key in ui_keys:
        assert key in real_obj, f"{scenario}: the server object no longer carries {key!r}"
        assert key in fixture_obj, f"{scenario}: the fixture object dropped {key!r}, which the UI reads"


def assert_error_code(scenario, fixture_payload, real_payload, expected):
    assert fixture_payload.get("error_code") == real_payload.get("error_code") == expected, (
        f"{scenario}: error_code mismatch -- fixture {fixture_payload.get('error_code')!r}, "
        f"server {real_payload.get('error_code')!r}, expected {expected!r}"
    )


# --------------------------------------------------------------------------
# Success shapes: list, create, update, delete.
# --------------------------------------------------------------------------

def test_list_shape_parity(environment):
    """The list envelope wraps the collection under ``prompts`` and each item matches the UI keys."""
    seed_prompt(environment.public_container, "p1")
    as_user(environment, "owner")
    real = environment.client.get(LIST_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", FIXTURE_LIST_PATH, query={"page": ["1"], "page_size": ["500"]})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, {"prompts"})
    assert_nested_parity("list item", payload["prompts"][0], real_payload["prompts"][0], PROMPT_ITEM_UI_KEYS)


def test_create_shape_parity(environment):
    """A create returns the new prompt at the top level with a 201, matching the UI item keys."""
    as_user(environment, "owner")
    body = {"name": "New prompt", "content": "Body text", "description": "A note."}
    real = environment.client.post(LIST_PATH, json=dict(body))
    status, payload = drive_fixture(new_fixture(), "POST", FIXTURE_LIST_PATH, body=dict(body))

    assert (status, real.status_code) == (201, 201)
    real_payload = real.get_json()
    assert_no_invented_keys("create", payload, real_payload)
    assert_nested_parity("create item", payload, real_payload, PROMPT_ITEM_UI_KEYS)


def test_update_shape_parity(environment):
    """A conditional update returns the updated prompt at the top level with a 200."""
    seed_prompt(environment.public_container, "p1")
    real = environment.client.patch(
        real_item_path("p1"), json={"name": "Renamed", "expected_etag": real_prompt_etag(environment, "p1")},
    )
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_item_path(FIXTURE_PROMPT_ID), body={
        "name": "Renamed", "expected_etag": fixture_prompt_etag(fixture),
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("update", payload, real_payload)
    assert_nested_parity("update item", payload, real_payload, PROMPT_ITEM_UI_KEYS)


def test_delete_success_shape_parity(environment):
    """A successful delete returns the same body shape and no error_code from both."""
    seed_prompt(environment.public_container, "p1")
    real = environment.client.delete(
        real_item_path("p1"), json={"expected_etag": real_prompt_etag(environment, "p1")},
    )
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(FIXTURE_PROMPT_ID), body={
        "expected_etag": fixture_prompt_etag(fixture),
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("delete_success", payload, real_payload)
    assert_error_code("delete_success", payload, real_payload, None)


# --------------------------------------------------------------------------
# Conflict and refusal shapes: stale etag, unknown prompt, unreadable status.
# --------------------------------------------------------------------------

def test_update_conflict_shape_parity(environment):
    """A stale ``expected_etag`` on PATCH is a 409 whose ``error_code`` is ``prompt_changed`` on both."""
    seed_prompt(environment.public_container, "p1")
    as_user(environment, "owner")
    real = environment.client.patch(real_item_path("p1"), json={"name": "Renamed", "expected_etag": '"stale-etag"'})
    status, payload = drive_fixture(new_fixture(), "PATCH", fixture_item_path(FIXTURE_PROMPT_ID), body={
        "name": "Renamed", "expected_etag": '"stale-etag"',
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("update_conflict", payload, real_payload)
    assert_shared_keys("update_conflict", payload, real_payload, {"error", "error_code"})
    assert_error_code("update_conflict", payload, real_payload, "prompt_changed")


def test_delete_conflict_shape_parity(environment):
    """A stale ``expected_etag`` on DELETE is a 409 whose ``error_code`` is ``prompt_changed`` on both."""
    seed_prompt(environment.public_container, "p1")
    as_user(environment, "owner")
    real = environment.client.delete(real_item_path("p1"), json={"expected_etag": '"stale-etag"'})
    status, payload = drive_fixture(new_fixture(), "DELETE", fixture_item_path(FIXTURE_PROMPT_ID), body={
        "expected_etag": '"stale-etag"',
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("delete_conflict", payload, real_payload)
    assert_shared_keys("delete_conflict", payload, real_payload, {"error", "error_code"})
    assert_error_code("delete_conflict", payload, real_payload, "prompt_changed")


def test_unknown_prompt_404_shape_parity(environment):
    """Editing a missing prompt is a 404 with no error_code on both."""
    as_user(environment, "owner")
    real = environment.client.patch(
        real_item_path("no-such-prompt"), json={"name": "Renamed", "expected_etag": '"whatever"'},
    )
    status, payload = drive_fixture(new_fixture(), "PATCH", fixture_item_path("no-such-prompt"), body={
        "name": "Renamed", "expected_etag": '"whatever"',
    })

    assert (status, real.status_code) == (404, 404)
    real_payload = real.get_json()
    assert_no_invented_keys("unknown_prompt", payload, real_payload)
    assert_shared_keys("unknown_prompt", payload, real_payload, {"error"})
    assert_error_code("unknown_prompt", payload, real_payload, None)


def test_unreadable_status_403_shape_parity(environment):
    """A workspace whose status is outside the browsable allowlist refuses reads with a 403 and no
    error_code on both. The server refuses an inactive workspace; the fixture places its workspace
    into the same status, so the workbench never falls back to a personal or active-scope read."""
    as_user(environment, "owner")
    real = environment.client.get("/api/public-workspaces/inactive-ws/prompts")
    fixture = new_fixture()
    fixture.set_prompt_policy(FIXTURE_WORKSPACE, status="inactive")
    status, payload = drive_fixture(fixture, "GET", FIXTURE_LIST_PATH, query={"page": ["1"], "page_size": ["500"]})

    assert (status, real.status_code) == (403, 403)
    real_payload = real.get_json()
    assert_no_invented_keys("unreadable_status", payload, real_payload)
    assert_shared_keys("unreadable_status", payload, real_payload, {"error"})
    assert_error_code("unreadable_status", payload, real_payload, None)
