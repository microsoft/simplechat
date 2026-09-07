# Workflow File Sync Prompt Context Fix

**Fixed in version: 0.250.226**
**Issue:** [microsoft/simplechat#1285](https://github.com/microsoft/simplechat/issues/1285)

## Issue

File Sync's **prompt context** — the block that tells a workflow *what actually changed* — never
reached the model in any task-based workflow. Since the workflow builder always creates at least
one task, that was effectively every workflow.

The failure was silent and actively misleading: the context **was** written into the
conversation's user message, so the run transcript displayed the changed-document list as though
the model had received it. In practice the model was given only the raw task instructions and
typically replied that it had no information about any documents.

### What File Sync is supposed to do

Before a workflow runs, File Sync scans the configured sources and hands the workflow two separate
things:

1. **Prompt context** — built by `_format_workflow_file_sync_context()`: the sync counts
   (`Scanned / Created / Updated / Unchanged / Skipped / Failed`) and a numbered list of each new
   or changed document (`relative_path`, `action`, `document_id`, `source_name`). This is what
   makes instructions like *"summarize the documents that changed since the last run"* work.
2. **Document targets** — when **Use changed documents** is enabled and the document action is
   Analyze, the action is repointed at exactly the changed document ids.

Item 2 worked. Item 1 did not.

### Who was affected

- **Monitor File Sync Changes** workflows — an entire trigger type whose purpose is reacting to
  what changed — unless they happened to use Analyze with **Use changed documents**.
- Any workflow using `Search` or `No document action` got nothing at all from File Sync.
- Any workflow with **Use changed documents** disabled got nothing.

## Root Cause

`_apply_file_sync_context_to_workflow()` appended the context to the **workflow-level**
`task_prompt`. `_build_workflow_task_execution_workflow()` expected it on a **different key**, then
overwrote `task_prompt` with the task's own instructions:

```python
file_sync_context = str(workflow.get('file_sync_prompt_context') or '').strip()  # always ''
if include_document_action and file_sync_context:                                # never fired
    task_instructions = f'{task_instructions}\n\n[Workflow input context]\n{file_sync_context}'
...
prepared_workflow['task_prompt'] = task_instructions   # discarded the appended context
```

`file_sync_prompt_context` was read in exactly one place and written nowhere. The producer line was
added in `79148c84` ("Add stepped workflow builder and task sequences") alongside the consumer:

```diff
     if file_sync_context:
         prepared_workflow['task_prompt'] = f"{workflow.get('task_prompt', '')}\n\n{file_sync_context}".strip()
+        prepared_workflow['file_sync_prompt_context'] = file_sync_context
```

It was later lost in a merge resolution on a long-lived branch (the
`fix/1031-tabular-row-orchestration-scale` / PR #1145 lineage). The consumer survived; the producer
did not.

### Why no test caught it

`functional_tests/test_workflow_task_sequence.py` hand-injected `file_sync_prompt_context` directly
into the workflow dict and then asserted that `[Workflow input context]` appeared in the dispatched
prompt. It exercised the consumer with a value production never supplied, so it passed while the
feature was broken.

## Technical Details

### Files Modified

| File | Change |
|---|---|
| `application/single_app/functions_workflow_runner.py` | Restored the producer, bounded the context, gave the search query a clean source, made the first-task gate explicit |
| `application/single_app/config.py` | `VERSION` `0.250.225` → `0.250.226` |
| `functional_tests/test_workflow_file_sync_prompt_context.py` | **New** producer-to-consumer coverage |
| `functional_tests/test_workflow_task_sequence.py` | Builds the context through the real producer instead of injecting the key |

### Code Changes

**1. Restored the producer.**

```python
if file_sync_context:
    prepared_workflow['task_prompt'] = f"{workflow.get('task_prompt', '')}\n\n{file_sync_context}".strip()
    prepared_workflow['file_sync_prompt_context'] = file_sync_context
    prepared_workflow.setdefault('task_search_query', str(workflow.get('task_prompt') or '').strip())
```

**2. Gave the document search query a clean source.**

This was the blocking discovery. `_prepare_workflow_search_context()` used `workflow['task_prompt']`
**verbatim as the Azure AI Search query**, and that single `query` value fed all four search call
sites. Restoring the injection without this change would have turned a Search task's query into 50
lines of file paths and sync counters.

The prepared workflow now carries `task_search_query`, captured from the task's instructions
*before* any context blocks are appended:

```python
task_search_query = task_instructions   # captured before File Sync / previous-output injection
...
prepared_workflow['task_search_query'] = task_search_query
```

```python
query = str(workflow.get('task_search_query') or workflow.get('task_prompt') or '').strip()
```

The fallback to `task_prompt` means every caller without the key behaves exactly as before.

This also corrects a related case: after per-task workspace documents shipped in
[#1284](https://github.com/microsoft/simplechat/pull/1284), a task other than the first can carry a
Search action, and its query previously included the entire previous-task reply. Search queries are
now scoped to the task's own instructions.

**3. Made the first-task gate explicit.**

The consumer was gated on `include_document_action`, which used to mean "task 1". After #1284 that
flag means "legacy record with no task-level document action", so it no longer expressed the
intent. A dedicated parameter now carries it:

```python
def _build_workflow_task_execution_workflow(
    workflow, task, previous_reply='', include_document_action=False, include_file_sync_context=False,
):
```

```python
prepared_workflow = _build_workflow_task_execution_workflow(
    workflow, task,
    previous_reply=previous_reply,
    include_document_action=task_index == 0,
    include_file_sync_context=task_index == 0,
)
```

Later tasks receive the information indirectly, through task one's response, which is already
chained forward as bounded context.

**4. Bounded the context block.**

`WORKFLOW_FILE_SYNC_CONTEXT_MAX_CHARS = 8000` with head/tail truncation and a
`[File Sync context truncated]` marker, mirroring the existing treatment of previous-task output.
It is applied inside `_format_workflow_file_sync_context()` rather than at the injection site, so
the conversation transcript and the prompt the model receives stay identical — the mismatch between
those two is exactly what made this bug invisible.

### Testing

`functional_tests/test_workflow_file_sync_prompt_context.py` covers:

- The producer publishes `file_sync_prompt_context`, and attaches nothing when File Sync is off.
- The first task's prompt carries `[Workflow input context]` and the changed-document list; later
  tasks do not.
- The legacy no-tasks path still carries the context on `task_prompt`.
- Search queries use the task's own instructions, with no File Sync block and no previous-task
  output, for both the task path and the legacy path.
- The truncation notice appears past the cap and not below it, including a realistic 50-document
  sync with deeply nested paths.
- A run with nothing changed still tells the first task that nothing changed.
- **Use changed documents** targeting is unaffected.

Both this file and the updated `test_workflow_task_sequence.py` were verified by mutation: removing
the restored producer line makes 4 of 8 and 1 of 10 tests fail respectively, so the regression
cannot silently return.

## Validation

### Before

| Scenario | Result |
|---|---|
| File Sync workflow, `No document action`, instructions ask what changed | Model has no information about any documents |
| Conversation transcript | Shows the full changed-document list, implying the model received it |
| Search task query | The task instructions only, because the context never arrived |

### After

| Scenario | Result |
|---|---|
| File Sync workflow, `No document action`, instructions ask what changed | First task's prompt contains the sync counts and changed-document list |
| Conversation transcript | Matches what the model received |
| Search task query | The task's own instructions, free of File Sync context and previous-task output |
| Very large sync | Context bounded at 8000 characters with an explicit truncation notice |
| Nothing changed | First task is told "No new or changed synced documents were detected." |

### Regression Testing

The full `test_workflow*` suite was run against a clean `git archive` export of the base commit.
Both baseline and branch produce the same 21 pre-existing failures, and per-file output diffs
contain only traceback path differences. Route policy tests pass, and the personal and group
document picker harnesses from #1284 still pass.

## Related

- Issue: [microsoft/simplechat#1285](https://github.com/microsoft/simplechat/issues/1285)
- Preceding work: [#1284](https://github.com/microsoft/simplechat/pull/1284), which introduced
  per-task workspace documents and changed the meaning of `include_document_action`
- Feature: `docs/explanation/features/WORKFLOW_PER_TASK_WORKSPACE_DOCUMENTS.md`
- Tests: `functional_tests/test_workflow_file_sync_prompt_context.py`,
  `functional_tests/test_workflow_task_sequence.py`
