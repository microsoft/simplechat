# test_public_document_fixture_parity.py
"""
Per-route shape parity between the M9B public document UI fixtures and the real routes.
Version: 0.261.180
Implemented in: 0.261.180

The V2 public Documents explorer mocks the network with three closed HTTP fixtures, which predate the
per-route parity rule:

- ``ui_tests/fixtures/public_documents.py`` serves the reads (list, facets, tags, detail and versions)
  from rows it computes;
- ``ui_tests/fixtures/public_document_management.py`` answers every management request with a
  response the browser test scripts through its receipt builders, and serves a manager's rows and the
  workspace's tag list;
- ``ui_tests/fixtures/public_document_collaboration.py`` serves the review state of each document and
  generated artifact it computes, and answers each publication decision with a scripted receipt.

A fixture whose shape drifts from the server lets a passing browser suite hide a real regression, so
this test is the M9B re-verification of the public document surface, built as the group pin
(``test_group_document_fixture_parity.py``) is. For every route the explorer's public read adapter,
operations and collaboration call, it asserts that the fixture never invents a key the server does not
return, at the top level, per document, and in every nested object the explorer reads; that the keys
the explorer reads are present on both sides; and that the status and every refusal's sentence and
machine code match. A management or publication receipt is compared whole: the builder a browser test
scripts must equal the real route's response to the same request, served through the fixture's own
``_dispatch``, which validates the request as it would the browser's.

The real routes run through the family API suites' harnesses: ``test_public_document_read_apis.py``
(the real public read, access, policy, projection and screening modules and routes),
``test_public_document_management.py`` (the real management module and routes over conditional
stores; the document primitives are its lightweight seams) and
``test_public_document_publication.py`` (the real collaboration and publication modules and the shared
canonical publication engine). The read and management checks store the fixture's own rows in the
fixture's workspace, ``pub-a``, so each projection is compared with the server's projection of the
same document; the publication harness publishes its own artifact into ``public-a``.

One product finding is pinned as a strict xfail: a public generated artifact awaiting publication is
listed with its full metadata and ``enhanced_citations: true``, where the group read path reduces the
same artifact to its held fields and the request, with "Awaiting generated artifact approval".
"""

import json
import sys
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN  # noqa: E402
from ui_tests.fixtures.public_workspace import public_context  # noqa: E402
from ui_tests.fixtures.public_documents import (  # noqa: E402
    PUBLIC_DOCUMENT_NOT_FOUND_ERROR, PUBLIC_DOCUMENTS_STATUS_ERROR, PublicDocumentsFixture,
)
from ui_tests.fixtures.public_document_management import (  # noqa: E402
    DOCUMENT_ACTIONS, DOWNLOAD_HEADERS, OPERATION_UNAVAILABLE_ERROR, PUBLIC_ARCHIVE_NAME,
    PublicDocumentManagementFixture, attachment, batch_error, bulk_tag_result, delete_result, metadata_result,
    operation_path, propagation_incomplete, queue_result, tag_created, tag_result, tag_vocabulary_conflict,
    tag_vocabulary_refusal, upload_refusal, upload_result,
)
from ui_tests.fixtures.public_document_collaboration import (  # noqa: E402
    COLLABORATION_MISSING, COLLABORATION_STATUS_REFUSED, FAILED_HANDOFF_ERRORS, STATE_CONFLICT,
    PublicDocumentCollaborationFixture, collaboration_path, collaboration_receipt,
)

import test_public_document_publication as publication_suite  # noqa: E402
from test_public_document_read_apis import environment, get, workspace  # noqa: E402,F401  (environment is a pytest fixture)
from test_public_document_management import StoreFailure, lose_the_vocabulary_patch, management  # noqa: E402,F401  (management is a pytest fixture)
from test_public_document_publication import publication, publication_modules  # noqa: E402,F401  (pytest fixtures)


WORKSPACE = "pub-a"
READS = f"/api/public-workspaces/{WORKSPACE}/documents"
READER, MANAGER = "reader", "manager"

# Keys only a read projection computes, so a stored document never carries them.
READ_PROJECTION_KEYS = {"document_actions", "document_collaboration_actions", "enhanced_citations"}
# Content a held row withholds; the stored document still has it.
WITHHELD_CONTENT = {
    "title": "Restricted title", "abstract": "Restricted abstract.", "authors": ["Restricted author"],
    "tags": ["restricted"], "document_classification": "Internal",
}

