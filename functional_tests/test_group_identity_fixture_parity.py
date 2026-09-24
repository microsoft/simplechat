# test_group_identity_fixture_parity.py
"""
Per-route shape parity between the M5A group identity UI fixture and the real routes.
Version: 0.261.157
Implemented in: 0.261.157

The V2 group Identities section and the group action editor's reusable-identity picker mock the
network with the closed HTTP fixture ``ui_tests/fixtures/group_identities.py`` (its dispatch lives
in the shared ``ui_tests/fixtures/group_workspace.py`` base). A fixture whose response shape drifts
from the server would let a passing browser suite hide a real regression -- exactly the M5B F1/F2
class, where a fixture invented keys the server never sends. The M5A identity fixtures predate the
per-route parity rule, so this test backfills the pin.

For every route the identity workbench (``lib/identityWorkbench.ts``) and its field mapper
(``lib/identityFields.ts``) call -- list, read, create, update, delete, the stale-etag conflict and
the still-in-use delete refusal -- it asserts that the fixture never invents a top-level, item,
credentials or reference key the server does not return (``fixture keys <= server keys``), that the
keys the UI actually reads are present in both, and that the status code and the machine-readable
``error_code`` match, including its absence.

The real routes run through the same isolated backend harness the identity API suite uses
(``test_support/group_identity_harness.py``: the real policy, access, projection, storage and route
modules over an etag-enforcing fake Cosmos and an in-memory Key Vault). The fixture handlers are the
production browser-test code, exercised through the same ``_dispatch`` entry the Playwright route
handler calls, with a tiny fake page and route that only capture the fulfilled status and JSON.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN
from ui_tests.fixtures.group_identities import (
    GroupIdentitiesFixture,
    EDITABLE_IDENTITY_ID,
    IN_USE_IDENTITY_ID,
)

from test_support.group_identity_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    as_user,
    environment,
    read_etag,
    seed_identity,
)


GROUP = "group-a"

# The keys the identity workbench and its field mapper read off a projected identity. The fixture may
# carry fewer keys than the server (a subset is fine), but it must never drop one the UI relies on:
# id/group_id (scope assertion), etag (conditional write), identity_actions (per-row gate), and the
# name/description/usage_contexts/credentials the editor draft reads (`draftFromIdentity`).
IDENTITY_ITEM_UI_KEYS = {
    "id", "group_id", "etag", "identity_actions",
    "name", "description", "usage_contexts", "credentials",
}
# The credential fields `readCredentials`/`draftFromIdentity` read. A key the server omits would open
# blank and be sent back blank, clearing the stored value; a key the fixture invents would hide that.
CREDENTIALS_UI_KEYS = {
    "auth_type", "username", "domain", "identity", "password_stored", "secret_stored",
}
# The reference fields `identityReferences` reads to name what still uses an identity on a refused
# delete.
REFERENCE_UI_KEYS = {"kind", "id", "name"}


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
    return GroupIdentitiesFixture(_FakePage())


def fixture_item_path(identity_id=EDITABLE_IDENTITY_ID):
    return f"{LIST_PATH}/{identity_id}"


def real_item_path(identity_id):
    return f"{LIST_PATH}/{identity_id}"


# --------------------------------------------------------------------------
# Parity assertions (top-level and nested), mirroring the file source parity test.
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
    """A nested object (an identity item, its credentials, a reference) must invent no key the
    server omits, and must carry every key the UI reads."""
    invented = set(fixture_obj) - set(real_obj)
    assert not invented, (
        f"{scenario}: the fixture object invents keys the server never returns: {sorted(invented)}"
    )
    for key in ui_keys:
        assert key in real_obj, f"{scenario}: the server object no longer carries {key!r}"
        assert key in fixture_obj, f"{scenario}: the fixture object dropped {key!r}, which the UI reads"


def assert_error_code(scenario, fixture_payload, real_payload, expected):
    """The machine-readable error_code must match, including its absence (neither side carries one)."""
    assert fixture_payload.get("error_code") == real_payload.get("error_code") == expected, (
        f"{scenario}: error_code mismatch -- fixture {fixture_payload.get('error_code')!r}, "
        f"server {real_payload.get('error_code')!r}, expected {expected!r}"
    )


# --------------------------------------------------------------------------
# Success shapes: list, read, create, update.
# --------------------------------------------------------------------------

def test_list_shape_parity(environment):
    """The list envelope and each identity item carry the same keys the UI reads."""
    seed_identity(environment)
    as_user(environment, "owner")
    real = environment.client.get(LIST_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", LIST_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, {"identities"})
    assert_nested_parity(
        "list item", payload["identities"][0], real_payload["identities"][0], IDENTITY_ITEM_UI_KEYS,
    )
    assert_nested_parity(
        "list item credentials", payload["identities"][0]["credentials"],
        real_payload["identities"][0]["credentials"], CREDENTIALS_UI_KEYS,
    )


def test_read_shape_parity(environment):
    """A single read returns one ``identity``, its item shape matching the list projection."""
    identity = seed_identity(environment)
    as_user(environment, "owner")
    real = environment.client.get(real_item_path(identity["id"]))
    status, payload = drive_fixture(new_fixture(), "GET", fixture_item_path())

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("read", payload, real_payload)
    assert_shared_keys("read", payload, real_payload, {"identity"})
    assert_nested_parity("read item", payload["identity"], real_payload["identity"], IDENTITY_ITEM_UI_KEYS)
    assert_nested_parity(
        "read item credentials", payload["identity"]["credentials"],
        real_payload["identity"]["credentials"], CREDENTIALS_UI_KEYS,
    )


def test_create_shape_parity(environment):
    """A create returns the new ``identity`` with a 201, its item shape matching a read."""
    as_user(environment, "owner")
    body = {
        "name": "New identity",
        "provider": "generic",
        "credentials": {"auth_type": "username_password", "username": "svc", "password": "p@ss"},
    }
    real = environment.client.post(LIST_PATH, json=body)
    status, payload = drive_fixture(new_fixture(), "POST", LIST_PATH, body=dict(body))

    assert (status, real.status_code) == (201, 201)
    real_payload = real.get_json()
    assert_no_invented_keys("create", payload, real_payload)
    assert_shared_keys("create", payload, real_payload, {"identity"})
    assert_nested_parity("create item", payload["identity"], real_payload["identity"], IDENTITY_ITEM_UI_KEYS)


def test_update_shape_parity(environment):
    """A conditional update returns the updated ``identity``."""
    identity = seed_identity(environment)
    as_user(environment, "owner")
    real = environment.client.patch(
        real_item_path(identity["id"]),
        json={"name": "Renamed identity", "expected_etag": read_etag(environment, identity["id"])},
    )
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_item_path(), body={
        "name": "Renamed identity",
        "expected_etag": fixture._identity_etag(GROUP, EDITABLE_IDENTITY_ID),
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("update", payload, real_payload)
    assert_shared_keys("update", payload, real_payload, {"identity"})
    assert_nested_parity("update item", payload["identity"], real_payload["identity"], IDENTITY_ITEM_UI_KEYS)


# --------------------------------------------------------------------------
# Conflict and refusal shapes: stale etag, still-in-use, delete success.
# --------------------------------------------------------------------------

def test_etag_conflict_shape_parity(environment):
    """A stale ``expected_etag`` on PATCH returns ``{error, error_code: "etag_conflict"}`` from both."""
    identity = seed_identity(environment)
    as_user(environment, "owner")
    real = environment.client.patch(
        real_item_path(identity["id"]),
        json={"name": "Renamed", "expected_etag": '"stale-etag"'},
    )
    status, payload = drive_fixture(new_fixture(), "PATCH", fixture_item_path(), body={
        "name": "Renamed", "expected_etag": "stale-etag",
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("etag_conflict", payload, real_payload)
    assert_shared_keys("etag_conflict", payload, real_payload, {"error", "error_code"})
    assert_error_code("etag_conflict", payload, real_payload, "etag_conflict")


def test_identity_in_use_delete_shape_parity(environment):
    """A delete refused because the identity is still referenced returns
    ``{error, error_code: "identity_in_use", references}`` from both, with matching reference keys."""
    identity = seed_identity(environment)
    environment.state.file_sync_sources = [
        {"id": "src-archive", "name": "Archive share", "identity_id": identity["id"]},
    ]
    as_user(environment, "owner")
    real = environment.client.delete(
        real_item_path(identity["id"]),
        json={"expected_etag": read_etag(environment, identity["id"])},
    )
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(IN_USE_IDENTITY_ID), body={
        "expected_etag": fixture._identity_etag(GROUP, IN_USE_IDENTITY_ID),
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("identity_in_use", payload, real_payload)
    assert_shared_keys("identity_in_use", payload, real_payload, {"error", "error_code", "references"})
    assert_error_code("identity_in_use", payload, real_payload, "identity_in_use")
    assert_nested_parity(
        "identity_in_use reference", payload["references"][0], real_payload["references"][0], REFERENCE_UI_KEYS,
    )


def test_delete_success_shape_parity(environment):
    """A successful delete returns ``{success: True}`` with a 200 and no error_code from both."""
    identity = seed_identity(environment)
    as_user(environment, "owner")
    real = environment.client.delete(
        real_item_path(identity["id"]),
        json={"expected_etag": read_etag(environment, identity["id"])},
    )
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(), body={
        "expected_etag": fixture._identity_etag(GROUP, EDITABLE_IDENTITY_ID),
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("delete_success", payload, real_payload)
    assert_shared_keys("delete_success", payload, real_payload, {"success"})
    assert_error_code("delete_success", payload, real_payload, None)


# --------------------------------------------------------------------------
# Denial shapes: unknown identity 404, role refusal 403, malformed query 400.
# --------------------------------------------------------------------------

def test_unknown_identity_404_shape_parity(environment):
    """An unknown identity is a 404 with no error_code from both."""
    seed_identity(environment)
    as_user(environment, "owner")
    real = environment.client.get(real_item_path("no-such-identity"))
    status, payload = drive_fixture(new_fixture(), "GET", fixture_item_path("no-such-identity"))

    assert (status, real.status_code) == (404, 404)
    real_payload = real.get_json()
    assert_no_invented_keys("unknown_identity", payload, real_payload)
    assert_shared_keys("unknown_identity", payload, real_payload, {"error"})
    assert_error_code("unknown_identity", payload, real_payload, None)


def test_role_refusal_403_shape_parity(environment):
    """A non-manager reader is refused with a 403 and no error_code from both. On the server an
    ordinary member of the group is refused; the fixture models the same refusal on its member group
    (group-b), so the reader never falls back to a personal identity read."""
    seed_identity(environment)
    as_user(environment, "member")
    real = environment.client.get(LIST_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", "/api/groups/group-b/identities")

    assert (status, real.status_code) == (403, 403)
    real_payload = real.get_json()
    assert_no_invented_keys("role_refusal", payload, real_payload)
    assert_shared_keys("role_refusal", payload, real_payload, {"error"})
    assert_error_code("role_refusal", payload, real_payload, None)


def test_unexpected_query_400_shape_parity(environment):
    """An unexpected query parameter is a 400 with no error_code from both."""
    seed_identity(environment)
    as_user(environment, "owner")
    real = environment.client.get(f"{LIST_PATH}?page=2")
    status, payload = drive_fixture(new_fixture(), "GET", LIST_PATH, query={"page": "2"})

    assert (status, real.status_code) == (400, 400)
    real_payload = real.get_json()
    assert_no_invented_keys("unexpected_query", payload, real_payload)
    assert_shared_keys("unexpected_query", payload, real_payload, {"error"})
    assert_error_code("unexpected_query", payload, real_payload, None)
