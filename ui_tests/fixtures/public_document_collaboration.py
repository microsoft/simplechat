# public_document_collaboration.py
"""
Closed M3C public generated-artifact approval HTTP fixtures for the real V2 SPA.
Version: 0.261.134
Implemented in: 0.261.134

Extend the M3B management boundary with the publication review surface. Public
workspaces have no cross-workspace sharing in this milestone, so only generated
artifact decisions exist: GET /publication is the authoritative per-document
review-state read and POST artifact/{approve,reject,cancel} are one-shot scripted
receipts. Every review and decision carries public_workspace_id and targets the
immutable /api/public-workspaces/<id>/documents/<id> path rather than an active
selection. Only HTTP and server snapshots are scripted; React state, workers and
notification delivery are never simulated.
"""

import copy
import re
from dataclasses import dataclass
from urllib.parse import quote

import pytest

from ui_tests.fixtures.public_document_management import (
    OperationReply, PRESENTATION_SETTINGS, PublicDocumentManagementFixture, operation_path,
)
from ui_tests.fixtures.public_documents import document
from ui_tests.fixtures.public_workspace import (  # noqa: F401
    PUBLIC_MANAGER_ROLES, connect_options,
)
from ui_tests.fixtures.workspace_authoring import OWNER_ID, WorkspaceAuthoringFixture


COLLABORATION_OPERATIONS = ("inspect", "approve_artifact", "reject_artifact", "cancel_artifact")
ARTIFACT_ROUTES = {
    "approve_artifact": "artifact/approve",
    "reject_artifact": "artifact/reject",
    "cancel_artifact": "artifact/cancel",
}
COLLABORATION_PATH = re.compile(
    r"/api/public-workspaces/([^/]+)/documents/([^/]+)/"
    r"(publication|artifact/(?:approve|reject|cancel))"
)


def collaboration_path(identifier, suffix="publication", workspace_id="pub-a"):
    return operation_path(f"{quote(identifier, safe='')}/{suffix}", workspace_id)


def publication(*, status="pending_approval", requester=False, actions=()):
    return {
        "status": status, "is_requester": requester,
        "requested_by_user_id": OWNER_ID if requester else "publication-requester",
        "requested_by_display_name": "Workspace editor" if requester else "Publishing colleague",
        "requested_at": "2026-09-22T10:00:00Z", "actions": list(actions),
    }


def publication_state(
    identifier, *, workspace_id="pub-a", version=3, etag=None, publication_review=None,
):
    return {
        "schema_version": 1, "public_workspace_id": workspace_id, "document_id": identifier,
        "document_version": version, "etag": etag or f'"publication:{workspace_id}:{identifier}:1"',
        "publication": copy.deepcopy(publication_review),
    }


def collaboration_receipt(
    identifier, action, state, *, public_workspace_id="pub-a", status="applied", errors=(),
):
    assert action in ARTIFACT_ROUTES
    return {
        "schema_version": 1, "public_workspace_id": public_workspace_id, "document_id": identifier,
        "action": action, "status": status, "state": state,
        "errors": copy.deepcopy(list(errors)),
    }


@dataclass
class CollaborationReply(OperationReply):
    document_id: str = ""
    publication_after: dict | None = None
    gone: bool = False


