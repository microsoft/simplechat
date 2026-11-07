# Workflow deletion and partial-cleanup recovery

Fixed in version: **0.261.305**

Application version tracking: `application/single_app/config.py`.

## Issue and evidence

Personal workflow DELETE requests returned HTTP 500 with
`WorkflowResultIntegrityError: Unexpected object in the private result prefix.`
The failing operation was the private result Blob cleanup, not workflow ownership
validation. An earlier deletion had already marked the workflow as `deleting`
and tombstoned its runtime control. Later Cancel requests therefore encountered
`WorkflowRuntimeConflict("not_found")`. Reading run history could also raise
`AnalysisWorkUnitConflictError("analysis_work_deleted")`.

The affected storage account has hierarchical namespace (HNS) enabled. Flat
Blob listings on these accounts can include directory entries as well as files.
The cleanup previously accepted only result-file paths, rejecting legitimate
directories before cleanup could complete.

A bounded, read-only inspection of both affected workflow prefixes confirmed
the directory entries. The email prefix contained four marked directories and
three result files; the Analyze prefix contained four marked directories and
24 result files. Entries inside the run cleanup scope had `hdi_isfolder=true`
and size zero in both the listing and a fresh properties read. Those entries
fail the previous result-file-only path validation. No result payloads were read
and no storage objects were changed during the inspection.

## Root cause and related run failure

Result cleanup checks hashed paths and stored identity metadata to avoid deleting
unrelated data. HNS directory objects do not have result-file suffixes or
result-specific metadata. Treating them as files caused cleanup to fail while
retaining the workflow and its history for retry.

Separately, the failed Analyze workflow emitted aggregate `completion_tokens`
while development telemetry was enabled. That metric was missing from the
telemetry allowlist, causing `Mixed-source telemetry contains non-allowlisted
fields`. Coverage telemetry also emitted the missing aggregate
`xml_schema_source_count`. Both fields are now allowlisted; arbitrary telemetry
fields remain rejected.

The email workflow's telemetry showed a Microsoft 365 wait and notification,
not continuous worker execution. A workflow can remain active while waiting
for sign-in or approval. The precise persisted wait state was not inspected,
and this fix does not force waiting workflows into an idle state.

## Code changes and safety boundaries

`application/single_app/functions_workflow_result_store.py` recognizes directory
entries only when an explicit `hdi_isfolder` metadata flag or `resource_type`
identifies a directory. A trailing slash alone is not sufficient.

Accepted directories must be zero bytes with a known size and use the exact
hash-path depth permitted by the workflow-run, chat, or orchestration cleanup
scope. Result files retain their existing path, identity, and metadata checks.
Files are deleted first; directories are then re-read and removed deepest-first
using their current ETag and a non-recursive conditional delete. Changed types,
changed ETags, unexpected objects, and storage failures still fail cleanup.
Already missing objects are safe to retry. Scope-root and ancestor directories
remain outside the prefix sweep.

`application/single_app/route_backend_workflows.py` now returns a stable JSON
500 for recognized cleanup/storage failures and logs the failure server-side.
It does not report deletion success when cleanup fails. All four personal/group
Cancel endpoints return JSON 409 for cancellation/runtime conflicts. Deleting
workflows receive guidance to retry Delete; a missing runtime receives a neutral
message because missing state does not always prove deletion.

`application/single_app/functions_saved_analysis.py` withholds unverifiable
previews when their saved analysis is deletion-fenced, preserving the existing
history redaction behavior rather than returning an unhandled exception.

`application/single_app/functions_mixed_source_orchestration.py` includes the two
aggregate telemetry metrics. `application/single_app/config.py` records
**0.261.305**. No new settings, routes, or deployment configuration are introduced.

## Recovery after deployment

Deploy **0.261.305** or later before retrying deletion on an affected site.
Retry **Delete** for a partially deleted workflow rather than **Cancel**.
Existing runtime tombstones continue to prevent late workers from publishing,
while cleanup can finish and remove the workflow's run history and definition.

If deletion still fails, an administrator should inspect the workflow-delete
event under `[WORKFLOW_ROUTES]` and the corresponding storage exception. Do not
bypass integrity checks, recursively delete broad prefixes, or delete original
source documents or independently published reports.

This change has not been deployed as part of the investigation. No live workflow,
conversation, or Blob was manually deleted.

## Testing and validation

Regression coverage:

- `functional_tests/test_workflow_result_store.py`: HNS files-before-directories
  ordering, personal/group/chat/orchestration path depths, case-insensitive
  metadata, trailing-slash entries, explicit directory identity, missing size,
  type replacement, ETag races, concurrent children, missing directories,
  idempotent retry, and existing result isolation checks.
- `functional_tests/test_workflow_delete_recovery_routes.py`: safe JSON errors,
  retry after partial deletion, 404 behavior, all four cancellation endpoints,
  successful scoped cancellation, and group management access before storage.
- `functional_tests/test_saved_analysis_service.py`: deletion-fenced result
  previews are withheld without leaking saved output.
- `functional_tests/test_workflow_cancellation.py` and
  `functional_tests/test_mixed_source_hardening.py`: runtime conflict translation
  and the exact aggregate token/coverage telemetry metric sets.
- `functional_tests/test_v2_workflow_run_action_clients.mjs`: existing V2
  cancellation and resume contracts remain compatible.

The focused result-store, recovery-route, saved-analysis, group-fixture,
run-history, and repeat-policy selection passed **211 tests and 112 subtests**.
The cancellation
log-injection/cold-import checks, V2 action tests, and all three required route
policy scripts also pass.

The complete mixed-source-hardening/cancellation run still has ten failures
previously reproduced on the baseline: stale AST harness dependencies, missing
Azure configuration, and older evidence/runner expectations. The focused
telemetry and route-helper selection passes. These baseline failures are not
reported as passing and are outside this fix.

Local route checks used isolated, repository-pinned Flask/Werkzeug packages
and a compatible OpenSSL dependency; no shared Python installation was changed.

## Before and after

Before, a legitimate HNS directory could interrupt deletion and leave Cancel
and Runs returning unhandled errors. After, validated empty directories are
cleaned after their files, partial cleanup remains retryable, cancellation
conflicts return JSON, and fenced saved previews are withheld.

See [Durable workflow execution](../features/WORKFLOW_DURABLE_EXECUTION.md)
and [Trigger a workflow](../../guides/trigger-a-workflow.md) for run states and
recovery guidance.
