# group_document_collaboration.py
"""
Closed M2C sharing/publication HTTP fixtures for the real production V2 SPA.
Version: 0.261.161
Implemented in: 0.261.130
The review states, recipient directory, receipts, refusals and partial outcomes are the real
collaboration routes', held to them by functional_tests/test_group_document_fixture_parity.py.

Reuse the existing local asset boundary, M2A reads, response gates, request
recording and Azure Playwright connection options. Collaboration decisions are
one-shot scripted responses with exact immutable targets and ETags. Only HTTP
and server snapshots are scripted; React state, workers and notification
delivery are not simulated. Ordinary removal uses 404s; a separately bound
recipient repair fixture exposes only verified negative-cleanup metadata.
"""

import copy
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import pytest

from ui_tests.fixtures.group_document_management import (
    GroupDocumentManagementFixture, OperationReply, PRESENTATION_SETTINGS, operation_path,
)
from ui_tests.fixtures.group_documents import (
    GROUP_DOCUMENT_NOT_FOUND_ERROR, GROUP_DOCUMENTS_DENIED_ERROR, GROUP_DOCUMENTS_STATUS_ERROR, document,
    pending_artifact,
)
from ui_tests.fixtures.group_workspace import connect_options  # noqa: F401
from ui_tests.fixtures.workspace_authoring import ORIGIN, OWNER_ID, WorkspaceAuthoringFixture


COLLABORATION_OPERATIONS = (
    "inspect", "share", "unshare", "approve_share", "remove_share",
    "approve_artifact", "reject_artifact", "cancel_artifact",
)
ACTION_ROUTES = {
    "share": ("POST", "share"),
    "unshare": ("DELETE", "share"),
    "approve_share": ("POST", "approve-share"),
    "remove_share": ("DELETE", "received-share"),
    "approve_artifact": ("POST", "artifact/approve"),
    "reject_artifact": ("POST", "artifact/reject"),
    "cancel_artifact": ("POST", "artifact/cancel"),
}
COLLABORATION_PATH = re.compile(
    r"/api/groups/([^/]+)/documents/([^/]+)/"
    r"(sharing(?:/targets)?|share(?:/[^/]+)?|approve-share|received-share|artifact/(?:approve|reject|cancel))"
)


def collaboration_path(identifier, suffix="sharing", group_id="group-a"):
    return operation_path(f"{quote(identifier, safe='')}/{suffix}", group_id)


# The collaboration routes' refusals and partial outcomes (functions_group_document_collaboration.py
# and functions_group_document_publication.py), held to them by
# functional_tests/test_group_document_fixture_parity.py. A refusal is a code and its sentence; a
# reader outside the group, or in a status that bars reading, is refused as the read routes refuse.
def collaboration_refusal(code, message):
    return {"error": code, "message": message}


STATE_CONFLICT = collaboration_refusal("state_conflict", "The document state changed. Refresh before retrying.")
COLLABORATION_GONE = collaboration_refusal("collaboration_gone", "The document is not available in this group.")
COLLABORATION_DENIED = collaboration_refusal("collaboration_unavailable", GROUP_DOCUMENTS_DENIED_ERROR)
COLLABORATION_STATUS_REFUSED = collaboration_refusal("collaboration_unavailable", GROUP_DOCUMENTS_STATUS_ERROR)
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


def effect_error(stage):
    """A decision that changed access but could not confirm one of its effects: `search`, `index`,
    `cache` or `notifications`."""
    return {
        "stage": stage, "code": f"{stage}_repair_required",
        "message": f"The {stage} update could not be confirmed. Refresh before retrying.",
    }


def recipient(identifier, name, approval_status="not_approved"):
    return {
        "id": identifier, "name": name, "description": f"Shared work for {name}.",
        "approval_status": approval_status,
    }


