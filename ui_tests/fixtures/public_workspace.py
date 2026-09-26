# public_workspace.py
"""
Closed HTTP fixtures for the real V2 public workspace shell.
Version: 0.261.179
Implemented in: 0.261.132
Every context carries the server's document_management hint, as build_public_workspace_context
sends it: 0.261.167
Every context is the real builder's, held to it by
functional_tests/test_public_context_fixture_parity.py: 0.261.168
Its prompts section opens and every context carries the server's prompt_management hint: 0.261.178
Its identities and sync sections and their management hints, gated on File Sync: 0.261.179
The context carries the native membership hint and its Members manage section: 0.261.179

The public surface mirrors the group shell. Its documents and prompts sections are open, and a
manager role can be granted document management, the generated-artifact review and prompt
management. From M10B, a File-Sync deployment also opens read-only identities and file sources that
a manager of an active workspace manages. It never advertises native delegation, and every document,
prompt or connection read or operation carries its workspace id in the request path rather than an
active selection.
"""

import copy
from urllib.parse import unquote, urlsplit

import pytest

from ui_tests.fixtures.workspace_authoring import (
    OWNER_ID, SPA_INDEX, WorkspaceAuthoringFixture, connect_options,  # noqa: F401
    personal_scope_leak,
)


PUBLIC_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
# The statuses the builder recognizes; it reports any other as "unknown". A workspace is viewable in
# the first three.
PUBLIC_STATUSES = ("active", "locked", "upload_disabled", "inactive")
PUBLIC_VIEWABLE_STATUSES = ("active", "locked", "upload_disabled")
# functions_public_document_policy.PUBLIC_DOCUMENT_OPERATIONS, in the server's order.
PUBLIC_DOCUMENT_OPERATIONS = (
    "upload", "edit_metadata", "tag_documents", "manage_tags",
    "delete", "download", "extract_metadata", "reprocess",
)
# functions_public_document_policy.PUBLIC_DOCUMENT_COLLABORATION_OPERATIONS, in the server's order.
PUBLIC_DOCUMENT_COLLABORATION_OPERATIONS = ("inspect", "approve_artifact", "reject_artifact", "cancel_artifact")
# functions_public_prompt_policy.PUBLIC_PROMPT_OPERATIONS, in the server's order.
PUBLIC_PROMPT_OPERATIONS = ("create", "edit", "delete")
# functions_public_identity_policy.PUBLIC_IDENTITY_OPERATIONS, in the server's order.
PUBLIC_IDENTITY_OPERATIONS = ("create", "edit", "delete")
# functions_public_file_source_policy.PUBLIC_FILE_SOURCE_OPERATIONS, in the server's order.
PUBLIC_FILE_SOURCE_OPERATIONS = ("create", "edit", "delete", "sync", "test")
# functions_public_membership_policy.PUBLIC_MEMBERSHIP_OPERATIONS, in the server's order.
PUBLIC_MEMBERSHIP_OPERATIONS = ("add_member", "review_requests", "change_role", "remove_member", "transfer_ownership")
# The statuses that let members be added or promoted (functions_public_membership_policy).
PUBLIC_MEMBER_ADD_STATUSES = ("active", "upload_disabled")
SECTION_GROUPS = {
    "documents": "knowledge", "tags": "knowledge", "sync": "knowledge", "prompts": "knowledge",
    "identities": "connections",
}
# Members joins the content sections in the shared "manage" group (M10A).
PUBLIC_MANAGE_SECTION_GROUP = "manage"
# The texts build_public_workspace_context sends: a section public workspaces don't offer, and why a
# workspace's status closes every section (check_public_workspace_status_allows_operation's "view").
PUBLIC_SECTION_UNAVAILABLE_REASON = "This section is not available for public workspaces yet."
PUBLIC_INACTIVE_REASON = "This public workspace is inactive. Access is restricted to administrators."
PUBLIC_STATUS_UNKNOWN_REASON = "This workspace's status is not recognized. Contact an administrator."
# The connections reasons build_public_workspace_context sends for the identities and sync sections
# (M10B): File Sync is the sole gate, so a manager sees the "requires File Sync" text and a reader the
# manager-only text. functions_public_identity_policy.PUBLIC_IDENTITIES_UNAVAILABLE_REASON and
# functions_public_file_source_policy.PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON.
PUBLIC_IDENTITIES_UNAVAILABLE_REASON = "Identities require File Sync."
PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON = "File sources require File Sync."
PUBLIC_CONNECTIONS_MANAGER_REASON = "Your role does not permit managing this public workspace's connections."
# The context route's refusals. The builder's access refusal is unreachable under today's role rules
# (every authenticated caller reads a public workspace as at least a User); the fixture keeps it as a
# client robustness scenario.
PUBLIC_CONTEXT_NOT_FOUND_ERROR = "The selected public workspace was not found."
PUBLIC_CONTEXT_DENIED_ERROR = "You do not have access to the selected public workspace."


