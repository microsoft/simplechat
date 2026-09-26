# cross_scope_journeys.py
"""One session that composes personal, group and public workspaces for the M11 cross-scope journeys.

Version: 0.261.185
Implemented in: 0.261.185

The M11 cross-scope journeys prove that a person moving between My Workspace, a group workspace and a
public workspace in one session reads only the scope they are on: a personal read never carries a
group or public id, a group page never reaches a personal or public route, and a public page never
reaches a personal or group route. That needs one fixture that can answer all three scopes from one
bootstrap while every route it does not serve stays a trap.

The fixture is built on GroupWorkspaceFixture -- the parity-pinned group base that already serves the
whole group scope (bootstrap-with-group, the group context, the group document list and facets, the
group picker and the classic handoff) and, crucially, already traps a personal-scope read reaching a
group page. Group and public keep their own stores (`self.groups`, `self.public_workspaces`), and the
group base uses neither `self.documents` nor `self.workspaces`, so personal and public each add a
distinctly named store with no collision. `_dispatch` routes a personal read to the personal handler
and a public read to the public handler before the group base sees it, so a legitimate personal or
public read never trips the group base's leak trap, while any unrouted personal read from a group page
still does.
"""

import copy
from collections import Counter
from urllib.parse import unquote, urlsplit

import pytest

from ui_tests.fixtures.workspace_authoring import OWNER_ID, SPA_INDEX
from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture
from ui_tests.fixtures.public_workspace import (
    public_context, PUBLIC_CONTEXT_DENIED_ERROR, PUBLIC_CONTEXT_NOT_FOUND_ERROR,
)
from ui_tests.fixtures.public_documents import document as public_document, served as public_served


def personal_document(identifier, title, *, timestamp, tags=None):
    """A stored personal document, in the shape route_backend_documents returns for `/api/documents`.
    Personal reads keep `_ts` in the response -- the explorer dates a personal row by it -- so unlike
    the public projection it is not stripped."""
    return {
        "id": identifier, "document_id": identifier,
        "user_id": OWNER_ID, "owner_id": OWNER_ID,
        "title": title, "file_name": f"{identifier}.txt", "file_type": "txt",
        "abstract": f"Private reference for {title}.", "authors": ["A. Author"],
        "keywords": [], "tags": list(tags or []), "version": 1, "number_of_pages": 1,
        "file_size": 1024, "num_chunks": 1, "percentage_complete": 100, "status": "Complete",
        "shared_approval_status": "owner", "is_current_version": True,
        "revision_family_id": f"family-{identifier}", "_ts": timestamp,
    }


