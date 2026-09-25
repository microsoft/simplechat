# test_group_document_fixture_parity.py
"""
Per-route shape parity between the M2 group document UI fixtures and the real routes.
Version: 0.261.168
Implemented in: 0.261.161
A tag vocabulary conflict is pinned from the etag pre-check and from a lost patch: 0.261.166
A bulk tagging batch or metadata save that meets it is refused whole, with no document written: 0.261.168

The V2 group Documents explorer mocks the network with three closed HTTP fixtures, which predate
the per-route parity rule:

- ``ui_tests/fixtures/group_documents.py`` serves the M2A reads (list, facets, tags, detail and
  versions) from rows it computes;
- ``ui_tests/fixtures/group_document_management.py`` answers every M2B management request with a
  response the browser test scripts through its receipt builders, and serves an Owner's rows and
  the group's tag list;
- ``ui_tests/fixtures/group_document_collaboration.py`` serves the M2C review state and recipient
  directory it computes, and answers each sharing and publication decision with a scripted receipt.

A fixture whose shape drifts from the server lets a passing browser suite hide a real regression,
so this test backfills the pin. For every route the explorer's read adapter
(``lib/documentReadAdapter.ts``), operations (``lib/documentOperations.ts``) and collaboration
(``lib/documentCollaboration.ts``) call, it asserts that the fixture never invents a key the server
does not return (``fixture keys <= server keys``) at the top level, per document, and in every
nested object the explorer reads, that the keys the explorer reads are present on both sides, and
that the status and the machine-readable code match. A management receipt is compared whole: the
builder a browser test scripts must equal the real route's response to the same request, and it
is served through the fixture's own ``_dispatch``, which validates the request as it would the
browser's. A document route carries a coded failure's machine code in ``error`` and its sentence in
``message``; any other refusal carries its sentence in ``error``, and a tag vocabulary conflict
also names its code in ``error_code``.

The real routes run through the family API suites' harnesses: ``test_group_document_read_apis.py``
for the reads (the real read, access, projection, screening and route modules),
``test_group_document_management.py`` for the operations (with the real File Sync delete guard),
and ``test_group_document_collaboration.py`` and ``test_group_document_publication.py`` for sharing
and publication. The stored documents are the fixture's own rows, translated into the shape the
server stores (a share becomes a ``shared_group_ids`` entry, a screening summary becomes a stored
marker whose scan the server can read), so each projection is compared with the server's
projection of the same document.

Three findings this backfill pinned as strict xfails in
``ui_tests/test_v2_group_document_management.py`` were fixed in 0.261.164 and are plain pins there
now: a coded failure's dialog showed its machine code, the conversation guard never named the
conversation, and a multi-document download was saved as ``documents.zip`` whatever the server
named it.
"""

import ast
import json
import sys
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN  # noqa: E402
from ui_tests.fixtures.group_workspace import group_context  # noqa: E402
from ui_tests.fixtures.group_documents import (  # noqa: E402
    GROUP_DOCUMENT_NOT_FOUND_ERROR, GROUP_DOCUMENTS_STATUS_ERROR, GroupDocumentsFixture,
)
from ui_tests.fixtures.group_document_management import (  # noqa: E402
    DOCUMENT_CHANGED_ERROR, GROUP_ARCHIVE_NAME, GroupDocumentManagementFixture, TAG_REVISION_CHANGED_ERROR,
    attachment, batch_error, bulk_tag_result, conversation_delete_guard, delete_result, metadata_result,
    operation_path, propagation_incomplete, queue_result, synced_delete_guard, tag_created, tag_result,
    tag_vocabulary_conflict, tag_vocabulary_refusal, upload_refusal, upload_result,
)
from ui_tests.fixtures.group_document_collaboration import (  # noqa: E402
    COLLABORATION_DENIED, COLLABORATION_GONE, COLLABORATION_STATUS_REFUSED, FAILED_HANDOFF_ERRORS,
    GroupDocumentCollaborationFixture, STATE_CONFLICT, collaboration_path, collaboration_receipt, effect_error,
)

import test_group_document_collaboration as collaboration_suite  # noqa: E402
import test_group_document_publication as publication_suite  # noqa: E402
from test_group_document_read_apis import document, environment, get  # noqa: E402,F401  (environment is a pytest fixture)
from test_group_document_management import StoreFailure, lose_the_vocabulary_patch, management  # noqa: E402,F401  (management is a pytest fixture)
from test_group_document_collaboration import sharing  # noqa: E402,F401  (sharing is a pytest fixture)
from test_group_document_publication import publication, publication_modules  # noqa: E402,F401  (pytest fixtures)
from test_support.agent_delegation import APP_ROOT, execute_functions  # noqa: E402


GROUP_A = "group-a"
ORIGIN_GROUP = "origin"
MEMBER = "reader"

# Keys only a read projection computes, so a stored document never carries them.
READ_PROJECTION_KEYS = {
    "owner_group_id", "owner_group_name", "shared_group_active_id", "shared_approval_status",
    "document_actions", "document_collaboration_actions", "enhanced_citations",
}
# Content a restricted (pending or held) row withholds; the stored document still has it.
WITHHELD_CONTENT = {
    "title": "Restricted title", "abstract": "Restricted abstract.", "authors": ["Restricted author"],
    "tags": ["restricted"], "document_classification": "Internal", "status": "Processing complete",
}

# The keys the explorer reads off every row: identity and the scope check, the status and
# progress columns, the revision fields, the relationship, and the per-row action gates.
ROW_UI_KEYS = {
    "id", "document_id", "group_id", "file_name", "status", "percentage_complete", "upload_date",
    "version", "revision_family_id", "is_current_version", "shared_approval_status", "owner_group_id",
    "document_actions", "document_collaboration_actions",
}
# A row the viewer may read in full also shows its metadata columns.
CONTENT_UI_KEYS = {"title", "tags", "document_classification", "file_size"}
# A row shared into the group names its source.
SHARE_UI_KEYS = {"shared_group_active_id", "owner_group_name"}
LIST_UI_KEYS = {"documents", "total_count", "page", "page_size"}
FACET_UI_KEYS = {"total", "untagged", "processing", "errors", "recent", "shared_with_me", "by_tag", "by_classification"}
TAG_UI_KEYS = {"name", "count", "color"}
VERSIONS_UI_KEYS = {"document_id", "group_id", "versions"}


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
        self.method = "GET"
        self.headers = {}
        self.post_data_buffer = None


class _FakeRoute:
    def __init__(self, url):
        self.request = _FakeRequest(url)
        self.status = 200
        self.payload = None
        self.headers = {}
        self.content_type = None

    def fulfill(self, status=200, json=None, body=None, headers=None, content_type=None, **kwargs):
        self.status = status
        self.payload = json if body is None else body
        self.headers = dict(headers or {})
        self.content_type = content_type