class PublicDocumentCollaborationFixture(PublicDocumentManagementFixture):
    """A small, explicitly scripted HTTP boundary, not a second review app."""

    def __init__(self, page):
        super().__init__(page)
        self.reviews = {}
        for workspace_id in self.workspaces:
            self.configure_workspace(workspace_id)
            for record in self.documents[workspace_id]:
                identifier = record["id"]
                # A document with no per-document actions advertises no review affordance,
                # even though the workspace context advertises the collaboration operations.
                actions = ["inspect"] if record.get("document_actions") else []
                record["document_collaboration_actions"] = actions
                if actions:
                    self.reviews[(workspace_id, identifier)] = publication_state(
                        identifier, workspace_id=workspace_id,
                    )
            for identifier, requester in (("pending-publication", False), ("requested-publication", True)):
                actions = (
                    ["inspect", "cancel_artifact"] if requester
                    else ["inspect", "approve_artifact", "reject_artifact"]
                )
                title = "Requested generated content" if requester else "Unreleased generated content"
                record = document(
                    workspace_id, identifier, title, timestamp=self.now - 8,
                    status="Pending approval", tags=[],
                )
                record.update({
                    "generated_artifact_promotion_status": "pending_approval",
                    "document_actions": [], "document_collaboration_actions": actions,
                })
                self.documents[workspace_id].append(record)
                self.reviews[(workspace_id, identifier)] = publication_state(
                    identifier, workspace_id=workspace_id,
                    publication_review=publication(requester=requester, actions=actions[1:]),
                )

    def configure_workspace(self, workspace_id="pub-a", *, role="DocumentManager", status="active", operations=None):
        self.set_policy(workspace_id, role=role, status=status)
        context = self.workspaces[workspace_id]
        if operations is None:
            manager = context["role"] in PUBLIC_MANAGER_ROLES
            operations = COLLABORATION_OPERATIONS if manager and status == "active" else ("inspect",)
            if status in ("inactive", "unknown"):
                operations = ()
        context["document_collaboration"] = {"schema_version": 1, "operations": list(operations)}

    def review_state(self, identifier="same-document", workspace_id="pub-a"):
        return self.reviews[(workspace_id, identifier)]

    def queue_decision(
        self, identifier, action, *, expected_etag, response, status=200,
        publication_after=None, records=(), gone=False, content_type=None, workspace_id="pub-a",
    ):
        suffix = ARTIFACT_ROUTES[action]
        reply = CollaborationReply(
            method="POST", path=collaboration_path(identifier, suffix, workspace_id),
            workspace_id=workspace_id, document_id=identifier,
            body={"expected_etag": expected_etag}, response=copy.deepcopy(response), status=status,
            content_type=content_type, records=copy.deepcopy(list(records)),
            remove_ids=(identifier,) if gone else (),
            publication_after=copy.deepcopy(publication_after), gone=gone,
        )
        self.planned_operations.append(reply)
        return reply

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["version"] = "0.261.134"
        return payload

    def _request_failed(self, request):
        if request.method != "GET":
            super()._request_failed(request)

    def _validate_operation(self, entry):
        match = COLLABORATION_PATH.fullmatch(entry.path)
        if not match:
            super()._validate_operation(entry)
            return
        workspace_id, identifier, suffix = match.groups()
        assert workspace_id in self.workspaces and identifier, entry
        if suffix == "publication":
            assert entry.method == "GET" and entry.body is None and not entry.query, entry
            return
        assert entry.method == "POST" and not entry.query, entry
        assert isinstance(entry.body, dict) and set(entry.body) == {"expected_etag"}, entry
        assert isinstance(entry.body["expected_etag"], str) and entry.body["expected_etag"].strip(), entry

    def _apply_response(self, reply):
        super()._apply_response(reply)
        if isinstance(reply, CollaborationReply):
            key = (reply.workspace_id, reply.document_id)
            if reply.publication_after is not None:
                self.reviews[key] = copy.deepcopy(reply.publication_after)
            if reply.gone:
                self.reviews.pop(key, None)

    def _dispatch(self, route, entry):
        match = COLLABORATION_PATH.fullmatch(entry.path)
        if match and entry.method == "GET" and match.group(3) == "publication":
            workspace_id, identifier, _ = match.groups()
            self._validate_operation(entry)
            if workspace_id in self.denied_workspaces or not self.workspaces[workspace_id]["document_permissions"]["can_view"]:
                self._json(route, {"error": "This public review is not available."}, 403)
                return
            state = self.reviews.get((workspace_id, identifier))
            if state is None:
                self._json(route, {"error": "This document or review no longer exists."}, 404)
            else:
                self._json(route, state)
            return
        super()._dispatch(route, entry)

    def assert_clean(self):
        # Bypass M3A's read-only prohibition; publication decisions are legitimate writes.
        WorkspaceAuthoringFixture.assert_clean(self)
        assert not self.planned_operations, f"Expected decisions were not made: {self.planned_operations}"
        assert not self.deferred_paths, f"Unused response gates: {self.deferred_paths}"
        assert not self.failed_operations, f"A publication decision was aborted: {self.failed_operations}"
        assert not self.classic_visits, "Review silently navigated to the classic public workspace."
        assert len(self.completed_operations) == len(self.operation_requests)
        assert not [entry for entry in self.requests if entry.path.startswith("/api/documents")], (
            "Public review made a personal document request."
        )
        assert not [entry for entry in self.requests if entry.path.startswith("/api/group_documents")], (
            "Public review made a group document request."
        )
        assert not [entry for entry in self.requests if entry.path.startswith("/api/groups")], (
            "Public review made a group workspace request."
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
            assert False, f"Unexpected mutation during public review: {entry}"
        for entry in self.requests:
            if entry.path.startswith("/api/public-workspaces/") and "/documents" in entry.path and not self._is_operation(entry):
                assert entry.method == "GET", f"Public document mutation outside the operation family: {entry}"
                assert "group_id" not in entry.query and "group_ids" not in entry.query, entry
                assert "public_workspace_id" not in entry.query, entry


@pytest.fixture
def public_collaboration_ui(page):
    fixture = PublicDocumentCollaborationFixture(page)
    yield fixture
    fixture.assert_clean()
