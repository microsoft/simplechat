# Workflow Task Document Picker Fix

**Fixed in version: 0.250.225**
**Issue:** [microsoft/simplechat#1282](https://github.com/microsoft/simplechat/issues/1282)

## Issue

In the workflow builder (personal **and** group workspaces), on the **Tasks** step of the
Create/Edit Workflow modal, choosing a **Document action** of `Search`, `Analyze`, or
`Compare` revealed the workspace document picker but the picker never initialized:

- The **Tags** control stayed disabled showing `Loading tags...` indefinitely, even when the
  workspace had no tags at all.
- The **Document** dropdown stayed empty, even when the workspace had documents.
- No browser console errors appeared, which made the failure hard to diagnose.

Clicking **Refresh selected documents** then warned
`Select one or more <workspace|group> documents in the picker first.`, which made no sense
because the empty picker offered nothing to select.

Because the picker is the only way to choose documents, document-backed workflows could not
be created or edited through the UI at all, with no workaround.

## Root Cause

`application/single_app/static/js/workspace/workspace_workflows.js` contained a single entry
point for loading picker data, `initializeWorkflowDocumentPicker()`. It is the only caller of
`setEffectiveScopes()` and `ensureDocumentPickerReady()` from `chat/chat-documents.js`, which
in turn run `loadAllDocs()` and `loadTagsForScope()`.

Two facts combined into the bug:

1. `initializeWorkflowDocumentPicker()` was invoked from exactly one place — `openWorkflowModal()` —
   and it returned early whenever the resolved action type was `none`:

   ```js
   const actionType = normalizeText(documentAction.type || workflowDocumentActionTypeSelect?.value) || DOCUMENT_ACTION_NONE;
   if (actionType === DOCUMENT_ACTION_NONE) { ...; return; }
   ```

   For a brand-new workflow the modal opens with `documentAction = {}`, so the action type is
   always `none` and the function returned immediately.

2. The `change` handler bound to `#workflow-document-action-type` was `updateDocumentActionFields()`,
   which only toggles element visibility. It never triggered a picker load.

The result: after switching the action to `Search`, nothing ever ran. The tags button simply
kept the static markup state authored in `workspace.html` / `group_workspaces.html`
(`disabled`, spinner visible, `Loading tags...`). Nothing threw, which is why the browser
console stayed clean.

The "Refresh selected documents" warning was a downstream symptom:
`applySelectedWorkspaceDocumentsToWorkflow()` only pushed the picker's current selection into
the workflow configuration, and that selection was necessarily empty.

## Technical Details

### Files Modified

| File | Change |
|---|---|
| `application/single_app/static/js/workspace/workspace_workflows.js` | Picker load lifecycle, refresh button behavior |
| `application/single_app/static/js/chat/chat-documents.js` | Defensive resolve of the tags dropdown state |
| `application/single_app/templates/workspace.html` | Button label and card copy |
| `application/single_app/templates/group_workspaces.html` | Button label and card copy |
| `application/single_app/config.py` | `VERSION` `0.250.224` → `0.250.225` |

### Code Changes

**1. The document action and document target now load the picker.**

A new `handleWorkflowDocumentActionSelectionChanged()` handler replaces the bare
`updateDocumentActionFields` binding on both `#workflow-document-action-type` and
`#workflow-analysis-target-mode` (the picker card is hidden in `Recent documents` mode and must
load again when switching back to `Selected documents`):

```js
function handleWorkflowDocumentActionSelectionChanged() {
    updateDocumentActionFields();
    ensureWorkflowDocumentPickerLoaded().catch((error) => {
        setWorkflowPickerError(error.message || "Unable to load documents for this workflow.");
    });
}
```

**2. `ensureWorkflowDocumentPickerLoaded()` drives loads from the live form state.**

It reads the current form with `readWorkflowDocumentActionFromForm()` so the picker scope,
action type, and selection always match what the user sees, and optionally preserves the live
picker selection across a reload.

**3. Overlapping loads can no longer strand the loading state.**

`initializeWorkflowDocumentPicker()` now stamps each run with `workflowDocumentPickerLoadToken`
and only the newest run is allowed to apply results, set an error, or clear the loading flag.

**4. The tags control always reaches a resolved state.**

`loadTagsForScope()` in `chat-documents.js` previously returned early without resolving the
button when the hidden `#chat-tags-filter` select was missing. It now calls `hideTagsDropdown()`
first, so the control can never be left in its initial `Loading tags...` markup.

**5. Refresh refreshes.**

`applySelectedWorkspaceDocumentsToWorkflow()` now reloads the picker before applying a
selection, and only reports the state it actually observes:

```js
await ensureWorkflowDocumentPickerLoaded({ preserveSelection: true });

const selectedIds = getWorkflowPickerSelectedDocumentIds();
if (!selectedIds.length) {
    showToast(
        getWorkflowPickerAvailableDocumentCount()
            ? `Document list refreshed. Select one or more ${selectedLabel} documents in the picker for this task.`
            : `Document list refreshed. No ${selectedLabel} documents are available in the selected scope.`,
        "info",
    );
    return;
}
```

The button is relabeled from **Refresh selected documents** to **Refresh documents** in both
templates to match what it does.

### Testing

- `functional_tests/test_workflow_task_document_actions.py` — new; asserts the change-handler
  wiring, the load token, the tags resolve path, and the refresh contract.
- `functional_tests/test_workflow_document_picker_recent_targets.py` — updated for the
  refactored serializer/validator symbols.
- A headless `jsdom` harness drove the real modal markup for both the personal and group
  workspace templates and confirmed that switching the action to `Search` resolves the tags
  control, populates the document dropdown, and that **Refresh documents** no longer warns
  about an empty picker.

## Validation

### Before

| Step | Result |
|---|---|
| Set Document action to `Search` | Tags stuck on `Loading tags...`, document list empty |
| Click **Refresh selected documents** | `Select one or more workspace documents in the picker first.` |
| Browser console | No errors |

### After

| Step | Result |
|---|---|
| Set Document action to `Search` | Documents load; tags resolve to the available tags or `No tags available for this scope` |
| Set Document target back to `Selected documents` | Picker reloads |
| Click **Refresh documents** | Document list reloads and the current selection is preserved |
| Empty workspace | `Document list refreshed. No workspace documents are available in the selected scope.` |

## Related

- Feature: `docs/explanation/features/WORKFLOW_PER_TASK_WORKSPACE_DOCUMENTS.md`
- Tests: `functional_tests/test_workflow_task_document_actions.py`
- Issue: [microsoft/simplechat#1282](https://github.com/microsoft/simplechat/issues/1282)