def drive_route(fixture, method, path, body=None, query=None):
    """Dispatch one request through the fixture exactly as its Playwright route handler would, and
    return the fulfilled route."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}")
    route.request.method = method
    fixture._dispatch(route, entry)
    return route


def drive_fixture(fixture, method, path, body=None, query=None):
    """The fulfilled (status, payload) of one request dispatched through the fixture."""
    route = drive_route(fixture, method, path, body=body, query=query)
    return route.status, route.payload


# --------------------------------------------------------------------------
# Parity assertions, mirroring the file source and endpoint parity tests.
# --------------------------------------------------------------------------

def assert_no_invented_keys(scenario, fixture_payload, real_payload):
    invented = set(fixture_payload) - set(real_payload)
    assert not invented, (
        f"{scenario}: the fixture returns keys the server never does: {sorted(invented)} "
        f"(server keys {sorted(real_payload)})"
    )


def assert_shared_keys(scenario, fixture_payload, real_payload, required):
    for key in required:
        assert key in real_payload, f"{scenario}: the server no longer returns {key!r}; the harness or contract drifted"
        assert key in fixture_payload, f"{scenario}: the fixture dropped {key!r}, which the UI reads"


def assert_nested_parity(scenario, fixture_obj, real_obj, ui_keys):
    assert_no_invented_keys(scenario, fixture_obj, real_obj)
    assert_shared_keys(scenario, fixture_obj, real_obj, ui_keys)


def by_id(rows):
    return {row["id"]: row for row in rows}


# --------------------------------------------------------------------------
# M2A reads: seed the real store from the read fixture's rows.
# --------------------------------------------------------------------------

def stored_document(row):
    """The stored document behind one projected fixture row."""
    stored = {key: deepcopy(value) for key, value in row.items() if key not in READ_PROJECTION_KEYS}
    for key, value in WITHHELD_CONTENT.items():
        stored.setdefault(key, deepcopy(value))
    if row.get("shared_group_active_id"):
        stored["shared_group_ids"] = [f"{row['shared_group_active_id']},{row['shared_approval_status']}"]
    else:
        stored["shared_group_ids"] = []
    screening = row.get("content_screening")
    if screening:
        stored["content_screening"] = {
            "state": screening["state"], "scan_id": f"scan-{row['id']}", "source_revision": str(row["version"]),
        }
    stored.update({"_etag": f"etag-{row['id']}", "user_id": "uploader"})
    stored.setdefault("keywords", [])
    return stored


def new_read_fixture():
    return GroupDocumentsFixture(_FakePage())


@pytest.fixture
def reads(environment):  # noqa: F811 - the imported harness fixture
    """The read harness holding the read fixture's group-a documents, versions and origin group."""
    env = environment
    fixture = new_read_fixture()
    env.groups[ORIGIN_GROUP] = {
        **deepcopy(env.groups["source-group"]), "id": ORIGIN_GROUP, "_etag": f"etag-{ORIGIN_GROUP}",
        "name": "Publishing group", "users": [],
    }
    env.source.records.clear()
    for row in fixture.documents[GROUP_A]:
        env.source.records[row["id"]] = stored_document(row)
    for rows in fixture.versions.values():
        for row in rows:
            env.source.records.setdefault(row["id"], stored_document(row))
    with env.client.session_transaction() as state:
        state["user"] = {"oid": MEMBER, "roles": ["User"]}
    env.fixture = fixture
    return env


def fixture_read(fixture, path, **query):
    return drive_fixture(fixture, "GET", path, query={"group_id": [GROUP_A], **{key: [value] for key, value in query.items()}})


def row_ui_keys(row):
    keys = set(ROW_UI_KEYS)
    if row.get("shared_approval_status") in ("approved", "owner") and not row.get("content_screening"):
        keys |= CONTENT_UI_KEYS
    if row.get("shared_approval_status") != "owner":
        keys |= SHARE_UI_KEYS
    if row.get("content_screening"):
        keys.add("content_screening")
    return keys


RELATIONSHIP_FIELDS = (
    "group_id", "owner_group_id", "shared_approval_status", "shared_group_active_id", "owner_group_name",
    "status",
)
# The explorer only asks whether a row allows an operation, so these compare as sets.
ACTION_FIELDS = ("document_actions", "document_collaboration_actions")


def assert_row_parity(scenario, served, stored):
    assert_nested_parity(scenario, served, stored, row_ui_keys(stored))
    for key in RELATIONSHIP_FIELDS:
        assert served.get(key) == stored.get(key), f"{scenario}: {key} fixture {served.get(key)!r}, server {stored.get(key)!r}"
    for key in ACTION_FIELDS:
        assert sorted(served[key]) == sorted(stored[key]), f"{scenario}: {key} fixture {served[key]!r}, server {stored[key]!r}"
    if "content_screening" in stored:
        assert_nested_parity(f"{scenario} screening", served["content_screening"], stored["content_screening"], {"state"})
    if "tags" in stored:
        assert served["tags"] == stored["tags"], f"{scenario}: the server stores normalized tags"


def test_read_list_shape_parity(reads):
    """The list envelope and every relationship: owned, shared, pending, held, held share,
    processing, failed, and one of the bulk rows."""
    real = get(reads, page_size=100)
    status, payload = fixture_read(reads.fixture, "/api/group_documents", page_size="100")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_no_invented_keys("list", payload, real_payload)
    assert_shared_keys("list", payload, real_payload, LIST_UI_KEYS)
    assert payload["total_count"] == real_payload["total_count"]
    served, stored = by_id(payload["documents"]), by_id(real_payload["documents"])
    assert set(served) == set(stored)
    for document_id in (
        "same-document", "shared-report", "pending-report", "held-report", "held-share",
        "processing-report", "failed-report", "team-01",
    ):
        assert_row_parity(f"list row {document_id}", served[document_id], stored[document_id])


@pytest.mark.parametrize("document_id", [
    "same-document", "shared-report", "pending-report", "held-report", "held-share",
])
def test_read_detail_shape_parity(reads, document_id):
    """A document's detail is its list row, from both."""
    real = get(reads, f"/api/group_documents/{document_id}")
    status, payload = fixture_read(reads.fixture, f"/api/group_documents/{document_id}")

    assert (status, real.status_code) == (200, 200), real.get_json()
    assert_row_parity(f"detail {document_id}", payload, real.get_json())


@pytest.mark.parametrize("document_id", ["same-document", "shared-report"])
def test_read_versions_shape_parity(reads, document_id):
    """The version history names the document and group, and each revision is a row."""
    real = get(reads, f"/api/group_documents/{document_id}/versions")
    status, payload = fixture_read(reads.fixture, f"/api/group_documents/{document_id}/versions")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_no_invented_keys("versions", payload, real_payload)
    assert_shared_keys("versions", payload, real_payload, VERSIONS_UI_KEYS)
    served, stored = by_id(payload["versions"]), by_id(real_payload["versions"])
    assert set(served) == set(stored)
    for version_id, row in served.items():
        assert_row_parity(f"version {version_id}", row, stored[version_id])