# The keys the explorer reads off every row: identity and the scope check, the status and progress
# columns, the revision fields and the per-row action gates.
ROW_UI_KEYS = {
    "id", "document_id", "public_workspace_id", "file_name", "status", "percentage_complete", "upload_date",
    "version", "revision_family_id", "is_current_version", "document_actions", "document_collaboration_actions",
}
# A row the viewer may read in full also shows its metadata columns.
CONTENT_UI_KEYS = {"title", "tags", "document_classification", "file_size"}
# A generated artifact names its request.
ARTIFACT_UI_KEYS = {
    "generated_artifact_promotion_status", "generated_artifact_requested_by_user_id",
    "generated_artifact_requested_by_display_name", "generated_artifact_requested_at",
}
LIST_UI_KEYS = {"documents", "total_count", "page", "page_size", "file_downloads_enabled"}
FACET_UI_KEYS = {"total", "untagged", "processing", "errors", "recent", "shared_with_me", "by_tag", "by_classification"}
TAG_UI_KEYS = {"name", "count", "color"}
VERSIONS_UI_KEYS = {"document_id", "public_workspace_id", "versions"}
RELATIONSHIP_FIELDS = ("public_workspace_id", "status", "is_current_version", "version", "percentage_complete")
# The explorer only asks whether a row allows an operation, so these compare as sets.
ACTION_FIELDS = ("document_actions", "document_collaboration_actions")


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
    """Dispatch one request through the fixture exactly as its Playwright route handler would."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}")
    route.request.method = method
    fixture._dispatch(route, entry)
    return route


def drive_fixture(fixture, method, path, body=None, query=None):
    """The fulfilled (status, payload) of one request, the payload as the browser receives it."""
    route = drive_route(fixture, method, path, body=body, query=query)
    payload = route.payload
    return route.status, json.loads(json.dumps(payload)) if isinstance(payload, (dict, list)) else payload


# --------------------------------------------------------------------------
# Parity assertions, mirroring the group document parity test.
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


def row_ui_keys(row):
    keys = set(ROW_UI_KEYS)
    screening = row.get("content_screening")
    if not (screening and screening.get("available") is False):
        keys |= CONTENT_UI_KEYS
    if screening:
        keys.add("content_screening")
    if row.get("generated_artifact_promotion_status"):
        keys |= ARTIFACT_UI_KEYS
    return keys


def assert_row_parity(scenario, served, stored):
    assert_nested_parity(scenario, served, stored, row_ui_keys(stored))
    for key in RELATIONSHIP_FIELDS:
        assert served.get(key) == stored.get(key), f"{scenario}: {key} fixture {served.get(key)!r}, server {stored.get(key)!r}"
    for key in ACTION_FIELDS:
        assert sorted(served[key]) == sorted(stored[key]), f"{scenario}: {key} fixture {served[key]!r}, server {stored[key]!r}"
    if "content_screening" in stored:
        assert_nested_parity(f"{scenario} screening", served["content_screening"], stored["content_screening"], {"state", "available"})
        assert served["content_screening"]["state"] == stored["content_screening"]["state"], scenario
    if "tags" in stored:
        assert served["tags"] == stored["tags"], f"{scenario}: the server stores normalized tags"


def stored_document(row):
    """The stored document behind one projected fixture row: projection-only keys removed, its tags as
    every server write normalizes them (functions_documents.normalize_tag), a held row's withheld
    content restored behind a screening marker, and a source the server can find. A fixture row whose
    tags no server write could have stored therefore fails the row parity."""
    normalize_tag = sys.modules["functions_documents"].normalize_tag
    stored = {key: deepcopy(value) for key, value in row.items() if key not in READ_PROJECTION_KEYS}
    if "tags" in stored:
        stored["tags"] = [normalize_tag(tag) for tag in stored["tags"]]
    screening = row.get("content_screening")
    if screening:
        stored["content_screening"] = {
            "state": screening["state"], "scan_id": f"scan-{row['id']}", "source_revision": str(row["version"]),
        }
        stored["status"] = "Processing complete"
        for key, value in WITHHELD_CONTENT.items():
            stored.setdefault(key, deepcopy(value))
    stored.update({
        "_etag": f"etag-{row['id']}", "user_id": stored.get("user_id", "uploader"),
        "blob_container": "public-documents", "blob_path": f"{row['public_workspace_id']}/{row['file_name']}",
    })
    stored.setdefault("keywords", [])
    return stored


def add_workspace(env, fixture, status="active"):
    """The fixture's workspace, `pub-a`, with the harness's members and the fixture's own tag
    definitions, named and coloured as the server's tag writes store them."""
    documents = sys.modules["functions_documents"]
    env.workspaces[WORKSPACE] = {
        **workspace(WORKSPACE, status=status), "_etag": f"ws-etag-{WORKSPACE}",
        "tag_definitions": {
            documents.normalize_tag(name): {"color": documents.normalize_tag_color(color)}
            for name, color in fixture.vocabulary[WORKSPACE].items()
        },
    }