def public_document_management(role, status):
    """`public_document_management_operations` for a deployment that allows downloads and extracts
    metadata. The server sends this hint in every public context, with no operations for a reader."""
    operations = set()
    if role in PUBLIC_MANAGER_ROLES and status in PUBLIC_VIEWABLE_STATUSES:
        operations.add("download")
        if status == "active":
            operations.update({"upload", "edit_metadata", "tag_documents", "manage_tags", "extract_metadata"})
        if status in ("active", "upload_disabled"):
            operations.update({"delete", "reprocess"})
    return {
        "schema_version": 1,
        "operations": [operation for operation in PUBLIC_DOCUMENT_OPERATIONS if operation in operations],
    }


def public_document_collaboration(role, status):
    """`public_document_collaboration_operations`: any reader inspects a viewable workspace's
    generated artifacts and cancels their own request while it takes changes; a manager also rejects
    then, and approves only while the workspace is active."""
    operations = set()
    if status in PUBLIC_VIEWABLE_STATUSES:
        operations.add("inspect")
        if status in ("active", "upload_disabled"):
            operations.add("cancel_artifact")
            if role in PUBLIC_MANAGER_ROLES:
                operations.add("reject_artifact")
                if status == "active":
                    operations.add("approve_artifact")
    return {
        "schema_version": 1,
        "operations": [operation for operation in PUBLIC_DOCUMENT_COLLABORATION_OPERATIONS if operation in operations],
    }


def public_prompt_management(role, status):
    """`public_prompt_management_operations`: a manager of an active workspace creates, edits and
    deletes prompts. No status but active permits a write, and a reader gets nothing. The server
    sends this hint in every public context from M9C on."""
    operations = []
    if role in PUBLIC_MANAGER_ROLES and status == "active":
        operations = list(PUBLIC_PROMPT_OPERATIONS)
    return {"schema_version": 1, "operations": operations}


def public_identity_management(role, status, file_sync):
    """`public_identity_management_operations`: a manager of an active workspace creates, edits and
    deletes identities, but only when File Sync is enabled for the workspace (its sole consumer). No
    status but active permits a write, and a reader gets nothing. The server sends this hint in every
    public context from M10B on."""
    operations = []
    if file_sync and role in PUBLIC_MANAGER_ROLES and status == "active":
        operations = list(PUBLIC_IDENTITY_OPERATIONS)
    return {"schema_version": 1, "operations": operations}


def public_file_source_management(role, status, file_sync):
    """`public_file_source_management_operations`: a manager of an active workspace creates, edits,
    deletes, syncs and tests file sources, but only when File Sync is enabled for the workspace. No
    status but active permits a write, and a reader gets nothing. The server sends this hint in every
    public context from M10B on."""
    operations = []
    if file_sync and role in PUBLIC_MANAGER_ROLES and status == "active":
        operations = list(PUBLIC_FILE_SOURCE_OPERATIONS)
    return {"schema_version": 1, "operations": operations}