class CrossScopeJourneyFixture(GroupWorkspaceFixture):
    """One store for all three scopes: the group base plus a personal and a public store, every
    unrouted route still a trap."""

    def __init__(self, page):
        super().__init__(page)
        # A real active group, so the group scope is live beside the others (the base leaves it None).
        self.active_group = "group-a"
        # The deployment-wide public toggle the Settings-activation journey flips; the group and file
        # sharing toggles stay on so all three scopes are reachable.
        self.public_enabled = True

        # Personal documents, in their own store so no scope shares a dict with another. The leak trap
        # is that a personal read must never carry a group or public id, asserted in _personal_documents.
        self.personal_documents = {
            "personal-alpha": personal_document("personal-alpha", "Personal Alpha", timestamp=2, tags=["Finance"]),
            "personal-beta": personal_document("personal-beta", "Personal Beta", timestamp=1),
        }

        # Public workspaces, their contexts and their documents, kept apart from the group and personal
        # stores. pub-a is the active public workspace; pub-b is reachable through the public picker.
        self.public_names = {"pub-a": "Research library", "pub-b": "Read-only library"}
        self.active_public = "pub-a"
        self.denied_public = set()
        self.public_workspaces = {
            "pub-a": public_context("pub-a", "Research library", role="Owner", viewer=self.viewer_id),
            "pub-b": public_context("pub-b", "Read-only library", role="User", viewer=self.viewer_id),
        }
        self.public_documents = {
            "pub-a": [public_document("pub-a", "public-alpha", "Research brief", timestamp=20, tags=["team"])],
            "pub-b": [public_document("pub-b", "public-beta", "Read-only brief", timestamp=10, tags=["team"])],
        }

    # --- bootstrap ----------------------------------------------------------------------------------

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["features"]["enable_public_workspaces"] = self.public_enabled
        payload["features"]["enable_file_sharing"] = True
        payload["scope"].update({
            "active_public_workspace_id": self.active_public,
            "public_workspaces": [
                {"id": workspace_id, "name": context["workspace"]["name"]}
                for workspace_id, context in self.public_workspaces.items()
            ],
        })
        return payload

    # --- page shells --------------------------------------------------------------------------------

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        path = unquote(parsed.path)
        if route.request.method == "GET" and path.startswith("/v2/public"):
            # The public SPA shell. The group base's _route already serves the personal, chat, group
            # and settings shells; only the public shell is new here.
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
            return
        if route.request.method == "GET" and path in ("/public_workspaces", "/public_directory"):
            self.classic_visits.append((path, self.active_public))
            route.fulfill(content_type="text/html", body="<html><body>Classic handoff target</body></html>")
            return
        super()._route(route)

    # --- dispatch -----------------------------------------------------------------------------------

    def _dispatch(self, route, entry):
        path = entry.path
        if path.startswith("/api/documents"):
            self._personal_documents(route, entry)
            return
        if (
            path.startswith("/api/public-workspaces/")
            or path.startswith("/api/v2/workspaces/public/")
            or path.startswith("/api/public_workspaces")
        ):
            self._public(route, entry)
            return
        # Everything else -- the group routes, the shared bootstrap and shell reads, and the group
        # base's leak trap for any personal read that reaches a group page -- stays with the group base.
        super()._dispatch(route, entry)

    # --- personal scope -----------------------------------------------------------------------------

    def _personal_documents(self, route, entry):
        # A personal read must never be retargeted by an active group or public workspace: the query
        # carries no group or public id. This is the isolation the personal-scope suite pins, kept here
        # so a cross-scope session cannot leak an active selection into a personal read.
        assert "group_id" not in entry.query and "group_ids" not in entry.query, entry
        assert "public_workspace_id" not in entry.query, entry
        rows = list(self.personal_documents.values())
        if entry.path == "/api/documents" and entry.method == "GET":
            term = entry.query.get("search", [""])[0].lower()
            if term:
                rows = [row for row in rows if term in f'{row["title"]} {row["file_name"]}'.lower()]
            tags = [tag for tag in entry.query.get("tags", [""])[0].split(",") if tag]
            if tags:
                rows = [row for row in rows if all(tag in row["tags"] for tag in tags)]
            rows.sort(key=lambda row: float(row.get("_ts") or 0), reverse=True)
            self._json(route, {
                "documents": rows, "page": 1, "page_size": 25,
                "total_count": len(rows), "file_downloads_enabled": False,
            })
        elif entry.path == "/api/documents/facets" and entry.method == "GET":
            self._json(route, {
                "total": len(rows),
                "untagged": sum(not row["tags"] for row in rows),
                "processing": 0, "errors": 0, "recent": 0, "shared_with_me": 0,
                "by_tag": dict(Counter(tag for row in rows for tag in row["tags"])),
                "by_classification": {},
            })
        elif entry.path == "/api/documents/tags" and entry.method == "GET":
            counts = Counter(tag for row in rows for tag in row["tags"])
            self._json(route, {"tags": [
                {"name": name, "count": count, "color": "#0078d4"} for name, count in counts.items()
            ]})
        else:
            self.unexpected_requests.append(f"{entry.method} {entry.path} (unhandled personal read)")
            self._json(route, {"error": "Unhandled personal read."}, 500)

    # --- public scope -------------------------------------------------------------------------------

    def _public(self, route, entry):
        path, method = entry.path, entry.method
        if path == "/api/public_workspaces/directory" and method == "GET":
            # The unified public picker reads the directory. It lists every public workspace in the
            # shared store, so the header picker reaches pub-b.
            term = entry.query.get("search", [""])[0].lower()
            page = int(entry.query.get("page", ["1"])[0])
            size = int(entry.query.get("page_size", ["25"])[0])
            workspaces = [
                {
                    "id": workspace_id, "name": context["workspace"]["name"],
                    "description": context["workspace"]["description"],
                    "isActive": workspace_id == self.active_public, "status": context["status"],
                }
                for workspace_id, context in self.public_workspaces.items()
                if workspace_id not in self.denied_public
                and term in f'{context["workspace"]["name"]} {context["workspace"]["description"]}'.lower()
            ]
            self._json(route, {
                "workspaces": workspaces[(page - 1) * size:page * size],
                "page": page, "page_size": size, "total_count": len(workspaces),
            })
            return
        if path.startswith("/api/v2/workspaces/public/") and method == "GET":
            workspace_id = path.rsplit("/", 1)[-1]
            if workspace_id in self.denied_public:
                self._json(route, {"error": PUBLIC_CONTEXT_DENIED_ERROR}, 403)
            elif workspace_id not in self.public_workspaces:
                self._json(route, {"error": PUBLIC_CONTEXT_NOT_FOUND_ERROR}, 404)
            else:
                payload = copy.deepcopy(self.public_workspaces[workspace_id])
                payload["viewer_id"] = self.viewer_id
                self._json(route, payload)
            return
        if path == "/api/public_workspaces/setActive" and method == "PATCH":
            workspace_id = (entry.body or {}).get("workspaceId")
            if workspace_id in self.public_workspaces and workspace_id not in self.denied_public:
                self.active_public = workspace_id
            self._json(route, {"message": "ok"})
            return
        prefix = "/api/public-workspaces/"
        if path.startswith(prefix) and "/documents" in path:
            self._public_documents(route, entry)
            return
        self.unexpected_requests.append(f"{method} {path} (unhandled public read)")
        self._json(route, {"error": "Unhandled public read."}, 500)

    def _public_documents(self, route, entry):
        path, method = entry.path, entry.method
        assert method == "GET", f"The cross-scope journeys never mutate public documents: {entry}"
        remainder = path[len("/api/public-workspaces/"):]
        workspace_id, _, tail = remainder.partition("/documents")
        assert workspace_id in self.public_workspaces, entry
        # The public list must identify its own workspace by the path, never a query id, and must never
        # carry a group id -- the isolation the public read adapter enforces.
        assert "group_id" not in entry.query and "group_ids" not in entry.query, entry
        assert "public_workspace_id" not in entry.query, entry
        rows = list(self.public_documents.get(workspace_id, []))
        if tail == "":
            rows = sorted(rows, key=lambda row: float(row.get("_ts") or 0), reverse=True)
            page = int(entry.query.get("page", ["1"])[0])
            size = int(entry.query.get("page_size", ["50"])[0])
            self._json(route, {
                "documents": [public_served(row) for row in rows[(page - 1) * size:page * size]],
                "total_count": len(rows), "page": page, "page_size": size,
                "file_downloads_enabled": False,
            })
        elif tail == "/facets":
            self._json(route, {
                "total": len(rows), "untagged": sum(not row["tags"] for row in rows),
                "processing": 0, "errors": 0, "recent": 0, "shared_with_me": 0,
                "by_tag": dict(Counter(tag for row in rows for tag in row["tags"])),
                "by_classification": {},
            })
        elif tail == "/tags":
            counts = Counter(tag for row in rows for tag in row["tags"])
            self._json(route, {"tags": [
                {"name": name, "count": count, "color": "#059669"} for name, count in counts.items()
            ]})
        else:
            identifier = tail.strip("/").split("/")[0]
            record = next((row for row in rows if row["id"] == identifier), None)
            if record is None:
                self._json(route, {"error": "Document not found or access denied."}, 404)
            else:
                self._json(route, public_served(record))


@pytest.fixture
def cross_scope_journeys_ui(page):
    fixture = CrossScopeJourneyFixture(page)
    yield fixture
    fixture.assert_clean()
