# Public Workspace Conversation Retention Fix

## Header Information

- **Fixed in version:** **0.261.272**
- **Area:** Retention policy for public workspaces, and retention scheduling from the V2
  admin surface
- **Related feature:** [V2 Admin Data Lifecycle Settings](../features/V2_ADMIN_DATA_LIFECYCLE_SETTINGS.md)

### Issue Description

Two retention problems surfaced while bringing the V2 Data Lifecycle settings to parity.

**Public workspace conversation retention did nothing.** Both admin pages offer a default
conversation period for public workspaces, and public workspace owners can set their own, but
the retention job never applied either. `process_public_retention` skipped conversations
entirely, and the public branch of `_build_conversation_retention_sources` referred to
`cosmos_public_conversations_container` and `cosmos_public_messages_container`, which do not
exist; it would have raised `NameError` had it ever been reached.

**Switching retention on from V2 did not schedule a run.** The classic save handler recomputes
`retention_policy_next_run` whenever it saves. The V2 PATCH saved the type switches through the
`enable_*` fallback without that step, so a type switched on in V2 left no next run. The
scheduler treats a missing next run as due, so retention ran within five minutes of the save
instead of at the configured hour.

### Root Cause

Public workspaces have no conversation store. A chat grounded in a public workspace is a
personal conversation in `conversations`, whose primary context is
`{type: primary, scope: public, id: <workspace>}` and whose `chat_type` is `public`. The
0.250.103 ownership rework gave chats grounded in a group to the group's policy but left
public-grounded chats under their owner's personal policy, and the public pass was written as
though a separate public conversation container existed.

The scheduling gap is a V1/V2 divergence: the rescheduling lived only in the server-rendered
form's save handler.

## Technical Details

### Policy Ownership Matrix

| Conversation type | Storage | Governing policy | Activity field |
|---|---|---|---|
| Personal single-user | `conversations` | Creator's personal policy | `last_updated` |
| Group single-user | `conversations` | Primary group's policy | `last_updated` |
| **Public single-user** | `conversations` | **Primary public workspace's policy** | `last_updated` |
| Personal multi-user | `collaboration_conversations` | Creator's personal policy | `updated_at` |
| Group multi-user | `collaboration_conversations` | `scope.group_id` policy | `updated_at` |
| Legacy group | `group_conversations` | Group policy | `last_updated` |

A public single-user chat is recognised by the workspace id in its primary context, not by
`chat_type` alone, and it follows the workspace's policy only while the workspace exists.
Deleting a public workspace removes only the workspace record, so its grounded chats stay in
`conversations` where no public run will reach them again. A chat with no workspace id, or
grounded in a workspace that no longer exists, therefore stays under its owner's personal policy
rather than falling outside every policy.

The personal run lists the existing public workspaces once (`SELECT c.id`) and passes the set to
each user's pass. A failed or interrupted listing yields `None`, never an empty set: the
personal run then skips every grounded chat for that run instead of reading the failure as
every workspace having been deleted and removing chats under the wrong policy.

### Files Modified

| File | Change |
|---|---|
| `application/single_app/functions_retention_policy.py` | `_get_primary_public_workspace_id`, `_is_governed_by_public_workspace`, `_get_existing_public_workspace_ids`, `_build_public_scope_query`; personal pass excludes chats grounded in an existing public workspace; public source reads `conversations` and `messages`; `process_public_retention` deletes aged public-grounded chats; activity logs carry the grounded workspace id; owner notifications |
| `application/single_app/admin_settings_fields.py` | `compute_retention_next_run` and `_apply_retention_schedule`, applied to valid V2 saves; the run hour validated and stored as an int |
| `functional_tests/test_retention_policy_conversation_scope_coverage.py` | Public matrix rows, chats from deleted workspaces returning to personal policy, failed-listing safety, public deletion and logging, notification privacy |
| `functional_tests/test_v2_admin_data_lifecycle_parity.py` | Rescheduling against the classic rule, hour normalization |
| `application/single_app/config.py` | Version `0.261.272` |

### Notification Privacy

A public workspace's retention notification goes to its owner, admins and document managers.
Group notifications have always listed the titles of deleted chats, but a public workspace's
chats belong to arbitrary users across the organisation, and their titles are not the
workspace managers' to see. So:

- the workspace notification reports how many conversations were removed, without titles, and
  lists removed documents as before;
- each chat's owner receives a personal notification naming their own removed chats and the
  workspace they were grounded in;
- records another process had already deleted are left out of owner notifications, because
  retention did not remove them.

### Scheduling Rule

`_apply_retention_schedule` runs only when a type switch or the run hour is in a valid save. It
moves the run when one of those values changed, or when no next run is stored. With every type
off it clears the next run; otherwise it sets the next occurrence of the hour in UTC, the rule
`execute_retention_policy` and the classic handler use. An unrelated save never moves a pending
run.

### Impact

- **Behaviour change:** chats grounded in a public workspace now follow that workspace's
  conversation period instead of their owner's personal period. Where public retention is off,
  retention no longer deletes them, exactly as with group-grounded chats when group retention is
  off. Administrators relying on personal retention to clear these chats should switch public
  retention on and set a default.
- Public workspace owners' conversation period, already offered in both interfaces, now takes
  effect.
- Switching retention on from V2 schedules the next run at the configured hour.
- **Known limitation, unchanged:** chats grounded in a group that has since been deleted are
  still excluded from personal retention and reached by no group run. This change does not
  alter group ownership.

## Validation

### Test Results

- `functional_tests/test_retention_policy_conversation_scope_coverage.py`: the policy matrix
  (including chats from deleted workspaces and a failed listing), the end-to-end personal run
  over live, deleted and ungrounded workspaces, public-grounded deletion and logging, and
  notification privacy pass. Three collaboration cleanup tests in the same file fail
  identically before and after this change, because the test harness cannot import every
  module `functions_collaboration` depends on; they are unrelated to retention scope.
- `functional_tests/test_v2_admin_data_lifecycle_parity.py`: 10 of 10 pass, including
  rescheduling compared with the classic rule across hours and dates.

### Before and After

| Scenario | Before | After |
|---|---|---|
| Public workspace conversation period | Stored, never applied | Applied to chats grounded in the workspace |
| Chat grounded in a public workspace | Followed the owner's personal period | Follows the public workspace's period |
| Chat grounded in a deleted public workspace | Followed the owner's personal period | Still follows the owner's personal period |
| Public retention notification | No conversation section | Count only for managers; titles to each owner |
| Retention type switched on from V2 | No next run; ran within five minutes | Next run at the configured hour |
| Run hour saved from V2 | Not editable in V2 | Saved as an int; out-of-range values refused |
