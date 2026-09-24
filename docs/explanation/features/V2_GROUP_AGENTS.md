# V2 Group Agents

## Overview

Implemented in version: **0.261.138**, tracked in
`application/single_app/config.py`.

Group agents can now be listed, opened, created, edited and deleted from the
native V2 group workspace, in the same collection and editor as personal agents.
Previously the group Agents section was marked Classic and sent users to the
classic group workspace.

The endpoint reference is [Group Agent APIs](GROUP_AGENT_APIS.md).

## Who can do what

| | Owner, Admin | DocumentManager, ordinary member |
|---|---|---|
| List agents and open their details | yes | yes |
| Use an agent in chat | yes | yes |
| Create, edit, delete | yes, in an `active` group | no |

When `require_owner_for_group_agent_management` is on, only the Owner can
change group agents. These are the rules the classic group workspace applies.

Everyone else gets a read-only collection and read-only details. A member's
editor receives no model list, so the model section says "Uses a configured
model." rather than showing authoring guidance. A manager with no models to
choose from still sees how to keep the saved connection or configure a custom
one.

## One collection and editor, not two

Personal and group agents share one collection (`AgentsSection`) and one editor
(`AgentEditorPage`). Group behaviour lives in a separate adapter,
`lib/agentWorkbench.ts`, which both components receive as a prop, as group
actions do with `lib/actionWorkbench.ts`.

The adapter's personal path calls the existing functions in
`workspaceAuthoringApi.ts` and the personal knowledge, drafting and delegation
helpers. It holds no personal URL of its own, so personal agents use exactly
the URLs and flows they did before.

The group path uses the group's own routes, with the group ID in the path. It
never relies on the group the account last selected. Every agent it receives is
checked against the page's group; a record from another group is refused rather
than shown.

## Gating

The collection and editor offer an operation only when the server allows it:

- **Create** needs the workspace's `agent_management` block to offer `create`.
- **Edit and delete** also need the agent to belong to this group and to list
  the operation in its own `agent_actions`.
- **Use in chat** needs `chat` in the agent's `agent_actions`.

There is no fallback. A missing or empty hint hides the operation rather than
enabling it. The server checks every request regardless.

The native collection appears only when the group's Agents section is available,
`sections.agents.enabled` in the workspace context. When it isn't, because group
agents are turned off or the administrator restricts them:

- Agents is left out of the group's navigation;
- the overview shows the section locked, with the reason;
- opening its address directly shows the same reason and loads no agent data.

This matches the classic group workspace, which hides its agents tab under the
same settings.

## Provided agents

When the administrator merges global agents into workspaces, they appear in the
group collection marked **Provided · read only**, and open read-only from the
group's own route. Nothing on them can be saved or deleted from the group, and
the group page offers no "Use in chat" for them. They remain available from the
chat agent picker.

## Everything the editor loads stays in the group

| Part of the editor | Group source |
|---|---|
| Model list and editor options | The group's `/agent-options`: global endpoints the caller may use and, when custom group endpoints are allowed, the group's own. Never personal endpoints |
| Custom model connection | Offered only when `allow_group_custom_endpoints` allows it |
| Assigned knowledge | The group's `/agent-knowledge` catalogue, which offers the group's own documents, as it does in the classic group workspace. Never personal sources |
| Actions to load | The group's actions, through the group action adapter. None are offered when group actions are unavailable |
| Call agent targets | The group's delegation catalogue |
| Instruction drafting | Speaks for the group: `agent_scope: "group"` and the group ID |
| Examples and templates | The shared template gallery. A group manager can submit an agent as a template only when the template service would accept it: the gallery is on and, for a non-administrator, personal agent creation and user submissions are allowed. The button reads "Submit template"; the submission is recorded as a personal one, as in the classic group workspace |

**Foundry discovery.** For a Foundry agent on a **global** connection, the group
editor discovers the connection's agents, applications or workflows as the
personal editor does. In 0.261.138, a **group-scoped** Foundry connection
offered no discovery, because the discovery service resolved the group from the
account's selected group rather than the page. **From 0.261.145**, a
group-scoped connection is discovered through
`POST /api/groups/<group_id>/models/foundry/agents`, which resolves the group
from the path. Discovery needs an Owner or Admin in an active group, as the
server requires. A member's read-only editor disables it.

## Creating an action from an agent

An agent editor can hand off to the group action editor to create a new action,
then return with it selected. This is offered only when group actions are
available and the group's `action_management` offers `create`. The created
action returns only to the same group's agent editor. It never lands in another
group's agent draft or in a personal one.

## Use in chat

"Use in chat" opens `/v2/chat?agent_id=<id>&agent_scope=group&agent_scope_id=<group id>&new=1`.
Chat resolves the agent in that group, not in the group the account last
selected. If the link is stale, for example because the agent was deleted or the
user left the group, chat names the group rather than silently choosing another
agent. Personal and provided agent links are unchanged.

## Credentials

Secrets behave as they do for personal agents:

- a stored secret is shown masked, and keeps its stored value when saved
  unchanged;
- a secret is removed only when explicitly cleared;
- a browser can never supply a Key Vault reference.

Group agent credentials are stored in the group's Key Vault namespace, the one
the classic group workspace uses. An agent created in either editor can be
edited and deleted in the other without re-entering its keys.

## Conflicting edits

Each save sends the revision the editor opened. If another manager saved the
agent in the meantime, the save is refused and the draft stays open. The editor
says "This agent changed in another session. Your draft has been retained." and
offers to open the latest saved agent in a new tab, to compare before discarding
or reapplying the changes. Deleting does not take a revision; the server deletes
the version it has just read.

## Drafts

Unsaved drafts are kept per workspace. A draft started in one group is never
restored in another group or in My Workspace, and the reverse. Personal draft
keys are unchanged. After a successful save, the editor returns to the group's
collection without the unsaved-changes prompt.

## Testing and validation

`ui_tests/test_v2_group_agents.py` drives the production V2 build against a
closed fixture that enforces the server's rules. It covers the group surface
with 29 cases:

- layout in light and dark themes at desktop and mobile widths;
- the list and editor reading only the group's routes, with each returned agent
  checked against the page's group;
- manager create, edit and delete, with conditional writes and the stored secret
  kept masked;
- a conflicting save keeping the draft;
- members getting a read-only collection and editor, "Use in chat" and the
  neutral model copy, while a manager with no models keeps the authoring
  guidance;
- provided agents opening read-only;
- the group "Use in chat" link naming the group;
- Foundry discovery for a group-scoped connection calling the named-group
  route (from 0.261.145), while a global connection keeps the existing route;
- template submission offered only when the server allows it;
- a new action created from the agent editor returning to the kept draft in the
  same group;
- the section staying unavailable, with no agent request, when group agents are
  off.

The group and public fixtures record any request for personal data from a
shared page as unexpected, so a test fails on it rather than the fixture
answering it. Personal data here means `/api/user/*` except settings, personal
identities, personal File Sync, personal prompts and documents, personal MCP
preconfigurations, and any `scope=personal` or `agent_scope=personal` query. No
suite surfaced one.

On the integrated tree these pass unchanged:

- personal authoring, `test_v2_workspace_authoring.py` (93);
- draft navigation (3) and delegation (4);
- group actions (25), group prompts (17) and the group shell (21);
- the document and public suites;
- the 27 workspace authoring logic checks.

## Related

- [Group Agent APIs](GROUP_AGENT_APIS.md)
- [V2 Group Actions](V2_GROUP_ACTIONS.md)
- [V2 Workspace Agents and Actions](V2_WORKSPACE_AGENTS_ACTIONS.md)