def test_read_facets_shape_parity(reads):
    real = get(reads, "/api/group_documents/facets")
    status, payload = fixture_read(reads.fixture, "/api/group_documents/facets")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_nested_parity("facets", payload, real_payload, FACET_UI_KEYS)
    assert payload["by_tag"] == real_payload["by_tag"]


def test_read_tags_shape_parity(reads):
    real = get(reads, "/api/group_documents/tags")
    status, payload = fixture_read(reads.fixture, "/api/group_documents/tags")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_no_invented_keys("tags", payload, real_payload)
    assert_shared_keys("tags", payload, real_payload, {"tags"})
    served, stored = {tag["name"]: tag for tag in payload["tags"]}, {tag["name"]: tag for tag in real_payload["tags"]}
    for name, tag in served.items():
        assert name in stored, f"tag {name!r}: the server lists {sorted(stored)}"
        assert_nested_parity(f"tag {name}", tag, stored[name], TAG_UI_KEYS)
        assert tag["count"] == stored[name]["count"], name


def test_read_unknown_document_shape_parity(reads):
    real = get(reads, "/api/group_documents/missing-document")
    status, payload = fixture_read(reads.fixture, "/api/group_documents/missing-document")

    assert (status, real.status_code) == (404, 404)
    real_payload = real.get_json()
    assert_no_invented_keys("unknown document", payload, real_payload)
    assert payload["error"] == real_payload["error"]


READ_ROUTES = (
    "/api/group_documents", "/api/group_documents/facets", "/api/group_documents/tags",
    "/api/group_documents/same-document", "/api/group_documents/same-document/versions",
)


@pytest.mark.parametrize("path", READ_ROUTES)
def test_read_non_member_shape_parity(reads, path):
    with reads.client.session_transaction() as state:
        state["user"] = {"oid": "stranger", "roles": ["User"]}
    real = get(reads, path)
    fixture = reads.fixture
    fixture.denied_groups.add(GROUP_A)
    status, payload = fixture_read(fixture, path)

    assert (status, real.status_code) == (403, 403)
    real_payload = real.get_json()
    assert_no_invented_keys("non-member", payload, real_payload)
    assert payload["error"] == real_payload["error"]


@pytest.mark.parametrize("path", READ_ROUTES)
def test_read_status_refusal_shape_parity(reads, path):
    """A status that bars reading refuses a member's every read with the status as the reason."""
    reads.groups[GROUP_A]["status"] = "inactive"
    real = get(reads, path)
    fixture = reads.fixture
    fixture.groups[GROUP_A] = group_context(
        GROUP_A, fixture.groups[GROUP_A]["workspace"]["name"], role="User", status="inactive",
        enable_extract_meta_data=True,
    )
    status, payload = fixture_read(fixture, path)

    assert (status, real.status_code) == (403, 403)
    real_payload = real.get_json()
    assert_no_invented_keys("inactive group", payload, real_payload)
    assert payload["error"] == real_payload["error"] == GROUP_DOCUMENTS_STATUS_ERROR


# --------------------------------------------------------------------------
# M2B management: every receipt builder, scripted and served exactly as a browser test does it,
# against the real route's response to the same request.
# --------------------------------------------------------------------------

MANAGEMENT_ROOT = "/api/groups/group-a/documents"
FILE_SYNC = {
    "source_id": "source-1", "source_name": "Research library",
    "remote_path": "/library/teams/research.pdf", "relative_path": "teams/research.pdf",
}
TAG_DEFINITIONS = {"unused": {"color": "#123456"}, "reference": {"color": "#8b5cf6"}}


def new_management_fixture():
    return GroupDocumentManagementFixture(_FakePage())


def fixture_receipt(fixture, method, resource, *, response, status=200, body=None, query=None):
    """Script one reply as a browser test does, send the same request through the fixture's
    `_dispatch` (which validates it as it would the browser's), and return what it fulfils."""
    fixture.queue_operation(method, resource, response=response, status=status, body=body, query=query)
    return drive_fixture(fixture, method, operation_path(resource), body=body, query=query)


def assert_receipt_parity(scenario, fixture_result, real):
    status, payload = fixture_result
    real_payload = real.get_json()
    assert status == real.status_code, f"{scenario}: fixture status {status}, server {real.status_code}: {real_payload}"
    assert_no_invented_keys(scenario, payload, real_payload)
    assert payload == real_payload, f"{scenario}:\n fixture {payload!r}\n server  {real_payload!r}"


def add_document(env, identifier, **changes):
    """A group-a document with a stored source, as the management harness seeds its own."""
    record = document(identifier, **changes)
    record.update(blob_container="group-documents", blob_path=f"{record['group_id']}/{record['file_name']}")
    env.source.records[identifier] = record
    env.blobs.put(record["blob_path"])
    return record


def fail_queue_for(env, predicate):
    """The job queue refuses the jobs `predicate` picks and accepts every other."""
    submit = env.queue.submit_stored

    def submit_stored(key, function, **kwargs):
        if predicate(key, kwargs):
            raise StoreFailure()
        return submit(key, function, **kwargs)

    env.queue.submit_stored = submit_stored


def real_synced_delete_guard(file_sync):
    """The real File Sync delete guard. Its two reads answer with the document's stored File Sync
    metadata and a source that still exists, which is when it asks for confirmation."""
    text = (APP_ROOT / "functions_file_sync.py").read_text(encoding="utf-8")
    actions = next(
        ast.literal_eval(node.value) for node in ast.parse(text).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "FILE_SYNC_DELETE_ACTIONS" for target in node.targets)
    )
    namespace = {
        "Any": Any, "Dict": Dict, "Optional": Optional, "FILE_SYNC_DELETE_ACTIONS": actions,
        "get_document_metadata": lambda **_kwargs: {"file_sync": deepcopy(file_sync)},
        "_read_file_sync_source_for_document_action": lambda *_args: {"id": file_sync["source_id"]},
    }
    execute_functions("functions_file_sync.py", {"build_synced_document_delete_guard"}, namespace)
    return namespace["build_synced_document_delete_guard"]


@pytest.mark.parametrize("scenario", ["updated", "queued", "propagation_incomplete"])
def test_metadata_receipt_parity(management, scenario):
    """A saved change names its fields in request order; a screened document's change is queued
    (202); a change whose projections failed after the document saved is a coded 500."""
    env = management
    body = {"title": "Changed title", "keywords": ["alpha", "beta"]}
    expected, status = metadata_result("document-a", body), 200
    if scenario == "queued":
        env.settings["enable_content_screening"] = True
        env.seed_release(env.source.records["document-a"])
        body = {"abstract": "Updated abstract"}
        expected, status = metadata_result("document-a", body, queued=True), 202
    elif scenario == "propagation_incomplete":
        def fail_chunk(**_kwargs):
            raise StoreFailure()

        env.document_helpers["update_chunk_metadata"] = fail_chunk
        expected, status = propagation_incomplete("document-a"), 500
    # The server names fields in the order the body sends them; Flask's test client would sort a
    # `json=` body's keys, so this one is sent exactly as written, as the browser sends its own.
    real = env.client.patch(
        f"{MANAGEMENT_ROOT}/document-a", data=json.dumps(body), content_type="application/json",
    )
    served = fixture_receipt(
        new_management_fixture(), "PATCH", "document-a", response=expected, status=status, body=body,
    )
    assert_receipt_parity(f"metadata {scenario}", served, real)


