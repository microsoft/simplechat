# group_journeys.py
"""One composite group store for the M8 end-to-end journeys.

Version: 0.261.162
Implemented in: 0.261.161

The M8 journeys drive the real built SPA across every group section in a single
session, so they need one fixture that answers the directory, membership, prompt,
document-collaboration and native-authoring routes from a shared group store while
keeping every family's trap intact.

Naive diamond inheritance cannot do this: `GroupDocumentManagementFixture._dispatch`
answers only the document routes and 500s everything else, so the authoring routes the
journeys reach through the base would hit that hard refusal. Instead the composite
routes each request to the owning family explicitly and sends everything else to the
base `GroupWorkspaceFixture`, whose own `_dispatch` still records unexpected requests.
"""

import re

import pytest

from ui_tests.fixtures.workspace_authoring import WorkspaceAuthoringFixture
from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture
from ui_tests.fixtures.group_directory import GroupDirectoryFixture
from ui_tests.fixtures.group_members import GroupMembersFixture
from ui_tests.fixtures.group_prompts import GroupPromptsFixture
from ui_tests.fixtures.group_document_collaboration import GroupDocumentCollaborationFixture


# One coherent bootstrap version for the whole store; the individual family fixtures each
# report their own implemented-in version, and a composite that inherited them would report
# whichever ran last. The journeys serve a single running app, so it reports the app VERSION.
JOURNEY_VERSION = "0.261.160"

_DOCUMENT_OPERATION = re.compile(r"/api/groups/[^/]+/documents/.+")
_CLASSIC_MEMBERSHIP = re.compile(r"/api/groups/[^/]+/(members|requests|transferOwnership)(/.*)?")


def _journey_search_matches(workspace, term):
    """`search_groups`' filter: the lowercased term in the name or the description, ignoring case.

    Cosmos' `LOWER` of a missing or non-string value is undefined, so that field never matches.
    An empty term matches every group, as the route then lists them all.
    """
    if not term:
        return True
    return any(
        isinstance(value, str) and term in value.lower()
        for value in (workspace.get("name"), workspace.get("description"))
    )