def seed_rows(env, fixture):
    """Store every current row and revision of the fixture's workspace."""
    for row in fixture.documents[WORKSPACE]:
        env.source.records[row["id"]] = stored_document(row)
    for (workspace_id, _identifier), rows in fixture.versions.items():
        if workspace_id == WORKSPACE:
            for row in rows:
                env.source.records.setdefault(row["id"], stored_document(row))
    blobs = getattr(env, "blobs", None)
    if blobs is not None:
        for record in env.source.records.values():
            if record.get("public_workspace_id") == WORKSPACE:
                blobs[(record["blob_container"], record["blob_path"])] = b"SOURCE"


def login(env, oid):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": oid, "roles": ["User"]}


# --------------------------------------------------------------------------
# Reads: the read fixture, viewed as an ordinary reader, against the real read routes.
# --------------------------------------------------------------------------

def new_read_fixture():
    return PublicDocumentsFixture(_FakePage())


@pytest.fixture
def reads(environment):  # noqa: F811 - the imported harness fixture
    env = environment
    env.fixture = new_read_fixture()
    add_workspace(env, env.fixture)
    seed_rows(env, env.fixture)
    login(env, READER)
    return env


def fixture_read(fixture, path, **query):
    return drive_fixture(fixture, "GET", path, query={key: [value] for key, value in query.items()})


def test_read_list_shape_parity(reads):
    """The list envelope and every row kind: the headline, processing, failed and one bulk row."""
    real = get(reads, READS, page_size=100)
    status, payload = fixture_read(reads.fixture, READS, page_size="100")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_nested_parity("list", payload, real_payload, LIST_UI_KEYS)
    assert payload["total_count"] == real_payload["total_count"]
    assert payload["file_downloads_enabled"] is real_payload["file_downloads_enabled"] is False
    served, stored = by_id(payload["documents"]), by_id(real_payload["documents"])
    assert set(served) == set(stored)
    for document_id in ("same-document", "processing-report", "failed-report", "team-01", "team-02"):
        assert_row_parity(f"list row {document_id}", served[document_id], stored[document_id])


@pytest.mark.parametrize("document_id", ["same-document", "processing-report", "failed-report"])
def test_read_detail_shape_parity(reads, document_id):
    real = get(reads, f"{READS}/{document_id}")
    status, payload = fixture_read(reads.fixture, f"{READS}/{document_id}")

    assert (status, real.status_code) == (200, 200), real.get_json()
    assert_row_parity(f"detail {document_id}", payload, real.get_json())


def test_read_versions_shape_parity(reads):
    real = get(reads, f"{READS}/same-document/versions")
    status, payload = fixture_read(reads.fixture, f"{READS}/same-document/versions")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_nested_parity("versions", payload, real_payload, VERSIONS_UI_KEYS)
    assert payload["revision_family_id"] == real_payload["revision_family_id"]
    served, stored = by_id(payload["versions"]), by_id(real_payload["versions"])
    assert set(served) == set(stored)
    for version_id, row in served.items():
        assert_row_parity(f"version {version_id}", row, stored[version_id])


def test_read_facets_shape_parity(reads):
    real = get(reads, f"{READS}/facets")
    status, payload = fixture_read(reads.fixture, f"{READS}/facets")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_nested_parity("facets", payload, real_payload, FACET_UI_KEYS)
    assert payload == real_payload


def test_read_tags_shape_parity(reads):
    real = get(reads, f"{READS}/tags")
    status, payload = fixture_read(reads.fixture, f"{READS}/tags")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert_nested_parity("tags", payload, real_payload, {"tags"})
    served, stored = {tag["name"]: tag for tag in payload["tags"]}, {tag["name"]: tag for tag in real_payload["tags"]}
    assert set(served) == set(stored)
    for name, tag in served.items():
        assert_nested_parity(f"tag {name}", tag, stored[name], TAG_UI_KEYS)
        assert (tag["count"], tag["color"]) == (stored[name]["count"], stored[name]["color"]), name


