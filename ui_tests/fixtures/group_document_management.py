# group_document_management.py
"""
Closed M2B group document management responses for the real production V2 SPA.
Version: 0.261.174
Implemented in: 0.261.129
Every receipt builder, an Owner's rows and the tag list are the real management routes', held to
them by functional_tests/test_group_document_fixture_parity.py.
A tag vocabulary conflict refusal carries its code (`tag_vocabulary_refusal`): 0.261.167
The refusal also answers a bulk tagging batch and, naming the document, a metadata save: 0.261.168
The group-scoped content screening routes, modelled in group_screening.py: 0.261.174

Reuse M2A reads, local production assets, request recording, response gates and
Azure Playwright connection options. Every management request must consume an
explicit response with an exact path, body and query. Scripted server snapshots
change only when that response is released; no React state or handlers are
replaced, and no request can reach a live service.
"""

import copy
import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from urllib.parse import quote, unquote, urlsplit

import pytest

from ui_tests.fixtures.group_documents import (
    GROUP_DOCUMENTS_DENIED_ERROR, GROUP_DOCUMENTS_STATUS_ERROR, GroupDocumentsFixture, document, restricted,
    restricted_status,
)
from ui_tests.fixtures.group_screening import SCREENING_PREFIX, GroupScreeningModel
from ui_tests.fixtures.group_workspace import connect_options, group_context  # noqa: F401
from ui_tests.fixtures.workspace_authoring import ORIGIN, WorkspaceAuthoringFixture


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
SHELL_READS = {
    "/api/v2/bootstrap", "/api/user/settings", "/api/groups", "/api/conversations/feed",
    "/api/agents/catalog", "/api/prompts", "/api/orchestration_types",
    "/api/orchestration_settings",
}


def operation_path(resource, group_id="group-a"):
    """Resource includes an already encoded document or tag path component."""
    return f"/api/groups/{quote(group_id, safe='')}/documents/{resource}"


# The receipts the real management routes send (functions_group_document_management.py and the
# File Sync delete guard), verbatim, so a browser test that renders a receipt's text renders the
# server's; functional_tests/test_group_document_fixture_parity.py holds every builder below to the
# real route. A coded failure carries its machine code in `error` and its sentence in `message`;
# any other refusal carries its sentence in `error`, and a tag vocabulary conflict also names its
# code in `error_code`.
METADATA_UPDATED_MESSAGE = "Group document metadata updated."
METADATA_QUEUED_MESSAGE = "Metadata saved and queued for content screening."
DOCUMENT_DELETED_MESSAGE = "Group document deleted."
TAG_CREATED_MESSAGE = "Group tag created."
TAG_MESSAGES = {
    "update": "Group tag updated.",
    "rename": "Group tag renamed.",
    "delete": "Group tag deleted.",
}
TAG_PARTIAL_MESSAGE = (
    "Some tag changes are incomplete. The original vocabulary has been retained; refresh before retrying."
)
# The one tag vocabulary conflict, whether the etag pre-check caught the change or the conditional
# patch lost to it (GROUP_TAG_VOCABULARY_CONFLICT_MESSAGE and _CODE).
VOCABULARY_CONFLICT_MESSAGE = "The group's tags or permissions changed. Refresh and retry."
VOCABULARY_CONFLICT_CODE = "vocabulary_conflict"
PROPAGATION_INCOMPLETE_MESSAGE = (
    "The operation changed stored data, but required cleanup or propagation is incomplete. Refresh before retrying."
)
# Why one document of a batch was refused: a job or write that failed outright, a write that lost a
# race with another change, and a tag change that found the document at a newer revision.
DOCUMENT_OPERATION_FAILED_ERROR = "Unable to complete this group document operation."
DOCUMENT_CHANGED_ERROR = "The resource changed. Refresh and retry the operation."
TAG_REVISION_CHANGED_ERROR = "The current document revision changed. Refresh and retry."
CONVERSATION_DELETE_MESSAGE = "This document is part of a conversation. Confirm its deletion."
SYNCED_DELETE_MESSAGE = (
    "This document was created by File Sync. Choose whether to ignore the remote file so it is not re-synced after deletion."
)
SYNCED_DELETE_OPTIONS = (
    {"action": "delete_only", "label": "Delete this copy only"},
    {"action": "ignore_remote", "label": "Delete and ignore the remote file"},
)