@pytest.mark.parametrize("mode, with_older, removed, promoted", [
    ("current_only", False, ["document-a"], None),
    ("current_only", True, ["document-a"], "older"),
    ("all_versions", True, ["document-a", "older"], None),
])
def test_single_delete_receipt_parity(management, mode, with_older, removed, promoted):
    """A single delete names the revisions it removed and the one it promoted, if any."""
    env = management
    if with_older:
        env.source.records["older"] = document(
            "older", revision_family_id="document-a", version=0, is_current_version=False,
            file_name="document-a.pdf",
        )
    real = env.client.delete(f"{MANAGEMENT_ROOT}/document-a?delete_mode={mode}")
    expected = delete_result(
        "document-a", deleted_mode=mode, deleted_document_ids=removed, promoted_document_id=promoted,
    )
    served = fixture_receipt(
        new_management_fixture(), "DELETE", "document-a", response=expected, query={"delete_mode": [mode]},
    )
    assert_receipt_parity(f"delete {mode}", served, real)


@pytest.mark.parametrize("missing", [False, True])
def test_bulk_delete_receipt_parity(management, missing):
    """A bulk delete counts what it deleted and refused, and says nothing else."""
    env = management
    body = {
        "document_ids": ["document-a", *(["missing"] if missing else [])],
        "delete_mode": "all_versions", "conversation_linked_delete_confirmed": False,
    }
    real = env.client.post(f"{MANAGEMENT_ROOT}/bulk-delete", json=body)
    errors = [batch_error("missing", GROUP_DOCUMENT_NOT_FOUND_ERROR)] if missing else []
    served = fixture_receipt(
        new_management_fixture(), "POST", "bulk-delete", response=delete_result("document-a", errors=errors),
        status=207 if missing else 200, body=body,
    )
    assert_receipt_parity(f"bulk delete missing={missing}", served, real)


@pytest.mark.parametrize("route", ["single", "bulk"])
def test_conversation_delete_guard_parity(management, route):
    """A document uploaded in a conversation asks for confirmation, alone or within a batch."""
    env = management
    env.source.records["document-a"].update(
        created_from_chat_upload=True, conversation_id="conversation-a", conversation_title_at_upload="Planning review",
    )
    guard = conversation_delete_guard(
        "document-a", "conversation-a", title="Planning review", file_name="document-a.pdf",
    )
    fixture = new_management_fixture()
    if route == "single":
        real = env.client.delete(f"{MANAGEMENT_ROOT}/document-a?delete_mode=all_versions")
        served = fixture_receipt(
            fixture, "DELETE", "document-a", response=guard, status=409, query={"delete_mode": ["all_versions"]},
        )
    else:
        add_document(env, "document-c")
        body = {
            "document_ids": ["document-c", "document-a"], "delete_mode": "all_versions",
            "conversation_linked_delete_confirmed": False,
        }
        real = env.client.post(f"{MANAGEMENT_ROOT}/bulk-delete", json=body)
        served = fixture_receipt(
            fixture, "POST", "bulk-delete", response=delete_result("document-c", errors=[guard]), status=207, body=body,
        )
    assert_receipt_parity(f"conversation guard {route}", served, real)


@pytest.mark.parametrize("route", ["single", "bulk", "confirmed"])
def test_synced_delete_guard_parity(management, route):
    """A File Sync document asks which of the two advertised actions to take, alone or within a
    batch, and a delete that names one of them proceeds."""
    env = management
    env.sync_guard.side_effect = real_synced_delete_guard(FILE_SYNC)
    guard = synced_delete_guard("document-a", FILE_SYNC)
    fixture = new_management_fixture()
    if route == "single":
        real = env.client.delete(f"{MANAGEMENT_ROOT}/document-a?delete_mode=all_versions")
        served = fixture_receipt(
            fixture, "DELETE", "document-a", response=guard, status=409, query={"delete_mode": ["all_versions"]},
        )
    elif route == "bulk":
        body = {"document_ids": ["document-a"], "delete_mode": "all_versions", "conversation_linked_delete_confirmed": False}
        real = env.client.post(f"{MANAGEMENT_ROOT}/bulk-delete", json=body)
        served = fixture_receipt(
            fixture, "POST", "bulk-delete", response=delete_result(errors=[guard]), status=207, body=body,
        )
    else:
        real = env.client.delete(
            f"{MANAGEMENT_ROOT}/document-a?delete_mode=all_versions&file_sync_delete_action=ignore_remote",
        )
        expected = delete_result(
            "document-a", deleted_mode="all_versions", deleted_document_ids=["document-a"], promoted_document_id=None,
        )
        served = fixture_receipt(
            fixture, "DELETE", "document-a", response=expected,
            query={"delete_mode": ["all_versions"], "file_sync_delete_action": ["ignore_remote"]},
        )
    assert_receipt_parity(f"synced guard {route}", served, real)


@pytest.mark.parametrize("scenario", ["applied", "not_found", "changed"])
def test_bulk_tag_receipt_parity(management, scenario):
    """A bulk tag lists each document's resulting tags, or why it could not be tagged."""
    env = management
    body = {
        "document_ids": ["document-a", *(["missing"] if scenario == "not_found" else [])],
        "action": "add_tags", "tags": ["review"],
    }
    success, errors = [{"document_id": "document-a", "tags": ["reference", "review"]}], []
    if scenario == "not_found":
        errors = [batch_error("missing", GROUP_DOCUMENT_NOT_FOUND_ERROR)]
    elif scenario == "changed":
        # Another write lands between the document's read and this one.
        env.source.before_write = lambda _operation, item, _body: env.source.change(item)
        success, errors = [], [batch_error("document-a", DOCUMENT_CHANGED_ERROR)]
    real = env.client.post(f"{MANAGEMENT_ROOT}/bulk-tag", json=body)
    served = fixture_receipt(
        new_management_fixture(), "POST", "bulk-tag", response=bulk_tag_result(success, errors),
        status=207 if errors else 200, body=body,
    )
    assert_receipt_parity(f"bulk tag {scenario}", served, real)


@pytest.mark.parametrize("resource, mode", [("extract_metadata", None), ("reprocess_extraction", "layout")])
@pytest.mark.parametrize("partial", [False, True])
def test_queue_receipt_parity(management, resource, mode, partial):
    """Extraction and reprocessing list what they queued, and each document they could not."""
    env = management
    ids = ["document-a"]
    if partial:
        add_document(env, "document-c")
        ids.append("document-c")
        fail_queue_for(env, lambda key, _kwargs: ":document-c:" in key)
    body = {"document_ids": ids, **({"extraction_mode": mode} if mode else {})}
    real = env.client.post(f"{MANAGEMENT_ROOT}/{resource}", json=body)
    expected = queue_result(
        "document-a", errors=[batch_error("document-c")] if partial else [], extraction_mode=mode,
    )
    served = fixture_receipt(
        new_management_fixture(), "POST", resource, response=expected, status=207 if partial else 202, body=body,
    )
    assert_receipt_parity(f"{resource} partial={partial}", served, real)


