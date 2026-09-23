# public_workspace.py
"""
Closed HTTP fixtures for the real V2 public workspace shell.
Version: 0.261.133
Implemented in: 0.261.132

The public surface mirrors the group shell. In M3A it is read-only; from M3B a
manager role can be granted document management. It never advertises collaboration
or native delegation, and every document read or operation carries its workspace id
in the request path rather than an active selection.
"""

import copy
from urllib.parse import unquote, urlsplit

import pytest

from ui_tests.fixtures.workspace_authoring import (
    OWNER_ID, SPA_INDEX, WorkspaceAuthoringFixture, connect_options,  # noqa: F401
)


PUBLIC_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
SECTION_GROUPS = {
    "documents": "knowledge", "tags": "knowledge", "sync": "knowledge", "prompts": "knowledge",
    "agents": "automation", "actions": "automation", "workflows": "automation",
    "identities": "connections", "endpoints": "connections",
}


def public_context(identifier, name, *, status="active", role="User", viewer=OWNER_ID):
    readable = status not in ("inactive", "unknown")
    manager = role in PUBLIC_MANAGER_ROLES
    sections = {
        section: {
            "group": group, "enabled": readable,
            "reason": None if readable else "This public workspace is inactive.",
            "can_manage": manager and readable,
        }
        for section, group in SECTION_GROUPS.items()
    }
    return {
        "schema_version": 1, "enabled": True, "viewer_id": viewer,
        "scope": {"kind": "public", "id": identifier},
        "workspace": {
            "name": name, "description": f"Published knowledge for {name}.",
            "owner": {"display_name": f"{name} owner", "email": "owner@example.test"},
            "hero_color": "#0078d4", "logo_url": None,
        },
        "role": role, "status": status, "can_manage_workspace": manager and readable,
        "sections": sections,
        "document_permissions": {
            "can_view": readable, "can_chat": readable and status != "locked",
            "can_upload": manager and status == "active",
            "can_edit": manager and status in ("active", "upload_disabled"),
            "can_delete": manager and status in ("active", "upload_disabled"),
            "can_download": readable,
        },
        "document_queries": {
            "sort_fields": [
                "_ts", "file_name", "title", "upload_date", "file_size",
                "number_of_pages", "version", "document_classification",
            ],
            "facets": True, "places": True,
        },
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
                self._json(route, {"error": "You do not have access to the selected public workspace."}, 403)
            elif workspace_id not in self.workspaces:
                self._json(route, {"error": "Public workspace not found."}, 404)
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