def metadata_result(document_id, changes, *, group_id="group-a", queued=False):
    """The server names the fields in the order the request sent them."""
    return {
        "message": METADATA_QUEUED_MESSAGE if queued else METADATA_UPDATED_MESSAGE,
        "document_id": document_id, "group_id": group_id,
        "updated_fields": list(changes), "status": "queued" if queued else "updated",
    }


def propagation_incomplete(document_id, *, group_id="group-a"):
    """The 500 a metadata write returns when the document saved but its projections did not."""
    return {
        "error": "document_propagation_incomplete", "message": PROPAGATION_INCOMPLETE_MESSAGE,
        "repair_required": True, "document_id": document_id, "group_id": group_id,
    }


def delete_result(*document_ids, errors=(), **revision_details):
    """A delete receipt. A single-document DELETE also names its revisions and says what it did;
    a bulk delete reports only what was deleted and what was refused."""
    result = {
        "deleted": [{"document_id": identifier} for identifier in document_ids],
        "errors": copy.deepcopy(list(errors)),
        "deleted_count": len(document_ids), "error_count": len(errors),
    }
    if revision_details:
        result["message"] = DOCUMENT_DELETED_MESSAGE
        result.update(revision_details)
    return result


def conversation_delete_guard(document_id, conversation_id, *, title, file_name, group_id="group-a"):
    """The confirmation a document uploaded in a conversation asks for, as a 409 or a bulk error
    entry. `title` is the conversation's title when the file was uploaded."""
    return {
        "error": "conversation_linked_document_delete_requires_confirmation",
        "message": CONVERSATION_DELETE_MESSAGE, "needs_confirmation": True,
        "conversation": {
            "id": conversation_id, "title": title,
            "url": f"/chats?conversation_id={quote(conversation_id, safe='')}",
        },
        "document": {"id": document_id, "file_name": file_name},
        "document_id": document_id, "group_id": group_id,
    }


def synced_delete_guard(document_id, file_sync, *, group_id="group-a"):
    """The confirmation a File Sync document's delete asks for, as a 409 or a bulk error entry."""
    return {
        "error": "synced_document_delete_requires_action", "message": SYNCED_DELETE_MESSAGE,
        "file_sync": copy.deepcopy(file_sync), "options": copy.deepcopy(list(SYNCED_DELETE_OPTIONS)),
        "needs_confirmation": True, "document_id": document_id, "group_id": group_id,
    }


def batch_error(document_id, error=DOCUMENT_OPERATION_FAILED_ERROR, *, group_id="group-a"):
    """One document a batch could not change, with the server's sentence for why."""
    return {"document_id": document_id, "error": error, "group_id": group_id}


def bulk_tag_result(success, errors=()):
    return {"success": copy.deepcopy(list(success)), "errors": copy.deepcopy(list(errors))}


def queue_result(*document_ids, errors=(), extraction_mode=None):
    """The receipt for queued metadata extraction or, given its `extraction_mode`, reprocessing."""
    return {
        "queued": [
            {"document_id": identifier, **({"extraction_mode": extraction_mode} if extraction_mode else {})}
            for identifier in document_ids
        ],
        "errors": copy.deepcopy(list(errors)),
    }


def upload_refusal(file_name, error=DOCUMENT_OPERATION_FAILED_ERROR):
    """An upload names each refused file with the reason, as one sentence."""
    return f"{file_name}: {error}"


def upload_result(document_ids, processed_filenames, errors=()):
    return {
        "message": f"Queued {len(processed_filenames)} file(s) for processing.",
        "document_ids": list(document_ids), "processed_filenames": list(processed_filenames),
        "errors": list(errors),
    }


def tag_created(name, color):
    return {"message": TAG_CREATED_MESSAGE, "tag": {"name": name, "color": color}}


