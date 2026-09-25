# test_public_file_source_fixture_parity.py
"""
Per-route shape parity between the M10B public file source UI fixture and the real routes.
Version: 0.261.179
Implemented in: 0.261.179

M10B: the V2 public file sources browser suite mocks the network with the closed HTTP fixture
`ui_tests/fixtures/public_file_sources.py`, so a fixture whose response shape drifts from the server
would let a passing browser test hide a real regression. This test pins the fixture's response keys
against the real immutable-target public file source routes, driven by the same isolated backend
harness the file source functional tests use (`test_support/public_file_source_harness.py`, running
the real policy, access, projection, service, route, Key Vault and settings modules against an
etag-enforcing fake Cosmos and an in-memory vault, with the real public workspace role logic).

For every route the V2 section calls -- list, read, create, update, delete and options -- it asserts
that the fixture never invents a top-level, source-item, credentials, connection or filters key the
server does not return (`fixture keys <= server keys`), that the keys the UI actually reads are
present in both, and that the status code and the machine-readable `error_code` match, including its
absence. It covers success, the `config_conflict` and `source_busy` 409 codes, an unknown source 404,
a non-manager reader's 403, and the missing-revision 400, so the run fails the moment the fixture
drifts. The live File Sync engine's run history, connection test and browse shapes are the
scope-generic engine's own and are pinned byte-for-byte by the group M5B suite.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "application" / "single_app", ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN
from ui_tests.fixtures.public_file_sources import (
    PublicFileSourcesFixture,
    EDITABLE_SOURCE_ID,
)

from test_support.public_file_source_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    OPTIONS_PATH,
    as_user,
    create_source,
    environment,
)


FIXTURE_WORKSPACE = "pub-a"
FIXTURE_MEMBER_WORKSPACE = "pub-b"

# The fixture seeds its own workspace ids (`pub-a`, `pub-b`); the harness serves `public-a`. Each side is
# driven at its own paths -- the parity is over response shape, not workspace id.
FIXTURE_LIST_PATH = f"/api/public-workspaces/{FIXTURE_WORKSPACE}/file-sources"
FIXTURE_OPTIONS_PATH = f"/api/public-workspaces/{FIXTURE_WORKSPACE}/file-source-options"
FIXTURE_MEMBER_LIST_PATH = f"/api/public-workspaces/{FIXTURE_MEMBER_WORKSPACE}/file-sources"

# The keys the shared file source workbench reads off a projected source. The fixture may carry fewer
# keys than the server (a subset is fine), but it must never drop one the editor relies on. The public
# reader also validates `public_workspace_id` on every returned source, so it is a required key.
SOURCE_ITEM_UI_KEYS = {
    "id", "name", "public_workspace_id", "source_type", "enabled", "recursive", "connection",
    "filters", "schedule", "identity_id", "config_revision", "source_actions", "remote_delete_policy",
}
SOURCE_CONNECTION_UI_KEYS = {"unc_path", "selected_paths"}
FILTERS_UI_KEYS = {"include_patterns", "exclude_patterns", "allowed_extensions", "fixed_tags", "folder_tag_mode"}
OPTIONS_UI_KEYS = {"source_types", "eligible_identity_ids", "schedule", "limits", "recursive_allowed"}
# The credential fields the editor's draftFromSource reads. A key the server omits would open blank and
# be sent back blank, which clears the stored value (the identity credential round-trip fix).
CREDENTIALS_UI_KEYS = {
    "auth_type", "username", "domain", "identity", "tenant_id", "managed_identity_client_id",
    "password_stored", "secret_stored",
}


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
    return PublicFileSourcesFixture(_FakePage())


def fixture_item_path(source_id=EDITABLE_SOURCE_ID):
    return f"{FIXTURE_LIST_PATH}/{source_id}"


def real_item_path(source_id):
    return f"{LIST_PATH}/{source_id}"


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
    """A nested object must invent no key the server omits, and carry every key the UI reads."""
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


def _assert_item_parity(scenario, fixture_item, real_item):
    assert_nested_parity(scenario, fixture_item, real_item, SOURCE_ITEM_UI_KEYS)
    assert_nested_parity(f"{scenario} credentials", fixture_item["credentials"], real_item["credentials"], CREDENTIALS_UI_KEYS)
    assert_nested_parity(f"{scenario} connection", fixture_item["connection"], real_item["connection"], SOURCE_CONNECTION_UI_KEYS)
    assert_nested_parity(f"{scenario} filters", fixture_item["filters"], real_item["filters"], FILTERS_UI_KEYS)


# --------------------------------------------------------------------------
# Success shapes.
# --------------------------------------------------------------------------

def test_list_shape_parity(environment):
    """The list envelope and each source item carry the same keys the UI reads."""
    create_source(environment)
    as_user(environment, "owner")
    real = environment.client.get(LIST_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", FIXTURE_LIST_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, {"file_sources", "file_source_management"})
    _assert_item_parity("list item", payload["file_sources"][0], real_payload["file_sources"][0])
    assert_no_invented_keys("list management", payload["file_source_management"], real_payload["file_source_management"])
    assert_shared_keys(
        "list management", payload["file_source_management"], real_payload["file_source_management"],
        {"schema_version", "operations"},
    )


def test_read_shape_parity(environment):
    """A single read returns one `file_source`, its item shape matching the list projection."""
    source = create_source(environment)
    as_user(environment, "owner")
    real = environment.client.get(real_item_path(source["id"]))
    status, payload = drive_fixture(new_fixture(), "GET", fixture_item_path())

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("read", payload, real_payload)
    assert_shared_keys("read", payload, real_payload, {"file_source"})
    _assert_item_parity("read item", payload["file_source"], real_payload["file_source"])


def test_create_shape_parity(environment):
    """A create returns the new `file_source` with a 201, its item shape matching a read."""
    as_user(environment, "owner")
    from test_support.public_file_source_harness import smb_payload
    real = environment.client.post(LIST_PATH, json=smb_payload())
    status, payload = drive_fixture(new_fixture(), "POST", FIXTURE_LIST_PATH, body=smb_payload())

    assert (status, real.status_code) == (201, 201)
    real_payload = real.get_json()
    assert_no_invented_keys("create", payload, real_payload)
    assert_shared_keys("create", payload, real_payload, {"file_source"})
    _assert_item_parity("create item", payload["file_source"], real_payload["file_source"])


def test_update_shape_parity(environment):
    """A conditional update returns the updated `file_source`."""
    source = create_source(environment)
    as_user(environment, "owner")
    real = environment.client.patch(
        real_item_path(source["id"]),
        json={"expected_config_revision": source["config_revision"], "name": "Renamed share"},
    )
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "PATCH", fixture_item_path(), body={
        "expected_config_revision": fixture._file_source_config_revision(FIXTURE_WORKSPACE, EDITABLE_SOURCE_ID),
        "name": "Renamed share",
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("update", payload, real_payload)
    assert_shared_keys("update", payload, real_payload, {"file_source"})
    _assert_item_parity("update item", payload["file_source"], real_payload["file_source"])


def test_delete_shape_parity(environment):
    """A conditional delete returns success with the delete_result counts."""
    source = create_source(environment)
    as_user(environment, "owner")
    real = environment.client.delete(
        real_item_path(source["id"]),
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(), body={
        "expected_config_revision": fixture._file_source_config_revision(FIXTURE_WORKSPACE, EDITABLE_SOURCE_ID),
        "delete_associated_files": False,
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("delete", payload, real_payload)
    assert_shared_keys("delete", payload, real_payload, {"success", "delete_result"})
    assert_no_invented_keys("delete result", payload["delete_result"], real_payload["delete_result"])


def test_options_shape_parity(environment):
    """The options envelope carries the same keys the picker reads."""
    as_user(environment, "owner")
    real = environment.client.get(OPTIONS_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", FIXTURE_OPTIONS_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("options", payload, real_payload)
    assert_shared_keys("options", payload, real_payload, OPTIONS_UI_KEYS)


# --------------------------------------------------------------------------
# Conflict and refusal shapes.
# --------------------------------------------------------------------------

def test_update_config_conflict_parity(environment):
    """A stale expected_config_revision returns 409 config_conflict on both sides."""
    source = create_source(environment)
    as_user(environment, "owner")
    real = environment.client.patch(
        real_item_path(source["id"]),
        json={"expected_config_revision": "stale-revision", "name": "x"},
    )
    status, payload = drive_fixture(new_fixture(), "PATCH", fixture_item_path(), body={
        "expected_config_revision": "stale-revision", "name": "x",
    })

    assert (status, real.status_code) == (409, 409)
    assert_error_code("config_conflict", payload, real.get_json(), "config_conflict")


def test_delete_source_busy_parity(environment):
    """A delete refused by an active run returns 409 source_busy on both sides."""
    source = create_source(environment)
    environment.runs_container.seed({"id": f"{source['id']}-run", "source_id": source["id"], "status": "running"})
    as_user(environment, "owner")
    real = environment.client.delete(
        real_item_path(source["id"]),
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    fixture = new_fixture()
    fixture.mark_source_busy(FIXTURE_WORKSPACE, EDITABLE_SOURCE_ID)
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(), body={
        "expected_config_revision": fixture._file_source_config_revision(FIXTURE_WORKSPACE, EDITABLE_SOURCE_ID),
        "delete_associated_files": False,
    })

    assert (status, real.status_code) == (409, 409)
    assert_error_code("source_busy", payload, real.get_json(), "source_busy")


def test_unknown_source_not_found_parity(environment):
    """An unknown source id returns 404 with no error_code on both sides."""
    create_source(environment)
    as_user(environment, "owner")
    real = environment.client.get(f"{LIST_PATH}/does-not-exist")
    status, payload = drive_fixture(new_fixture(), "GET", f"{FIXTURE_LIST_PATH}/does-not-exist")

    assert (status, real.status_code) == (404, 404)
    assert_error_code("unknown source", payload, real.get_json(), None)


def test_role_refusal_parity(environment):
    """An ordinary reader's workspace refuses every file source route with 403 -- no personal read."""
    as_user(environment, "stranger")
    real = environment.client.get(LIST_PATH)
    status, payload = drive_fixture(
        new_fixture(), "GET", FIXTURE_MEMBER_LIST_PATH,
    )

    assert (status, real.status_code) == (403, 403)
    assert_error_code("role refusal", payload, real.get_json(), None)


def test_missing_revision_rejected_parity(environment):
    """A write without expected_config_revision is refused with 400 on both sides."""
    source = create_source(environment)
    as_user(environment, "owner")
    real = environment.client.patch(real_item_path(source["id"]), json={"name": "x"})
    status, payload = drive_fixture(new_fixture(), "PATCH", fixture_item_path(), body={"name": "x"})

    assert (status, real.status_code) == (400, 400)
    assert_error_code("missing revision", payload, real.get_json(), None)