def test_read_unknown_document_shape_parity(reads):
    real = get(reads, f"{READS}/missing-document")
    status, payload = fixture_read(reads.fixture, f"{READS}/missing-document")

    assert (status, real.status_code) == (404, 404)
    assert payload == real.get_json() == {"error": PUBLIC_DOCUMENT_NOT_FOUND_ERROR}


READ_ROUTES = (READS, f"{READS}/facets", f"{READS}/tags", f"{READS}/same-document", f"{READS}/same-document/versions")


@pytest.mark.parametrize("path", READ_ROUTES)
def test_read_status_refusal_shape_parity(reads, path):
    """A status that bars reading refuses a reader's every read with the status as the reason."""
    reads.workspaces[WORKSPACE]["status"] = "inactive"
    real = get(reads, path)
    fixture = reads.fixture
    fixture.workspaces[WORKSPACE] = public_context(WORKSPACE, "Research library", status="inactive")
    status, payload = fixture_read(fixture, path)

    assert (status, real.status_code) == (403, 403)
    assert payload == real.get_json() == {"error": PUBLIC_DOCUMENTS_STATUS_ERROR}


def test_every_caller_reads_a_public_workspace(reads):
    """Everyone reads a public workspace as at least a User, so the fixture's access refusal is a
    client robustness scenario the server cannot send today: a stranger reads the list."""
    login(reads, "stranger")
    real = get(reads, READS, page_size=100)
    assert real.status_code == 200, real.get_json()
    assert real.get_json()["total_count"] == len(reads.fixture.visible(WORKSPACE))


# --------------------------------------------------------------------------
# Management: every receipt builder, scripted and served exactly as a browser test does it, against
# the real route's response to the same request; and a manager's rows.
# --------------------------------------------------------------------------

def new_management_fixture():
    return PublicDocumentManagementFixture(_FakePage())


@pytest.fixture
def manage(management):  # noqa: F811 - the imported harness fixture
    env = management
    env.fixture = new_management_fixture()
    add_workspace(env, env.fixture)
    seed_rows(env, env.fixture)
    login(env, MANAGER)
    return env


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


def raw_json(env, method, resource, body):
    """Send a JSON body exactly as written: the server names fields in request order, and Flask's test
    client would sort a `json=` body's keys."""
    return env.client.open(
        f"{READS}/{resource}", method=method, data=json.dumps(body), content_type="application/json",
    )


def test_manager_rows_shape_parity(manage):
    """A manager's rows: every operation for an owned current document, and none for a document held
    by a scan no one can clean up."""
    real = get(manage, READS, page_size=100)
    status, payload = fixture_read(manage.fixture, READS, page_size="100")

    assert (status, real.status_code) == (200, 200), real.get_json()
    real_payload = real.get_json()
    assert payload["file_downloads_enabled"] is real_payload["file_downloads_enabled"] is True
    served, stored = by_id(payload["documents"]), by_id(real_payload["documents"])
    assert set(served) == set(stored)
    for document_id, row in served.items():
        assert_row_parity(f"manager row {document_id}", row, stored[document_id])
    assert sorted(stored["same-document"]["document_actions"]) == sorted(DOCUMENT_ACTIONS)
    assert stored["withheld-document"]["document_actions"] == []


def test_manager_versions_shape_parity(manage):
    """A historical revision can still be downloaded or deleted."""
    real = get(manage, f"{READS}/same-document/versions")
    status, payload = fixture_read(manage.fixture, f"{READS}/same-document/versions")

    assert (status, real.status_code) == (200, 200), real.get_json()
    served, stored = by_id(payload["versions"]), by_id(real.get_json()["versions"])
    assert set(served) == set(stored)
    for version_id, row in served.items():
        assert_row_parity(f"manager version {version_id}", row, stored[version_id])


def test_manager_tags_read_shape_parity(manage):
    real = get(manage, f"{READS}/tags")
    status, payload = fixture_read(manage.fixture, f"{READS}/tags")

    assert (status, real.status_code) == (200, 200), real.get_json()
    served, stored = {tag["name"]: tag for tag in payload["tags"]}, {tag["name"]: tag for tag in real.get_json()["tags"]}
    assert set(served) == set(stored)
    for name, tag in served.items():
        assert_nested_parity(f"manager tag {name}", tag, stored[name], TAG_UI_KEYS)
        assert (tag["count"], tag["color"]) == (stored[name]["count"], stored[name]["color"]), name