@pytest.mark.parametrize("partial", [False, True])
def test_upload_receipt_parity(management, partial):
    """An upload lists the files it queued, and names each refused file with its reason."""
    env = management
    files = [(BytesIO(b"%PDF accepted"), "good.pdf")]
    refusals = []
    if partial:
        files += [(BytesIO(b"refused"), "bad.exe"), (BytesIO(b"%PDF unqueued"), "failed.pdf")]
        fail_queue_for(env, lambda _key, kwargs: kwargs.get("original_filename") == "failed.pdf")
        refusals = [upload_refusal("bad.exe", "This file type is not allowed."), upload_refusal("failed.pdf")]
    real = env.client.post(f"{MANAGEMENT_ROOT}/upload", data={"file": files})
    accepted = real.get_json()["document_ids"]
    assert len(accepted) == 1, real.get_json()
    served = fixture_receipt(
        new_management_fixture(), "POST", "upload", response=upload_result(accepted, ["good.pdf"], refusals),
        status=207 if partial else 200, body="multipart",
    )
    assert_receipt_parity(f"upload partial={partial}", served, real)


@pytest.mark.parametrize("scenario", ["create", "recolour", "rename", "merge", "delete"])
def test_tag_receipt_parity(management, scenario):
    """Creating, recolouring, renaming (into a new or an existing tag) and deleting a tag each
    confirm the resulting tag and every re-tagged document."""
    env = management
    env.groups[GROUP_A]["tag_definitions"] = deepcopy(TAG_DEFINITIONS)
    fixture = new_management_fixture()
    if scenario == "create":
        body = {"tag_name": "urgent", "color": "#ef4444"}
        real = env.client.post(f"{MANAGEMENT_ROOT}/tags", json=body)
        served = fixture_receipt(fixture, "POST", "tags", response=tag_created("urgent", "#ef4444"), status=201, body=body)
    elif scenario == "delete":
        real = env.client.delete(f"{MANAGEMENT_ROOT}/tags/reference")
        served = fixture_receipt(
            fixture, "DELETE", "tags/reference",
            response=tag_result("delete", success=[{"document_id": "document-a", "tags": []}]),
        )
    else:
        body, expected = {
            "recolour": ({"color": "#ef4444"}, tag_result("update", tag={"name": "reference", "color": "#ef4444"})),
            "rename": ({"new_name": "archive"}, tag_result(
                "rename", tag={"name": "archive", "color": "#8b5cf6"},
                success=[{"document_id": "document-a", "tags": ["archive"]}],
            )),
            "merge": ({"new_name": "unused"}, tag_result(
                "rename", tag={"name": "unused", "color": "#123456"},
                success=[{"document_id": "document-a", "tags": ["unused"]}],
            )),
        }[scenario]
        real = env.client.patch(f"{MANAGEMENT_ROOT}/tags/reference", json=body)
        served = fixture_receipt(fixture, "PATCH", "tags/reference", response=expected, body=body)
    assert_receipt_parity(f"tag {scenario}", served, real)


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_partial_tag_receipt_parity(management, operation):
    """A document found at a newer revision is left alone, and the old vocabulary is kept."""
    env = management
    env.groups[GROUP_A]["tag_definitions"] = deepcopy(TAG_DEFINITIONS)
    add_document(env, "document-c")
    env.source.before_write = lambda _operation, item, _body: (
        env.source.change("document-c", version=2) if item == "document-a" else None
    )
    tag, tags = ({"name": "archive", "color": "#8b5cf6"}, ["archive"]) if operation == "rename" else (None, [])
    expected = tag_result(
        operation, tag=tag, success=[{"document_id": "document-a", "tags": tags}],
        errors=[batch_error("document-c", TAG_REVISION_CHANGED_ERROR)],
    )
    fixture = new_management_fixture()
    if operation == "rename":
        body = {"new_name": "archive"}
        real = env.client.patch(f"{MANAGEMENT_ROOT}/tags/reference", json=body)
        served = fixture_receipt(fixture, "PATCH", "tags/reference", response=expected, status=207, body=body)
    else:
        real = env.client.delete(f"{MANAGEMENT_ROOT}/tags/reference")
        served = fixture_receipt(fixture, "DELETE", "tags/reference", response=expected, status=207)
    assert_receipt_parity(f"partial tag {operation}", served, real)


def change_before_the_vocabulary_pre_check(env):
    """The group changes just before the vocabulary's pre-check reads it, after every earlier read
    of the operation, so the pre-check refuses before any patch is sent."""
    original = env.management.require_group_document_management_context

    def changed_at_the_pre_check(user_id, group_id, operation):
        if sys._getframe(1).f_code.co_name == "_patch_tag_definitions":
            env.group_container.change(group_id, users=[{"userId": "new-member"}])
        return original(user_id, group_id, operation)

    env.scoped_monkeypatch.setattr(env.management, "require_group_document_management_context", changed_at_the_pre_check)


@pytest.mark.parametrize("check", ["pre_check", "lost_patch"])
@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_tag_vocabulary_conflict_receipt_parity(management, operation, check):
    """When the group changes while its documents are re-tagged, or while the old name is removed,
    the old vocabulary is kept and the conflict is reported as the vocabulary's own error."""
    env = management
    env.groups[GROUP_A]["tag_definitions"] = deepcopy(TAG_DEFINITIONS)
    if check == "pre_check":
        def concurrent_group_edit(**_kwargs):
            env.group_container.change(GROUP_A, tag_definitions={
                **env.groups[GROUP_A]["tag_definitions"], "parallel": {"color": "#ffffff"},
            })

        env.document_helpers["update_chunk_metadata"] = concurrent_group_edit
    else:
        lose_the_vocabulary_patch(env, removing=True)
    tag, tags = ({"name": "archive", "color": "#8b5cf6"}, ["archive"]) if operation == "rename" else (None, [])
    expected = tag_result(
        operation, tag=tag, success=[{"document_id": "document-a", "tags": tags}], errors=[tag_vocabulary_conflict()],
    )
    fixture = new_management_fixture()
    if operation == "rename":
        body = {"new_name": "archive"}
        real = env.client.patch(f"{MANAGEMENT_ROOT}/tags/reference", json=body)
        served = fixture_receipt(fixture, "PATCH", "tags/reference", response=expected, status=207, body=body)
    else:
        real = env.client.delete(f"{MANAGEMENT_ROOT}/tags/reference")
        served = fixture_receipt(fixture, "DELETE", "tags/reference", response=expected, status=207)
    assert_receipt_parity(f"vocabulary conflict {operation} ({check})", served, real)


