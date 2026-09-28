# group_journeys.py
"""One composite group store for the M8 end-to-end journeys.

Version: 0.261.165
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
        # J9 sweeps the Settings editor, which drafts both the profile name and a retention period
        # (S1/S5). Retention is off in the modelled deployment default, so turn it on for group-a
        # here; the call rebuilds the context so its `settings_management` matches the served read.
        self.apply_group_settings_flags("group-a", retention_enabled=True)

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
        # The picker's list and activation write (`GET /api/groups`, `PATCH /api/groups/setActive`)
        # fall through to the base fixture, which models `route_backend_groups` exactly; the picker
        # parity pin holds both fixtures to the real routes.
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