@pytest.mark.parametrize("scenario", ["updated", "propagation_incomplete"])
def test_metadata_receipt_parity(manage, scenario):
    """A saved change names its fields in request order; a change whose projections failed after the
    document saved is a coded 500."""
    env = manage
    body = {"title": "Changed title", "keywords": ["alpha", "beta"]}
    expected, status = metadata_result("same-document", body), 200
    if scenario == "propagation_incomplete":
        env.propagation_fail = True
        expected, status = propagation_incomplete("same-document"), 500
    real = raw_json(env, "PATCH", "same-document", body)
    served = fixture_receipt(env.fixture, "PATCH", "same-document", response=expected, status=status, body=body)
    assert_receipt_parity(f"metadata {scenario}", served, real)


def test_queued_metadata_receipt_parity(manage):
    """A screened document's change is queued for screening (202). The screening release proof is made
    to pass, so the document counts as available, as a released document is."""
    env = manage
    record = env.source.records["same-document"]
    record["content_screening"] = {"state": "cleared", "scan_id": "scan-same-document", "source_revision": "3"}
    env.settings["enable_content_screening"] = True
    payload_of = env.access.public_document_payload

    def released(document):
        payload = payload_of({key: value for key, value in document.items() if key != "content_screening"})
        payload["content_screening"] = {"state": "cleared", "available": True}
        return payload

    env.scoped_monkeypatch.setattr(env.access, "public_document_payload", released)
    body = {"abstract": "Updated abstract"}
    real = raw_json(env, "PATCH", "same-document", body)
    served = fixture_receipt(
        env.fixture, "PATCH", "same-document", response=metadata_result("same-document", body, queued=True),
        status=202, body=body,
    )
    assert_receipt_parity("metadata queued", served, real)


@pytest.mark.parametrize("mode", ["current_only", "all_versions"])
def test_single_delete_receipt_parity(manage, mode):
    """A single delete names the mode and the revisions it removed."""
    env = manage
    real = env.client.delete(f"{READS}/notes-document?delete_mode={mode}")
    expected = delete_result(
        "notes-document", deleted_mode=mode, deleted_document_ids=["notes-document"], promoted_document_id=None,
    )
    served = fixture_receipt(env.fixture, "DELETE", "notes-document", response=expected, query={"delete_mode": [mode]})
    assert_receipt_parity(f"delete {mode}", served, real)


@pytest.mark.parametrize("missing", [False, True])
def test_bulk_delete_receipt_parity(manage, missing):
    """A bulk delete counts what it deleted and refused, and says nothing else."""
    env = manage
    body = {
        "document_ids": ["same-document", "notes-document", *(["missing"] if missing else [])],
        "delete_mode": "all_versions", "conversation_linked_delete_confirmed": False,
    }
    real = env.client.post(f"{READS}/bulk-delete", json=body)
    errors = [batch_error("missing", PUBLIC_DOCUMENT_NOT_FOUND_ERROR)] if missing else []
    served = fixture_receipt(
        env.fixture, "POST", "bulk-delete", response=delete_result("same-document", "notes-document", errors=errors),
        status=207 if missing else 200, body=body,
    )
    assert_receipt_parity(f"bulk delete missing={missing}", served, real)


@pytest.mark.parametrize("scenario", ["applied", "not_found"])
def test_bulk_tag_receipt_parity(manage, scenario):
    env = manage
    ids = ["same-document", "notes-document", *(["missing"] if scenario == "not_found" else [])]
    body = {"document_ids": ids, "action": "add_tags", "tags": ["review"]}
    real = env.client.post(f"{READS}/bulk-tag", json=body)
    expected = bulk_tag_result(
        [
            {"document_id": "same-document", "tags": ["finance", "team", "review"]},
            {"document_id": "notes-document", "tags": ["team", "legacy/review", "review"]},
        ],
        [batch_error("missing", PUBLIC_DOCUMENT_NOT_FOUND_ERROR)] if scenario == "not_found" else [],
    )
    served = fixture_receipt(
        env.fixture, "POST", "bulk-tag", response=expected, status=207 if scenario == "not_found" else 200, body=body,
    )
    assert_receipt_parity(f"bulk tag {scenario}", served, real)


