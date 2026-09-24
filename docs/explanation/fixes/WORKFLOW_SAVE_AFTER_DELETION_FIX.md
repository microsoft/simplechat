# Workflow Save After Deletion Fix (v0.261.149)

## Issue

Two things deleted while the V2 workflow editor was open made the next save go
wrong.

1. **A File Sync source deleted after the editor loaded.** Saving a workflow
   that still selected the source failed:
   - a **group** workflow got a 404, "The workflow or one of its sources is not
     available." The V2 editor treats a 404 as lost access. It cleared the
     cached authoring details and told the user to close the editor, so the
     draft was lost;
   - a **personal** workflow got a 500, "Unable to save workflow right now.",
     logged as a server error.

   A deleted owning group has the same effect when a personal workflow uses
   that group's sources.
2. **The workflow itself deleted after the editor opened it.** Saving silently
   **recreated** the workflow under the same ID, with the editor's copy. A
   delete that landed during the save was refused with "This workflow was
   deleted. Your draft was not saved.", with advice to reload, which can't
   help.

Fixed in version: **0.261.149**, tracked in `application/single_app/config.py`.

## Root cause

- The personal and group `_normalize_file_sync_config` resolve each selected
  source through `get_authorized_sync_source`, which raises `LookupError` when
  the source or its group is gone. The group save route maps `LookupError` to
  404. The personal save route has no such branch, so it fell through to its
  generic 500.
- `get_personal_workflow` and `get_group_workflow` return `None` for a missing
  record. The save then created a new record, because
  `save_workflow_definition_record` creates whenever nothing is stored. The
  revision check only runs when a record exists, so an editor that opened the
  workflow at a known revision could still recreate it.

## Technical details

### Files modified

- `functions_workflow_definitions.py`:
  - `WorkflowSourceUnavailableError`, a reviewed settings error with code
    `file_sync_source_unavailable`;
  - `WorkflowDeletedConflict`, a definition conflict with code
    `workflow_deleted`.
- `functions_personal_workflows.py` and `functions_group_workflows.py`: a
  `LookupError` from `get_authorized_sync_source` becomes
  `WorkflowSourceUnavailableError`. A `PermissionError` still gives 403, and
  any other `LookupError` keeps its old mapping: 404 on the group route, 500 on
  the personal one.
- `functions_workflow_definition_store.py`:
  - `refuse_save_of_deleted_workflow` runs right after each save's lookup.
    When the payload names an `id` and carries the `definition_revision` it was
    opened at, and nothing is stored for that ID, it confirms the record is gone
    and refuses with `WorkflowDeletedConflict`. It writes nothing.
  - A delete that lands during the conditional replace raises the same
    conflict.
- `route_backend_workflows.py`: both save routes return each error's own
  `code`.
- `WorkflowEditorDialog.tsx` and `workflowEditor.ts`:
  - on `file_sync_source_unavailable`, a group editor reloads its source list,
    so the deleted source is marked **No longer available**. The draft is kept;
  - on `workflow_deleted`, the editor shows the server's message and "Your
    draft has been retained. Copy anything you need, then close this editor.",
    with no reload advice.

### Responses

| Situation | Before | After |
|---|---|---|
| Group save, selected source deleted | 404, and the V2 draft was lost | 400 `file_sync_source_unavailable`: "A selected File Sync source is no longer available. Remove it and save again." The draft is kept and the source marked |
| Personal save, selected source deleted | 500 | The same 400. The draft is kept |
| Save after the workflow was deleted | The workflow was recreated | 409 `workflow_deleted`: "This workflow was deleted after it was opened, so your changes were not saved." Nothing written |
| Workflow deleted during the save | 409, "This workflow was deleted. Your draft was not saved." | The same 409 `workflow_deleted` |
| Caller lost access to a source | 403 | 403, unchanged |
| Group gone when the route resolves it | 404 | 404, unchanged |

### Tests

- `functional_tests/test_workflow_settings_reviewed_messages.py` (93 cases),
  through both save routes:
  - a deleted source is a 400 with nothing written, and a stored record is left
    unchanged;
  - a deleted owning workspace gets the same 400;
  - a source the caller may not use stays 403 on both routes, a deleted group
    stays 404, and other lookup errors keep their mapping;
  - saving a deleted workflow is a 409 that creates nothing. The refusal comes
    before any other save rule, and a delete during the save gets the same 409;
  - a transient read failure is never reported as a deletion, and a lookup that
    fails only once keeps the existing conflict;
  - creates, and updates at the current revision, are unchanged;
  - the known limitation below, a save without a revision, is pinned.
- `ui_tests/test_v2_workflow_settings_errors.py`:
  - a group source deleted after opening keeps the draft and marks the source;
  - a personal one keeps the draft;
  - saving a workflow deleted after opening keeps the draft and explains what to
    do, in both scopes.

## Known limitations

- **Personal File Sync sources can't be removed in V2 yet.** V2 has no personal
  File Sync section, so a personal workflow whose stored source was deleted
  keeps getting the 400. The draft is kept and the message shown. A version 1
  workflow can be fixed in the classic editor.
- **Saves without a revision still recreate a deleted workflow.** The classic
  editor for version 1 workflows sends no `definition_revision`, so its saves
  behave as before. This is pinned, so changing it later is a deliberate
  decision.

## Validation

- Before: a deleted source lost a group draft, or failed a personal save with a
  server error, and a stale editor could bring a deleted workflow back.
- After: both are refused with a specific message, the draft is kept, and
  nothing is written.

## Related

- [Workflow Settings Reviewed Messages Fix](WORKFLOW_SETTINGS_REVIEWED_MESSAGES_FIX.md)
- [V2 Group Workflows](../features/V2_GROUP_WORKFLOWS.md)