def publication(*, status="pending_approval", requester=False, actions=()):
    return {
        "status": status, "is_requester": requester,
        "requested_by_user_id": OWNER_ID if requester else "publication-requester",
        "requested_by_display_name": "Workspace editor" if requester else "Publishing colleague",
        "requested_at": "2026-09-22T10:00:00Z", "actions": list(actions),
    }


def sharing_state(
    identifier, *, group_id="group-a", owner_group_id=None, owner_name=None,
    relationship="owner", version=3, etag=None, actions=("inspect",),
    recipients=(), publication_state=None,
):
    assert relationship in ("owner", "not_approved", "approved")
    return {
        "schema_version": 1, "group_id": group_id, "document_id": identifier,
        "document_version": version, "etag": etag or f'"review:{group_id}:{identifier}:1"',
        "owner_group": {
            "id": owner_group_id or group_id,
            "name": owner_name or ("Research group" if group_id == "group-a" else "Operations group"),
        },
        "relationship": relationship, "actions": list(actions),
        "recipients": copy.deepcopy(list(recipients)),
        "publication": copy.deepcopy(publication_state),
    }


def cleanup_repair_state(
    identifier, *, group_id, source_group_id, source_name, version,
    relationship="removed", cleanup_pending=False, etag=None,
):
    """Project a verified negative receipt without granting ordinary read access."""
    assert relationship in ("removed", "denied")
    assert source_group_id and source_group_id != group_id
    assert isinstance(version, int) and not isinstance(version, bool) and version > 0
    state = sharing_state(
        identifier, group_id=group_id, owner_group_id=source_group_id,
        owner_name=source_name, version=version, relationship="approved",
        etag=etag or f'"cleanup:{group_id}:{identifier}:{version}"',
        actions=["inspect", "remove_share"] if cleanup_pending else ["inspect"],
    )
    state["relationship"] = relationship
    return state


def collaboration_receipt(
    identifier, action, state, *, group_id="group-a", status="applied",
    target_group_id=None, errors=(),
):
    assert action in ACTION_ROUTES
    result = {
        "schema_version": 1, "group_id": group_id, "document_id": identifier,
        "action": action, "status": status, "state": state,
        "errors": copy.deepcopy(list(errors)),
    }
    if action in ("share", "unshare"):
        assert target_group_id and target_group_id != group_id
        result["target_group_id"] = target_group_id
    else:
        assert target_group_id is None
    return result


@dataclass
class CollaborationReply(OperationReply):
    document_id: str = ""
    sharing_after: dict | None = None
    gone: bool = False


