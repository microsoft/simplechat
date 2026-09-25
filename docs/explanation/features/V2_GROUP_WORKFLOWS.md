# V2 Group Workflows: File Sync Triggers And Alert Summary (v0.261.141)

## Overview

The native V2 editor for group workflows can now author the two File Sync
behaviours the classic group editor offers:

- the **Monitor File Sync changes** trigger;
- **Run File Sync before each run**.

It also shows a workflow's stored alert settings. Before this release, V2 kept an
existing workflow's File Sync configuration but couldn't create or change it,
and it offered no view of alerts.

Implemented in version: **0.261.141**, tracked in
`application/single_app/config.py`.

Personal workflows are unchanged. No new setting, route or container is added.

## What changed

### File Sync sources for the named group

`GET /api/group/workflows/file-sync-sources` used to read the account's active
group directly. It now resolves the group through
`_resolve_active_group_for_workflows`, like every other group workflow route:

- `?group_id=G` is honoured first, and checked with `assert_group_role` against
  the File Sync manager roles (Owner, Admin and DocumentManager);
- without it, the route behaves as before.

A member is refused with 403, and an unknown group is 404. When File Sync isn't
enabled for the group, the list is empty. From version **0.261.149** the
response also carries `file_sync_enabled`, so a client can tell "File Sync is
off" from "no sources". It is computed by the same
`is_file_sync_enabled_for_group` call the save uses.

Each source is:

```json
{"scope_type": "group", "scope_id": "G", "source_id": "...", "name": "...",
 "source_type": "...", "enabled": true, "label": "..."}
```

The V2 editor rejects the whole list if any entry belongs to another scope or
group, rather than showing a partial list.

### Authoring File Sync in the group editor

These apply only when the editor can manage the workflow. The source list is
requested with the page's explicit group.

- **Trigger.** **Monitor File Sync changes** is offered when the group has at
  least one File Sync source, or when the workflow already uses it. Choosing it
  applies the server's rules: File Sync runs before each run, the workflow waits
  for it to complete, and continues only when files changed. The interval value
  and unit then set how often the sources are checked.
- **File Sync section:**
  - **Run File Sync before each run**. This is required, and locked on, for the
    Monitor trigger.
  - **File Sync sources**. Choose between 1 and 10, from this group only.
    Disabled sources are flagged. A saved source the group no longer offers is
    flagged **No longer available**, and must be removed before saving.
  - **Wait for File Sync**: **Until sync completes** or **Queue only**.
  - **Continue the workflow**: **Always continue** or **Only when files
    changed**. Queue only with Only when files changed is refused.
  - **Use changed files as Analyze targets**.
- **Validation.** The editor applies the same rules `save_group_workflow`,
  `_normalize_file_sync_config` and `_normalize_schedule` enforce. So a save the
  editor allows is one the server accepts. The schedule ranges are 1-59 for
  seconds and minutes, and 1-24 for hours. Until 0.261.149 the server answered
  every refused setting with one generic message. From **0.261.149** it names
  the rule, and the editor checks personal and group workflows with the same
  messages; see the
  [reviewed messages fix](../fixes/WORKFLOW_SETTINGS_REVIEWED_MESSAGES_FIX.md).
  When File Sync is off for the group, the editor says so and applies the
  save's rule.
- **Preservation.** A save sends `file_sync` only when it changed. An untouched
  stored value goes back exactly as it was loaded.

### Analyze on the files a sync changed

The server lets an Analyze task run with no selected documents when File Sync is
enabled with **Use changed files as Analyze targets**. The V2 editor used to
require selected evidence anyway. So a group workflow built that way in the
classic editor could be opened in V2, but not saved. In group scope, V2 now
allows it, and explains that the task analyzes the files each sync changed.

### Alerts

In 0.261.141, group workflows showed a read-only **Alerts** summary, and linked
to the classic editor for version 1 workflows. **From 0.261.144, alerts are
edited natively in V2, for personal and group workflows. The classic link is
gone.** See [V2 Workflow Alert Editing](V2_WORKFLOW_ALERT_EDITING.md). Viewers
who can't manage a workflow still see the read-only summary, which is resolved
the way the server's `resolve_workflow_alert_config` does.

### Approvals

The V2 run approval panel already decides group runs through the group route,
`/api/group/workflows/<workflow>/runs/<run>/runtime/decision?group_id=G`. Every
runtime read also carries `group_id`. No change was needed.

### Who can run a group workflow (0.261.178)

Classic, and the server's run and cancel routes, let every group member run
and cancel a group workflow. Before this version, V2 offered **Run** and
**Cancel** only to the members who can manage group workflows. From version
**0.261.178**:
- The group workspace context publishes `workflow_management`, `{schema_version:
  1, operations: [...]}`. It comes from `functions_group_workflow_policy.py`,
  which the routes' own role lists also come from:
  - `run` and `cancel` go to every member (`GROUP_WORKFLOW_MEMBER_ROLES`);
  - `create`, `edit` and `delete` go to the roles allowed to manage group
    workflows.
- The Workflows section gates each control on its own operation. A member
  sees **Run**, **Cancel** and **View**, but not **Create**, **Edit** or
  **Delete**.
