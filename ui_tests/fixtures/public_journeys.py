# public_journeys.py
"""One composite public store for the M11 public end-to-end journeys.

Version: 0.261.182
Implemented in: 0.261.182

The M11 public journeys drive the real built SPA across every public workspace
section in a single session, so they need one fixture that answers the directory,
membership, prompt, document, identity and file-source routes from a shared public
store while keeping every family's trap intact.

Naive diamond inheritance cannot do this: each public family's ``_dispatch`` answers
only its own routes and sends everything else to a shared base, so a request one family
does not own would reach another family's assertion rather than the one that models the
real route. This composite instead routes each request to the owning family explicitly,
exactly like ``group_journeys.GroupJourneyFixture`` does for the group families, and sends
everything else (the context read, the active-workspace courtesy write, the bootstrap and
the shell) to ``PublicWorkspaceFixture``, whose ``_dispatch`` still records unexpected
requests as traps.

``set_matrix`` is the one authoritative role/status/File-Sync setter the rail matrix rides:
it rebuilds a workspace's stored membership and its context so ``self.workspaces[id]`` is
the single source of truth for what the rail and overview render, without any family's
``__init__`` ordering deciding the state.
"""

import pytest

from ui_tests.fixtures.workspace_authoring import OWNER_ID, WorkspaceAuthoringFixture
from ui_tests.fixtures.public_workspace import PublicWorkspaceFixture, public_context
from ui_tests.fixtures.public_directory import PublicDirectoryFixture
from ui_tests.fixtures.public_members import (
    PublicMembersFixture, workspace_document, _MEMBERSHIP_ROUTE,
)
from ui_tests.fixtures.public_prompts import PublicPromptsFixture
from ui_tests.fixtures.public_document_collaboration import PublicDocumentCollaborationFixture
from ui_tests.fixtures.public_identities import PublicIdentitiesFixture
from ui_tests.fixtures.public_file_sources import PublicFileSourcesFixture


class PublicJourneyFixture(
    PublicDirectoryFixture,
    PublicMembersFixture,
    PublicPromptsFixture,
    PublicDocumentCollaborationFixture,
    PublicIdentitiesFixture,
    PublicFileSourcesFixture,
):
    """The composite the M11 public journeys ride: one public store, every family's trap kept."""

    def __init__(self, page):
        super().__init__(page)
        # The families' __init__ chain each rebuild `self.workspaces` for their own store, so the last
        # to run decides the state. The journeys always open with pub-a selected, so establish both
        # workspaces' canonical state here rather than depend on the cooperative ordering.
        self.active_workspace = "pub-a"
        self.set_matrix("pub-a", role="Owner", status="active")
        self.set_matrix("pub-b", role="User", status="active")

    def set_matrix(self, workspace_id, *, role="User", status="active", file_sync=False):
        """Rebuild a workspace's stored membership and its context under `role`, `status` and File Sync.

        This is the single authority the rail matrix reads. `self.workspaces[id]` is the real builder's
        context (held to it by test_public_context_fixture_parity), so the rail, the overview and the
        header status all follow it, and the connection sections open exactly when File Sync is on for a
        manager of an active workspace.
        """
        name = self.names.get(workspace_id) or self.workspaces[workspace_id]["workspace"]["name"]
        self.workspace_docs[workspace_id] = workspace_document(role, status=status)
        self.workspaces[workspace_id] = public_context(
            workspace_id, name, role=role, status=status, file_sync=file_sync, viewer=self.viewer_id,
        )
        self.denied_workspaces.discard(workspace_id)
        return self.workspaces[workspace_id]

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        # The document chain owns every /documents route under a public workspace: the list, its facets
        # and tags, an item, its versions, the M3B operations and the generated-artifact publication.
        if path.startswith("/api/public-workspaces/") and "/documents" in path:
            PublicDocumentCollaborationFixture._dispatch(self, route, entry)
            return
        if path.startswith("/api/public-workspaces/") and "/prompts" in path:
            PublicPromptsFixture._dispatch(self, route, entry)
            return
        if path.startswith("/api/public-workspaces/") and ("/file-sources" in path or "/file-source-options" in path):
            PublicFileSourcesFixture._dispatch(self, route, entry)
            return
        if path.startswith("/api/public-workspaces/") and "/identities" in path:
            PublicIdentitiesFixture._dispatch(self, route, entry)
            return
        if _MEMBERSHIP_ROUTE.match(path) or (path == "/api/userSearch" and method == "GET"):
            PublicMembersFixture._dispatch(self, route, entry)
            return
        if (path == "/api/public_workspaces" and method == "POST") or (
            path.startswith("/api/public_workspaces/") and path.endswith("/logo")
        ):
            PublicDirectoryFixture._dispatch(self, route, entry)
            return
        # The unified picker and the directory page share GET /api/public_workspaces/directory. The
        # directory page is out of scope for the journeys, so the base handler answers it -- listing
        # every workspace in the shared store, so the header picker reaches pub-b -- rather than the
        # directory projection, which seeds only its own browse rows. The base also answers the context
        # read, the active-workspace courtesy write, the bootstrap and the shell, and records anything
        # it does not know as an unexpected request. Only owned routes went to a family above, so no
        # family reaches its own hard refusal.
        PublicWorkspaceFixture._dispatch(self, route, entry)

    def assert_clean(self):
        # The base authoring assertion still fails on any trap -- a personal-scope leak, a classic
        # membership route, or any unexpected request -- without the document suites' stricter rule
        # that every request be a public document read.
        WorkspaceAuthoringFixture.assert_clean(self)


@pytest.fixture
def public_journeys_ui(page):
    fixture = PublicJourneyFixture(page)
    yield fixture
    fixture.assert_clean()
