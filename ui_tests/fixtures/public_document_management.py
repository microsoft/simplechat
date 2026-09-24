# public_document_management.py
"""
Closed M3B public document management responses for the real production V2 SPA.
Version: 0.261.163
Implemented in: 0.261.133
Server-verbatim propagation failure (`propagation_incomplete`): 0.261.163

Reuse M3A public reads, local production assets, request recording, response gates
and Azure Playwright connection options. Reads and operations share the immutable
/api/public-workspaces/<id>/documents family, so this fixture distinguishes them by
method: every mutating request must consume an explicit response with an exact path,
body and query. Scripted server snapshots change only when that response is released;
no React state or handlers are replaced, and no request can reach a live service.
"""

import copy
import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from urllib.parse import quote, unquote, urlsplit

import pytest

from ui_tests.fixtures.public_documents import PublicDocumentsFixture, document
from ui_tests.fixtures.public_workspace import (  # noqa: F401
    PUBLIC_MANAGER_ROLES, connect_options, public_context,
)
from ui_tests.fixtures.workspace_authoring import WorkspaceAuthoringFixture


OPERATIONS = (
    "upload", "edit_metadata", "tag_documents", "manage_tags", "delete",
    "download", "extract_metadata", "reprocess",
)
DOCUMENT_ACTIONS = tuple(
    operation for operation in OPERATIONS if operation not in ("upload", "manage_tags")
)
METADATA_FIELDS = {
    "title", "abstract", "keywords", "publication_date",
    "document_classification", "authors", "tags",
}
DELETE_OPTIONS = {
    "delete_mode", "conversation_linked_delete_confirmed", "file_sync_delete_action",
}
PRESENTATION_SETTINGS = {
    "v2DocumentsPrefs", "v2WorkspaceRailCollapsed", "v2RailCollapsed", "darkModeEnabled",
}


def operation_path(resource, workspace_id="pub-a"):
    """Resource includes an already encoded document or tag path component."""
    return f"/api/public-workspaces/{quote(workspace_id, safe='')}/documents/{resource}"


def metadata_result(document_id, changes, *, public_workspace_id="pub-a", queued=False):
    return {
        "message": "Metadata saved and queued for screening." if queued else "Metadata updated.",
        "document_id": document_id, "public_workspace_id": public_workspace_id,
        "updated_fields": list(changes), "status": "queued" if queued else "updated",
    }


def delete_result(*document_ids, errors=(), **revision_details):
    return {
        "message": "Requested document deletion results.",
        "deleted": [{"document_id": identifier} for identifier in document_ids],
        "errors": copy.deepcopy(list(errors)),
        "deleted_count": len(document_ids), "error_count": len(errors),
        **revision_details,
    }


def tag_result(*, tag=None, success=(), errors=(), retained=False):
    result = {
        "message": "Tag vocabulary update results.",
        "documents_updated": len(success),
        "success": copy.deepcopy(list(success)), "errors": copy.deepcopy(list(errors)),
        "vocabulary_retained": retained,
    }
    if tag is not None:
        result["tag"] = copy.deepcopy(tag)
    return result


def tag_vocabulary_conflict(public_workspace_id="pub-a"):
    return {
        "stage": "vocabulary", "public_workspace_id": public_workspace_id,
        "error": "tag_vocabulary_conflict",
        "message": "The public workspace tag vocabulary changed during propagation. Review the refreshed tags and retry.",
    }


# The 500 a metadata write returns when the document saved but its projections did not, verbatim
# from functions_public_document_management.public_operation_error: the machine code is in `error`
# and the sentence the explorer shows is in `message`.
PROPAGATION_INCOMPLETE_MESSAGE = (
    "The operation changed stored data, but required cleanup or propagation is incomplete. Refresh before retrying."
)


def propagation_incomplete(document_id, *, public_workspace_id="pub-a"):
    return {
        "error": "document_propagation_incomplete", "message": PROPAGATION_INCOMPLETE_MESSAGE,
        "repair_required": True, "document_id": document_id, "public_workspace_id": public_workspace_id,
    }


@dataclass
class OperationReply:
    method: str
    path: str
    workspace_id: str
    response: dict | bytes
    status: int = 200
    body: object = None
    query: dict = field(default_factory=dict)
    files: list | None = None
    content_type: str | None = None
    headers: dict = field(default_factory=dict)
    records: list = field(default_factory=list)
    remove_ids: tuple = ()
    vocabulary: dict | None = None
    versions: dict = field(default_factory=dict)


