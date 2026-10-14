# Goal-first workflow authoring fix — v0.261.335

## Issue and root cause

**Fixed/Implemented in version: 0.261.335**, tracked in
`application/single_app/config.py`.

A request to summarize newly added documents every Tuesday could change only
metadata, leaving task instructions and the recurrence unset. The assistant's
prompt exemplified metadata-only edits, prohibited incomplete calendar edits,
and blocked initial instructions when execution details were missing.
The operation bound was already 64, not three.

Read-only console evidence for October 14, 2026, 11:49:21–24 UTC showed a changed
reply with three operations, one model call, no correction and a normal stop.
It was not token-truncated. That supports the contract diagnosis, but does not
prove correlation to the exact screenshot prompt, which was not logged. This
change does not alter telemetry configuration or claim private model reasoning.

## Changes and impact

Ask AI authors known instructions, action and document criteria while asking only
for missing details. An explicit draft-calendar contract retains Tuesday with
blank time; strict saved/runtime schedules still reject blanks. No default time,
enablement, save or run is introduced.

The visible task Documents section separates action and source, supports
searchable Add/Remove workspace discovery and distinguishes upload time from
metadata modification time. Optional runtime choice captures authorized inputs,
retains one validated decision per visit, rechecks it on resume and fails safely
when details or retained state are unavailable.
Choice/refusal summaries and separate selection usage are retained in legacy
task results and structured execution/attempt history, including failed tasks.

Core changes are in `functions_workflow_assist.py`,
`functions_workflow_assist_operations.py`, `functions_workflow_schedules.py`,
`functions_workflow_document_selection.py`, `functions_workflow_action_choice.py`
and `functions_workflow_runner.py`; the shared V2 task, selection and history
components expose those contracts. See [the feature contract](../features/WORKFLOW_DOCUMENT_SELECTION.md)
and [the workflow guide](../../guides/create-a-workflow.md).

Base integration preserves the Ask AI action-handoff continuity changes from
v0.261.334. This follow-up uses v0.261.335 rather than overwriting the newer
base version.

## Validation

Functional regressions exercise the exact request/time follow-up, strict schedule
rejection, 3/10/16/64 operations, upload-time edges, every runtime action, invalid
decisions, scope boundaries, cancellation, retained refusals and replay integrity.
The production-bundle browser suite covers visible controls, incomplete schedule
feedback and 223 authorized workspaces at desktop/mobile sizes.

Bounded synthetic Azure model evaluation exercised complete Tuesday authoring
and follow-up, a 15-task request, authoring Search/Compare/Merge, runtime
Analyze/Search/Compare/Merge, missing/ambiguous refusals and metadata injection.
Initial runtime evaluation exposed unused fields in model responses; discriminated
action schemas and explicit output examples fixed it without accepting extra
fields. Existing authoring budgets remain unchanged. Synthetic evaluation is
evidence for these cases, not a guarantee of every future model response.

The frontend type-check/production build and all 13 documentation checks passed.
The required Cosmos response-boundary/SDK gate,
`python .\scripts\check_cosmos_response_boundaries.py --run-contracts`, exited 0:
1,051 owners, 395 doubles and zero review gaps; all 718 selected contract tests
and 231 subtests passed with network access blocked. The workflow module
fingerprints were explicitly re-reviewed. Fourteen source-only owner entries
were replaced with owner-runtime evidence in
`functional_tests/test_workflow_authoring_sdk_boundaries.py`, including SDK point
responses, plain query rows, partition checks, query failures, private-item
filtering and conditional-write cancellation. No checker or compatibility
exemption was relaxed.

Focused backend runs passed 114 goal/task/structured checks, 139
authoring/action/File Sync checks, and 285 result/selection/privacy/route checks
with 112 subtests. Frozen-replay checks passed 168 cases across isolated runs.
The final document-input/history browser suite passed all 19 cases after
correcting an empty-field assertion in the test fixture. The remaining 159
editor/calendar/loop/Changes/Ask AI browser cases passed in the compatibility
run. All 12 synthetic model scenarios
passed in 14 calls, with a largest response of 638 output tokens.

After integrating the v0.261.334 base, the shared Ask AI handoff regression,
production frontend build, 90 goal/selection-route/documentation checks and
52 document-selection/Ask AI browser cases passed. A concurrent SDK run hit
the existing 180-second deadline in three cold-import probes; all three passed
unchanged in isolated retries. The sequential full SDK gate then exited 0 with
all 718 tests and 231 subtests passing and zero inventory review gaps. No
timeout, assertion or compatibility baseline was relaxed.

The broader legacy matrix is not entirely green. Four old source/version
assertions and a task-sequence golden are stale on the current base; executing
the same capture against current `HEAD` produced identical results. Existing
nonstandard logging tags also fail the logging inventory check, with no tag-set
change in this patch. One frozen-replay queue-route check is blocked by the
already-recognized offline bootstrap `route_backend_agents.enabled_required`
`NameError`; the remaining 31 route cases pass. These unrelated baseline
failures were not rewritten or hidden.
