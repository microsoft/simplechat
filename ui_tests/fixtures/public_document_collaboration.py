# public_document_collaboration.py
"""
Closed M3C public generated-artifact approval HTTP fixtures for the real V2 SPA.
Version: 0.261.179
Implemented in: 0.261.134
A configured workspace carries the server's review handshake (public_context) unless a test scripts
its own: 0.261.168
The review states, pending rows, receipts, refusals and partial outcomes are the real collaboration
routes', held to them by functional_tests/test_public_document_fixture_parity.py: 0.261.179

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
from ui_tests.fixtures.public_documents import (
    PUBLIC_DOCUMENT_NOT_FOUND_ERROR, PUBLIC_DOCUMENTS_DENIED_ERROR, PUBLIC_DOCUMENTS_STATUS_ERROR, document,
)
from ui_tests.fixtures.public_workspace import connect_options  # noqa: F401
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


# The collaboration routes' refusals and partial outcomes (functions_public_document_collaboration.py
# and functions_public_document_publication.py), held to them by
# functional_tests/test_public_document_fixture_parity.py. A refusal is a code and its sentence. A
# review read that its read checks refuse is `collaboration_unavailable` with the read's sentence --
# a status that bars reading, a document that does not exist (or no longer does, after a decision
# removed it), or, unreachable today since everyone reads a public workspace, a caller with no access.
def collaboration_refusal(code, message):
    return {"error": code, "message": message}


STATE_CONFLICT = collaboration_refusal("state_conflict", "The document state changed. Refresh before retrying.")
COLLABORATION_GONE = collaboration_refusal("collaboration_gone", "The document is not available in this public workspace.")
COLLABORATION_MISSING = collaboration_refusal("collaboration_unavailable", PUBLIC_DOCUMENT_NOT_FOUND_ERROR)
COLLABORATION_DENIED = collaboration_refusal("collaboration_unavailable", PUBLIC_DOCUMENTS_DENIED_ERROR)
COLLABORATION_STATUS_REFUSED = collaboration_refusal("collaboration_unavailable", PUBLIC_DOCUMENTS_STATUS_ERROR)
PUBLICATION_HANDOFF_ERROR = {
    "stage": "queue", "code": "publication_handoff_unconfirmed",
    "message": "Approval was recorded, but processing has not been confirmed. Reconcile the existing handoff.",
}
# An approval whose processing handoff failed records the decision, then reports that the handoff
# was interrupted, was not confirmed, and sent no decision notice.
FAILED_HANDOFF_ERRORS = (
    {
        "stage": "publication", "code": "publication_reconciliation_required",
        "message": "The existing decision or processing handoff needs reconciliation; no second copy was requested.",
    },
    PUBLICATION_HANDOFF_ERROR,
    {
        "stage": "notifications", "code": "publication_notification_incomplete",
        "message": "Decision notification delivery has not been confirmed.",
    },
)


def publication(*, status="pending_approval", requester=False, actions=()):
    return {
        "status": status, "is_requester": requester,
        "requested_by_user_id": OWNER_ID if requester else "publication-requester",
        "requested_by_display_name": "Workspace editor" if requester else "Publishing colleague",
        "requested_at": "2026-09-22T10:00:00Z", "actions": list(actions),
    }


def publication_state(
    identifier, *, workspace_id="pub-a", version=3, etag=None, actions=("inspect",), publication_review=None,
):
    """The review state: the document's collaboration actions and, for a generated artifact, its
    publication request."""
    return {
        "schema_version": 1, "public_workspace_id": workspace_id, "document_id": identifier,
        "document_version": version, "etag": etag or f'"publication:{workspace_id}:{identifier}:1"',
        "actions": list(actions), "publication": copy.deepcopy(publication_review),
    }


def pending_artifact(workspace_id, identifier, title, *, timestamp, review, actions):
    """A generated artifact awaiting publication, as the public list projection shows it: the
    document with its request (unlike a group's, it is not reduced to its held fields -- a product
    finding the parity test pins), not yet processed, and no document operation until decided."""
    record = document(
        workspace_id, identifier, title, timestamp=timestamp, status="Pending approval", tags=[],
        percentage_complete=0, user_id=review["requested_by_user_id"],
    )
    for field in ("num_chunks", "document_intelligence_extraction_mode"):
        record.pop(field)
    record.update({
        "generated_artifact_promotion_status": "pending_approval",
        "generated_artifact_requested_by_user_id": review["requested_by_user_id"],
        "generated_artifact_requested_by_display_name": review["requested_by_display_name"],
        "generated_artifact_requested_at": review["requested_at"],
        "document_actions": [], "document_collaboration_actions": list(actions),
    })
    return record


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
                # Every document of a workspace that offers review can be inspected; the server
                # computes the inline actions fresh, never from storage.
                record["document_collaboration_actions"] = ["inspect"]
                self.reviews[(workspace_id, identifier)] = publication_state(identifier, workspace_id=workspace_id)
            # The viewer is a document manager, and only a hosting workspace's manager can request a
            # publication, so the viewer's own request offers approve and reject as well as cancel.
            for identifier, requester in (("pending-publication", False), ("requested-publication", True)):
                actions = (
                    ["inspect", "approve_artifact", "reject_artifact", "cancel_artifact"] if requester
                    else ["inspect", "approve_artifact", "reject_artifact"]
                )
                title = "Requested generated content" if requester else "Unreleased generated content"
                review = publication(requester=requester, actions=actions[1:])
                self.documents[workspace_id].append(pending_artifact(
                    workspace_id, identifier, title, timestamp=self.now - 8, review=review, actions=actions,
                ))
                self.reviews[(workspace_id, identifier)] = publication_state(
                    identifier, workspace_id=workspace_id, actions=actions, publication_review=review,
                )

    def configure_workspace(self, workspace_id="pub-a", *, role="DocumentManager", status="active", operations=None):
        """The server's context for a role and status; a test that scripts its own review handshake
        passes `operations`."""
        self.set_policy(workspace_id, role=role, status=status)
        if operations is not None:
            self.workspaces[workspace_id]["document_collaboration"] = {"schema_version": 1, "operations": list(operations)}

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
            if workspace_id in self.denied_workspaces:
                self._json(route, COLLABORATION_DENIED, 403)
                return
            if not self.workspaces[workspace_id]["document_permissions"]["can_view"]:
                self._json(route, COLLABORATION_STATUS_REFUSED, 403)
                return
            state = self.reviews.get((workspace_id, identifier))
            if state is None:
                self._json(route, COLLABORATION_MISSING, 404)
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