class GroupJourneyFixture(
    GroupDirectoryFixture,
    GroupMembersFixture,
    GroupPromptsFixture,
    GroupDocumentCollaborationFixture,
):
    """The composite the M8 journeys ride: one group store, every family's trap kept."""

    def __init__(self, page):
        super().__init__(page)
        # `GroupDirectoryFixture.__init__` is the leftmost base, so its body runs last in the
        # cooperative chain and leaves `active_group` at None. The journeys always open with
        # group-a selected, so the members store (group-a Owner, group-b User) is authoritative.
        self.active_group = "group-a"

    # --- bootstrap ------------------------------------------------------------------------------

    def _whole_number(self, values, *, default, maximum, message=None):
        # Two families define an incompatible `_whole_number`. The members family's staticmethod
        # raises `_invalid(message)` and returns an int; the directory family's instance method
        # returns a `(number, error)` tuple and takes no `message`. The composite MRO puts the
        # directory variant first, so a members list-query (which the J3/J5 journeys reach by
        # opening the Members section) would hit an unexpected-keyword TypeError. Route by the
        # `message` kwarg, which only the members family passes.
        if message is not None:
            return GroupMembersFixture._whole_number(
                values, default=default, maximum=maximum, message=message
            )
        return GroupDirectoryFixture._whole_number(self, values, default=default, maximum=maximum)

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["version"] = JOURNEY_VERSION
        return payload

    # --- route families -------------------------------------------------------------------------

    @staticmethod
    def _is_document_family(path):
        return (
            path.startswith("/api/group_documents")
            or path.startswith("/api/notifications")
            or bool(_DOCUMENT_OPERATION.fullmatch(path))
        )

    @staticmethod
    def _is_prompt_family(path):
        return path.startswith("/api/groups/") and "/prompts" in path

    @staticmethod
    def _is_member_family(path):
        if path == "/api/userSearch":
            return True
        if not path.startswith("/api/groups/"):
            return False
        return "/membership/" in path or bool(_CLASSIC_MEMBERSHIP.fullmatch(path))

    @staticmethod
    def _is_directory_family(path):
        if path == "/api/groups/directory":
            return True
        if not path.startswith("/api/groups/"):
            return False
        return path.endswith("/join-request") or path.endswith("/logo")

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        # One authoritative orchestration handler, ahead of every family: the documents fixture's
        # own handler asserts the conversation is known, and the prompts fixture answers an empty
        # list unconditionally. The composite validates when the conversation is known and falls
        # back to the empty list otherwise, so neither family's assertion can fire.
        if path == "/api/v2/orchestration/runs" and method == "GET":
            self._journey_orchestration_runs(route, entry)
            return
        # The picker's paged, searchable list, modelled on `route_backend_groups` exactly so the
        # picker parity pin holds. The real route strips the term, and `functions_group.search_groups`
        # lowercases it and matches it anywhere in the name or the description, ignoring case (from
        # 0.261.162); the route then pages the natural (insertion) order with `total_count =
        # len(all)`. Modelling it here, rather than in the shared base three other slices edit, keeps
        # the seam the parity pin guards in one reviewed place.
        if path == "/api/groups" and method == "GET":
            self._journey_list_groups(route, entry)
            return
        # The picker's activation write, modelled to the real `api_set_active_group` branches so the
        # picker parity pin holds: a missing id is a 400, an unknown group a 404, a group the caller
        # cannot reach a 403, and a reachable group a 200. The shared base handler answers 403 for an
        # unknown group and raises on a missing id, neither of which the picker itself ever sends, so
        # the journeys never see the difference; the composite still models the server exactly.
        if path == "/api/groups/setActive" and method == "PATCH":
            self._journey_set_active(route, entry)
            return
        # The group workflow document picker searches documents across an explicit scope list with the
        # plural `group_ids` param (WorkflowDocumentPicker -> fetchGroupDocuments([scopeId])). That
        # multi-scope read is an authoring concern the base fixture answers (group_workspace.py ~L1045),
        # not the single-group document management family, whose `/api/group_documents` handler asserts
        # a singular `group_id`. Route the plural form to the base so J9's workflow editor can open.
        if path == "/api/group_documents" and "group_ids" in entry.query:
            GroupWorkspaceFixture._dispatch(self, route, entry)
            return
        if self._is_document_family(path):
            GroupDocumentCollaborationFixture._dispatch(self, route, entry)
            return
        if self._is_prompt_family(path):
            GroupPromptsFixture._dispatch(self, route, entry)
            return
        if self._is_member_family(path):
            GroupMembersFixture._dispatch(self, route, entry)
            return
        if self._is_directory_family(path):
            GroupDirectoryFixture._dispatch(self, route, entry)
            return
        # The base answers the picker, context and every native authoring section, and records
        # anything it does not know as an unexpected request. Routing here never reaches the document
        # management fixture's hard 500, because only true document routes went to it above.
        GroupWorkspaceFixture._dispatch(self, route, entry)

    def _journey_set_active(self, route, entry):
        group_id = (entry.body or {}).get("groupId")
        if not group_id:
            self._json(route, {"error": "Missing groupId"}, 400)
            return
        if group_id not in self.groups:
            self._json(route, {"error": "Group not found"}, 404)
            return
        if group_id in self.denied_groups:
            self._json(route, {"error": "You are not a member of this group"}, 403)
            return
        self.active_group = group_id
        self._json(route, {"message": "Active group saved."})

    def _journey_list_groups(self, route, entry):
        # `route_backend_groups` GET /api/groups: the route strips the term and `search_groups`
        # lowercases it and matches it in the name or the description (`CONTAINS(LOWER(...))`), then
        # the route pages the natural order with `total_count = len(all_matching)`. A missing or empty
        # term lists every group the caller is in. `self.groups` preserves insertion order, which is
        # the order the harness's fake Cosmos returns, so the picker parity pin can compare the
        # page-1 and page-2 id lists.
        term = entry.query.get("search", [""])[0].strip().lower()
        page = int(entry.query.get("page", ["1"])[0])
        size = int(entry.query.get("page_size", ["25"])[0])
        rows = [
            {
                "id": group_id, "name": context["workspace"]["name"],
                "description": context["workspace"]["description"], "userRole": context["role"],
                "isActive": group_id == self.active_group, "status": context["status"],
            }
            for group_id, context in self.groups.items()
            if group_id not in self.denied_groups and _journey_search_matches(context["workspace"], term)
        ]
        self._json(route, {
            "groups": rows[(page - 1) * size:page * size],
            "page": page, "page_size": size, "total_count": len(rows),
        })

    def _journey_orchestration_runs(self, route, entry):
        conversation = entry.query.get("conversation_id", [None])[0]
        if conversation is not None and conversation in getattr(self, "messages", {}):
            assert entry.query.get("limit") == ["25"]
        self._json(route, {"runs": []})

    # --- cleanliness ----------------------------------------------------------------------------

    def assert_clean(self):
        # Deliberately use the base authoring assertion rather than the document suites' strict one,
        # which requires every request to be a document, notification or shell read. The base check
        # still fails on any trap: a personal-scope leak, an admin route, a classic membership route,
        # or any unexpected request, all of which land in `unexpected_requests`.
        WorkspaceAuthoringFixture.assert_clean(self)


@pytest.fixture
def group_journeys_ui(page):
    fixture = GroupJourneyFixture(page)
    yield fixture
    fixture.assert_clean()