def tag_result(operation, *, tag=None, success=(), errors=()):
    """A tag vocabulary receipt for what the request did: `update` a colour, `rename` (or merge)
    the tag, or `delete` it. Only a delete names no tag, and only a rename or delete re-tags the
    documents; the old vocabulary is retained exactly when a change is incomplete."""
    assert operation in TAG_MESSAGES, operation
    assert (tag is None) == (operation == "delete"), "Only a tag delete omits the resulting tag."
    assert operation != "update" or not (success or errors), "A colour change re-tags no documents."
    result = {
        "message": TAG_PARTIAL_MESSAGE if errors else TAG_MESSAGES[operation],
        "documents_updated": len(success),
        "success": copy.deepcopy(list(success)), "errors": copy.deepcopy(list(errors)),
        "vocabulary_retained": bool(errors),
    }
    if tag is not None:
        result["tag"] = copy.deepcopy(tag)
    return result


def tag_vocabulary_conflict(group_id="group-a"):
    """The vocabulary's own entry in a re-tag receipt, when removing the old name finds the group
    changed."""
    return {
        "stage": "vocabulary", "group_id": group_id, "error": VOCABULARY_CONFLICT_CODE,
        "message": VOCABULARY_CONFLICT_MESSAGE,
    }


def tag_vocabulary_refusal(group_id="group-a", document_id=None):
    """The 409 a tag vocabulary write sends when it finds the group changed: from a tag create,
    recolour or rename, from a bulk tagging batch, or, naming the document, from a metadata save."""
    refusal = {"error": VOCABULARY_CONFLICT_MESSAGE, "error_code": VOCABULARY_CONFLICT_CODE, "group_id": group_id}
    if document_id is not None:
        refusal["document_id"] = document_id
    return refusal