class GroupDocumentCollaborationFixture(GroupDocumentManagementFixture):
    def __init__(self, page):
        super().__init__(page)
        self.reviews = {}
        self.repair_bindings = {}
        self.target_catalog = {}
        self.document_failures = {}
        self.notifications = []
        self.notification_reads = []
        for group_id in self.groups:
            self.configure_group(group_id)
            for record in self.documents[group_id]:
                identifier = record["id"]
                owned = record["group_id"] == group_id
                if owned:
                    actions = ["inspect", "share", "unshare"] if identifier != "held-report" else ["inspect", "unshare"]
                    recipients = [
                        recipient("target-01", "Destination 01", "approved"),
                        recipient("target-02", "Destination 02"),
                    ]
                else:
                    actions = ["inspect", "remove_share"]
                    if record["shared_approval_status"] == "not_approved":
                        actions.append("approve_share")
                    recipients = [recipient(
                        group_id, self.groups[group_id]["workspace"]["name"],
                        record["shared_approval_status"],
                    )]
                record["document_collaboration_actions"] = actions
                self.reviews[(group_id, identifier)] = sharing_state(
                    identifier, group_id=group_id, owner_group_id=record["group_id"],
                    owner_name=self.groups[group_id]["workspace"]["name"] if owned else "Publishing group",
                    relationship=record["shared_approval_status"], actions=actions, recipients=recipients,
                )
            # Each generated artifact awaits approval. The Owner decides one; the other was requested
            # by the viewer, as the member who asked for it (the role the suite reviews it under).
            for identifier, requester in (("pending-publication", False), ("requested-publication", True)):
                actions = ["inspect", "cancel_artifact"] if requester else ["inspect", "approve_artifact", "reject_artifact"]
                request = publication(requester=requester, actions=actions[1:])
                record = pending_artifact(
                    document(
                        group_id, identifier, "Unreleased generated content", timestamp=self.now - 8, tags=[],
                    ),
                    requested_by_user_id=request["requested_by_user_id"],
                    requested_by_display_name=request["requested_by_display_name"],
                    requested_at=request["requested_at"],
                )
                record["document_collaboration_actions"] = actions
                self.documents[group_id].append(record)
                self.reviews[(group_id, identifier)] = sharing_state(
                    identifier, group_id=group_id, actions=actions, publication_state=request,
                )
            self.target_catalog[group_id] = [
                {"id": group_id, "name": self.groups[group_id]["workspace"]["name"], "description": "Self must not be offered."},
                *[
                    {
                        "id": f"target-{index:02d}", "name": f"Destination {index:02d}",
                        "description": f"Eligible destination number {index:02d}.",
                    }
                    for index in range(1, 36)
                ],
            ]

    def configure_group(self, group_id="group-a", *, role=None, status="active", operations=None):
        """Recompute a group's context, whose collaboration handshake is the server's. A test may
        still pass `operations` to intersect the handshake with a narrower record-level scenario."""
        super().set_policy(group_id, role=role, status=status)
        if operations is not None:
            self.groups[group_id]["document_collaboration"] = {"schema_version": 1, "operations": list(operations)}

    def review_state(self, identifier="same-document", group_id="group-a"):
        return self.reviews[(group_id, identifier)]

    def install_cleanup_repair(self, identifier, *, group_id="group-a", relationship="removed"):
        original = self.record(identifier, group_id)
        source_id, version = original["owner_group_id"], original["version"]
        state = cleanup_repair_state(
            identifier, group_id=group_id, source_group_id=source_id,
            source_name=original["owner_group_name"], version=version, relationship=relationship,
        )
        key = (group_id, identifier)
        self.repair_bindings[key] = (source_id, version)
        self.reviews[key] = state
        self.document_failures[key] = 404
        self.documents[group_id] = [record for record in self.documents[group_id] if record["id"] != identifier]
        return state

    def add_off_page_document(self):
        for index in range(26):
            self.documents["group-a"].append(document(
                "group-a", f"filler-{index:02d}", f"Earlier page item {index:02d}",
                timestamp=self.now - 20 - index, tags=[], document_actions=[],
                document_collaboration_actions=["inspect"],
            ))
        record = document(
            "group-a", "off-page", "Exact off-page revision", timestamp=self.now - 86400,
            version=7, tags=[], document_actions=[],
            document_collaboration_actions=["inspect", "share", "unshare"],
        )
        self.documents["group-a"].append(record)
        self.reviews[("group-a", "off-page")] = sharing_state(
            "off-page", version=7, actions=["inspect", "share", "unshare"],
        )
        return record

    @property
    def operation_requests(self):
        return [
            entry for entry in self.requests
            if entry.method != "GET" and COLLABORATION_PATH.fullmatch(entry.path)
        ]

    def queue_decision(
        self, identifier, action, *, expected_etag, response, status=200,
        target_group_id=None, sharing_after=None, records=(), gone=False,
        content_type=None, group_id="group-a",
    ):
        method, suffix = ACTION_ROUTES[action]
        body = {"expected_etag": expected_etag}
        if action == "share":
            assert target_group_id and target_group_id != group_id
            body["target_group_id"] = target_group_id
        elif action == "unshare":
            assert target_group_id and target_group_id != group_id
            suffix = f"{suffix}/{quote(target_group_id, safe='')}"
        else:
            assert target_group_id is None
        reply = CollaborationReply(
            method=method, path=collaboration_path(identifier, suffix, group_id),
            group_id=group_id, document_id=identifier,
            body=body, response=copy.deepcopy(response), status=status, content_type=content_type,
            records=copy.deepcopy(list(records)), remove_ids=(identifier,) if gone else (),
            sharing_after=copy.deepcopy(sharing_after), gone=gone,
        )
        self.planned_operations.append(reply)
        return reply

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["version"] = "0.261.130"
        return payload

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        if f"{parsed.scheme}://{parsed.netloc}" == ORIGIN and parsed.path == "/notifications":
            route.fulfill(content_type="text/html", body="""<!doctype html>
<html lang="en"><head><title>Notifications fixture</title></head><body>
<main><h1>Notifications</h1><div id="loading-indicator">Loading</div>
<div id="notifications-container"></div><div id="pagination-container"></div></main>
<script src="/static/js/notifications.js"></script></body></html>""")
            return
        super()._route(route)

    def _request_failed(self, request):
        if request.method != "GET":
            super()._request_failed(request)

    def _validate_operation(self, entry):
        match = COLLABORATION_PATH.fullmatch(entry.path)
        assert match, f"Only immutable M2C paths are permitted: {entry}"
        group_id, identifier, suffix = match.groups()
        assert group_id in self.groups and identifier
        if suffix.startswith("sharing"):
            assert entry.method == "GET" and entry.body is None, entry
            if suffix == "sharing":
                assert not entry.query, entry
            else:
                assert set(entry.query) <= {"search", "page", "page_size"}, entry
                assert all(len(values) == 1 for values in entry.query.values()), entry
                assert int(entry.query.get("page", ["0"])[0]) >= 1, entry
                assert entry.query.get("page_size") == ["25"], entry
            return
        assert not entry.query, f"Scope and ETag must not use query aliases: {entry}"
        assert isinstance(entry.body, dict), entry
        expected_fields = {"expected_etag", "target_group_id"} if suffix == "share" else {"expected_etag"}
        assert set(entry.body) == expected_fields, entry
        assert isinstance(entry.body["expected_etag"], str) and entry.body["expected_etag"].strip(), entry
        if suffix == "share":
            assert entry.method == "POST"
            target = entry.body["target_group_id"]
            assert isinstance(target, str) and target and target != group_id, entry
        elif suffix.startswith("share/"):
            assert entry.method == "DELETE" and suffix.split("/", 1)[1] != group_id, entry
        elif suffix == "received-share":
            assert entry.method == "DELETE", entry
        else:
            assert entry.method == "POST", entry

    def _apply_response(self, reply):
        assert isinstance(reply, CollaborationReply)
        super()._apply_response(reply)
        key = (reply.group_id, reply.document_id)
        if reply.sharing_after is not None:
            self.reviews[key] = copy.deepcopy(reply.sharing_after)
        if reply.gone:
            self.reviews.pop(key, None)
            self.repair_bindings.pop(key, None)
            self.document_failures[key] = 404

    def _dispatch(self, route, entry):
        if entry.path == "/api/notifications/count" and entry.method == "GET":
            self._json(route, {"success": True, "count": 0, "chat_completion_audio_enabled": False})
            return
        if entry.path == "/api/notifications" and entry.method == "GET":
            self._json(route, {
                "success": True, "notifications": self.notifications, "total": len(self.notifications),
                "page": 1, "per_page": 20, "has_more": False,
            })
            return
        if entry.path.startswith("/api/notifications/") and entry.path.endswith("/read") and entry.method == "POST":
            identifier = entry.path.split("/")[3]
            notice = next(item for item in self.notifications if item["id"] == identifier)
            notice["is_read"] = True
            self.notification_reads.append(identifier)
            self._json(route, {"success": True})
            return
        match = COLLABORATION_PATH.fullmatch(entry.path)
        if match and entry.method == "GET":
            self._validate_operation(entry)
            group_id, identifier, suffix = match.groups()
            state = self.reviews.get((group_id, identifier))
            if state is not None and state["relationship"] in ("removed", "denied"):
                binding = self.repair_bindings.get((group_id, identifier))
                verified = (
                    binding == (state["owner_group"]["id"], state["document_version"])
                    and state["group_id"] == group_id and state["document_id"] == identifier
                    and self.document_failures.get((group_id, identifier)) == 404
                    and self.groups[group_id]["role"] in ("Owner", "Admin", "DocumentManager")
                    and state["owner_group"]["id"] != group_id
                    and not state["recipients"] and state["publication"] is None
                    and set(state["actions"]) <= {"inspect", "remove_share"}
                    and suffix == "sharing"
                )
                if not verified:
                    state = None
            if group_id in self.denied_groups:
                self._json(route, COLLABORATION_DENIED, 403)
            elif not self.groups[group_id]["document_permissions"]["can_view"]:
                self._json(route, COLLABORATION_STATUS_REFUSED, 403)
            elif state is None:
                self._json(route, COLLABORATION_GONE, 404)
            elif suffix == "sharing":
                self._json(route, state)
            else:
                query = entry.query.get("search", [""])[0].lower()
                candidates = sorted((
                    target for target in self.target_catalog[group_id]
                    if target["id"] != group_id
                    and (not query or any(query in target[field].lower() for field in ("name", "description", "id")))
                ), key=lambda target: (target["name"].casefold(), target["id"]))
                page = int(entry.query["page"][0])
                self._json(route, {
                    "groups": candidates[(page - 1) * 25:page * 25],
                    "page": page, "page_size": 25, "total_count": len(candidates),
                })
            return
        detail = re.fullmatch(r"/api/group_documents/([^/]+)(?:/versions)?", entry.path)
        if detail and entry.method == "GET":
            group_id = entry.query.get("group_id", [None])[0]
            failure = self.document_failures.get((group_id, detail[1]))
            if failure is not None:
                assert entry.query == {"group_id": [group_id]}
                self._json(route, {"error": GROUP_DOCUMENT_NOT_FOUND_ERROR}, failure)
                return
        super()._dispatch(route, entry)

    def assert_clean(self):
        WorkspaceAuthoringFixture.assert_clean(self)
        assert not self.planned_operations, self.planned_operations
        assert not self.deferred_paths, self.deferred_paths
        assert not self.failed_operations, f"A collaboration mutation was aborted: {self.failed_operations}"
        assert not self.classic_visits, "Review silently navigated to classic management."
        assert len(self.completed_operations) == len(self.operation_requests)
        for entry in self.requests:
            assert not entry.path.startswith(("/api/documents", "/api/users")), entry
            if entry.path.startswith("/api/groups/") and "/documents/" in entry.path:
                self._validate_operation(entry)
            elif entry.path.startswith("/api/group_documents"):
                assert entry.method == "GET", f"Legacy active-scoped mutation: {entry}"
                assert len(entry.query.get("group_id", [])) == 1 and "group_ids" not in entry.query, entry
                assert entry.query["group_id"][0] in self.groups, entry
            elif entry.path.startswith("/api/notifications"):
                assert entry.method == "GET" or (
                    entry.method == "POST" and entry.path.endswith("/read") and entry.body is None
                ), entry
            else:
                assert self._is_shell_request(entry), f"Unexpected collaboration API: {entry}"
                if (entry.method, entry.path) == ("POST", "/api/user/settings"):
                    assert set(entry.body) == {"settings"}
                    assert set(entry.body["settings"]) <= PRESENTATION_SETTINGS, entry
                elif (entry.method, entry.path) == ("PATCH", "/api/groups/setActive"):
                    assert not entry.query and set(entry.body) == {"groupId"}
                    assert entry.body["groupId"] in self.groups


@pytest.fixture
def group_collaboration_ui(page):
    fixture = GroupDocumentCollaborationFixture(page)
    yield fixture
    fixture.assert_clean()
