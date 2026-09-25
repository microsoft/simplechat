# test_group_file_source_fixture_parity.py
"""
Per-route shape parity between the M5B group file source UI fixture and the real routes.
Version: 0.261.171
Implemented in: 0.261.147
Credentials block compared: 0.261.156
Sync fields and browse paths compared by value: 0.261.171

M5B contract Section 11, F6. The V2 group file sources browser suite mocks the network with the
closed HTTP fixture `ui_tests/fixtures/group_file_sources.py`, so a fixture whose response shape
drifts from the server would let a passing browser test hide a real regression -- exactly the F1
and F2 defects, where the fixture invented `testResult.ok`/`entry.is_dir` shapes the server never
returns. This test pins the fixture's response keys against the real immutable-target group routes,
driven by the same isolated backend harness the file source functional tests use
(`test_support/group_file_source_harness.py`, running the real policy, access, projection, service,
route, Key Vault and settings modules against an etag-enforcing fake Cosmos and an in-memory vault).

For every route the V2 section calls -- list, read, create, update, delete, sync, runs, test
connection, browse, ignore, and options -- it asserts that the fixture never invents a top-level,
source-item, credentials, run or browse-entry key the server does not return (`fixture keys <= server keys`),
that the keys the UI actually reads are present in both, and that the status code and the
machine-readable `error_code` match, including its absence. It covers success, each 409 code
(`config_conflict`, `write_conflict`, `source_busy`, `delete_incomplete`) and a partial refusal
with its counts, the two Sync now 400s shown verbatim, and one reviewed 400, so the run fails the
moment the fixture drifts.

The fixture handlers are the production browser-test code, exercised here through the same
`_dispatch` entry the Playwright route handler calls, with a tiny fake page and route that only
capture the fulfilled status and JSON. The real connection test and browse run genuinely against a
fake SMB session, so their top-level and entry shapes are the engine's own, never hand-written.

Keys alone can't catch a fixture that stores a different value, so the four sync fields the editor
edits -- the selected paths, fixed tags, folder tag mode and remote delete policy -- are also compared
by value: the same write, set, left out, or carrying a value the server rewrites, must leave both
sides holding the same values, and a path leaving the root must be refused the same way. Browse is
compared by path too: over the fixture's own tree, served to the real engine through the fake SMB
session, every browse path resolves relative to the source root on both sides, and the root's own
path or a missing folder fails with the same status and message.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN
from ui_tests.fixtures.group_file_sources import (
    GroupFileSourcesFixture,
    EDITABLE_SOURCE_ID,
)
from ui_tests.fixtures.group_workspace import FILE_SOURCE_BROWSE_TREE

from test_support.group_file_source_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    OPTIONS_PATH,
    UNC_PATH,
    as_user,
    create_source,
    environment,
    seed_synced_document,
    smb_payload,
)


GROUP = "group-a"

# The keys the shared file source workbench reads off a projected source. The fixture may carry
# fewer keys than the server (a subset is fine), but it must never drop one the editor relies on.
SOURCE_ITEM_UI_KEYS = {
    "id", "name", "source_type", "enabled", "recursive", "connection", "filters",
    "schedule", "identity_id", "config_revision", "source_actions", "remote_delete_policy",
}
# The nested keys the editor reads for an SMB source (the only type the parity fixtures seed).
SOURCE_CONNECTION_UI_KEYS = {"unc_path", "selected_paths"}
FILTERS_UI_KEYS = {"include_patterns", "exclude_patterns", "allowed_extensions", "fixed_tags", "folder_tag_mode"}
RUN_ITEM_UI_KEYS = {"id", "run_id", "source_id", "status", "trigger", "started_at", "completed_at", "counts"}
ENTRY_UI_KEYS = {"name", "path", "type"}
IGNORE_ITEM_UI_KEYS = {"id", "remote_path", "status", "ignored"}
CONNECTION_UI_KEYS = {"success", "entries_checked", "files_seen", "folders_seen"}
OPTIONS_UI_KEYS = {"source_types", "eligible_identity_ids", "schedule", "limits", "recursive_allowed"}
# The credential fields the editor's draftFromSource reads. A key the server omits would open blank
# and be sent back blank, which clears the stored value (the 0.261.156 tenant fix).
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
    return GroupFileSourcesFixture(_FakePage())


def fixture_item_path(source_id=EDITABLE_SOURCE_ID):
    return f"{LIST_PATH}/{source_id}"


def real_item_path(source_id):
    return f"{LIST_PATH}/{source_id}"


# --------------------------------------------------------------------------
# A fake SMB session so the real connection test and browse run genuinely,
# producing the engine's own top-level and entry shapes without a network.
# --------------------------------------------------------------------------

class _FakeStat:
    st_size = 20480
    st_mtime = 1704153600  # 2024-01-02T00:00:00+00:00


class _FakeDirEntry:
    def __init__(self, name, is_dir):
        self.name = name
        self._is_dir = is_dir

    def is_dir(self):
        return self._is_dir

    def is_file(self):
        return not self._is_dir

    def stat(self):
        return _FakeStat()


class _FakeSmbClient:
    def scandir(self, path):
        return [_FakeDirEntry("reports", True), _FakeDirEntry("budget.xlsx", False)]


class _BrokenSmbClient:
    def scandir(self, path):
        raise OSError("share unreachable")


def install_fake_smb(environment, monkeypatch, *, broken=False):
    client = _BrokenSmbClient() if broken else _FakeSmbClient()
    monkeypatch.setattr(environment.filesync, "_register_smb_session", lambda source: client)


# --------------------------------------------------------------------------
# Parity assertions (top-level and nested), mirroring the M5C parity test.
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
    """A nested object (a source item, a run, a browse entry) must invent no key the server omits,
    and must carry every key the UI reads."""
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
    """The list envelope and each source item carry the same keys the UI reads."""
    create_source(environment)
    as_user(environment, "owner")
    real = environment.client.get(LIST_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", LIST_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, {"file_sources", "file_source_management"})
    assert_nested_parity("list item", payload["file_sources"][0], real_payload["file_sources"][0], SOURCE_ITEM_UI_KEYS)
    assert_nested_parity(
        "list item credentials", payload["file_sources"][0]["credentials"],
        real_payload["file_sources"][0]["credentials"], CREDENTIALS_UI_KEYS,
    )
    assert_nested_parity(
        "list item connection", payload["file_sources"][0]["connection"],
        real_payload["file_sources"][0]["connection"], SOURCE_CONNECTION_UI_KEYS,
    )
    assert_nested_parity(
        "list item filters", payload["file_sources"][0]["filters"],
        real_payload["file_sources"][0]["filters"], FILTERS_UI_KEYS,
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
    assert_nested_parity("read item", payload["file_source"], real_payload["file_source"], SOURCE_ITEM_UI_KEYS)
    assert_nested_parity(
        "read item credentials", payload["file_source"]["credentials"],
        real_payload["file_source"]["credentials"], CREDENTIALS_UI_KEYS,
    )
    assert_nested_parity(
        "read item connection", payload["file_source"]["connection"],
        real_payload["file_source"]["connection"], SOURCE_CONNECTION_UI_KEYS,
    )
    assert_nested_parity(
        "read item filters", payload["file_source"]["filters"],
        real_payload["file_source"]["filters"], FILTERS_UI_KEYS,
    )


def test_create_shape_parity(environment):
    """A create returns the new `file_source` with a 201, its item shape matching a read."""
    as_user(environment, "owner")
    real = environment.client.post(LIST_PATH, json=smb_payload())
    status, payload = drive_fixture(new_fixture(), "POST", LIST_PATH, body=smb_payload())

    assert (status, real.status_code) == (201, 201)
    real_payload = real.get_json()
    assert_no_invented_keys("create", payload, real_payload)
    assert_shared_keys("create", payload, real_payload, {"file_source"})
    assert_nested_parity("create item", payload["file_source"], real_payload["file_source"], SOURCE_ITEM_UI_KEYS)


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
        "expected_config_revision": fixture._file_source_config_revision(GROUP, EDITABLE_SOURCE_ID),
        "name": "Renamed share",
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("update", payload, real_payload)
    assert_shared_keys("update", payload, real_payload, {"file_source"})
    assert_nested_parity("update item", payload["file_source"], real_payload["file_source"], SOURCE_ITEM_UI_KEYS)


# --------------------------------------------------------------------------
# Conflict codes on write: config_conflict and write_conflict.
# --------------------------------------------------------------------------

def test_config_conflict_shape_parity(environment):
    """A stale revision on PATCH returns `{error, error_code: "config_conflict"}` from both."""
    source = create_source(environment)
    as_user(environment, "owner")
    real = environment.client.patch(
        real_item_path(source["id"]),
        json={"expected_config_revision": "stale-revision", "name": "Renamed"},
    )
    fixture = new_fixture()
    fixture.touch_file_source(GROUP, EDITABLE_SOURCE_ID)
    status, payload = drive_fixture(fixture, "PATCH", fixture_item_path(), body={
        "expected_config_revision": "stale-revision",
        "name": "Renamed",
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("config_conflict", payload, real_payload)
    assert_shared_keys("config_conflict", payload, real_payload, {"error", "error_code"})
    assert_error_code("config_conflict", payload, real_payload, "config_conflict")


def test_write_conflict_shape_parity(environment):
    """A bare etag race whose config revision never moves exhausts the guard and returns
    `{error, error_code: "write_conflict"}` from both."""
    source = create_source(environment)
    key = (GROUP, source["id"])

    def bump_etag_only():
        # An engine write touches a non-editable field and bumps the etag, so the config revision is
        # unchanged (the conflict check passes) but the conditional replace still 412s. Landing one on
        # every attempt exhausts the guard into a write_conflict, never a config_conflict.
        record = environment.sources_container.records[key]
        record["last_run_status"] = "success"
        record["_etag"] = f'"etag-race-{environment.sources_container.records[key].get("_etag", "0")}"'

    attempts = environment.filesync.FILE_SYNC_WRITE_ATTEMPTS
    environment.sources_container.before_replace.extend(bump_etag_only for _ in range(attempts))
    as_user(environment, "owner")
    real = environment.client.patch(
        real_item_path(source["id"]),
        json={"expected_config_revision": source["config_revision"], "name": "Renamed"},
    )

    fixture = new_fixture()
    fixture.file_source_forced_write_conflict = "write_conflict"
    status, payload = drive_fixture(fixture, "PATCH", fixture_item_path(), body={
        "expected_config_revision": fixture._file_source_config_revision(GROUP, EDITABLE_SOURCE_ID),
        "name": "Renamed",
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("write_conflict", payload, real_payload)
    assert_shared_keys("write_conflict", payload, real_payload, {"error", "error_code"})
    assert_error_code("write_conflict", payload, real_payload, "write_conflict")


# --------------------------------------------------------------------------
# Delete: success, source_busy, delete_incomplete, and a partial refusal.
# --------------------------------------------------------------------------

def test_delete_success_shape_parity(environment):
    """A successful delete returns `{success, delete_result}` with the counts."""
    source = create_source(environment)
    seed_synced_document(environment, source["id"], "doc-1")
    as_user(environment, "owner")
    real = environment.client.delete(
        real_item_path(source["id"]),
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": True},
    )
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(), body={
        "expected_config_revision": fixture._file_source_config_revision(GROUP, EDITABLE_SOURCE_ID),
        "delete_associated_files": True,
    })

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("delete", payload, real_payload)
    assert_shared_keys("delete", payload, real_payload, {"success", "delete_result"})
    assert payload["success"] is True and real_payload["success"] is True
    assert_nested_parity(
        "delete_result", payload["delete_result"], real_payload["delete_result"],
        {"associated_files_requested", "documents_deleted", "documents_skipped", "documents_failed"},
    )


def test_delete_source_busy_shape_parity(environment):
    """A delete refused because a run is active returns `{error, error_code: "source_busy"}`."""
    source = create_source(environment)
    import uuid
    environment.runs_container.seed({
        "id": str(uuid.uuid4()), "source_id": source["id"], "scope_type": "group",
        "group_id": GROUP, "status": "running",
    })
    as_user(environment, "owner")
    real = environment.client.delete(
        real_item_path(source["id"]),
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    fixture = new_fixture()
    fixture.mark_file_source_running(GROUP, EDITABLE_SOURCE_ID)
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(), body={
        "expected_config_revision": fixture._file_source_config_revision(GROUP, EDITABLE_SOURCE_ID),
        "delete_associated_files": False,
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("source_busy", payload, real_payload)
    assert_shared_keys("source_busy", payload, real_payload, {"error", "error_code"})
    assert_error_code("source_busy", payload, real_payload, "source_busy")


def test_delete_incomplete_shape_parity(environment):
    """A delete that removed some documents but could not finish returns
    `{error, error_code: "delete_incomplete", partial, delete_result}`."""
    from unittest.mock import Mock
    source = create_source(environment)
    seed_synced_document(environment, source["id"], "doc-ok")
    seed_synced_document(environment, source["id"], "doc-bad")

    def maybe_fail(*_args, document_id=None, **_kwargs):
        if document_id == "doc-bad":
            raise RuntimeError("provider rejected the delete")

    environment.filesync.delete_document_revision = Mock(side_effect=maybe_fail)
    as_user(environment, "owner")
    real = environment.client.delete(
        real_item_path(source["id"]),
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": True},
    )

    fixture = new_fixture()
    # The browser suite scripts delete_incomplete through file_source_delete_plan with the reviewed
    # shape; pin that exact shape against the server's.
    fixture.file_source_delete_plan[(GROUP, EDITABLE_SOURCE_ID)] = {
        "status": 409,
        "payload": {
            "error": "The documents were removed, but the file source could not be deleted.",
            "error_code": "delete_incomplete",
            "partial": True,
            "delete_result": {
                "associated_files_requested": True,
                "documents_deleted": 1, "documents_skipped": 0, "documents_failed": 1,
            },
        },
    }
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(), body={
        "expected_config_revision": fixture._file_source_config_revision(GROUP, EDITABLE_SOURCE_ID),
        "delete_associated_files": True,
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("delete_incomplete", payload, real_payload)
    assert_shared_keys("delete_incomplete", payload, real_payload, {"error", "error_code", "partial", "delete_result"})
    assert_error_code("delete_incomplete", payload, real_payload, "delete_incomplete")
    assert payload["partial"] is True and real_payload["partial"] is True
    assert_nested_parity(
        "delete_incomplete result", payload["delete_result"], real_payload["delete_result"],
        {"documents_deleted", "documents_failed"},
    )


def test_delete_partial_refusal_shape_parity(environment):
    """A refusal after the documents were removed carries `partial` and the counts alongside its
    conflict code, so the UI can say the documents WERE deleted."""
    source = create_source(environment)
    seed_synced_document(environment, source["id"], "doc-1")
    key = (GROUP, source["id"])

    def edit_underneath():
        record = environment.sources_container.records[key]
        record["name"] = "Renamed Mid Delete"
        record["_etag"] = '"etag-edited"'

    environment.sources_container.before_delete.append(edit_underneath)
    as_user(environment, "owner")
    real = environment.client.delete(
        real_item_path(source["id"]),
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": True},
    )

    fixture = new_fixture()
    fixture.file_source_delete_plan[(GROUP, EDITABLE_SOURCE_ID)] = {
        "status": 409,
        "payload": {
            "error": "The source's documents were deleted, but the source changed before it could be removed. "
                     "Reload it and try again.",
            "error_code": "config_conflict",
            "partial": True,
            "delete_result": {
                "associated_files_requested": True,
                "documents_deleted": 1, "documents_skipped": 0, "documents_failed": 0,
            },
        },
    }
    status, payload = drive_fixture(fixture, "DELETE", fixture_item_path(), body={
        "expected_config_revision": fixture._file_source_config_revision(GROUP, EDITABLE_SOURCE_ID),
        "delete_associated_files": True,
    })

    assert (status, real.status_code) == (409, 409)
    real_payload = real.get_json()
    assert_no_invented_keys("partial refusal", payload, real_payload)
    assert_shared_keys("partial refusal", payload, real_payload, {"error", "error_code", "partial", "delete_result"})
    assert_error_code("partial refusal", payload, real_payload, "config_conflict")
    assert payload["partial"] is True and real_payload["partial"] is True
    assert_nested_parity(
        "partial refusal result", payload["delete_result"], real_payload["delete_result"],
        {"documents_deleted"},
    )


# --------------------------------------------------------------------------
# Sync: 202 run, the busy 400 (no code) and the concurrent-limit 400, verbatim.
# --------------------------------------------------------------------------

def test_sync_queued_shape_parity(environment):
    """A queued sync returns `{run}` with a 202, its run shape matching the runs list."""
    source = create_source(environment)
    as_user(environment, "owner")
    real = environment.client.post(f"{real_item_path(source['id'])}/sync")
    fixture = new_fixture()
    status, payload = drive_fixture(fixture, "POST", f"{fixture_item_path()}/sync", body={})

    assert (status, real.status_code) == (202, 202)
    real_payload = real.get_json()
    assert_no_invented_keys("sync", payload, real_payload)
    assert_shared_keys("sync", payload, real_payload, {"run"})
    assert_nested_parity("sync run", payload["run"], real_payload["run"], RUN_ITEM_UI_KEYS)


def test_sync_busy_shape_parity(environment):
    """A sync while one is running is the reviewed 400 with no error_code, shown verbatim."""
    import uuid
    source = create_source(environment)
    environment.runs_container.seed({
        "id": str(uuid.uuid4()), "source_id": source["id"], "scope_type": "group",
        "group_id": GROUP, "status": "running",
    })
    as_user(environment, "owner")
    real = environment.client.post(f"{real_item_path(source['id'])}/sync")
    fixture = new_fixture()
    fixture.mark_file_source_running(GROUP, EDITABLE_SOURCE_ID)
    status, payload = drive_fixture(fixture, "POST", f"{fixture_item_path()}/sync", body={})

    assert (status, real.status_code) == (400, 400)
    real_payload = real.get_json()
    assert_no_invented_keys("sync busy", payload, real_payload)
    assert_shared_keys("sync busy", payload, real_payload, {"error"})
    assert_error_code("sync busy", payload, real_payload, None)
    # A reviewed refusal the UI renders verbatim, so its copy must not drift from the server's.
    assert payload["error"] == real_payload["error"] == "This source already has a queued or running sync."


def test_sync_concurrent_limit_shape_parity(environment, monkeypatch):
    """Reaching the concurrent-run limit is the reviewed 400 with no error_code, shown verbatim."""
    source = create_source(environment)
    monkeypatch.setattr(environment.filesync, "_count_active_runs", lambda *a, **k: 9999)
    as_user(environment, "owner")
    real = environment.client.post(f"{real_item_path(source['id'])}/sync")
    fixture = new_fixture()
    fixture.file_source_sync_limit_reached.add((GROUP, EDITABLE_SOURCE_ID))
    status, payload = drive_fixture(fixture, "POST", f"{fixture_item_path()}/sync", body={})

    assert (status, real.status_code) == (400, 400)
    real_payload = real.get_json()
    assert_no_invented_keys("sync limit", payload, real_payload)
    assert_shared_keys("sync limit", payload, real_payload, {"error"})
    assert_error_code("sync limit", payload, real_payload, None)
    assert payload["error"] == real_payload["error"] == (
        "The File Sync concurrent run limit has been reached. Try again later."
    )


# --------------------------------------------------------------------------
# Runs: the real run record.
# --------------------------------------------------------------------------

def test_runs_list_shape_parity(environment):
    """The runs list returns `{runs}` and each run carries the keys the history reads."""
    source = create_source(environment)
    as_user(environment, "owner")
    # A queued run through the real route persists a full engine run record, so the runs list shape
    # is the engine's own, not a hand-written stub.
    environment.client.post(f"{real_item_path(source['id'])}/sync")
    real = environment.client.get(f"{real_item_path(source['id'])}/runs")
    status, payload = drive_fixture(new_fixture(), "GET", f"{fixture_item_path()}/runs")

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("runs", payload, real_payload)
    assert_shared_keys("runs", payload, real_payload, {"runs"})
    assert_nested_parity("run record", payload["runs"][0], real_payload["runs"][0], RUN_ITEM_UI_KEYS)


# --------------------------------------------------------------------------
# Test connection and browse, saved and unsaved.
# --------------------------------------------------------------------------

def test_saved_test_connection_shape_parity(environment, monkeypatch):
    """A saved connection test returns `{connection}` with the counts, from a genuine engine run."""
    source = create_source(environment)
    install_fake_smb(environment, monkeypatch)
    as_user(environment, "owner")
    real = environment.client.post(
        f"{real_item_path(source['id'])}/test-connection",
        json={"source_type": "smb"},
    )
    status, payload = drive_fixture(new_fixture(), "POST", f"{fixture_item_path()}/test-connection",
                                    body={"source_type": "smb"})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("test-connection", payload, real_payload)
    assert_shared_keys("test-connection", payload, real_payload, {"connection"})
    assert_nested_parity("connection", payload["connection"], real_payload["connection"], CONNECTION_UI_KEYS)
    assert payload["connection"]["success"] is True and real_payload["connection"]["success"] is True


def test_unsaved_test_connection_shape_parity(environment, monkeypatch):
    """An unsaved connection test over a full payload returns the same `{connection}` shape."""
    create_source(environment)
    install_fake_smb(environment, monkeypatch)
    as_user(environment, "owner")
    real = environment.client.post(f"{LIST_PATH}/test-connection", json=smb_payload())
    status, payload = drive_fixture(new_fixture(), "POST", f"{LIST_PATH}/test-connection", body=smb_payload())

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("unsaved test-connection", payload, real_payload)
    assert_shared_keys("unsaved test-connection", payload, real_payload, {"connection"})
    assert_nested_parity("unsaved connection", payload["connection"], real_payload["connection"], CONNECTION_UI_KEYS)


def test_test_connection_failure_shape_parity(environment, monkeypatch):
    """A failed connection test is an HTTP 400 with `{error}` and no error_code from both."""
    source = create_source(environment)
    install_fake_smb(environment, monkeypatch, broken=True)
    as_user(environment, "owner")
    real = environment.client.post(
        f"{real_item_path(source['id'])}/test-connection",
        json={"source_type": "smb"},
    )
    fixture = new_fixture()
    fixture.file_source_test_failure = "SMB connection test failed. Verify the UNC path and credentials."
    status, payload = drive_fixture(fixture, "POST", f"{fixture_item_path()}/test-connection",
                                    body={"source_type": "smb"})

    assert (status, real.status_code) == (400, 400)
    real_payload = real.get_json()
    assert_no_invented_keys("test failure", payload, real_payload)
    assert_shared_keys("test failure", payload, real_payload, {"error"})
    assert_error_code("test failure", payload, real_payload, None)


def test_saved_browse_shape_parity(environment, monkeypatch):
    """A saved browse returns `{browse}` and each entry carries `type`, never `is_dir`."""
    source = create_source(environment)
    install_fake_smb(environment, monkeypatch)
    as_user(environment, "owner")
    real = environment.client.post(
        f"{real_item_path(source['id'])}/browse",
        json={"browse_path": ""},
    )
    status, payload = drive_fixture(new_fixture(), "POST", f"{fixture_item_path()}/browse",
                                    body={"browse_path": ""})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("browse", payload, real_payload)
    assert_shared_keys("browse", payload, real_payload, {"browse"})
    assert_no_invented_keys("browse body", payload["browse"], real_payload["browse"])
    assert_shared_keys("browse body", payload["browse"], real_payload["browse"], {"path", "source_type", "entries"})
    folder = next(e for e in payload["browse"]["entries"] if e["type"] == "folder")
    real_folder = next(e for e in real_payload["browse"]["entries"] if e["type"] == "folder")
    assert_nested_parity("browse folder entry", folder, real_folder, ENTRY_UI_KEYS)
    file_entry = next(e for e in payload["browse"]["entries"] if e["type"] == "file")
    real_file = next(e for e in real_payload["browse"]["entries"] if e["type"] == "file")
    assert_nested_parity("browse file entry", file_entry, real_file, ENTRY_UI_KEYS)


def test_unsaved_browse_shape_parity(environment, monkeypatch):
    """An unsaved browse over a full payload returns the same `{browse}` entry shape."""
    create_source(environment)
    install_fake_smb(environment, monkeypatch)
    as_user(environment, "owner")
    payload_body = dict(smb_payload(), browse_path="")
    real = environment.client.post(f"{LIST_PATH}/browse", json=payload_body)
    status, payload = drive_fixture(new_fixture(), "POST", f"{LIST_PATH}/browse", body=payload_body)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("unsaved browse", payload, real_payload)
    assert_shared_keys("unsaved browse", payload, real_payload, {"browse"})
    entry = payload["browse"]["entries"][0]
    real_entry = real_payload["browse"]["entries"][0]
    assert_nested_parity("unsaved browse entry", entry, real_entry, ENTRY_UI_KEYS)


# --------------------------------------------------------------------------
# Ignore: the returned item record.
# --------------------------------------------------------------------------

def test_ignore_shape_parity(environment):
    """Ignoring a path returns `{item}`, the File Sync item record whose `ignored` flag the UI reads."""
    source = create_source(environment)
    as_user(environment, "owner")
    real = environment.client.post(
        f"{real_item_path(source['id'])}/ignore-path",
        json={"remote_path": f"{UNC_PATH}\\reports", "ignored": True},
    )
    status, payload = drive_fixture(new_fixture(), "POST", f"{fixture_item_path()}/ignore-path",
                                    body={"remote_path": f"{UNC_PATH}\\reports", "ignored": True})

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("ignore", payload, real_payload)
    assert_shared_keys("ignore", payload, real_payload, {"item"})
    assert_nested_parity("ignore item", payload["item"], real_payload["item"], IGNORE_ITEM_UI_KEYS)


# --------------------------------------------------------------------------
# Options.
# --------------------------------------------------------------------------

def test_options_shape_parity(environment):
    """The options envelope carries the same picker keys the editor reads."""
    create_source(environment)
    as_user(environment, "owner")
    real = environment.client.get(OPTIONS_PATH)
    status, payload = drive_fixture(new_fixture(), "GET", OPTIONS_PATH)

    assert (status, real.status_code) == (200, 200)
    real_payload = real.get_json()
    assert_no_invented_keys("options", payload, real_payload)
    assert_shared_keys("options", payload, real_payload, OPTIONS_UI_KEYS)


# --------------------------------------------------------------------------
# The four sync fields, by value: set, left out, and rewritten by the server.
# --------------------------------------------------------------------------

FIXTURE_UNC_PATH = "\\\\files.example.test\\reports"
SETTING_WRITE = {
    "selected_paths": ["Reports\\2024\\", "reports/2024", "Budget.xlsx", " Archive "],
    "filters": {"fixed_tags": ["Q1 Reports", "q1-reports", "Legal/Contracts", "!!"], "folder_tag_mode": " FULL_PATH "},
    "remote_delete_policy": "Hard_Delete",
}
SCENARIO_WRITES = {
    # Sets all four, each in a form the server normalizes.
    "set": dict(SETTING_WRITE),
    # Leaves all four out: both sides must keep what the first write stored.
    "omitted": {"filters": {"include_patterns": ["*.pdf"]}},
    # Values the server doesn't recognise: both sides must store its fallbacks.
    "unrecognised": {"filters": {"folder_tag_mode": "sideways"}, "remote_delete_policy": "shred"},
    # Clears the selection and the tags explicitly.
    "cleared": {"selected_paths": [], "filters": {"fixed_tags": []}},
}


def write_body(scenario_write, unc_path, revision):
    body = {"expected_config_revision": revision}
    if "selected_paths" in scenario_write:
        body["connection"] = {"unc_path": unc_path, "selected_paths": list(scenario_write["selected_paths"])}
    if "filters" in scenario_write:
        body["filters"] = dict(scenario_write["filters"])
    if "remote_delete_policy" in scenario_write:
        body["remote_delete_policy"] = scenario_write["remote_delete_policy"]
    return body


def sync_values(item):
    return {
        "selected_paths": item["connection"].get("selected_paths"),
        "fixed_tags": item["filters"].get("fixed_tags"),
        "folder_tag_mode": item["filters"].get("folder_tag_mode"),
        "include_patterns": item["filters"].get("include_patterns"),
        "remote_delete_policy": item.get("remote_delete_policy"),
    }


def real_patch(environment, source_id, scenario_write):
    revision = environment.client.get(real_item_path(source_id)).get_json()["file_source"]["config_revision"]
    return environment.client.patch(real_item_path(source_id), json=write_body(scenario_write, UNC_PATH, revision))


def fixture_patch(fixture, scenario_write):
    revision = fixture._file_source_config_revision(GROUP, EDITABLE_SOURCE_ID)
    return drive_fixture(fixture, "PATCH", fixture_item_path(),
                         body=write_body(scenario_write, FIXTURE_UNC_PATH, revision))


@pytest.mark.parametrize("scenario", sorted(SCENARIO_WRITES))
def test_sync_fields_store_the_same_values(environment, scenario):
    """After the same writes, both sides hold the same selected paths, tags, folder tag mode and
    remote delete policy -- set, left out, rewritten, or cleared."""
    source = create_source(environment)
    as_user(environment, "owner")
    fixture = new_fixture()
    writes = [SETTING_WRITE] if scenario == "set" else [SETTING_WRITE, SCENARIO_WRITES[scenario]]
    for step, scenario_write in enumerate(writes):
        real = real_patch(environment, source["id"], scenario_write)
        status, payload = fixture_patch(fixture, scenario_write)
        assert (status, real.status_code) == (200, 200), f"{scenario} step {step}: {payload} / {real.get_json()}"
        real_values = sync_values(real.get_json()["file_source"])
        fixture_values = sync_values(payload["file_source"])
        assert fixture_values == real_values, (
            f"{scenario} step {step}: the fixture stores {fixture_values}, the server {real_values}"
        )
    # The stored record behind the fixture's response agrees too, not just the projection.
    assert sync_values(fixture.record_file_source(GROUP, EDITABLE_SOURCE_ID)) == real_values


def test_a_new_source_stores_the_same_defaults(environment):
    """A create that sets none of the four stores the server's defaults on both sides."""
    as_user(environment, "owner")
    real = environment.client.post(LIST_PATH, json=smb_payload())
    status, payload = drive_fixture(new_fixture(), "POST", LIST_PATH, body=smb_payload())
    assert (status, real.status_code) == (201, 201)
    assert sync_values(payload["file_source"]) == sync_values(real.get_json()["file_source"])


