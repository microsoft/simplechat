# V2 Group Workflow Analyze Changed Files Fix

Fixed in version: **0.261.141**

## Issue

A group workflow can run File Sync before each run and pass the files that sync
changed to an Analyze task. The Analyze task then needs no selected documents.
The classic editor creates such workflows, and `save_group_workflow` accepts
them. The server allows an empty Analyze target list when
`file_sync.enabled` and `file_sync.use_changed_documents` are both set.

The V2 editor opened these workflows, but refused to save them with "needs
selected evidence for Analyze". The only way to save one was to add documents
the task didn't need.

## Root cause

`workflowValidationErrors` in `workflowEditor.ts` required selected evidence
for every Analyze task that doesn't target the current item. It didn't check
whether File Sync would supply the targets. The task editor applied the same
rule when it marked evidence as missing.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/workflowEditor.ts` | `workflowFileSyncProvidesAnalyzeTargets`, and its use in `workflowValidationErrors` |
| `application/v2_ui/src/components/workflows/WorkflowTaskFields.tsx` | Analyze doesn't report missing evidence when File Sync supplies the changed files, and explains where the targets come from |

`workflowFileSyncProvidesAnalyzeTargets` is true only for **group** workflows
whose `file_sync` is enabled with `use_changed_documents`, which is the server's
own condition. Personal workflows are unchanged.

## Validation

- `functional_tests/test_group_workflow_file_sync_client_parity.py` runs the
  production TypeScript under Node. Each payload goes through the real
  `save_group_workflow`, including Analyze with no `document_ids` and
  `use_changed_documents`. The editor allows a save if and only if the server
  accepts it.
- `ui_tests/test_v2_group_workflow_file_sync.py` saves this case in the browser
  and checks the round trip.

| Case | Before | After |
| --- | --- | --- |
| Group workflow, File Sync with changed files, Analyze without documents | V2 refuses to save | Saves |
| The same workflow without File Sync | V2 refuses to save | V2 refuses to save, as the server does |
| Personal workflow | Unchanged | Unchanged |

## Related

- [V2 Group Workflows](../features/V2_GROUP_WORKFLOWS.md)
