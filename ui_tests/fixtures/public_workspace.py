# public_workspace.py
"""
Closed HTTP fixtures for the real V2 public workspace shell.
Version: 0.261.168
Implemented in: 0.261.132
Every context carries the server's document_management hint, as build_public_workspace_context
sends it: 0.261.166
Every context is the real builder's, held to it by
functional_tests/test_public_context_fixture_parity.py: 0.261.168

The public surface mirrors the group shell. Only its documents section is open, and a manager role
can be granted document management and the generated-artifact review. It never advertises native
delegation, and every document read or operation carries its workspace id in the request path
rather than an active selection.
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
SECTION_GROUPS = {
    "documents": "knowledge", "tags": "knowledge", "sync": "knowledge", "prompts": "knowledge",
    "agents": "automation", "actions": "automation", "workflows": "automation",
    "identities": "connections", "endpoints": "connections",
}
# The texts build_public_workspace_context sends: a section public workspaces don't offer, and why a
# workspace's status closes every section (check_public_workspace_status_allows_operation's "view").
PUBLIC_SECTION_UNAVAILABLE_REASON = "This section is not available for public workspaces yet."
PUBLIC_INACTIVE_REASON = "This public workspace is inactive. Access is restricted to administrators."
PUBLIC_STATUS_UNKNOWN_REASON = "This workspace's status is not recognized. Contact an administrator."
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


def public_context(identifier, name, *, status="active", role="User", viewer=OWNER_ID):
    """`build_public_workspace_context` for the modelled deployment: public workspaces, metadata
    extraction and the administrator's public downloads on."""
    status = status if status in PUBLIC_STATUSES else "unknown"
    readable = status in PUBLIC_VIEWABLE_STATUSES
    manager = role in PUBLIC_MANAGER_ROLES
    status_reason = None if readable else PUBLIC_INACTIVE_REASON if status == "inactive" else PUBLIC_STATUS_UNKNOWN_REASON
    sections = {}
    for section, group in SECTION_GROUPS.items():
        # Only documents open; no section is offered for management, since every write reauthorizes.
        enabled = readable and section == "documents"
        sections[section] = {
            "group": group, "enabled": enabled, "can_manage": False,
            "reason": None if enabled else status_reason or PUBLIC_SECTION_UNAVAILABLE_REASON,
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
        if path == "/api/public_workspaces" and method == "GET":
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