@pytest.mark.parametrize("check", ["pre_check", "lost_patch"])
@pytest.mark.parametrize("scenario", ["create", "recolour", "rename", "bulk_tag", "metadata"])
def test_tag_vocabulary_refusal_parity(management, scenario, check):
    """A tag create, recolour or rename, a bulk tagging batch or a metadata save whose vocabulary
    write finds the group changed is refused with the one coded conflict, whichever check catches
    the change, and no document is written."""
    env = management
    env.groups[GROUP_A]["tag_definitions"] = deepcopy(TAG_DEFINITIONS)
    if check == "pre_check":
        change_before_the_vocabulary_pre_check(env)
    else:
        lose_the_vocabulary_patch(env)
    fixture = new_management_fixture()
    if scenario == "create":
        body = {"tag_name": "urgent", "color": "#ef4444"}
        real = env.client.post(f"{MANAGEMENT_ROOT}/tags", json=body)
        served = fixture_receipt(fixture, "POST", "tags", response=tag_vocabulary_refusal(), status=409, body=body)
    elif scenario == "bulk_tag":
        body = {"document_ids": ["document-a"], "action": "add_tags", "tags": ["archive"]}
        real = env.client.post(f"{MANAGEMENT_ROOT}/bulk-tag", json=body)
        served = fixture_receipt(fixture, "POST", "bulk-tag", response=tag_vocabulary_refusal(), status=409, body=body)
    elif scenario == "metadata":
        body = {"tags": ["reference", "archive"]}
        real = env.client.patch(f"{MANAGEMENT_ROOT}/document-a", json=body)
        served = fixture_receipt(
            fixture, "PATCH", "document-a", response=tag_vocabulary_refusal(document_id="document-a"), status=409, body=body,
        )
    else:
        body = {"color": "#ef4444"} if scenario == "recolour" else {"new_name": "archive"}
        real = env.client.patch(f"{MANAGEMENT_ROOT}/tags/reference", json=body)
        served = fixture_receipt(fixture, "PATCH", "tags/reference", response=tag_vocabulary_refusal(), status=409, body=body)
    assert_receipt_parity(f"vocabulary refusal {scenario} ({check})", served, real)
    assert env.group_container.writes == [] and env.source.writes == []


@pytest.mark.parametrize("batch", [False, True])
def test_download_response_parity(management, batch):
    """A download is a 200 attachment named for its file, or for the group archive, and carries
    the server's protective headers."""
    env = management
    fixture = new_management_fixture()
    if batch:
        add_document(env, "document-c")
        body = {"document_ids": ["document-a", "document-c"]}
        real = env.client.post(f"{MANAGEMENT_ROOT}/download", json=body)
        method, resource, name, content_type = "POST", "download", GROUP_ARCHIVE_NAME, "application/zip"
    else:
        body = None
        real = env.client.get(f"{MANAGEMENT_ROOT}/document-a/download")
        method, resource, name, content_type = "GET", "document-a/download", "document-a.pdf", "application/pdf"
    fixture.queue_operation(
        method, resource, response=b"file bytes", body=body, content_type=content_type, headers=attachment(name),
    )
    route = drive_route(fixture, method, operation_path(resource), body=body)

    assert (route.status, real.status_code) == (200, 200), real.get_data(as_text=True)
    assert real.mimetype == route.content_type
    for header, value in route.headers.items():
        assert real.headers.get(header) == value, f"{header}: fixture {value!r}, server {real.headers.get(header)!r}"


def seed_manager_rows(env, fixture):
    """The management harness holding the management fixture's group-a rows and revisions. The
    source a row cannot download is the one without a stored file, and a held row is held by a
    scan the server can read, as every held document is."""
    env.groups[ORIGIN_GROUP] = {
        **deepcopy(env.groups["source-group"]), "id": ORIGIN_GROUP, "_etag": f"etag-{ORIGIN_GROUP}",
        "name": "Publishing group", "users": [],
    }
    env.source.records.clear()
    revisions = [row for (group_id, _identifier), rows in fixture.versions.items() if group_id == GROUP_A for row in rows]
    for row in [*fixture.documents[GROUP_A], *revisions]:
        if row["id"] in env.source.records:
            continue
        stored = stored_document(row)
        stored.update(blob_container="group-documents", blob_path=f"{stored['group_id']}/{stored['file_name']}")
        if row["id"] != "source-denied":
            env.blobs.put(stored["blob_path"])
        env.source.records[row["id"]] = stored
        screening = row.get("content_screening")
        if screening:
            env.seed_release(stored)
            stored["content_screening"]["state"] = screening["state"]
            env.scans.records[stored["content_screening"]["scan_id"]]["state"] = screening["state"]


def test_manager_rows_shape_parity(management):
    """The Owner's rows carry the operations and review actions the server computes for each
    relationship: owned, shared, shared without a readable source, pending, held and held share."""
    env = management
    fixture = new_management_fixture()
    seed_manager_rows(env, fixture)
    real = get(env, page_size=100)
    status, payload = fixture_read(fixture, "/api/group_documents", page_size="100")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_no_invented_keys("manager list", payload, real_payload)
    served, stored = by_id(payload["documents"]), by_id(real_payload["documents"])
    assert set(served) == set(stored)
    for document_id, row in served.items():
        assert_row_parity(f"manager row {document_id}", row, stored[document_id])


def test_manager_versions_shape_parity(management):
    """A manager's version history: the current revision as in the list, and a historical one
    that can still be downloaded or deleted, and only inspected."""
    env = management
    fixture = new_management_fixture()
    seed_manager_rows(env, fixture)
    real = get(env, "/api/group_documents/same-document/versions")
    status, payload = fixture_read(fixture, "/api/group_documents/same-document/versions")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_no_invented_keys("manager versions", payload, real_payload)
    assert_shared_keys("manager versions", payload, real_payload, VERSIONS_UI_KEYS)
    served, stored = by_id(payload["versions"]), by_id(real_payload["versions"])
    assert set(served) == set(stored)
    for version_id, row in served.items():
        assert_row_parity(f"manager version {version_id}", row, stored[version_id])


def test_manager_tags_read_shape_parity(management):
    """The tag list names every tag in use and every defined tag, with its count and colour."""
    env = management
    fixture = new_management_fixture()
    seed_manager_rows(env, fixture)
    env.groups[GROUP_A]["tag_definitions"] = {
        name: {"color": color} for name, color in fixture.vocabulary[GROUP_A].items()
    }
    real = get(env, "/api/group_documents/tags")
    status, payload = fixture_read(fixture, "/api/group_documents/tags")

    assert (status, real.status_code) == (200, 200), real.get_json()
    assert payload == real.get_json()


@pytest.mark.parametrize("cause", ["non_member", "inactive"])
def test_manager_tags_read_refusal_parity(management, cause):
    env = management
    fixture = new_management_fixture()
    if cause == "non_member":
        with env.client.session_transaction() as state:
            state["user"] = {"oid": "stranger", "roles": ["User"]}
        fixture.denied_groups.add(GROUP_A)
    else:
        env.groups[GROUP_A]["status"] = "inactive"
        fixture.set_policy(GROUP_A, status="inactive")
    real = get(env, "/api/group_documents/tags")
    status, payload = fixture_read(fixture, "/api/group_documents/tags")

    assert (status, real.status_code) == (403, 403)
    assert payload == real.get_json()