def public_membership_management(role, status):
    """`public_membership_operations` for the modelled deployment (public workspaces on). A manager
    reviews requests and removes members in any status, and adds or changes roles only while the
    workspace takes members; the owner also transfers ownership. A reader gets nothing. Only the
    Owner and Admins manage membership -- a DocumentManager is a member, not a manager, here."""
    operations = set()
    if role in ("Owner", "Admin"):
        operations.update({"review_requests", "remove_member"})
        if status in PUBLIC_MEMBER_ADD_STATUSES:
            operations.update({"add_member", "change_role"})
    if role == "Owner":
        operations.add("transfer_ownership")
    return {
        "schema_version": 1,
        "operations": [operation for operation in PUBLIC_MEMBERSHIP_OPERATIONS if operation in operations],
    }


def public_context(identifier, name, *, status="active", role="User", viewer=OWNER_ID, file_sync=False):
    """`build_public_workspace_context` for the modelled deployment: public workspaces, metadata
    extraction and the administrator's public downloads on. `file_sync` toggles File Sync for the
    workspace, which is the sole gate on the identities and sync sections and their management hints
    (M10B); it is off in the base deployment and turned on by the connection suites' fixtures."""
    status = status if status in PUBLIC_STATUSES else "unknown"
    readable = status in PUBLIC_VIEWABLE_STATUSES
    manager = role in PUBLIC_MANAGER_ROLES
    status_reason = None if readable else PUBLIC_INACTIVE_REASON if status == "inactive" else PUBLIC_STATUS_UNKNOWN_REASON

    def gate(enabled_flag, unavailable_reason):
        """One section entry, mirroring the builder's `section()`: a status that closes viewing wins
        over the section's own reason, and management needs an active workspace and a manager role."""
        enabled = readable and bool(enabled_flag)
        return {
            "enabled": enabled,
            "can_manage": bool(enabled and status == "active" and manager),
            "reason": None if enabled else (status_reason if not readable else unavailable_reason),
        }
    # Documents and prompts open; a manager of an active workspace manages either. Identities and sync
    # are gated solely on File Sync for the workspace and are manager-only; tags stay unavailable.
    sections = {
        "documents": {"group": "knowledge", **gate(True, PUBLIC_SECTION_UNAVAILABLE_REASON)},
        "tags": {"group": "knowledge", **gate(False, PUBLIC_SECTION_UNAVAILABLE_REASON)},
        "prompts": {"group": "knowledge", **gate(True, PUBLIC_SECTION_UNAVAILABLE_REASON)},
        "identities": {"group": "connections", **gate(
            manager and file_sync,
            PUBLIC_IDENTITIES_UNAVAILABLE_REASON if manager else PUBLIC_CONNECTIONS_MANAGER_REASON,
        )},
        "sync": {"group": "knowledge", **gate(
            manager and file_sync,
            PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON if manager else PUBLIC_CONNECTIONS_MANAGER_REASON,
        )},
    }
    # Members (M10A) opens in any viewable status; its can_manage is navigation only, gated on an
    # active workspace and a manager role like the server's section(True, manager).
    sections["members"] = {
        "group": PUBLIC_MANAGE_SECTION_GROUP, "enabled": readable,
        "can_manage": bool(readable and status == "active" and role in ("Owner", "Admin")),
        "reason": None if readable else status_reason,
    }
    return {
        "schema_version": 1, "enabled": True, "viewer_id": viewer,
        "scope": {"kind": "public", "id": identifier},
        "workspace": {
            "name": name, "description": f"Published knowledge for {name}.",
            "owner": {"display_name": f"{name} owner", "email": "owner@example.test"},
            "hero_color": "#0078d4", "logo_url": None,
        },
        "role": role, "status": status, "can_manage_workspace": role in ("Owner", "Admin"),
        "sections": sections,
        "document_permissions": {
            "can_view": readable, "can_chat": readable,
            "can_upload": manager and status == "active",
            "can_edit": manager and status == "active",
            "can_delete": manager and status in ("active", "upload_disabled"),
            "can_download": manager and readable,
        },
        "document_queries": {
            "sort_fields": [
                "_ts", "file_name", "title", "upload_date", "file_size",
                "number_of_pages", "version", "document_classification",
            ],
            "facets": True, "places": True,
        },
        "document_management": public_document_management(role, status),
        "document_collaboration": public_document_collaboration(role, status),
        "prompt_management": public_prompt_management(role, status),
        "identity_management": public_identity_management(role, status, file_sync),
        "file_source_management": public_file_source_management(role, status, file_sync),
        "membership_management": public_membership_management(role, status),
    }