def test_a_path_leaving_the_root_is_refused_the_same_way(environment):
    """A selected path with a `..` folder fails the whole write with the same 400 on both sides."""
    source = create_source(environment)
    as_user(environment, "owner")
    refused = {"selected_paths": ["reports/../secrets"]}
    real = real_patch(environment, source["id"], refused)
    status, payload = fixture_patch(new_fixture(), refused)
    assert (status, real.status_code) == (400, 400)
    assert payload == real.get_json()
    assert_error_code("selected path refusal", payload, real.get_json(), None)


# --------------------------------------------------------------------------
# Browse paths: relative to the source root on both sides.
# --------------------------------------------------------------------------

class _TreeSmbClient:
    """A fake SMB session over the fixture's own browse tree, so both sides list the same items and
    only their path semantics are compared."""

    def scandir(self, path):
        root = UNC_PATH.rstrip("\\")
        if path.lower() == root.lower():
            relative = ""
        elif path.lower().startswith(root.lower() + "\\"):
            relative = path[len(root) + 1:].replace("\\", "/")
        else:
            raise FileNotFoundError(path)
        children = FILE_SOURCE_BROWSE_TREE.get(relative)
        if children is None:
            raise FileNotFoundError(path)
        return [_FakeDirEntry(name, kind == "folder") for name, kind in children]