@pytest.mark.parametrize("resource, mode", [("extract_metadata", None), ("reprocess_extraction", "layout")])
@pytest.mark.parametrize("partial", [False, True])
def test_queue_receipt_parity(manage, resource, mode, partial):
    """Queued extraction or reprocessing names each queued document, and one the queue refused."""
    env = manage
    ids = ["same-document", *(["notes-document"] if partial else [])]
    if partial:
        submit = env.executor.submit_stored

        def refuse_notes(key, function, **kwargs):
            if kwargs.get("document_id") == "notes-document":
                raise StoreFailure()
            return submit(key, function, **kwargs)

        env.executor.submit_stored = refuse_notes
    body = {"document_ids": ids, **({"extraction_mode": mode} if mode else {})}
    real = env.client.post(f"{READS}/{resource}", json=body)
    expected = queue_result(
        "same-document", extraction_mode=mode, errors=[batch_error("notes-document")] if partial else (),
    )
    served = fixture_receipt(env.fixture, "POST", resource, response=expected, status=207 if partial else 202, body=body)
    assert_receipt_parity(f"{resource} partial={partial}", served, real)


def test_upload_receipt_parity(manage):
    """An upload names what it accepted and each refused file with the server's reason."""
    env = manage
    submit = env.executor.submit_stored

    def refuse_second(key, function, **kwargs):
        if kwargs.get("original_filename") == "refused.txt":
            raise StoreFailure()
        return submit(key, function, **kwargs)

    env.executor.submit_stored = refuse_second
    real = env.client.post(f"{READS}/upload", data={"file": [
        (BytesIO(b"Accepted public source.\n"), "accepted.txt"), (BytesIO(b"Rejected public source.\n"), "refused.txt"),
    ]})
    real_payload = real.get_json()
    expected = upload_result(real_payload["document_ids"], ["accepted.txt"], [upload_refusal("refused.txt")])
    assert (real.status_code, real_payload) == (207, expected), real_payload
    # The browser suite validates the multipart files themselves; here the reply is the builder's.
    fixture = env.fixture
    fixture.queue_operation("POST", "upload", response=expected, status=207, body="multipart")
    assert drive_fixture(fixture, "POST", operation_path("upload"), body="multipart") == (207, expected)


@pytest.mark.parametrize("scenario", ["create", "recolour", "rename", "delete"])
def test_tag_receipt_parity(manage, scenario):
    env = manage
    if scenario == "create":
        body, method, resource = {"tag_name": "archive", "color": "#123456"}, "POST", "tags"
        expected, status = tag_created("archive", "#123456"), 201
    elif scenario == "recolour":
        body, method, resource = {"color": "#abcdef"}, "PATCH", "tags/finance"
        expected, status = tag_result("update", tag={"name": "finance", "color": "#abcdef"}), 200
    elif scenario == "rename":
        body, method, resource = {"new_name": "funding"}, "PATCH", "tags/finance"
        expected, status = tag_result(
            "rename", tag={"name": "funding", "color": "#0078d4"},
            success=[{"document_id": "same-document", "tags": ["funding", "team"]}],
        ), 200
    else:
        body, method, resource = None, "DELETE", "tags/finance"
        expected, status = tag_result(
            "delete", success=[{"document_id": "same-document", "tags": ["team"]}],
        ), 200
    real = env.client.open(f"{READS}/{resource}", method=method, json=body)
    served = fixture_receipt(env.fixture, method, resource, response=expected, status=status, body=body)
    assert_receipt_parity(f"tag {scenario}", served, real)


def test_tag_vocabulary_conflict_receipt_parity(manage):
    """R5.8, re-checked here through the fixture's own dispatch: a lost vocabulary patch refuses a tag
    create with the one coded conflict, and a rename whose old-name cleanup loses keeps the old name
    and reports the conflict as the vocabulary's own entry."""
    env = manage
    lose_the_vocabulary_patch(env)
    real = env.client.post(f"{READS}/tags", json={"tag_name": "archive"})
    served = fixture_receipt(
        env.fixture, "POST", "tags", response=tag_vocabulary_refusal(), status=409, body={"tag_name": "archive"},
    )
    assert_receipt_parity("tag create lost patch", served, real)


def test_renamed_tag_cleanup_conflict_receipt_parity(manage):
    env = manage
    lose_the_vocabulary_patch(env, removing=True)
    real = env.client.patch(f"{READS}/tags/finance", json={"new_name": "funding"})
    expected = tag_result(
        "rename", tag={"name": "funding", "color": "#0078d4"},
        success=[{"document_id": "same-document", "tags": ["funding", "team"]}],
        errors=[tag_vocabulary_conflict()],
    )
    served = fixture_receipt(
        env.fixture, "PATCH", "tags/finance", response=expected, status=207, body={"new_name": "funding"},
    )
    assert_receipt_parity("tag rename lost cleanup", served, real)