# A download route sends each file with these protective headers (the Cache-Control as the
# browser receives it), names it as an attachment, and names a multi-document archive this.
DOWNLOAD_HEADERS = {
    "Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}
GROUP_ARCHIVE_NAME = "group-documents.zip"


def attachment(file_name):
    return {"Content-Disposition": f'attachment; filename="{file_name}"'}


@dataclass
class OperationReply:
    method: str
    path: str
    group_id: str
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


class GroupDocumentManagementFixture(GroupScreeningModel, GroupDocumentsFixture):
    """A small, explicitly scripted HTTP boundary, not a second document app."""

    def __init__(self, page):
        super().__init__(page)
        # The group-scoped screening routes the section's screening controls call (group_screening.py).
        self._init_group_screening()
        self.planned_operations = []
        self.completed_operations = []
        self.multipart_uploads = []
        self.failed_operations = []
        self.vocabulary = {}
        self.groups["group-b"] = group_context("group-b", "Operations group", role="DocumentManager")
        self.documents = {}
        self.versions = {}
        for group_id, role, title in (
            ("group-a", "Owner", "Research brief"), ("group-b", "DocumentManager", "Operations brief"),
        ):
            self.set_policy(group_id, role=role)
            owned = document(
                group_id, "same-document", title, timestamp=self.now,
                tags=["finance", "team"], keywords=["baseline"],
                publication_date="2026-09-01", document_actions=list(DOCUMENT_ACTIONS),
            )
            notes = document(
                group_id, "notes-document", "Field notes", timestamp=self.now - 1,
                tags=["team", "legacy/review"], document_actions=list(DOCUMENT_ACTIONS),
            )
            shared = document(
                "origin", "shared-report", "Published report", timestamp=self.now - 2,
                shared_group_active_id=group_id, shared_approval_status="approved",
                owner_group_name="Publishing group", tags=["finance"],
                document_actions=["download"],
            )
            denied_source = document(
                "origin", "source-denied", "Source download unavailable", timestamp=self.now - 3,
                shared_group_active_id=group_id, shared_approval_status="approved",
                owner_group_name="Publishing group", tags=[], document_actions=[],
            )
            pending = restricted(document(
                "origin", "pending-report", "Restricted pending title", timestamp=self.now - 4,
                shared_group_active_id=group_id, shared_approval_status="not_approved",
                owner_group_name="Publishing group",
            ))
            held = restricted(document(
                group_id, "held-report", "Restricted held title", timestamp=self.now - 5,
                content_screening={"state": "pending_review", "available": False, "finding_count": 1},
            ))
            held_share = restricted(document(
                "origin", "held-share", "Restricted shared title", timestamp=self.now - 6,
                shared_group_active_id=group_id, shared_approval_status="approved",
                owner_group_name="Publishing group",
                content_screening={"state": "scanning", "available": False, "finding_count": 0},
            ))
            pending["document_actions"] = []
            held["document_actions"] = ["delete"]
            held_share["document_actions"] = []
            for record in (pending, held, held_share):
                restricted_status(record)
            # The review actions the server computes for a manager: an owned current document can
            # be shared, a received share removed (and, while it awaits approval, approved), and
            # any other row only inspected.
            for record, actions in (
                (owned, ["inspect", "share"]), (notes, ["inspect", "share"]),
                (shared, ["inspect", "remove_share"]), (denied_source, ["inspect", "remove_share"]),
                (pending, ["inspect", "approve_share", "remove_share"]), (held, ["inspect"]),
                (held_share, ["inspect", "remove_share"]),
            ):
                record["document_collaboration_actions"] = actions
            self.documents[group_id] = [owned, notes, shared, denied_source, pending, held, held_share]
            # A historical revision can still be downloaded or deleted, and only inspected.
            previous = document(
                group_id, "previous-version", "Earlier research brief",
                timestamp=self.now - 86400, version=2, is_current_version=False,
                revision_family_id=owned["revision_family_id"], tags=["finance", "team"],
                document_actions=["delete", "download"], document_collaboration_actions=["inspect"],
            )
            self.versions[(group_id, "same-document")] = [copy.deepcopy(owned), previous]
            self.vocabulary[group_id] = {
                "finance": "#0078d4", "team": "#059669",
                "legacy/review": "#8b5cf6", "review": "#64748b",
            }
        page.on("requestfailed", self._request_failed)

    def set_policy(self, group_id="group-a", *, role=None, status="active"):
        """Recompute a group's context for a role and status, exactly as the server builds it.

        The document deployment extracts metadata, so an active manager's handshake carries
        `extract_metadata`; every other bit, including chat in a locked group, is the server's.
        """
        current = self.groups[group_id]
        self.groups[group_id] = group_context(
            group_id, current["workspace"]["name"], role=role or current["role"], status=status,
            enable_extract_meta_data=True,
        )

    def record(self, identifier, group_id="group-a"):
        return next(record for record in self.documents[group_id] if record["id"] == identifier)

    @property
    def operation_requests(self):
        return [
            entry for entry in self.requests
            if re.fullmatch(r"/api/groups/[^/]+/documents/.+", entry.path)
        ]

    def queue_operation(
        self, method, resource, *, response, body=None, query=None, status=200,
        files=None, records=(), remove_ids=(), vocabulary=None, versions=None,
        content_type=None, headers=None, group_id="group-a",
    ):
        assert group_id in self.groups
        reply = OperationReply(
            method=method, path=operation_path(resource, group_id), group_id=group_id,
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
        payload["version"] = "0.261.129"
        return payload

    def _request_failed(self, request):
        path = unquote(urlsplit(request.url).path)
        is_download = request.method in ("GET", "POST") and path.endswith("/download")
        if not is_download and re.fullmatch(r"/api/groups/[^/]+/documents/.+", path):
            self.failed_operations.append((request.method, request.url, request.failure))

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(f"{route.request.method} {route.request.url}")
            route.abort()
            return
        super()._route(route)

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
        match = re.fullmatch(r"/api/groups/([^/]+)/documents/(.+)", entry.path)
        assert match, f"Not an immutable group operation: {entry}"
        group_id, resource = match.groups()
        assert group_id in self.groups, entry
        method, body = entry.method, entry.body
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
        if resource.endswith("/download"):
            assert method == "GET" and resource.count("/") == 1 and body is None, entry
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
        assert "/" not in resource and method == "PATCH", f"Unsupported group operation: {entry}"
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
                "Uploads must contain only repeated file fields, not group aliases."
            )
            assert part.get_filename(), "Every upload part must be a file."
            files.append({
                "name": part.get_filename(), "mimeType": part.get_content_type(),
                "buffer": part.get_payload(decode=True),
            })
        assert files, "No files were uploaded."
        return files

    def _apply_response(self, reply):
        rows = self.documents[reply.group_id]
        replacements = {record["id"]: record for record in reply.records}
        assert len(replacements) == len(reply.records), "Duplicate scripted document IDs."
        rows = [record for record in rows if record["id"] not in reply.remove_ids]
        retained_ids = {record["id"] for record in rows}
        self.documents[reply.group_id] = [
            copy.deepcopy(replacements.get(record["id"], record)) for record in rows
        ] + [copy.deepcopy(record) for identifier, record in replacements.items() if identifier not in retained_ids]
        for identifier, versions in reply.versions.items():
            self.versions[(reply.group_id, identifier)] = copy.deepcopy(versions)
        if reply.vocabulary is not None:
            self.vocabulary[reply.group_id] = copy.deepcopy(reply.vocabulary)

    def _dispatch(self, route, entry):
        if entry.path.startswith(SCREENING_PREFIX):
            self._serve_screening(route, entry)
            return
        if re.fullmatch(r"/api/groups/[^/]+/documents/.+", entry.path):
            self._validate_operation(entry)
            assert self.planned_operations, f"Unplanned document operation: {entry}"
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
                    headers={**DOWNLOAD_HEADERS, **reply.headers},
                )
            else:
                self._json(route, reply.response, reply.status)
            return
        if entry.path == "/api/group_documents/tags" and entry.method == "GET":
            assert set(entry.query) == {"group_id"} and len(entry.query["group_id"]) == 1, entry
            group_id = entry.query["group_id"][0]
            assert group_id in self.groups, entry
            if group_id in self.denied_groups:
                self._json(route, {"error": GROUP_DOCUMENTS_DENIED_ERROR}, 403)
            elif not self.groups[group_id]["document_permissions"]["can_view"]:
                self._json(route, {"error": GROUP_DOCUMENTS_STATUS_ERROR}, 403)
            else:
                counts = self.facets(group_id)["by_tag"]
                self._json(route, {"tags": [
                    {"name": name, "color": color, "count": counts.get(name, 0)}
                    for name, color in sorted(self.vocabulary[group_id].items())
                ]})
            return
        if entry.path.startswith("/api/group_documents") or self._is_shell_request(entry):
            super()._dispatch(route, entry)
            return
        self.unexpected_requests.append(f"{entry.method} {entry.path}")
        self._json(route, {"error": "Unexpected group management fixture request."}, 500)

    def _is_shell_request(self, entry):
        if entry.method == "GET":
            return entry.path in SHELL_READS or any(
                entry.path == f"/api/v2/workspaces/group/{group_id}" for group_id in self.groups
            )
        return (entry.method, entry.path) in (
            ("PATCH", "/api/groups/setActive"), ("POST", "/api/user/settings"),
        )

    def assert_clean(self):
        # Deliberately bypass M2A's unconditional prohibition of document writes.
        WorkspaceAuthoringFixture.assert_clean(self)
        assert not self.planned_operations, f"Expected operations were not made: {self.planned_operations}"
        assert not self.deferred_paths, f"Unused response gates: {self.deferred_paths}"
        assert not self.failed_operations, f"Document mutations were aborted: {self.failed_operations}"
        assert not self.classic_visits, "M2B unexpectedly fell back to the classic workspace."
        assert len(self.completed_operations) == len(self.operation_requests)
        for entry in self.requests:
            assert not entry.path.startswith("/api/documents"), f"Personal document traffic: {entry}"
            if re.fullmatch(r"/api/groups/[^/]+/documents/.+", entry.path):
                self._validate_operation(entry)
            elif entry.path.startswith(SCREENING_PREFIX):
                self._validate_screening_request(entry)
            elif entry.path.startswith("/api/group_documents"):
                assert entry.method == "GET", f"Legacy group document mutation: {entry}"
                assert len(entry.query.get("group_id", [])) == 1 and "group_ids" not in entry.query, entry
                assert entry.query["group_id"][0] in self.groups, entry
            else:
                assert self._is_shell_request(entry), f"Unexpected API: {entry}"
                if entry.path == "/api/user/settings" and entry.method == "POST":
                    assert set(entry.body) == {"settings"}, entry
                    assert set(entry.body["settings"]) <= PRESENTATION_SETTINGS, entry
                elif entry.path == "/api/groups/setActive" and entry.method == "PATCH":
                    assert not entry.query and set(entry.body) == {"groupId"}, entry
                    assert entry.body["groupId"] in self.groups, entry


@pytest.fixture
def group_management_ui(page):
    fixture = GroupDocumentManagementFixture(page)
    yield fixture
    fixture.assert_clean()