def browse_entries(payload):
    return [
        {key: entry[key] for key in ("name", "path", "type")}
        for entry in payload["browse"]["entries"]
    ]


@pytest.mark.parametrize("browse_path", ["", "reports", "reports/2024", "/reports/", "reports\\2024"])
def test_browse_lists_the_same_items_under_the_root(environment, monkeypatch, browse_path):
    """A browse path is relative to the root on both sides: each lists the same children, with
    entry paths relative to the root that open their folder when sent back."""
    source = create_source(environment)
    monkeypatch.setattr(environment.filesync, "_register_smb_session", lambda _source: _TreeSmbClient())
    as_user(environment, "owner")
    real = environment.client.post(f"{real_item_path(source['id'])}/browse", json={"browse_path": browse_path})
    status, payload = drive_fixture(new_fixture(), "POST", f"{fixture_item_path()}/browse",
                                    body={"browse_path": browse_path})
    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert payload["browse"]["path"] == real_payload["browse"]["path"]
    assert browse_entries(payload) == browse_entries(real_payload)


@pytest.mark.parametrize("browse_path,expected_status", [
    (UNC_PATH, 500),            # the root's own path, which V2 once sent: resolved under the root
    ("missing", 500),
    ("reports/2025", 500),
    ("../x", 400),
    ("reports/../x", 400),
])
def test_browse_refuses_a_path_not_under_the_root_the_same_way(environment, monkeypatch, browse_path, expected_status):
    """The root's own path, a missing folder and a path leaving the root fail with the same status and
    message on both sides, so a client that browses the wrong path fails in the browser suite."""
    source = create_source(environment)
    monkeypatch.setattr(environment.filesync, "_register_smb_session", lambda _source: _TreeSmbClient())
    as_user(environment, "owner")
    real = environment.client.post(f"{real_item_path(source['id'])}/browse", json={"browse_path": browse_path})
    # The fixture's root is its own share; its UNC path is just as foreign to the tree.
    fixture_path = FIXTURE_UNC_PATH if browse_path == UNC_PATH else browse_path
    status, payload = drive_fixture(new_fixture(), "POST", f"{fixture_item_path()}/browse",
                                    body={"browse_path": fixture_path})
    assert (status, real.status_code) == (expected_status, expected_status), real.get_json()
    assert payload == real.get_json()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