# --------------------------------------------------------------------------
# M2C collaboration: the review states and recipient directory the collaboration fixture computes,
# and the decision receipts, refusals and partial outcomes it scripts, against the real routes.
# --------------------------------------------------------------------------

SHARED_DOCUMENT = collaboration_suite.DOCUMENT_ID
SHARING_KEYS = {
    "schema_version", "group_id", "document_id", "document_version", "etag",
    "owner_group", "relationship", "actions", "recipients", "publication",
}
RECIPIENT_KEYS = {"id", "name", "description", "approval_status"}
PUBLICATION_KEYS = {
    "status", "is_requester", "requested_by_user_id", "requested_by_display_name", "requested_at", "actions",
}
# A generated artifact's row keeps only what a held row does, and names the request.
ARTIFACT_ROW_UI_KEYS = ROW_UI_KEYS | {"generated_artifact_promotion_status"}


def new_collaboration_fixture():
    return GroupDocumentCollaborationFixture(_FakePage())


def fixture_review(fixture, identifier, group_id=GROUP_A, suffix="sharing", query=None):
    return drive_fixture(fixture, "GET", collaboration_path(identifier, suffix, group_id), query=query)


def fixture_decision(fixture, identifier, action, etag, response, status=200, target_group_id=None, group_id=GROUP_A):
    """Script one decision as a browser test does and send the browser's request for it."""
    reply = fixture.queue_decision(
        identifier, action, expected_etag=etag, response=response, status=status,
        target_group_id=target_group_id, group_id=group_id,
    )
    return drive_fixture(fixture, reply.method, reply.path, body=reply.body)


def assert_review_parity(scenario, served, real):
    assert_nested_parity(scenario, served, real, SHARING_KEYS)
    assert_nested_parity(f"{scenario} owner group", served["owner_group"], real["owner_group"], {"id", "name"})
    assert served["relationship"] == real["relationship"], f"{scenario}: relationship"
    assert set(served["actions"]) == set(real["actions"]), f"{scenario}: fixture {served['actions']}, server {real['actions']}"
    assert all(isinstance(value["document_version"], int) and isinstance(value["etag"], str) for value in (served, real))
    assert sorted(item["approval_status"] for item in served["recipients"]) == sorted(
        item["approval_status"] for item in real["recipients"]
    ), f"{scenario}: recipients"
    for served_item, real_item in zip(served["recipients"], real["recipients"]):
        assert_nested_parity(f"{scenario} recipient", served_item, real_item, RECIPIENT_KEYS)
    if real["publication"] is None:
        assert served["publication"] is None, f"{scenario}: the server has no publication"
        return
    assert_nested_parity(f"{scenario} publication", served["publication"], real["publication"], PUBLICATION_KEYS)
    for key in ("status", "is_requester"):
        assert served["publication"][key] == real["publication"][key], f"{scenario}: publication {key}"
    assert set(served["publication"]["actions"]) == set(real["publication"]["actions"]), f"{scenario}: publication actions"


@pytest.mark.parametrize("relationship, identifier", [
    ("owner", "same-document"), ("not_approved", "pending-report"), ("approved", "shared-report"),
])
def test_review_state_shape_parity(sharing, relationship, identifier):
    """An owner's review of a document it shares with an approved and a pending recipient, and a
    recipient's review of a pending and of an approved share."""
    env = sharing
    if relationship == "owner":
        collaboration_suite.seed_share(env, "approved", target="group-b")
        collaboration_suite.seed_share(env, "not_approved", target="source-group")
        real = collaboration_suite.state(env)
    else:
        collaboration_suite.seed_share(env, relationship)
        real = collaboration_suite.state(env, "group-b")
    status, payload = fixture_review(new_collaboration_fixture(), identifier)

    assert (status, real.status_code) == (200, 200), real.get_json()
    assert_review_parity(f"review {relationship}", payload, real.get_json())


@pytest.mark.parametrize("actor, identifier", [
    ("manager", "pending-publication"), (publication_suite.REQUESTER, "requested-publication"),
])
def test_publication_review_shape_parity(publication, actor, identifier):
    """A manager's review of an artifact awaiting publication, and the requester's."""
    env = publication
    publication_suite.submit(env)
    publication_suite.set_actor(env, actor)
    real = publication_suite.sharing(env)
    status, payload = fixture_review(new_collaboration_fixture(), identifier)

    assert (status, real.status_code) == (200, 200), real.get_json()
    assert_review_parity(f"publication review {identifier}", payload, real.get_json())


@pytest.mark.parametrize("actor, identifier", [
    ("manager", "pending-publication"), (publication_suite.REQUESTER, "requested-publication"),
])
def test_pending_artifact_row_shape_parity(publication, actor, identifier):
    """An artifact awaiting publication is listed with only its held fields and the request, for
    the manager who decides it and for its requester."""
    env = publication
    publication_suite.submit(env)
    publication_suite.set_actor(env, actor)
    real = get(env, "/api/group_documents", page_size=100)
    status, payload = fixture_read(new_collaboration_fixture(), "/api/group_documents", page_size="100")

    assert (status, real.status_code) == (200, 200), real.get_json()
    stored, served = by_id(real.get_json()["documents"])[env.target], by_id(payload["documents"])[identifier]
    assert_nested_parity(f"artifact row {identifier}", served, stored, ARTIFACT_ROW_UI_KEYS)
    for key in ("status", "generated_artifact_promotion_status", "shared_approval_status", "document_actions"):
        assert served[key] == stored[key], f"artifact row {identifier}: {key}"
    assert set(served["document_collaboration_actions"]) == set(stored["document_collaboration_actions"])


@pytest.mark.parametrize("suffix", ["sharing", "sharing/targets"])
@pytest.mark.parametrize("cause", ["non_member", "inactive", "gone"])
def test_review_refusal_parity(sharing, suffix, cause):
    """The review and the recipient search refuse a non-member and a status that bars reading as
    the read routes do, and a document the group has no relationship with is gone."""
    env = sharing
    fixture = new_collaboration_fixture()
    group_id, identifier, expected = GROUP_A, "same-document", None
    if cause == "non_member":
        collaboration_suite.set_actor(env, "stranger")
        fixture.denied_groups.add(GROUP_A)
        expected = COLLABORATION_DENIED
    elif cause == "inactive":
        env.groups[GROUP_A]["status"] = "inactive"
        fixture.configure_group(GROUP_A, status="inactive")
        expected = COLLABORATION_STATUS_REFUSED
    else:
        group_id, identifier, expected = "group-b", "unknown-document", COLLABORATION_GONE
    query = {"page": "1", "page_size": "25"} if suffix != "sharing" else {}
    real = env.client.get(f"/api/groups/{group_id}/documents/{SHARED_DOCUMENT}/{suffix}", query_string=query)
    status, payload = fixture_review(
        fixture, identifier, GROUP_A, suffix, {key: [value] for key, value in query.items()} or None,
    )

    assert status == real.status_code, real.get_json()
    assert payload == real.get_json() == expected