@pytest.mark.parametrize("batch", [False, True])
def test_download_response_parity(manage, batch):
    """A download sends the file as an attachment with the protective headers, and a multi-document
    download names its archive the public archive name."""
    env = manage
    if batch:
        real = env.client.post(f"{READS}/download", json={"document_ids": ["same-document", "notes-document"]})
        name, method, resource, body = PUBLIC_ARCHIVE_NAME, "POST", "download", {"document_ids": ["same-document", "notes-document"]}
    else:
        real = env.client.get(f"{READS}/same-document/download")
        name, method, resource, body = "same-document.pdf", "GET", "same-document/download", None
    assert real.status_code == 200, real.get_data(as_text=True)
    fixture = env.fixture
    fixture.queue_operation(method, resource, response=real.data, body=body, headers=attachment(name))
    route = drive_route(fixture, method, operation_path(resource), body=body)
    assert route.status == 200
    assert route.headers["Content-Disposition"] == real.headers["Content-Disposition"] == attachment(name)["Content-Disposition"]
    for header, value in DOWNLOAD_HEADERS.items():
        assert route.headers[header] == real.headers[header] == value, header


def test_a_download_the_workspace_no_longer_offers_is_refused_as_the_server_refuses_it(manage):
    env = manage
    env.downloads = False
    real = env.client.get(f"{READS}/same-document/download")
    served = fixture_receipt(
        env.fixture, "GET", "same-document/download", status=403,
        response={"error": OPERATION_UNAVAILABLE_ERROR, "document_id": "same-document", "public_workspace_id": WORKSPACE},
    )
    assert_receipt_parity("download refused", served, real)


# --------------------------------------------------------------------------
# Collaboration: the review states and rows the collaboration fixture computes, and the decision
# receipts, refusals and partial outcomes it scripts, against the real routes.
# --------------------------------------------------------------------------

PUBLICATION_ROOT = publication_suite.ROOT
REVIEW_KEYS = {"schema_version", "public_workspace_id", "document_id", "document_version", "etag", "actions", "publication"}
PUBLICATION_KEYS = {
    "status", "is_requester", "requested_by_user_id", "requested_by_display_name", "requested_at", "actions",
}


def new_collaboration_fixture():
    return PublicDocumentCollaborationFixture(_FakePage())


def fixture_review(fixture, identifier):
    return drive_fixture(fixture, "GET", collaboration_path(identifier))


def fixture_decision(fixture, identifier, action, etag, response, status=200):
    """Script one decision as a browser test does and send the browser's request for it."""
    reply = fixture.queue_decision(identifier, action, expected_etag=etag, response=response, status=status)
    return drive_fixture(fixture, reply.method, reply.path, body=reply.body)


def assert_review_parity(scenario, served, real):
    assert_nested_parity(scenario, served, real, REVIEW_KEYS)
    assert set(served["actions"]) == set(real["actions"]), f"{scenario}: fixture {served['actions']}, server {real['actions']}"
    assert all(isinstance(value["document_version"], int) and isinstance(value["etag"], str) for value in (served, real))
    if real["publication"] is None:
        assert served["publication"] is None, f"{scenario}: the server has no publication"
        return
    assert_nested_parity(f"{scenario} publication", served["publication"], real["publication"], PUBLICATION_KEYS)
    for key in ("status", "is_requester"):
        assert served["publication"][key] == real["publication"][key], f"{scenario}: publication {key}"
    assert set(served["publication"]["actions"]) == set(real["publication"]["actions"]), f"{scenario}: publication actions"


def test_document_review_shape_parity(publication):  # noqa: F811
    """An ordinary document's review: it can be inspected, and it has no publication."""
    env = publication
    real = env.client.get(f"{PUBLICATION_ROOT}/document-a/publication")
    status, payload = fixture_review(new_collaboration_fixture(), "same-document")

    assert (status, real.status_code) == (200, 200), real.get_json()
    assert_review_parity("document review", payload, real.get_json())


@pytest.mark.parametrize("actor, identifier", [
    ("manager", "pending-publication"), (publication_suite.REQUESTER, "requested-publication"),
])
def test_publication_review_shape_parity(publication, actor, identifier):  # noqa: F811
    """A manager's review of an artifact awaiting publication, and its requester's -- who, as every
    requester must be, is a manager of the workspace too."""
    env = publication
    publication_suite.submit(env)
    publication_suite.set_actor(env, actor)
    real = publication_suite.state(env)
    status, payload = fixture_review(new_collaboration_fixture(), identifier)

    assert (status, real.status_code) == (200, 200), real.get_json()
    assert_review_parity(f"publication review {identifier}", payload, real.get_json())


