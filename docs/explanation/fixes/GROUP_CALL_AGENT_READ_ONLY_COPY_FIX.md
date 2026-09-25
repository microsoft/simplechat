# Group Call Agent Read-Only Copy Fix

## Issue

In the V2 group workspace's **Actions** section, the **Call agent** manager's
introduction always offered a choice: "Choose which agents this group can call
and which local actions may trigger them." When group actions were off, the
section said "You can still choose which agents this group can call…".

The manager beneath it is often read-only, though. The server's
`native_delegation.can_manage` hint decides, and the manager already followed it
(`allowManage`). So a member, or anyone in a group with group actions turned
off, read an invitation to choose that the controls below didn't honour.

## Root cause

The introductions were written as fixed strings when M8A (version 0.261.153)
removed the classic handoffs from the group sections, and never read the hint
the manager itself uses.

Fixed in version: **0.261.166**

## Technical details

`native_delegation.can_manage` is true only when all of these hold (from
`functions_workspace_context.py`):
- the viewer's role is one of the roles allowed to manage group workflows
  (`get_group_workflow_management_roles`);
- the group is active;
- group actions (`allow_group_plugins`) are on.

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/pages/GroupWorkspacePage.tsx` | Both introductions follow `native_delegation.can_manage`. Comments that said an unavailable section "falls through to Classic" now say it shows its locked state with the server's reason, as it has since M8A. |
| `application/v2_ui/src/lib/groupWorkspaceNavigation.ts` | The unused `classicGroupSectionLabel` export is removed. Nothing in the app called it after M8A. |
| `functional_tests/test_v2_group_workspace_context_logic.mjs` | Its pin of that export is removed. |
| `ui_tests/fixtures/group_workspace.py` | Imports `action_editor_auth_types` from `workspace_authoring` instead of carrying an identical copy. |
| `ui_tests/test_v2_group_actions.py` | A three-way check: a manager, a member, and a group with group actions off. |
| `ui_tests/test_v2_group_classic_handoffs.py` | The two tests that pinned the old copy in read-only cases expect the read-only wording. |

### The copy

| Case | Before | After |
| --- | --- | --- |
| Group actions on, can manage | Choose which agents this group can call and which local actions may trigger them. | Unchanged |
| Group actions on, read-only | Choose which agents this group can call and which local actions may trigger them. | The agents this group can call and the local actions that may trigger them. |
| Group actions off, can manage | Group actions are turned off for this group. You can still choose which agents this group can call and which local actions may trigger them. | Unchanged |
| Group actions off, read-only | Group actions are turned off for this group. You can still choose which agents this group can call and which local actions may trigger them. | Group actions are turned off for this group. These are the agents this group can call and the local actions that may trigger them. |

## Validation

- `ui_tests/test_v2_group_actions.py` checks the manager, member and
  actions-off cases. Restoring the old copy fails all three read-only checks.
- Group actions (28), classic handoffs (10), workspace shell (21), agents (29),
  journeys and delegation pass on the integrated tree, as do the action fixture
  parity pin and the context logic checks.

## Related

- [V2 Group Actions](../features/V2_GROUP_ACTIONS.md)
- [Call agent action reference](../../reference/actions/agent.md)
