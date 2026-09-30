# V2 Personal Workflow File Sync (v0.261.207)

## Overview

The V2 editor for personal workflows can now author File Sync, the same way the
V2 group editor has since 0.261.141 and the classic personal editor always has:

- the **Monitor File Sync changes** trigger;
- **Run File Sync before each run**, with **Wait for File Sync** and **Continue
  the workflow**;
- **Use changed files as Analyze targets**.

Before this release, V2 kept a personal workflow's stored File Sync settings but
couldn't create or change them, so a personal workflow whose stored source was
deleted couldn't be fixed in V2.

This is the first part of [Chat Orchestration Workflows Phase 4](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md)
(issue #1547): a workflow proposed from chat that reviews new File Sync files
must open in an editor that can show and change its File Sync settings.

Implemented in version: **0.261.207**, tracked in
`application/single_app/config.py`.

Dependencies: the V2 group File Sync editor ([V2 Group Workflows](V2_GROUP_WORKFLOWS.md)),
the File Sync settings mirror in `workflowSettings.ts` (0.261.149), and the
personal File Sync gate in `functions_file_sync.py`. No setting, container or
deployer change is added.

## Technical specifications

### Sources a personal workflow can use

`GET /api/user/workflows/file-sync-sources` keeps its path, decorators and
rules. Its body moved into the Flask-free
`functions_workflow_file_sync_sources.py`, so the chat planner can list the same
sources without a request context. `collect_personal_workflow_file_sync_sources`
returns the personal File Sync gate and the sources:

- the user's own sources, while `is_file_sync_enabled_for_user` allows them.
  That gate applies `enable_file_sync`, `enable_file_sync_personal`,
  `file_sync_personal_admin_only` and `file_sync_personal_require_app_role`
  (the **PersonalFileSyncUser** app role);
- the **active** group's sources, when the user holds a File Sync manager role
  there (Owner, Admin or DocumentManager) and File Sync is on for the group;
- the **active** public workspace's sources, by the same two rules. Its id is
  trimmed.

A missing, unknown or unmanaged workspace is skipped rather than failing the
list, and sources without an id are dropped. User settings are read once,
through the reader the caller passes; the route uses `get_user_settings`.

The response now also carries `file_sync_enabled`, the personal gate, so the
editor can say "File Sync is not enabled for your personal workspace" instead
of showing an empty list:

```json
{"sources": [{"scope_type": "personal", "scope_id": "U", "source_id": "...",
  "name": "...", "source_type": "...", "enabled": true, "label": "Home share (Personal)"}],
 "file_sync_enabled": true}
```

A failure returns "Unable to load File Sync sources right now." with a 500.
Credentials are never returned.

The save path is unchanged. `save_personal_workflow` authorizes every selected
source again with `get_authorized_sync_source`: a deleted source is the reviewed
400 `file_sync_source_unavailable`, and a source the user may no longer use is
the existing 403.

### The editor

| Area | Personal behaviour |
|---|---|
| Source list | Fetched from the personal route when the editor can save. A read-only editor, including one opened read-only for an unsupported schedule, never asks for it. |
| Labels | Every source shows where it lives: "Name (Personal)", "(Group)" or "(Public)". |
| Monitor trigger | Offered when the list has sources, or when the workflow already uses it. Choosing it applies the server's rules, as for a group. |
| Personal File Sync off | The editor says so. The active group's and public workspace's sources are still listed, and stored sources stay selected. |
| Deleted sources | While personal File Sync is on, a stored personal source missing from the list is marked **No longer available**. Stored group or public sources outside the active workspaces can't be checked from this list, so they stay selected without a mark. A save refused with `file_sync_source_unavailable` reloads the list so the deleted source is marked. |
| Save | An untouched `file_sync` is sent exactly as loaded. A changed one is sent with identity-only sources. The client mirror asks for "Select at least one File Sync source for this workflow." |

Only the File Sync lines of `WorkflowEditorDialog.tsx` changed, so the change
tracking work in #1548 merges cleanly. That work adds `file_sync` to the
authored fields of version 3 (flow) workflows; until it lands, File Sync edits
on a version 3 workflow are refused by the authoring history, as they are for
groups. New workflows and chat proposals are version 2.

### Files

| File | Change |
|---|---|
| `application/single_app/functions_workflow_file_sync_sources.py` | New: the collector and the planner projection |
| `application/single_app/route_backend_workflows.py` | The personal sources route uses the collector and returns `file_sync_enabled` |
| `application/v2_ui/src/lib/workflowEditor.ts` | The personal source fetch and File Sync save rules for both scopes |
| `application/v2_ui/src/components/workflows/WorkflowFileSyncFields.tsx` | Personal labels, lists and messages |
| `application/v2_ui/src/components/workflows/WorkflowEditorDialog.tsx` | The File Sync lines only: the trigger and section for both scopes |
| `application/v2_ui/src/components/workflows/WorkflowsSection.tsx` | The notice for personal workflows |

## Usage

Open **Workflows** in V2, create or edit a personal workflow, and either choose
**Monitor File Sync changes** as the trigger or turn on **Run File Sync before
each run**. Choose between 1 and 10 sources. See
[Create a workflow](../../guides/create-a-workflow.md#run-a-workflow-when-file-sync-finds-changes).

## Testing and validation

| Suite | Coverage |
|---|---|
| `functional_tests/test_personal_workflow_file_sync_sources.py` | The real collector with the real personal gate and role checks: each personal setting and the app role, the active group and public workspace rules, trimmed ids, a single settings read through the given reader, dropped sources, the planner projection, no Flask import, and the route's response and failure message |
| `functional_tests/test_group_workflow_file_sync_client_parity.py` | The production TypeScript against the real save routes in both scopes, including personal File Sync authoring |
| `functional_tests/test_workflow_settings_client.js` | The client mirror's personal messages |
| `ui_tests/test_v2_personal_workflow_file_sync.py` | Authoring and reopening, the active workspaces a manager may use, personal File Sync off, the read-only schedule view, keyboard use and both themes |
| `ui_tests/test_v2_group_workflow_file_sync.py`, `test_v2_workflow_settings_errors.py`, `test_v2_workflow_editor.py` | Untouched settings round-trip, Analyze on changed files, and a deleted personal source marked and removed |

### Known limitations

- The personal list offers only the **active** group's and public workspace's
  sources, as the classic editor does. A stored source from another workspace
  stays selected but can't be checked from the list.
- File Sync edits on version 3 (flow) workflows depend on #1548.

## Related

- [V2 Group Workflows](V2_GROUP_WORKFLOWS.md)
- [File Sync Source Workflow](FILE_SYNC_SOURCE_WORKFLOW.md)
- [Workflow Save After Deletion Fix](../fixes/WORKFLOW_SAVE_AFTER_DELETION_FIX.md)