class PublicWorkspaceFixture(WorkspaceAuthoringFixture):
    def __init__(self, page):
        super().__init__(page)
        self.public_enabled = True
        self.viewer_id = OWNER_ID
        self.active_workspace = None
        self.workspaces = {
            "pub-a": public_context("pub-a", "Research library"),
            "pub-b": public_context("pub-b", "Read-only library"),
        }
        self.denied_workspaces = set()
        self.set_active_failures = set()
        self.classic_visits = []

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["user"]["id"] = self.viewer_id
        payload["features"]["enable_public_workspaces"] = self.public_enabled
        payload["scope"].update({
            "active_public_workspace_id": self.active_workspace,
            "public_workspaces": [
                {"id": workspace_id, "name": context["workspace"]["name"]}
                for workspace_id, context in self.workspaces.items()
            ],
        })
        return payload

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        path = unquote(parsed.path)
        if route.request.method == "GET":
            if path == "/v2/settings" or path.startswith("/v2/public"):
                route.fulfill(path=str(SPA_INDEX), content_type="text/html")
                return
            if path in ("/public_workspaces", "/public_directory", "/profile"):
                self.classic_visits.append((path, self.active_workspace))
                route.fulfill(content_type="text/html", body="<html><body>Classic handoff target</body></html>")
                return
        super()._route(route)

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        leak = personal_scope_leak(path, entry.query)
        if leak:
            # A public workspace page must never read a personal-scope resource. Record it so
            # assert_clean() fails rather than the base fixture silently answering it.
            self.unexpected_requests.append(f"{method} {path} ({leak} from a public page)")
            self._json(route, {"error": "Personal-scope reads are not available on public pages."}, 500)
            return
        if path == "/api/public_workspaces/directory" and method == "GET":
            # The V2 picker and settings tab now share the native directory route (M9A commit 4).
            # This suite only needs the request answered with a valid page; the directory page's own
            # fixture (public_directory.py) intercepts this path first for the directory-specific
            # projection, so the two never collide.
            term = entry.query.get("search", [""])[0].lower()
            page = int(entry.query.get("page", ["1"])[0])
            size = int(entry.query.get("page_size", ["25"])[0])
            workspaces = [
                {
                    "id": workspace_id, "name": context["workspace"]["name"],
                    "description": context["workspace"]["description"],
                    "isActive": workspace_id == self.active_workspace, "status": context["status"],
                }
                for workspace_id, context in self.workspaces.items()
                if workspace_id not in self.denied_workspaces
                and term in f'{context["workspace"]["name"]} {context["workspace"]["description"]}'.lower()
            ]
            self._json(route, {
                "workspaces": workspaces[(page - 1) * size:page * size],
                "page": page, "page_size": size, "total_count": len(workspaces),
            })
        elif path.startswith("/api/v2/workspaces/public/") and method == "GET":
            workspace_id = path.rsplit("/", 1)[-1]
            if workspace_id in self.denied_workspaces:
                self._json(route, {"error": PUBLIC_CONTEXT_DENIED_ERROR}, 403)
            elif workspace_id not in self.workspaces:
                self._json(route, {"error": PUBLIC_CONTEXT_NOT_FOUND_ERROR}, 404)
            else:
                payload = copy.deepcopy(self.workspaces[workspace_id])
                payload["viewer_id"] = self.viewer_id
                self._json(route, payload)
        elif path == "/api/public_workspaces/setActive" and method == "PATCH":
            workspace_id = entry.body["workspaceId"]
            if workspace_id in self.set_active_failures:
                self._json(route, {"error": "The active public workspace could not be saved."}, 403)
            elif workspace_id in self.denied_workspaces or workspace_id not in self.workspaces:
                self._json(route, {"error": "Unavailable public workspace."}, 403)
            else:
                self.active_workspace = workspace_id
                self._json(route, {"message": "Active public workspace saved."})
        else:
            super()._dispatch(route, entry)


@pytest.fixture
def public_ui(page):
    fixture = PublicWorkspaceFixture(page)
    yield fixture
    fixture.assert_clean()
