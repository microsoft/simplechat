# group_actions.py
"""
Closed M4 group action HTTP fixtures for the real production V2 SPA.
Version: 0.261.137
Implemented in: 0.261.137

The fixture serves the immutable `/api/groups/<group_id>/actions[...]` family and
the `/actions/types` catalogue, and injects the `action_management` context hint
that gates create, edit, delete and test. It never permits personal
`/api/user/plugins` writes and never falls back to personal behaviour: an
`action_management` block is always present for a shipped backend, but a member's
block advertises no operations, so the workbench renders read-only. Every
returned action identifies the requested group exactly as the reader validates,
stored credentials stay masked on the server side, and writes carry
`expected_revision`, `clear_secret_paths` and `removed_paths` like the personal
editor. Group actions have no cross-scope identities and no personal favourites.
"""

import pytest

from ui_tests.fixtures.group_workspace import (  # noqa: F401
    ACTION_ACTIONS, ACTION_OPERATIONS, GroupWorkspaceFixture, WRITER_ROLES,
    action_management, connect_options, group_action, group_context,
)


EDITABLE_ACTION_ID = "group-a-openapi"
WITHHELD_ACTION_ID = "group-a-withheld"
MEMBER_ACTION_ID = "group-b-openapi"
IDENTITY_ACTION_ID = "group-a-identity"
MCP_ACTION_ID = "group-a-mcp"
PROVIDED_ACTION_ID = "global-shared-api"
BOUND_IDENTITY_ID = "group-identity-legacy"


class GroupActionsFixture(GroupWorkspaceFixture):
    """A small scripted action boundary; no second plugin service, no live Key Vault."""

    def __init__(self, page):
        super().__init__(page)
        self.active_group = "group-a"
        self.created_counter = 0
        # Per (group, action) mutable server state kept apart from the legacy group_actions store.
        self.native_actions = {}
        self.native_secret_paths = {}
        self.native_revisions = {}
        # group-a: a manager workspace. The OpenAPI action is fully editable; the withheld action
        # keeps an empty inline `action_actions` while the workspace advertises the operations, so
        # its edit, delete and test affordances stay hidden beside the editable control.
        self.set_action_policy("group-a", role="Owner", status="active")
        # A provided (global) action merged into the group list read-only. It carries is_global with
        # an empty inline action_actions and no owning group_id, so no edit, delete or test is offered
        # and the group read route still answers for it.
        provided_action = group_action("group-a", PROVIDED_ACTION_ID, "Shared platform API",
                                       actions=(), is_global=True, is_group=False)
        provided_action["group_id"] = None
        self._seed("group-a", [
            group_action("group-a", EDITABLE_ACTION_ID, "Weekly report API"),
            group_action("group-a", WITHHELD_ACTION_ID, "Withheld API", actions=()),
            # A V1-era action bound to a group identity. No reusable group identity route exists yet
            # (M5A), so the editor keeps the binding with neutral copy and lists no identities.
            group_action("group-a", IDENTITY_ACTION_ID, "Bound report API",
                         identity_id=BOUND_IDENTITY_ID, auth={"type": "identity"}),
            # An editable MCP action. Its editor reads reminder defaults from the group
            # action-options route and never lists personal MCP preconfigurations, so it proves the
            # group editor makes no personal-scope reads. No inline credential, so no masked path.
            group_action("group-a", MCP_ACTION_ID, "Team MCP server", type="mcp",
                         endpoint="https://mcp.example.test/sse", auth={"type": "none"},
                         additionalFields={
                             "server_profile": "generic",
                             "transport": "streamable_http",
                             "preconfiguration_id": "",
                             "allowed_tool_names": [],
                             "mcp_tools": [],
                         }),
            provided_action,
        ])
        # group-b: an ordinary member. Actions are readable but the management hint offers no
        # operations, so the workbench is read-only: no create, edit, delete or test affordances.
        self.set_action_policy("group-b", role="User", status="active")
        self._seed("group-b", [
            group_action("group-b", MEMBER_ACTION_ID, "Team charter API", actions=()),
        ])
        # group-c: group agents are on but group actions are off. Navigation still surfaces the
        # Actions slot through native_delegation, so the pre-M4 Call agent view must render and no
        # /api/groups/group-c/actions request may be made.
        delegation_only = group_context("group-c", "Delegation only workspace", role="Owner", status="active")
        delegation_only["sections"]["actions"]["enabled"] = False
        delegation_only["sections"]["actions"]["can_manage"] = False
        delegation_only["sections"]["actions"]["reason"] = "Group actions are turned off for this workspace."
        # The backend empties the management hint when the capability is off; mirror that so nothing
        # can read create rights for a workspace whose native routes are refused.
        delegation_only["action_management"] = {"schema_version": 1, "operations": []}
        self.groups["group-c"] = delegation_only
        # group-c is added after the parent seeded its per-group delegation stores, so mirror that
        # seeding here: the Call agent view reads the group's caller agent when actions are off.
        self.group_agents["group-c"] = [{
            "id": "caller", "name": "caller", "display_name": "Local caller",
            "agent_type": "local", "group_id": "group-c", "is_group": True,
            "actions_to_load": ["legacy-name"], "other_settings": {},
        }]
        self.group_actions["group-c"] = []
        self.workflows["group-c"] = []



@pytest.fixture
def group_actions_ui(page):
    fixture = GroupActionsFixture(page)
    yield fixture
    fixture.assert_clean()
