# Orchestration Execution Failures Fix (v0.261.141)

**Fixed in version: 0.261.141**

The application version is tracked in `application/single_app/config.py`.

## Issue

Three orchestration requests, retested on a deployed V2 environment running
0.261.140, each produced a correct plan and then failed while executing it:

- **Compare a PDF with a CSV.** The run never completed. Recovery later reported
  that it could not confirm a saved result, or that the run was still running,
  instead of the actual reason.
- **Create a CSV of US states and their capitals.** The content-preparation step
  failed within a second of a successful model call, so no file was produced.
- **Turn an illustrated report into a Word file.** The Word file was created and
  could be downloaded, but the run took about 23 minutes, ended as **Failed** with
  its answer not delivered, and reopening the conversation offered the plan's
  **Approve** controls again. The file card also showed internal attempt counters
  and failure codes.

Diagnosing all three required reconstructing events from dependency telemetry,
because the failure logs recorded only exception class names.

## Root cause

### Compare a PDF with a CSV

The plan authorized the current revision of the CSV. The tabular step located the
file by its storage path, and `_resolve_blob_document` in
`content_screening/access.py` returned the first document row whose paths
included that location. Every row was also treated as stored at the implied
legacy path `{scope}/{file_name}`, so an older, archived revision with the same
file name matched the current revision's location.

The older revision's provenance was stamped onto the export, while the native
source kept the authorized document ID. The evidence gate then saw two different
document identities, rejected the source as malformed, and raised a strict
`SourceAuthorityUnverifiedError`. Strict authority failures are deliberately
fenced: the run is left for recovery rather than marked failed, which is why
recovery reported an unconfirmed result instead of a clear failure.

The same wrong-row selection could evaluate the current file's bytes under the
older revision's screening state. A clean or unenrolled older revision could
therefore stand in for a current revision that screening had held.

### Create a CSV of US states and capitals

The planner correctly declared a table output (`records-v1`, columns `State` and
`Capital`) to be rendered as CSV. Deliverable guidance for the preparing step
nonetheless told the model to "write its complete content as the finished file",
which asks for CSV text. The compose policy never described the row-object shape,
JSON mode was off, and a contract violation failed the step with no second
chance. The model returned CSV text where a JSON array of row objects was
required, and validation rejected it as `result_records_invalid`.

### Turn an illustrated report into a Word file

1. **Re-authorization on every write.** Each render `check()` performed a full
   authorization: an output-record read, a render-output authorization, and a
   complete source lineage walk with current-source checks, repeated by a
   `recheck()` and, in Office renders, a third source recheck. Checks ran on
   every 64 KB buffer write, every ZIP entry and every DOCX node. A 5.47 MB DOCX
   with three roughly 1.8 MB images made about 947 checks at around 1.4 seconds
   each, which accounts for the 22 to 23 minutes and a large Cosmos DB read load.
2. **A finished step was overwritten.** After a step returned, the executor
   probed the stop conditions once more. The render had passed the 180-second
   step limit, so `step_timeout` replaced the COMPLETED result with a failure even
   though the file was already stored and published.
3. **The limit was not enforced during rendering.** `execute_render_file`
   checked the stop probe once before starting; `render_attempt` never consulted
   it, so the limit only took effect after the work had finished.
4. **The live stream went idle.** The execution stream sent nothing while the
   render was busy, so an idle connection could be closed before the run
   finished.
5. **A stale plan status was trusted on reload.** The server records
   `plan.status = "running"` when execution is claimed and does not write the
   terminal status back onto the saved plan or the run's `plan_summary`. On
   reload, the V2 interface rebuilt the plan card from that saved plan, so a run
   that had failed or been cancelled could present approval controls again.
6. **The file card showed bookkeeping.** Attempt numbers, automatic-attempt
   limits, raw failure codes, raw counts and an explanatory paragraph were
   printed on every card, next to a duplicated download section.

## Technical details

### Files modified

