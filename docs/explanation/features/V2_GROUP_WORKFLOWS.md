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
enabled for the group, the list is empty.

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
  editor allows is one the server accepts. That matters because the server
  answers every refused workflow with one generic message, which the editor
  shows as returned. The schedule ranges are 1-59 for seconds and minutes, and
  1-24 for hours.
- **Preservation.** A save sends `file_sync` only when it changed. An untouched
  stored value goes back exactly as it was loaded.

### Analyze on the files a sync changed

The server lets an Analyze task run with no selected documents when File Sync is
enabled with **Use changed files as Analyze targets**. The V2 editor used to
require selected evidence anyway. So a group workflow built that way in the
classic editor could be opened in V2, but not saved. In group scope, V2 now
allows it, and explains that the task analyzes the files each sync changed.

### Alerts

Every group workflow shows a read-only **Alerts** summary: **When to alert**,
**Pop-up priority**, and the number of **Alert rules**. The values are resolved
the way the server's `resolve_workflow_alert_config` does, including older
records that store only a priority.

Whether the summary offers a classic link depends on the workflow:

| Workflow | Summary |
|---|---|
| `definition_version` 1 with no `flow` | **Edit alerts in the classic workspace** is offered. It uses the group page's classic handoff, which asks about unsaved changes and selects this group first. The summary warns that saving the workflow in V2 converts it, after which the classic editor can no longer open it. |
| Saved by V2 (version 2 or 3) | Says the alert settings are kept unchanged when you save. The classic editor refuses these definitions, so their alerts can't be changed until native alert editing is available. |
| New in V2 | Says alerts can't be added yet. |

The link predicate matches the classic editor's own `workflowNeedsNativeEditor`.

### Approvals

The V2 run approval panel already decides group runs through the group route,
`/api/group/workflows/<workflow>/runs/<run>/runtime/decision?group_id=G`. Every
runtime read also carries `group_id`. No change was needed.

## Files

| File | Change |
|---|---|
| `application/single_app/route_backend_workflows.py` | The sources route honours `?group_id` |
| `application/v2_ui/src/lib/workflowEditor.ts` | File Sync configuration, validation and save helpers; the source list fetch; the alert summary and classic predicate; Analyze targets |
| `application/v2_ui/src/components/workflows/WorkflowFileSyncFields.tsx` | New: the File Sync section |
| `application/v2_ui/src/components/workflows/WorkflowAlertSummary.tsx` | New: the alert summary |
| `application/v2_ui/src/components/workflows/WorkflowEditorDialog.tsx`, `WorkflowTaskFields.tsx` | Trigger choice, schedule fields, the new sections, Analyze targets |
| `application/v2_ui/src/pages/workspace/WorkflowsSection.tsx`, `pages/GroupWorkspacePage.tsx` | The classic handoff for the alerts link |

## Known limitations

- **Deleted sources.** A source deleted after the editor loaded its list makes
  the save fail with 404. The editor treats that as lost access and closes the
  draft. The editor prevents this whenever its list was loaded after the
  deletion.
- **Personal workflows.** Personal File Sync workflows that analyze changed files
  still can't be saved in V2. Personal File Sync authoring isn't part of this
  release.
- **Older group records.** A group workflow saved before `definition_version`
  existed reads as version 2 in V2, so it offers no classic alerts link, even
  though the classic editor could open it.
- **Member view.** A member's read-only editor asks for the group's Microsoft 365
  run-as accounts. The route refuses members, so the editor shows "Could not load
  eligible Microsoft 365 accounts". This is pre-existing.
- **Native alert editing** is the follow-up slice M6B.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_group_workflow_file_sync_sources_scope.py` | 12 | The explicit group is listed and the active group is never read; the `groupId` and whitespace spellings; DocumentManager allowed; a member refused with a group ID; a non-member and an unknown group; the legacy path without `group_id` unchanged; the disabled and unassigned gates; File Sync off gives an empty list |
| `functional_tests/test_group_workflow_round_trip_preservation.py` | 5 | A workflow with alert rules, URL access, a Monitor File Sync trigger and an Analyze action is saved, loaded and sent back unchanged. Every stored field matches except the modification stamps, and a second round trip is stable. Runs through the real workflow modules |
| `functional_tests/test_group_workflow_file_sync_client_parity.py` | 25 | The production TypeScript runs under Node, and each payload goes through the real `save_group_workflow`. The editor allows a save if and only if the server accepts it, over 21 cases. The alert summary and classic predicate match the server and classic implementations |
| `ui_tests/test_v2_group_workflow_file_sync.py` | 12 | Authoring checked on the saved body; editing and the round trip, including Analyze on changed files; File Sync before a manual run; unavailable sources; no sources and the server's refusal text; the member view; responsive layout |
| `functional_tests/test_workflow_*.js` | 112 | The existing workflow editor logic, unchanged |

The existing V2 workflow browser suites and the group workspace browser suites
show the same results before and after this change.

## Related

- [V2 Group Workflow Analyze Changed Files Fix](../fixes/V2_GROUP_WORKFLOW_ANALYZE_CHANGED_FILES_FIX.md)
- [Group Workflows](GROUP_WORKFLOWS.md)
- [Workflow Alert Rules](WORKFLOW_ALERT_RULES.md)
- [File Sync Source Workflow](FILE_SYNC_SOURCE_WORKFLOW.md)
- [Create a workflow](../../guides/create-a-workflow.md)
