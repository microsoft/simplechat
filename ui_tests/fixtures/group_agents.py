# group_agents.py
"""
Closed M4C group agent HTTP fixtures for the real production V2 SPA.
Version: 0.261.137
Implemented in: 0.261.137

The fixture serves the immutable `/api/groups/<group_id>/agents[...]` family, the
`/api/groups/<group_id>/agent-options` editor options and the
`/api/groups/<group_id>/agent-knowledge` catalogue, and injects the
`agent_management` context hint that gates create, edit and delete. It never
permits a personal-scope read: the shared base fixture records any `/api/user/*`,
personal identity, personal MCP preconfiguration, or `?agent_scope=personal`
request from a group page as unexpected rather than answering it, so a group agent
editor that leaked into personal reads would fail. It never falls back to personal
behaviour: an `agent_management` block is always present for a shipped backend, but
a member's block advertises no operations, so the workbench renders read-only.
Every returned agent identifies the requested group exactly as the reader
validates, stored credentials stay masked on the server side, and writes carry
`expected_revision`, `clear_secret_paths` and `removed_paths` like the personal
editor. Group agents bind only group identities and offer no personal favourites.
"""

import pytest

from ui_tests.fixtures.workspace_authoring import STORED_KEY, connect_options  # noqa: F401
from ui_tests.fixtures.group_workspace import (  # noqa: F401
    AGENT_ACTIONS, AGENT_OPERATIONS, GroupWorkspaceFixture, WRITER_ROLES,
    agent_management, group_agent, group_context,
)


EDITABLE_AGENT_ID = "group-a-editable"
WITHHELD_AGENT_ID = "group-a-withheld"
MEMBER_AGENT_ID = "group-b-agent"
PROVIDED_AGENT_ID = "global-shared-agent"


class GroupAgentsFixture(GroupWorkspaceFixture):
    """A small scripted agent boundary; no second agent service, no live Key Vault."""

    def __init__(self, page):
        super().__init__(page)
        self.active_group = "group-a"
        self.created_agent_counter = 0
        # Per (group, agent) mutable server state kept apart from the legacy group_agents store that
        # feeds the Call agent manager.
        self.native_agents = {}
        self.native_agent_secret_paths = {}
        self.native_agent_revisions = {}
        # group-a: a manager workspace. The editable agent is fully editable and carries an inline
        # connection credential so a rename proves the stored secret stays masked. The withheld agent
        # keeps an empty inline `agent_actions` while the workspace advertises the operations, so its
        # edit, delete and use-in-chat affordances stay hidden beside the editable control.
        self.set_agent_policy("group-a", role="Owner", status="active")
        # A provided (global) agent merged into the group list read-only. It carries is_global with an
        # empty inline agent_actions and no owning group_id, so no edit or delete is offered and the
        # group read route still answers for it.
        provided_agent = group_agent("group-a", PROVIDED_AGENT_ID, "Shared platform agent",
                                      actions=(), is_global=True, is_group=False)
        provided_agent["group_id"] = None
        self._seed_agents("group-a", [
            group_agent("group-a", EDITABLE_AGENT_ID, "Weekly reviewer",
                        other_settings={"connection": {"api_key": STORED_KEY}}),
            group_agent("group-a", WITHHELD_AGENT_ID, "Withheld reviewer", actions=()),
            provided_agent,
        ])
        # group-b: an ordinary member. Agents are readable but the management hint offers no
        # operations, so the workbench is read-only: no create, edit or delete affordances.
        self.set_agent_policy("group-b", role="User", status="active")
        self._seed_agents("group-b", [
            group_agent("group-b", MEMBER_AGENT_ID, "Team charter agent", actions=()),
        ])
        # group-c: group actions are on but group agents are off. Navigation still surfaces the
        # Agents slot through native_delegation, so the pre-M4 Call agent view must render and no
        # /api/groups/group-c/agents request may be made.
        actions_only = group_context("group-c", "Actions only workspace", role="Owner", status="active")
        actions_only["sections"]["agents"]["enabled"] = False
        actions_only["sections"]["agents"]["can_manage"] = False
        actions_only["sections"]["agents"]["reason"] = "Group agents are turned off for this workspace."
        # The backend empties the management hint when the capability is off; mirror that so nothing
        # can read create rights for a workspace whose native routes are refused.
        actions_only["agent_management"] = {"schema_version": 1, "operations": []}
        self.groups["group-c"] = actions_only
        # group-c is added after the parent seeded its per-group delegation stores, so mirror that
        # seeding here: the Call agent view reads the group's caller agent when agents are off.
        self.group_agents["group-c"] = [{
            "id": "caller", "name": "caller", "display_name": "Local caller",
            "agent_type": "local", "group_id": "group-c", "is_group": True,
            "actions_to_load": ["legacy-name"], "other_settings": {},
        }]
        self.group_actions["group-c"] = []
        self.workflows["group-c"] = []
        self.native_agents["group-c"] = []


@pytest.fixture
def group_agents_ui(page):
    fixture = GroupAgentsFixture(page)
    yield fixture
    fixture.assert_clean()
