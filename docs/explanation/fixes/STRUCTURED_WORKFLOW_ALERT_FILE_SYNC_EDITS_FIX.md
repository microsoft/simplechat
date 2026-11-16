# Structured Workflow Alert And File Sync Edits Fix (v0.261.203)

## Issue

In the V2 workflow editor, changing the alert settings of a structured (version 3) workflow
failed. Picking a new **When to alert** option snapped back, and the editor showed "Workflow
edits cannot change saved identity, scope, revision, or runtime metadata." A group workflow's File
Sync settings had the same problem, because the File Sync section and the **Monitor File Sync
changes** trigger both write them.

Fixed in version: **0.261.203**, tracked in `application/single_app/config.py`. Found while
building [workflow editor change tracking](../features/WORKFLOW_EDITOR_CHANGE_TRACKING.md)
(#1548), whose Revert and Restore to here depend on the same list.

## Root cause

The editor's authoring session keeps a list of the top-level fields it authors. It uses the list
twice:

- **Checking an edit.** For a structured draft, an edit that changes any field outside the list is
  treated as a change to identity or runtime state, rolled back, and reported with the message
  above.
- **Restoring a checkpoint.** Undo, Redo and restores copy only the listed fields from the
  checkpoint, and keep every other field as it currently is.

The list had no alert fields (`alert_mode`, `alert_priority`, `alert_rules`,
`alert_evaluation`) and no `file_sync`. The alert editor and the group File Sync section both
update the draft through the session's `changeDraft`, so their edits were refused on structured
drafts. Classic drafts skip the check, so their edits applied, but restoring an earlier point, which
this release adds for every format, would have left those settings unchanged.

## Technical details

### Files modified

- `application/v2_ui/src/components/workflows/WorkflowAuthoringHistory.tsx`: the list is now the
  exported `WORKFLOW_AUTHORED_FIELDS`, with `file_sync` and `WORKFLOW_ALERT_FIELDS` from
  `lib/workflowAlerts.ts` added. Identity, scope, revision and runtime fields stay outside it and
  are still refused.

### Tests

- `functional_tests/test_workflow_authoring_session.js`, "alert and File Sync settings are
  authored fields that apply and replay": alert and File Sync edits apply, Undo restores the
  opened values (including an absent field), Redo reapplies them, no error is reported, and both
  edits are attributed to you.
- `ui_tests/test_v2_workflow_change_tracking.py`, `test_structured_alert_edits_apply_and_undo`:
  in a structured workflow, **When to alert** accepts **rules**, shows no identity error, is
  highlighted as **Edited**, and follows Undo and Redo, with nothing saved.

## Impact

- Alert settings of structured workflows, and File Sync settings of structured group workflows,
  can be edited again.
- Undo, Redo, Revert and Restore to here cover alert and File Sync settings.
- Nothing else changes. The saved payload, the server's validation, and the fields the editor
  refuses to change are the same as before.

## Validation

- Before: the edit was rolled back with "Workflow edits cannot change saved identity, scope,
  revision, or runtime metadata."
- After: the edit applies, is highlighted as a change, and follows Undo and Redo.

## Related

- [Workflow Editor Change Tracking](../features/WORKFLOW_EDITOR_CHANGE_TRACKING.md)
- [Workflow Authoring Undo And Redo](../features/WORKFLOW_AUTHORING_UNDO_REDO.md)
