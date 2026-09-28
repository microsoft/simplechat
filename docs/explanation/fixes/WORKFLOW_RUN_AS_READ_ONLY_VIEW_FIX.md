# Workflow Run As Read-Only View Fix (v0.261.149)

## Issue

A group member who opened a workflow they couldn't manage saw "Could not load
eligible Microsoft 365 accounts" in the read-only editor. The editor requested
the group's eligible run-as accounts, but `GET /api/workflows/m365-run-as-users`
refuses anyone outside the group's workflow management roles, which are Owner
and Admin by default. It answers "You cannot configure this group workflow."
with a 403.

Fixed in version: **0.261.149**, tracked in `application/single_app/config.py`.

## Root cause

`WorkflowMicrosoft365RunAs.tsx` requested the account list whenever it rendered,
whatever the viewer's rights. A disabled select still loaded its choices. The
browser fixtures answered that route for everyone, so no suite caught it.

## Technical details

### Files modified

- `components/workflows/WorkflowMicrosoft365RunAs.tsx`: a new `canListAccounts`
  input. When it's false, the component requests nothing. It shows a disabled
  select reading **Account selected** or **No Microsoft 365 account selected**,
  and the line "Only workflow managers can see which account is selected or
  change it." A member can't resolve the selected person's name, so the stored
  user ID is never shown.
- `components/workflows/WorkflowEditorDialog.tsx`: passes
  `options.can_manage`. The gate is the viewer's management right, not the
  editor's read-only state, so a manager whose editor is read-only during an
  active run still sees the account's name.
- `ui_tests/fixtures/workflow_editor.py` and
  `ui_tests/fixtures/group_workspace.py`: the run-as route answers non-managers
  with the server's 403, and records the request as unexpected.

### Tests

`ui_tests/test_v2_workflow_m365_run_as.py` (17 cases):
- a member's read-only editor never requests accounts and shows the stored
  state, with and without a stored account;
- the fixture refuses and records a member's request, which keeps the other
  tests honest;
- the manager cases are unchanged.

## Validation

- Before: a member's read-only editor showed a load error for the run-as
  accounts.
- After: it shows whether an account is selected, with no request and no error.
  Managers see and change the account as before.

## Related

- [Microsoft 365 Actions](../features/MICROSOFT_365_ACTIONS.md)
- [Create a workflow: choose the Microsoft 365 Run as account](../../guides/create-a-workflow.md)
- [V2 Group Workflows](../features/V2_GROUP_WORKFLOWS.md)