@pytest.mark.parametrize("actor, identifier", [
    ("manager", "pending-publication"), (publication_suite.REQUESTER, "requested-publication"),
])
def test_pending_artifact_row_shape_parity(publication, actor, identifier):  # noqa: F811
    """An artifact awaiting publication is listed with its request and no document operation."""
    env = publication
    publication_suite.submit(env)
    publication_suite.set_actor(env, actor)
    real = get(env, PUBLICATION_ROOT, page_size=100)
    status, payload = fixture_read(new_collaboration_fixture(), READS, page_size="100")

    assert (status, real.status_code) == (200, 200), real.get_json()
    stored, served = by_id(real.get_json()["documents"])[env.target], by_id(payload["documents"])[identifier]
    assert_nested_parity(f"artifact row {identifier}", served, stored, row_ui_keys(stored))
    for key in ("status", "generated_artifact_promotion_status", "percentage_complete", "document_actions"):
        assert served[key] == stored[key], f"artifact row {identifier}: {key} fixture {served[key]!r}, server {stored[key]!r}"
    assert set(served["document_collaboration_actions"]) == set(stored["document_collaboration_actions"])


@pytest.mark.xfail(strict=True, reason=(
    "Product finding (M9B): the public read projection lists a generated artifact awaiting publication "
    "with its full metadata and enhanced_citations true. The group read path "
    "(functions_group_document_reads._project_group_document) reduces the same artifact to its held "
    "fields and the request, with 'Awaiting generated artifact approval'; the public projector "
    "(functions_public_document_reads._project_public_document) has no such branch."
))
def test_a_pending_public_artifact_is_listed_like_a_pending_group_artifact(publication):  # noqa: F811
    env = publication
    publication_suite.submit(env)
    publication_suite.set_actor(env, READER)
    row = by_id(get(env, PUBLICATION_ROOT, page_size=100).get_json()["documents"])[env.target]
    assert row["status"] == "Awaiting generated artifact approval"
    assert row["enhanced_citations"] is False
    assert not {"title", "abstract", "authors", "keywords", "tags"} & set(row)


@pytest.mark.parametrize("cause", ["missing", "inactive"])
def test_review_refusal_parity(publication, cause):  # noqa: F811
    """A review of a document that does not exist -- or no longer does, after a decision removed it --
    and one in a status that bars reading are refused as the read checks refuse them."""
    env = publication
    fixture = new_collaboration_fixture()
    identifier, expected, http_status = "missing-document", COLLABORATION_MISSING, 404
    if cause == "inactive":
        env.workspaces["public-a"]["status"] = "inactive"
        fixture.configure_workspace(WORKSPACE, status="inactive")
        identifier, expected, http_status = "same-document", COLLABORATION_STATUS_REFUSED, 403
    real = env.client.get(f"{PUBLICATION_ROOT}/{'document-a' if cause == 'inactive' else identifier}/publication")
    status, payload = fixture_review(fixture, identifier)

    assert (status, real.status_code) == (http_status, http_status), real.get_json()
    assert payload == real.get_json() == expected


@pytest.mark.parametrize("action, state, status, http_status", [
    ("approve", "approved", "queued", 202), ("approve_unqueued", "approval_failed", "partial", 207),
    ("reject", "rejected", "applied", 200), ("cancel", "cancelled", "applied", 200),
])
def test_publication_receipt_parity(publication, action, state, status, http_status):  # noqa: F811
    """Approving queues the artifact, or records the approval with an unconfirmed handoff; rejecting
    and the requester's cancelling apply at once."""
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
        env.target, f"{decision}_artifact", state, public_workspace_id="public-a", status=status,
        errors=list(FAILED_HANDOFF_ERRORS) if status == "partial" else (),
    )
    served = fixture_decision(new_collaboration_fixture(), "pending-publication", f"{decision}_artifact", etag, expected, http_status)
    assert_receipt_parity(f"publication {action}", served, real)


def test_stale_decision_parity(publication):  # noqa: F811
    """A decision against a changed review is the coded state conflict."""
    env = publication
    publication_suite.submit(env)
    real = publication_suite.decide(env, "approve", etag="stale-etag")
    served = fixture_decision(new_collaboration_fixture(), "pending-publication", "approve_artifact", "stale-etag", STATE_CONFLICT, 409)
    assert_receipt_parity("stale decision", served, real)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
