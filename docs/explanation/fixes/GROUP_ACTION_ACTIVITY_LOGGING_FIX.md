# Group Action Activity Logging Fix

## Issue

Fixed in version: **0.261.138**

Creating, editing or deleting a group action from the native V2 group workspace
recorded no activity event. The native routes shipped in 0.261.137
(`/api/groups/<group_id>/actions[/<action_id>]`). The classic group action routes
record one for every change, with `scope='group'` and the group, so activity
views and audits showed native changes as if they had never happened.

## Root cause

The native group action handlers in `functions_group_action_access.py`
(`create_group_action`, `update_group_action` and `delete_group_action`) ran the
shared editor engine's conditional writes and returned. They never called the
activity logging that the classic routes call:

- `log_action_creation` and `log_action_update`, in `route_backend_plugins.py`,
  after a group save;
- `log_action_deletion`, after a group delete.

The personal editor records these events in `personal_editor_response`, but the
group handlers do not go through it. The M4 implementation contract listed
authorization, conditional writes and the chat cache bump, but not activity
logging, so neither half added it.

## Fix

A shared helper, `log_committed_group_editor_change(kind, user_id, group_id,
stored, operation)`, in `functions_workspace_authoring.py`, records the event
the classic routes record:

- `log_action_creation`, `log_action_update` or `log_action_deletion` for
  actions, and `log_agent_*` for the new native group agent routes;
- with `scope='group'` and the group named in the path, never the active group;
- with the record's ID and name, plus the action type or the agent display name,
  except on delete.

The group handlers call it only after the conditional write has committed. A
refused write (400, 403 or 409) raises before that point, so it records nothing.
A failure to record activity is caught and logged at warning level as
`[WORKSPACE_ACTIVITY] Unable to record a committed editor change.`, and never
undoes or fails the committed change. This matches the personal editor.

### Files modified

- `application/single_app/functions_workspace_authoring.py`:
  `log_committed_group_editor_change`.
- `application/single_app/functions_group_action_access.py`: the create, update
  and delete handlers call it.
- `application/single_app/functions_group_agent_access.py`: the same for the new
  native group agent routes.

## Validation

`functional_tests/test_group_action_apis.py` (63 cases) covers:

- each of create, update and delete records its event, with `scope='group'`,
  the path group, and the record's ID, plus the name and type on create;
- a logger that raises still returns success, the write is kept, and the
  warning is emitted;
- a refused write, from a non-writer (403) or after a conflict (409), records
  nothing.

`functional_tests/test_group_agent_apis.py` covers the same for group agents.

Related: [Group Action APIs](../features/GROUP_ACTION_APIS.md),
[Group Agent APIs](../features/GROUP_AGENT_APIS.md).