| Area | Files |
| --- | --- |
| Source resolution and authority reasons | `application/single_app/content_screening/access.py`, `application/single_app/functions_mixed_source_orchestration.py`, `application/single_app/functions_native_tabular_compute.py`, `application/single_app/functions_orchestration_native_results.py` |
| Content preparation | `application/single_app/functions_orchestration_deliverables.py`, `application/single_app/functions_orchestration_composition.py`, `application/single_app/functions_orchestration_execution.py`, `application/single_app/model_endpoint_clients.py` |
| Rendering, step budgets and streaming | `application/single_app/functions_orchestration_rendering.py`, `application/single_app/functions_orchestration_executor.py`, `application/single_app/functions_orchestration_output_store.py`, `application/single_app/functions_orchestration_schema.py`, `application/single_app/route_backend_orchestration.py` |
| Diagnostics | `application/single_app/functions_appinsights.py` |
| V2 interface | `application/v2_ui/src/lib/orchestration.ts`, `application/v2_ui/src/lib/orchestrationController.ts`, `application/v2_ui/src/lib/orchestrationResume.ts`, `application/v2_ui/src/lib/orchestrationOutputs.ts`, `application/v2_ui/src/components/chat/OrchestrationPlanCard.tsx`, `application/v2_ui/src/components/chat/OrchestrationPlanPanel.tsx`, `application/v2_ui/src/components/chat/OrchestrationOutputs.tsx`, `application/v2_ui/src/components/chat/GeneratedArtifactCard.tsx` |
| Version | `application/single_app/config.py` |

### Source resolution (compare)

- `_blob_location_owner` resolves a storage location in tiers. An exact
  `blob_path` or screening `active_blob.path` match wins, then an exact
  `archived_blob_path`, then the implied `{scope}/{file_name}` only for legacy
  rows that never stored a path. Legacy rows sharing one location prefer the
  explicitly current revision, then any not marked archived, then the newest by
  version, upload date and timestamp. An exact tie is denied with
  `DocumentHeldError` instead of guessed.
- This closes the wrong-revision screening evaluation described above: the
  current bytes are only ever judged by the row that owns their location.
- Native tabular compute raises `native_compute_source_identity_mismatch` when
  the resolved provenance does not match the authorized document. The native
  bridge maps it to `native_access_unavailable` and a clean, non-retryable
  `context_unavailable` step failure instead of an escaped authority error.
- Every malformed-authority rejection now carries a reason code such as
  `provenance_mismatch` or `manifest_revision_invalid`, logged as
  `authority_reason`.

### Content preparation (CSV)

- Deliverable guidance is kind-aware. A table output is told that the file will
  be written from its rows and that it must not write CSV or table text.
- The compose policy states each declared output's exact JSON shape. Table
  outputs name their keys and value types and include a one-row example.
- JSON outputs request `response_format={"type": "json_object"}`.
  `is_response_format_rejection` recognizes an endpoint that refuses the option,
  and the call is resent once without it.
- A reply that breaks a rule stated by the declarations, such as a missing
  output or a non-array table value, receives exactly one corrective call naming
  that rule. Plan, profile, size and access failures are never retried, and
  neither reply is logged.

### Rendering, budgets and streaming (Word)

- `_RenderAttempt` paces the render's checks. A full check (claim, parent run,
  capability admission and source access) runs at attempt start, before the
  intent is prepared, at least every `RENDER_FULL_CHECK_INTERVAL_SECONDS` (5
  seconds, and never less often than a quarter of the lease), at lease half-life
  and at the deadline. The calls in between do no I/O. `_PacedSource` applies the
  same cadence to the renderer's source rechecks. Intent preparation, staging
  writes and commit keep their own fenced checks.
- The step's stop probe is consulted on full checks until the file is staged. A
  stop that the claim check does not explain ends the attempt with the
  non-retryable `output_step_time_limit`, which the step reports as
  `step_timeout`. Staged bytes are always committed.
- The executor keeps a COMPLETED, PARTIAL or WAITING result when a time budget
  is first noticed only after the step returned, and logs the overrun instead.
  A cancellation still discards the result.
- The `step_timeout` message names **Admin Settings > Orchestration > Chat
  Orchestration > Limits**. Failed and cancelled files show
  "This file was stopped because its step reached the time limit." or
  "This file was stopped because the run reached its time limit." where those
  codes apply.
- The execution stream sends an SSE comment (`: keep-alive`) after 15 idle
  seconds. Event parsers skip comment frames.

### Diagnostics

- The diagnostic allowlist keeps `step_id_hash` and the codes `failure_code`,
  `authority_reason`, `capability_id` and `output_format`.