@pytest.mark.parametrize("search, page", [
    (None, 1), (None, 2), ("destination 1", 1), ("NUMBER 07", 1), ("target-2", 1),
])
def test_recipient_directory_parity(sharing, search, page):
    """The recipient search matches a group's name, description or id, excludes the source group,
    and pages the result in name order."""
    env = sharing
    fixture = new_collaboration_fixture()
    # Only the fixture's catalog can receive a share: the harness's other groups are inactive.
    for group_id in ("group-b", "source-group"):
        env.groups[group_id]["status"] = "inactive"
    for target in fixture.target_catalog[GROUP_A]:
        if target["id"] != GROUP_A:
            env.groups[target["id"]] = {
                **target, "type": "group", "status": "active", "_etag": f"etag-{target['id']}",
                "owner": {"id": "someone-else"}, "users": [],
            }
    query = {"page": str(page), "page_size": "25", **({"search": search} if search else {})}
    real = env.client.get(f"/api/groups/group-a/documents/{SHARED_DOCUMENT}/sharing/targets", query_string=query)
    status, payload = fixture_review(
        fixture, "same-document", suffix="sharing/targets", query={key: [value] for key, value in query.items()},
    )

    assert (status, real.status_code) == (200, 200), real.get_json()
    assert payload == real.get_json()


@pytest.mark.parametrize("scenario", [
    "share", "share_repeat", "unshare", "approve_share", "remove_pending", "remove_approved",
])
def test_decision_receipt_parity(sharing, scenario):
    """Each sharing decision confirms its exact action, recipient and resulting relationship; a
    repeated share of a pending recipient changes nothing."""
    env = sharing
    action = {"remove_pending": "remove_share", "remove_approved": "remove_share", "share_repeat": "share"}.get(scenario, scenario)
    seed = {
        "share_repeat": "not_approved", "unshare": "approved", "approve_share": "not_approved",
        "remove_pending": "not_approved", "remove_approved": "approved",
    }.get(scenario)
    if seed:
        collaboration_suite.seed_share(env, seed)
    group_id = "group-b" if action in {"approve_share", "remove_share"} else GROUP_A
    target = "group-b" if action in {"share", "unshare"} else None
    state = {
        "share": "not_approved", "unshare": "removed", "approve_share": "approved",
        "remove_share": "denied" if seed == "not_approved" else "removed",
    }[action]
    etag = env.source.records[SHARED_DOCUMENT]["_etag"]
    real = collaboration_suite.invoke(env, action)
    expected = collaboration_receipt(
        SHARED_DOCUMENT, action, state, group_id=group_id, target_group_id=target,
        status="unchanged" if scenario == "share_repeat" else "applied",
    )
    served = fixture_decision(new_collaboration_fixture(), SHARED_DOCUMENT, action, etag, expected, 200, target, group_id)
    assert_receipt_parity(f"decision {scenario}", served, real)


@pytest.mark.parametrize("scenario", ["notifications", "stale"])
def test_decision_partial_and_conflict_parity(sharing, scenario):
    """A share whose recipient notice was not confirmed is partial; a stale review is a conflict."""
    env = sharing
    etag = env.source.records[SHARED_DOCUMENT]["_etag"]
    fixture = new_collaboration_fixture()
    if scenario == "stale":
        real = collaboration_suite.invoke(env, "share", etag="stale-etag")
        served = fixture_decision(fixture, SHARED_DOCUMENT, "share", "stale-etag", STATE_CONFLICT, 409, "group-b")
    else:
        env.notices.failure = StoreFailure(403)
        real = collaboration_suite.invoke(env, "share")
        expected = collaboration_receipt(
            SHARED_DOCUMENT, "share", "not_approved", target_group_id="group-b", status="partial",
            errors=[effect_error("notifications")],
        )
        served = fixture_decision(fixture, SHARED_DOCUMENT, "share", etag, expected, 207, "group-b")
    assert_receipt_parity(f"decision {scenario}", served, real)


@pytest.mark.parametrize("status, relationship", [("not_approved", "denied"), ("approved", "removed")])
def test_recipient_repair_parity(sharing, status, relationship):
    """A recipient's removal whose cache effect failed: its partial receipt, the cleanup-only
    review it leaves, and the ordinary read that no longer finds the document."""
    env = sharing
    collaboration_suite.seed_share(env, status)
    env.cache.failure = StoreFailure(403)
    etag = env.source.records[SHARED_DOCUMENT]["_etag"]
    removal = collaboration_suite.invoke(env, "remove_share")
    review = collaboration_suite.state(env, "group-b")
    ordinary = get(env, f"/api/group_documents/{SHARED_DOCUMENT}", group_id="group-b")
    fixture = new_collaboration_fixture()
    expected = collaboration_receipt(
        SHARED_DOCUMENT, "remove_share", relationship, group_id="group-b", status="partial",
        errors=[effect_error("cache")],
    )
    assert_receipt_parity(
        f"repair removal {relationship}",
        fixture_decision(fixture, SHARED_DOCUMENT, "remove_share", etag, expected, 207, None, "group-b"), removal,
    )
    state = fixture.install_cleanup_repair("shared-report", relationship=relationship)
    state["actions"] = ["inspect", "remove_share"]
    served_status, served = fixture_review(fixture, "shared-report")
    assert (served_status, review.status_code) == (200, 200), review.get_json()
    assert_review_parity(f"repair review {relationship}", served, review.get_json())
    failure_status, failure = fixture_read(fixture, "/api/group_documents/shared-report")
    assert (failure_status, ordinary.status_code) == (404, 404)
    assert failure == ordinary.get_json()


@pytest.mark.parametrize("action, state, status, http_status", [
    ("approve", "approved", "queued", 202), ("approve_unqueued", "approval_failed", "partial", 207),
    ("reject", "rejected", "applied", 200), ("cancel", "cancelled", "applied", 200),
])
def test_publication_receipt_parity(publication, action, state, status, http_status):
    """Approving queues the artifact, or records the approval with an unconfirmed handoff;
    rejecting and the requester's cancelling apply at once."""
    env = publication
    publication_suite.submit(env)
    if action == "cancel":
        publication_suite.set_actor(env, publication_suite.REQUESTER)
    if action == "approve_unqueued":
        env.publication_state["queue_failure"] = True
    decision = "approve" if action == "approve_unqueued" else action
    etag = env.source.read_item(env.target, env.target)["_etag"]
    real = publication_suite.decide(env, decision)
    expected = collaboration_receipt(
        env.target, f"{decision}_artifact", state, status=status,
        errors=list(FAILED_HANDOFF_ERRORS) if status == "partial" else (),
    )
    served = fixture_decision(
        new_collaboration_fixture(), env.target, f"{decision}_artifact", etag, expected, http_status,
    )
    assert_receipt_parity(f"publication {action}", served, real)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