- All of them need an **active** group. The routes check no status, so V2 keeps
  its active-only rule, and adding a status check to the routes is a recorded
  follow-up.
- Per-run **Cancel** and **Resume failed** in the run history aren't in V2 yet,
  for personal or group workflows (an approved exception).

## Files

| File | Change |
|---|---|
| `application/single_app/route_backend_workflows.py` | The sources route honours `?group_id` |
| `application/v2_ui/src/lib/workflowEditor.ts` | File Sync configuration, validation and save helpers; the source list fetch; the alert summary and classic predicate (moved to `workflowAlerts.ts`, and the predicate removed, in 0.261.144); Analyze targets |
| `application/v2_ui/src/components/workflows/WorkflowFileSyncFields.tsx` | New: the File Sync section |
| `application/v2_ui/src/components/workflows/WorkflowAlertSummary.tsx` | New: the alert summary (read-only viewers only from 0.261.144) |
| `application/v2_ui/src/components/workflows/WorkflowEditorDialog.tsx`, `WorkflowTaskFields.tsx` | Trigger choice, schedule fields, the new sections, Analyze targets |
| `application/v2_ui/src/lib/workflowSettings.ts` (0.261.149) | New: the client mirror of the server's File Sync, schedule and trigger rules and messages, for both scopes |

## Known limitations

- **Personal workflows.** Personal File Sync authoring isn't part of this
  release. From 0.261.144, a personal workflow that analyzes changed files can
  be saved in V2; see the [Analyze changed files fix](../fixes/V2_GROUP_WORKFLOW_ANALYZE_CHANGED_FILES_FIX.md).
  So a personal workflow whose stored source was deleted can't be fixed in V2:
  the save is refused with a reviewed message and the draft is kept.
- **Someone else saved the workflow first.** The editor sends the revision it
  opened, and the server refuses a save made from an older copy ("This workflow
  changed since it was opened. Reload it before saving."). So a save can never
  overwrite someone else's changes. The editor keeps your draft on screen, but
  it can't merge it with theirs: closing and reopening the workflow loads the
  saved version, and your unsaved edits are lost. Note what you changed before
  reopening. The prompt, identity, endpoint and file source editors merge
  instead (version 0.261.152).

Fixed in 0.261.149, and listed here as limitations until then:
- **Deleted sources.** A source deleted after the editor loaded its list made
  the save fail with 404, which the editor treated as lost access, losing the
  draft. The save is now refused with a reviewed 400 that keeps the draft and
  marks the source; see the [save after deletion fix](../fixes/WORKFLOW_SAVE_AFTER_DELETION_FIX.md).
- **Member view.** A member's read-only editor asked for the group's Microsoft
  365 run-as accounts, and showed an error when the route refused. It no longer
  asks; see the [run-as read-only view fix](../fixes/WORKFLOW_RUN_AS_READ_ONLY_VIEW_FIX.md).

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_group_workflow_file_sync_sources_scope.py` | 12 | The explicit group is listed and the active group is never read; the `groupId` and whitespace spellings; DocumentManager allowed; a member refused with a group ID; a non-member and an unknown group; the legacy path without `group_id` unchanged; the disabled and unassigned gates; File Sync off gives an empty list, and from 0.261.149 `file_sync_enabled: false` |
| `functional_tests/test_group_workflow_file_sync_enabled_seam.py` | 22 (0.261.149) | `file_sync_enabled` equals the save's File Sync gate, across the File Sync states, the admin-only setting and the caller's app roles |
| `functional_tests/test_group_workflow_round_trip_preservation.py` | 5 | A workflow with alert rules, URL access, a Monitor File Sync trigger and an Analyze action is saved, loaded and sent back unchanged. Every stored field matches except the modification stamps, and a second round trip is stable. Runs through the real workflow modules |
| `functional_tests/test_group_workflow_file_sync_client_parity.py` | 173 (25 before 0.261.149) | The production TypeScript runs under Node, and each payload goes through the real save routes. The editor allows a save if and only if the server accepts it, and from 0.261.149 shows the same message, in both scopes. The alert summary matches the server |
| `ui_tests/test_v2_group_workflow_file_sync.py` | 13 | Authoring checked on the saved body; editing and the round trip, including Analyze on changed files; File Sync before a manual run; unavailable sources; no sources and the server's refusal text; the member view; responsive layout |
| `ui_tests/test_v2_workflow_settings_errors.py` | 6 (0.261.149) | Deleted sources and workflows keep the draft; personal schedules are checked with the server's message; the File-Sync-off state |
| `functional_tests/test_workflow_*.js` | 167 | The workflow editor logic, including the settings mirror from 0.261.149 |

The existing V2 workflow browser suites and the group workspace browser suites
show the same results before and after this change.

## Related

- [V2 Group Workflow Analyze Changed Files Fix](../fixes/V2_GROUP_WORKFLOW_ANALYZE_CHANGED_FILES_FIX.md)
- [Group Workflows](GROUP_WORKFLOWS.md)
- [Workflow Alert Rules](WORKFLOW_ALERT_RULES.md)
- [File Sync Source Workflow](FILE_SYNC_SOURCE_WORKFLOW.md)
- [Create a workflow](../../guides/create-a-workflow.md)
