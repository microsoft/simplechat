# Workflow Ask AI authoring fix — v0.261.329

## Issue and root cause

**Fixed in version: 0.261.329**, tracked by
`application/single_app/config.py`.

Two observed personal-workflow requests returned HTTP 200 and successful
model dependencies, but produced no edits. The new-workflow goal was classified
as an explanation; the contextual naming follow-up was classified as a
question. Conversation history was present. This was an authoring-contract
failure, not a transport error or missing history.

The original guidance emphasized editing existing fields without sufficiently
describing creation from a goal. Recent-document runtime selection also had no
model/editor contract for rolling windows and metadata filters. Debug console
logging worked, but generic telemetry string reduction hid useful categories.
Historical logs did not contain model bodies or private reasoning.

## Changes

The prompt now receives explicit new-draft/blank-task context, generates
metadata from the conversational goal, reuses the initial task, and distinguishes
clear edits from missing execution details. A changed response may carry a
separate clarification. A no-op edit preserves that question.

Closed operation schemas remain authoritative. The implementation uses
`set_task_name` for naming, authorized workspace handles for selection, and
targeted window/filter operations for follow-ups. No keyword-based creation or
filter-intent router was added. Regex is an explicit document-metadata operator,
not an intent heuristic.

The server prevents operations from filling a detail that the same response
asks the user to specify. Complete-authoring declarations must pass a real save
projection without placeholder task instructions. The assistant still cannot
save, enable, or run a workflow.

Logging uses normalized `[WORKFLOW_ASSIST]` and
`[WORKFLOW_DOCUMENT_SELECTION]` tags with application-owned code fields,
numeric counts, durations, and hashed correlation. Token usage is logged as
`input_count`, `output_count`, and `total_count`, avoiding credential-oriented
token-key redaction. Prompts, replies, document content, filenames, filter
literals, and raw user/submission IDs are not emitted by these diagnostics.

Key files are `functions_workflow_assist.py`,
`functions_workflow_assist_operations.py`, `functions_workflow_assist_runtime.py`,
`route_backend_workflows.py`, and the V2 assist parser/hook.
The accompanying selector implementation is described in
[per-task rolling document selection](../features/WORKFLOW_DOCUMENT_SELECTION.md).

## Validation

Scripted regression coverage includes contextual naming plus task naming,
changed-plus-question responses, no-op clarification, full-authoring
instruction requirements, unauthorized handles, invalid paths, and preservation
of unaffected conditions/tasks. Existing assistant candidate, dry-run, request,
rate-limit, and browser parity suites remain the regression surfaces.

Bounded synthetic GPT-4o evaluations exercised the original goal, contextual
naming, a fully specified Tuesday/Thursday workflow with the exact
PDF/CSV AND (filename OR tag) filter, and a window/regex follow-up that preserved
the other conditions. No production workflows or documents were read or
written by those evaluations.

The expected difference is an editable draft and focused missing-detail
questions, rather than editor instructions or a request for the user to invent
metadata. These source changes require deployment before production behavior
changes.