class PublicDocumentManagementFixture(PublicDocumentsFixture):
    """A small, explicitly scripted HTTP boundary, not a second document app."""

    def __init__(self, page):
        super().__init__(page)
        self.planned_operations = []
        self.completed_operations = []
        self.multipart_uploads = []
        self.failed_operations = []
        self.vocabulary = {}
        self.documents = {}
        self.versions = {}
        self.detail_overrides = {}
        for workspace_id, title in (("pub-a", "Research brief"), ("pub-b", "Operations brief")):
            self.set_policy(workspace_id)
            owned = document(
                workspace_id, "same-document", title, timestamp=self.now,
                tags=["finance", "team"], keywords=["baseline"],
                publication_date="2026-09-01", document_actions=list(DOCUMENT_ACTIONS),
            )
            notes = document(
                workspace_id, "notes-document", "Field notes", timestamp=self.now - 1,
                tags=["team", "legacy/review"], document_actions=list(DOCUMENT_ACTIONS),
            )
            withheld = document(
                workspace_id, "withheld-document", "Withheld by server", timestamp=self.now - 2,
                tags=[], document_actions=[],
            )
            self.documents[workspace_id] = [owned, notes, withheld]
            previous = document(
                workspace_id, "previous-version", "Earlier research brief",
                timestamp=self.now - 86400, version=2, is_current_version=False,
                revision_family_id=owned["revision_family_id"], tags=["finance", "team"],
                document_actions=[],
            )
            self.versions[(workspace_id, "same-document")] = [copy.deepcopy(owned), previous]
            self.vocabulary[workspace_id] = {
                "finance": "#0078d4", "team": "#059669",
                "legacy/review": "#8b5cf6", "review": "#64748b",
            }
        page.on("requestfailed", self._request_failed)

    def set_policy(self, workspace_id="pub-a", *, role="DocumentManager", status="active"):
        name = self.workspaces[workspace_id]["workspace"]["name"]
        context = public_context(workspace_id, name, role=role, status=status, viewer=self.viewer_id)
        manager = role in PUBLIC_MANAGER_ROLES
        operations = list(OPERATIONS) if manager and status == "active" else []
        if manager and status == "locked":
            operations = ["download"]
        elif manager and status == "upload_disabled":
            operations = ["delete", "download", "reprocess"]
        context["document_management"] = {"schema_version": 1, "operations": operations}
        self.workspaces[workspace_id] = context

    def record(self, identifier, workspace_id="pub-a"):
        return next(record for record in self.documents[workspace_id] if record["id"] == identifier)

    @staticmethod
    def _is_operation(entry):
        match = re.fullmatch(r"/api/public-workspaces/([^/]+)/documents/(.+)", entry.path)
        if not match:
            return False
        if entry.method != "GET":
            return True
        return match.group(2).endswith("/download")

    @property
    def operation_requests(self):
        return [entry for entry in self.requests if self._is_operation(entry)]

    def queue_operation(
        self, method, resource, *, response, body=None, query=None, status=200,
        files=None, records=(), remove_ids=(), vocabulary=None, versions=None,
        content_type=None, headers=None, workspace_id="pub-a",
    ):
        assert workspace_id in self.workspaces
        reply = OperationReply(
            method=method, path=operation_path(resource, workspace_id), workspace_id=workspace_id,
            response=copy.deepcopy(response), status=status, body=copy.deepcopy(body),
            query=copy.deepcopy(query or {}), files=copy.deepcopy(files),
            content_type=content_type, headers=copy.deepcopy(headers or {}),
            records=copy.deepcopy(list(records)), remove_ids=tuple(remove_ids),
            vocabulary=copy.deepcopy(vocabulary), versions=copy.deepcopy(versions or {}),
        )
        self.planned_operations.append(reply)
        return reply

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["version"] = "0.261.133"
        payload["features"]["enable_enhanced_extraction"] = True
        return payload

    def _request_failed(self, request):
        path = unquote(urlsplit(request.url).path)
        is_download = request.method in ("GET", "POST") and path.endswith("/download")
        if not is_download and re.fullmatch(r"/api/public-workspaces/[^/]+/documents/.+", path):
            self.failed_operations.append((request.method, request.url, request.failure))

    @staticmethod
    def _validate_delete_options(options, *, query=False):
        assert set(options) <= DELETE_OPTIONS, f"Unsupported deletion options: {options}"
        mode = options.get("delete_mode")
        allowed_modes = (["current_only"], ["all_versions"]) if query else ("current_only", "all_versions")
        assert mode in allowed_modes, options
        if "conversation_linked_delete_confirmed" in options:
            value = options["conversation_linked_delete_confirmed"]
            assert value in (["true"], ["false"]) if query else type(value) is bool
        if "file_sync_delete_action" in options:
            action = options["file_sync_delete_action"]
            allowed_actions = (["delete_only"], ["ignore_remote"]) if query else ("delete_only", "ignore_remote")
            assert action in allowed_actions, options

    def _validate_operation(self, entry):
        match = re.fullmatch(r"/api/public-workspaces/([^/]+)/documents/(.+)", entry.path)
        assert match, f"Not an immutable public operation: {entry}"
        workspace_id, resource = match.groups()
        assert workspace_id in self.workspaces, entry
        method, body = entry.method, entry.body
        if method == "GET":
            assert resource.endswith("/download") and resource.count("/") == 1 and body is None, entry
            assert not entry.query, entry
            return
        if method == "DELETE" and "/" not in resource:
            assert body is None
            self._validate_delete_options(entry.query, query=True)
            return
        assert not entry.query, f"Operation scope/options must not use query aliases: {entry}"
        if resource == "upload":
            assert method == "POST" and isinstance(body, str), entry
            return
        if resource.startswith("tags/"):
            assert method in ("PATCH", "DELETE"), entry
            if method == "DELETE":
                assert body is None, entry
            else:
                assert isinstance(body, dict) and body and set(body) <= {"new_name", "color"}, entry
            return
        if resource == "tags":
            assert method == "POST" and isinstance(body, dict), entry
            assert "tag_name" in body and set(body) <= {"tag_name", "color"}, entry
            return
        batch_fields = {
            "bulk-delete": {"document_ids", *DELETE_OPTIONS},
            "download": {"document_ids"}, "extract_metadata": {"document_ids"},
            "reprocess_extraction": {"document_ids", "extraction_mode"},
            "bulk-tag": {"document_ids", "action", "tags"},
        }
        if resource in batch_fields:
            assert method == "POST" and isinstance(body, dict), entry
            assert set(body) <= batch_fields[resource] and "document_ids" in body, entry
            ids = body["document_ids"]
            assert isinstance(ids, list) and ids and all(isinstance(identifier, str) and identifier for identifier in ids)
            assert len(ids) == len(set(ids)), entry
            if resource == "bulk-delete":
                self._validate_delete_options({key: value for key, value in body.items() if key != "document_ids"})
            elif resource == "reprocess_extraction":
                assert body.get("extraction_mode") in ("read", "layout"), entry
            elif resource == "bulk-tag":
                assert body.get("action") in ("add_tags", "remove_tags", "set_tags"), entry
                assert isinstance(body.get("tags"), list), entry
            return
        assert "/" not in resource and method == "PATCH", f"Unsupported public operation: {entry}"
        assert isinstance(body, dict) and body and set(body) <= METADATA_FIELDS, entry

    @staticmethod
    def _multipart_files(request):
        content_type = request.headers.get("content-type", "")
        assert content_type.startswith("multipart/form-data;"), content_type
        raw = request.post_data_buffer
        assert raw is not None, "The upload did not contain multipart bytes."
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + raw
        )
        assert message.is_multipart() and not message.defects, "Malformed multipart upload."
        files = []
        for part in message.iter_parts():
            assert part.get_content_disposition() == "form-data"
            assert part.get_param("name", header="content-disposition") == "file", (
                "Uploads must contain only repeated file fields, not workspace aliases."
            )
            assert part.get_filename(), "Every upload part must be a file."
            files.append({
                "name": part.get_filename(), "mimeType": part.get_content_type(),
                "buffer": part.get_payload(decode=True),
            })
        assert files, "No files were uploaded."
        return files

    def _apply_response(self, reply):
        rows = self.documents[reply.workspace_id]
        replacements = {record["id"]: record for record in reply.records}
        assert len(replacements) == len(reply.records), "Duplicate scripted document IDs."
        rows = [record for record in rows if record["id"] not in reply.remove_ids]
        retained_ids = {record["id"] for record in rows}
        self.documents[reply.workspace_id] = [
            copy.deepcopy(replacements.get(record["id"], record)) for record in rows
        ] + [copy.deepcopy(record) for identifier, record in replacements.items() if identifier not in retained_ids]
        for identifier, versions in reply.versions.items():
            self.versions[(reply.workspace_id, identifier)] = copy.deepcopy(versions)
        if reply.vocabulary is not None:
            self.vocabulary[reply.workspace_id] = copy.deepcopy(reply.vocabulary)

    def _dispatch(self, route, entry):
        if self._is_operation(entry):
            self._validate_operation(entry)
            assert self.planned_operations, f"Unplanned public document operation: {entry}"
            reply = self.planned_operations[0]
            assert (entry.method, urlsplit(route.request.url).path, entry.query) == (
                reply.method, reply.path, reply.query,
            ), f"Wrong method, immutable target, encoding or query: {entry}; expected {reply}"
            if reply.files is not None:
                files = self._multipart_files(route.request)
                assert files == reply.files, f"Unexpected multipart files: {files}"
                self.multipart_uploads.append((entry.path, files))
            else:
                assert entry.body == reply.body, f"Unexpected request body: {entry.body!r}; expected {reply.body!r}"
            self.planned_operations.pop(0)
            self._apply_response(reply)
            self.completed_operations.append(entry)
            if isinstance(reply.response, bytes):
                if reply.status >= 400:
                    self.expected_http_errors.add((route.request.url, reply.status))
                route.fulfill(
                    status=reply.status, body=reply.response,
                    content_type=reply.content_type or "application/octet-stream",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", **reply.headers},
                )
            else:
                self._json(route, reply.response, reply.status)
            return
        match = re.fullmatch(r"/api/public-workspaces/([^/]+)/documents/tags", entry.path)
        if match and entry.method == "GET":
            workspace_id = match.group(1)
            assert entry.query == {}, entry
            assert workspace_id in self.workspaces, entry
            if workspace_id in self.denied_workspaces or not self.workspaces[workspace_id]["document_permissions"]["can_view"]:
                self._json(route, {"error": "Public workspace tags are unavailable."}, 403)
            else:
                counts = self.facets(workspace_id)["by_tag"]
                self._json(route, {"tags": [
                    {"name": name, "color": color, "count": counts.get(name, 0)}
                    for name, color in sorted(self.vocabulary[workspace_id].items())
                ]})
            return
        super()._dispatch(route, entry)

    def assert_clean(self):
        # Deliberately bypass M3A's unconditional prohibition of public document writes.
        WorkspaceAuthoringFixture.assert_clean(self)
        assert not self.planned_operations, f"Expected operations were not made: {self.planned_operations}"
        assert not self.deferred_paths, f"Unused response gates: {self.deferred_paths}"
        assert not self.failed_operations, f"Document mutations were aborted: {self.failed_operations}"
        assert not self.classic_visits, "M3B unexpectedly fell back to the classic public workspace."
        assert len(self.completed_operations) == len(self.operation_requests)
        assert not [entry for entry in self.requests if entry.path.startswith("/api/documents")], (
            "Public management made a personal document request."
        )
        assert not [entry for entry in self.requests if entry.path.startswith("/api/group_documents")], (
            "Public management made a group document request."
        )
        for entry in self.writes:
            if self._is_operation(entry):
                self._validate_operation(entry)
                continue
            if entry.path == "/api/public_workspaces/setActive" and entry.method == "PATCH":
                assert not entry.query and set(entry.body) == {"workspaceId"}, entry
                assert entry.body["workspaceId"] in self.workspaces, entry
                continue
            if entry.path == "/api/user/settings" and entry.method == "POST":
                assert set(entry.body) == {"settings"}, entry
                assert set(entry.body["settings"]) <= PRESENTATION_SETTINGS, entry
                continue
            assert False, f"Unexpected mutation during public management: {entry}"
        for entry in self.requests:
            if entry.path.startswith("/api/public-workspaces/") and "/documents" in entry.path and not self._is_operation(entry):
                assert entry.method == "GET", f"Public document mutation outside the operation family: {entry}"
                assert "group_id" not in entry.query and "group_ids" not in entry.query, entry
                assert "public_workspace_id" not in entry.query, entry


@pytest.fixture
def public_management_ui(page):
    fixture = PublicDocumentManagementFixture(page)
    yield fixture
    fixture.assert_clean()