- New events record each file render attempt with phase timings and check
  counts, a step that overran its budget after finishing, the compose correction
  and JSON-format fallback, and native bridge failures with run, conversation
  and step hashes. See
  [Orchestration failure diagnostics](../../reference/logging-tags.md#orchestration-failure-diagnostics).

### V2 interface

- `isOrchestrationRunSettled` and `persistedRunPlan` overlay a waiting or
  settled run status onto the saved plan wherever a run is rehydrated: recovery
  loading, run reconciliation, resume and archived-run loading.
  `OrchestrationPlanCard` also refuses approval controls for a settled run.
- The file card shows the file name, type, status, and, once completed, its row
  count and size. Failed, cancelled and unavailable files show the server's
  explanation, and a scheduled retry shows its time. `GeneratedArtifactCard`
  gained an `embedded` mode that draws only the download controls and any
  approval notice, so the file card no longer repeats the file header and
  preview.

## Testing

New functional tests:

- `functional_tests/test_orchestration_step_budget_outcome.py`: a finished step
  keeps its result after a late budget stop, while cancellation still discards
  it.
- `functional_tests/test_orchestration_render_check_cadence.py`: full checks are
  bounded by the interval, commit remains fully checked, revocation is detected
  within the interval, and the step limit stops a render before staging.
- `functional_tests/test_orchestration_compose_output_retry.py`: shape guidance,
  JSON mode and its fallback, the single corrective call, and no retry for
  non-correctable failures.

Updated functional tests: `test_content_screening_access.py` (tiered resolution,
same-name revisions, ties denied, archived paths), `test_native_tabular_compute_service.py`,
`test_orchestration_native_results.py`, `test_orchestration_source_access.py`,
`test_orchestration_deliverables.py`, `test_orchestration_render_waiting_runtime.py`,
`test_orchestration_harness_routes.py` (keep-alive frames) and
`test_orchestration_failure_telemetry.py` (allowlist).

Updated UI tests: `ui_tests/test_v2_orchestration_outputs.py` covers the
simplified card, and `ui_tests/test_v2_orchestration_recovery.py` reloads failed
and cancelled runs whose saved plan still says `running` and asserts that no
approval control or run request appears.

## Validation

- The orchestration, content-screening, native tabular, mixed-source, route
  policy, model-endpoint, V2 tabular parity, logging-tag and docs test files
  (195 files) were each run in their own process.
- These failures are identical test for test on the 0.261.140 base commit and
  unrelated to this change:
  - content-screening history and review fixtures, and mixed-source fixtures;
  - model-endpoint tests that stop on `get_effective_model_profiles`;
  - `test_v2_tabular_parity.py::test_the_confirmation_precedes_the_send`;
  - `test_orchestration_plan_revision_routes.py::PlanRevisionRouteTests::test_document_removal_is_not_lost_when_editor_opens`;
  - `test_logging_tag_standardization.py`, for tags outside orchestration;
  - `test_docs_json_gem_security_fix.py`, which expects an older `json` gem pin
    than `docs/Gemfile.lock` now has;
  - `route_tests/test_workflow_execution_journal_policy.py`,
    `test_workflow_loop_policy.py` and `test_workflow_repeat_policy.py`, which
    cannot create a Flask test client in the local environment because
    Flask 2.2.5 reads `werkzeug.__version__`, which Werkzeug 3.1.4 removed.
- `test_orchestration_harness_execution.py` failed two tests once while 195
  files ran four at a time. All 649 tests passed in six later runs: alone, as
  four concurrent copies, and alongside the files it first ran with.
- The new and updated backend test files also pass together in one pytest
  session (555 tests), including after the shared dependency-runtime fixture,
  which leaves modules imported under test stubs cached.
- Every V2 orchestration UI test file passes when run individually. One
  elicitation composer test failed once during a looped run and passed on rerun.
- Temporarily reverting the settled-run guard made the new recovery and output
  reload tests fail, confirming that they detect the stale approval card.

### Before and after

| Scenario | Before | After |
| --- | --- | --- |
| Compare a PDF with a CSV | An older same-name revision could own the CSV's location; the run stalled on a strict authority failure. | The current revision owns its location; an identity mismatch fails the step cleanly with a logged reason. |
| CSV of states and capitals | The model was asked for CSV text where rows were required; one bad reply failed the step. | The model is told the row shape, JSON mode is requested, and one corrective call is allowed. |
| Illustrated Word report | About 947 full checks; a finished file was reported as failed; reload offered approval again. | Full checks run at most every five seconds plus boundaries; a finished file keeps its result; reload shows the outcome. |

## Follow-ups

- Recovery still reports a fenced strict authority failure as unconfirmed
  rather than naming the reason. The cause fixed here no longer triggers it, but
  the recovery message could use the logged `authority_reason`.
- Azure SDK HTTP logging produces a very high volume of traces, including the
  telemetry exporter's own calls, which makes investigations slower and more
  expensive.
- A source-authority failure can be logged by more than one layer.
- An illustrated Word render downloads each image twice, once while preparing and
  once while rendering.
- `finalize_m365_json_request` raises on pass-through static responses.
