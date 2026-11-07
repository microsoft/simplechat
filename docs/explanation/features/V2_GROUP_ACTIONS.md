# V2 Group Actions

## Overview

Implemented in version: **0.261.137**, tracked in
`application/single_app/config.py`.

Group actions can now be listed, opened, created, edited, tested and deleted
from the native V2 group workspace, in the same collection and editor as
personal actions. Previously the group Actions section offered only the Call
agent manager and sent every other action to the classic interface.

The endpoint reference is [Group Action APIs](GROUP_ACTION_APIS.md).

## Who can do what

| | Owner, Admin | DocumentManager, ordinary member |
|---|---|---|
| List actions and open their details | yes | yes |
| Create, edit, delete | yes, in an `active` group | no |
| Test a connection | yes, in an `active` group | no |

When `require_owner_for_group_agent_management` is on, only the Owner can
change or test group actions. These are the same rules the classic group
workspace applies.

Everyone else gets a read-only collection and read-only details. The details
still render the action's configuration fields, because the action type
catalogue is available to every member.

## One collection and editor, not two

Personal and group actions share one collection (`ActionsSection`) and one
editor (`ActionEditorPage`). Group behaviour lives in a separate adapter,
`lib/actionWorkbench.ts`, which the two components receive as a prop.

The adapter's personal path calls the existing functions in
`workspaceAuthoringApi.ts` and `workspaceActionServices.ts`. It holds no
personal URL of its own, so personal actions still use exactly the URLs and
flows they did before.

The group path uses the group's own routes, with the group ID in the path. It
never relies on the group the account last selected. Every action it receives
is checked against the page's group; a record from another group is refused
rather than shown.

## Gating

The collection and editor offer an operation only when the server allows it:

- **Create** needs the workspace's `action_management` block to offer `create`.
- **Edit, delete and test** additionally need the action to belong to this group
  and to list the operation in its own `action_actions`.

There is no fallback. A missing or empty hint hides the operation rather than
enabling it. The server checks every request regardless.

The native collection appears only when the group's Actions section is
available, `sections.actions.enabled` in the workspace context. A tenant can
enable group agents without group actions. The group then keeps the Call agent
manager, with no classic link from version 0.261.153. From version
**0.261.166**, the manager and its introduction are read-only unless the
workspace context's `native_delegation.can_manage` is true. That needs one of
the roles allowed to manage group workflows, an active group, and group actions
turned on.

## Provided actions

When the administrator merges global actions into workspaces, they appear in the
group collection marked **Provided · Read only**. Opening one shows its details
read-only, from the group's own route. Nothing on it can be saved, deleted or
tested from the group.

## Credentials

Secrets behave exactly as they do for personal actions:

- a stored secret is shown masked, and keeps its stored value when saved unchanged;
- a secret is removed only when explicitly cleared;
- a browser can never supply a Key Vault reference.

Group action secrets are stored in the group's Key Vault namespace, not the
saving member's.

The editor's secret-expiration and reminder defaults come from the group's own
`/api/groups/<group_id>/action-options` route. The group editor never reads the
member's personal agent settings.

## MCP actions

The MCP editor keeps its compatibility presets, which are the same for every
workspace. Saved MCP preconfigurations are not offered for group actions yet:
the personal list is the wrong workspace, and the only group list follows the
account's selected group. The editor says so, and the server can still be
configured manually.

## Identities

From version **0.261.139**, the group action editor lists the group's reusable
identities from the group's own route (`GET /api/groups/<group_id>/identities`),
keeping those the server reports as usable for actions. It never loads a
member's personal identities. Group identities are managed in the group's
Identities section; see [V2 Group Identities](V2_GROUP_IDENTITIES.md).

- **Someone who cannot list the group's identities**, such as an ordinary
  member: the editor shows no error, and keeps an existing binding, described as
  "Uses a group identity; kept as is."
- **The list loaded, but the bound identity is not in it:** the editor calls
  the binding unavailable.
- **The list could not be loaded:** the editor shows the load error and keeps
  the neutral wording.

In 0.261.137 no group identity could be chosen, and an existing binding was
kept as "Group identity".

## Connection tests

A connection test from a group editor names the page's group:
`action_scope: "group"` and `group_id` in the request, and a group-scoped
action context. The server then tests the action in that group, not in the
group the account last selected. Personal tests are unchanged.

## Conflicting edits

Each save sends the revision the editor opened. If another manager saved the
action in the meantime, the save is refused. The editor stays open with the
draft intact and offers **Load saved version**. Deleting does not take a
revision; the server deletes the version it has just read.

## Drafts

Unsaved drafts are kept per workspace. A draft started in one group is never
restored in another group or in My Workspace, and the reverse. The same applies
to an action created from an agent editor and handed back to it. Personal draft
keys are unchanged.

After a successful save, the editor returns to the group's collection without
the unsaved-changes prompt.

## Testing and validation

`ui_tests/test_v2_group_actions.py` covers the group surface with 25 cases:

- reads only from the group routes, and response identity checked against the group;
- manager create, edit (conditional) and delete;
- a stored secret preserved on save;
- the group connection-test payload;
- draft retention on a conflict;
- an action with empty `action_actions` beside one with actions, proving the
  gate works action by action;
- member read-only collection and editor, with the type catalogue loaded;
- an identity-bound action edited without any identity request;
- a group MCP editor that reads its reminder defaults from the group route and
  makes no preconfiguration or personal settings request;
- the Call agent fallback when group actions are unavailable;
- a provided action opened read-only;
- draft isolation between groups and personal scope;
- layout in light and dark at 1440x900 and 390x844.

Its fixture refuses what the server refuses: a query string on any group route,
and `action_actions` sent back in a write. It also records any request from a
group page to the personal agent settings or the MCP preconfiguration list as
unexpected, so a personal-scope read fails the suite rather than passing
silently.

`functional_tests/test_group_action_fixture_parity.py` holds that fixture to the
real group action routes, route by route: only server keys, every field the
editor reads present on both sides, and matching statuses and error codes. The
type catalogue comes from the real editor type builder. When it was added, after
version **0.261.161**, it corrected four places where the fixture had drifted:
the provided row's invented `group_id`, invented refusal texts, invented
stored-credential refusals, and the auth types offered for each action type,
which the server sorts and, for a type with no definition file, takes from the
shared plugin schema.

The personal authoring, draft navigation and delegation suites pass unchanged,
as do the group prompt, group document and personal document suites.

## Related

- [Group Action APIs](GROUP_ACTION_APIS.md)
- [Group Action Test Role Alignment Fix](../fixes/GROUP_ACTION_TEST_ROLE_ALIGNMENT_FIX.md)
- [V2 Group Prompts](V2_GROUP_PROMPTS.md)
