# Repeat until with saved typed state

Implemented in version: **0.261.120**.

Application version tracking: `application\single_app\config.py`.

## Overview and dependencies

Repeat until runs a serial body at least once, saves its next state, and then
evaluates a typed stopping condition. Use it for a bounded refinement process,
such as improving a report while retaining its latest draft and a separate
structured review decision. A model saying "finished" is not an engine command.

This M4C-3 capability extends definition-version-3
[structured workflows](WORKFLOW_STRUCTURED_CONTROL_FLOW.md), the existing
[durable runner](WORKFLOW_DURABLE_EXECUTION.md), schema-2 journal, exact result
readers, and personal/group permissions. It requires durable execution and
locally metered models or local agents. Ordinary hosted non-loop workflows
remain supported. There is no second scheduler, result store, publication
ledger, database container, or browser runtime dependency.

## Administrator policy and authored limits

| Control | Value and meaning |
| --- | --- |
| **Workflow Repeat Iteration Limit** | `workflow_max_repeat_iterations`; administrator default **25**, supported range **1-1,000** |
| **Maximum rounds before manual continuation** | Required explicit `max_iterations` on each Repeat block; includes the first body iteration |
| Technical batch ceiling | **1,000** iterations per automatic batch, not a lifetime limit of 1,000 |
| Run execution admissions | Existing authored/admitted budget, at most **5,000**, shared with tasks, retries, and nested control work |
| Run elapsed deadline | Existing authored/admitted deadline, at most **86,400 seconds**, including human and output waits |

The administrator default is not an authored default. A missing block maximum
is invalid; the editor starts that field unset. A new run whose authored
maximum exceeds the current administrator ceiling is rejected, not clamped or
silently shortened. No unadmitted snapshot is written for that rejected
submission. Lowering the ceiling does not rewrite saved definitions.

An admitted run freezes its Repeat policy and batch size. Administrator changes
affect new runs only, including when an existing run later receives a manual
continuation. A grant of another batch does not promise that the remaining
global budgets can accommodate the whole batch.

Editor `flow_limits.max_repeat_iterations` shows the current administrator
ceiling. Runtime `limits.max_repeat_iterations` is the frozen admitted ceiling;
`gate.repeat.batch_size` is the particular block's frozen authored maximum.
The administrator ceiling is not a replacement for that authored batch size.

The separate **Workflow Loop Item Limit** remains default **500**, range
**1-5,000**, for actual selected For each items. Searching many documents is
not itself a Repeat iteration or a For each visit. Neither setting is a model
context limit or cumulative run-token/spending cap.

Configure the policy in [Workflow settings](../../admin/workflow.md).

## Definition contract

Keep `definition_version: 3` and `durable_execution: true`. The `tasks` array
remains the task catalogue; `flow` is the executable structure.

| Repeat field | Contract |
| --- | --- |
| `id` | Unique stable engine-node ID |
| `kind` | Exactly `repeat_until` |
| `max_iterations` | Required positive integer, at most 1,000 per automatic batch |
| `state` | One to 100 uniquely named typed state declarations |
| `body` | Region with `id`, `nodes`, and explicit `outputs` |
| `until` | Existing bounded data-only predicate, selecting validated next-state slots by name |
| `exports` | Explicit final names selecting declared body-output names; an explicit empty list is allowed |

Every state declaration has `name`, `initial`, `next`, and `output_contract`.
For example, this declaration carries a schema-validated review decision:

```json
{
  "name": "review",
  "initial": {
    "kind": "node_output",
    "node_id": "seed_review",
    "output": "json",
    "scope": "current"
  },
  "next": "next_review",
  "output_contract": {
    "kind": "json",
    "schema": {
      "type": "object",
      "required": ["ready"],
      "properties": {"ready": {"type": "boolean"}}
    },
    "allow_partial": false
  }
}
```

Here `seed_review` must be a visible eligible earlier producer, and
`next_review` must be an explicitly declared body output. This is a declaration
excerpt, not a complete workflow.

### Initial and current state

State kinds must be explicit: `text`, `json`, `records`, or `document_results`,
not `any`. Initialize each slot from an exact saved output visible at the
Repeat entry, or from explicitly named enclosing Repeat state. Starting
literals, arbitrary document IDs, result-store locators, foreign-run
references, and "latest result" selectors are not supported.

A body task selects the state admitted for its exact round:

```json
{
  "name": "review",
  "source": {
    "kind": "repeat_state",
    "loop_id": "refine_report",
    "state_name": "review",
    "scope": "current"
  },
  "required": true,
  "expected_kind": "json",
  "allow_partial": false
}
```

The admitted state is read-only throughout that body. A nested Repeat can read
named enclosing state but cannot mutate it. The outer state changes only at
the outer transition.

Each slot needs its own explicit next-body-output selection. To retain a slot
unchanged, export its current-state receipt from the body rather than asking a
model to echo the value. There is no implicit merge, append, transcript
accumulation, deduplication, truncation, or conversion into downloaded files.

A For each inside the body can select a saved collection through a required,
non-partial `repeat_state` input. Its frozen source must retain and authorize
the exact admitted state receipt, not apply an earlier-node ancestry shortcut.
Explicit **Saved-record report** collection bindings can also select current
Repeat state; the report keeps the original collection stored and follows the
existing processing and partial-data rules. Neither path permits direct
`repeat_state` publication.

### Transition and condition

After all required body work completes, the engine resolves every next-state
output, checks its exact producer and slot contract, and evaluates Until
against that **next** state. JSON decision fields need an explicit supported
schema. The existing typed comparison, ordered short-circuit, missing/null,
and `exists` rules apply.

An example condition for the declaration above is:

```json
{
  "op": "eq",
  "left": {"input": "review", "path": "/ready"},
  "right": {"literal": true}
}
```

Even if the initial state already meets that condition, the body runs once.
A true condition on the last permitted round succeeds. A false condition at
the batch maximum pauses without completing the Repeat boundary or releasing
its final exports.

Body outputs do not leak across the boundary as "the last task." A downstream
task binds a named Repeat export through `node_output`, for example an export
declared as `{"name": "review", "output": "next_review"}`. Use explicit joins
when different branches provide a required next value.

Schema validity does not prove factual correctness. An over-budget condition
read or model input is an explicit retained-data blocker, not permission to
evaluate a prefix, summarize automatically, or silently switch sources.

## Durable state and mixed execution paths

Large values remain at their original result references. Private state
snapshots retain exact slot receipts, validation, coverage, and predecessor
transitions; they are not a growing transcript in the runtime control row.
Earlier saved state versions and original outputs remain retained.

A Repeat frame is exactly:

```json
{"loop_id": "refine_report", "iteration": 26}
```

`iteration` is the zero-based **lifetime** index for this exact Repeat
invocation. The example is displayed as round 27. It does not reset after a
manual continuation. Existing For each frames remain
`{loop_id, item_id, index}` without a new discriminator or changed hashes.

Mixed nesting retains the existing limits of four regions including the root
and at most three enclosing loop frames. A new round gets a distinct execution
identity; a retry retains that identity and advances its attempt. A new batch
does not rewrite prior executions.

A For each nested inside Repeat freezes membership per exact inner-loop
execution. Resume reuses that saved selection. A genuinely new outer round
creates a new inner execution and may perform the authored selection afresh,
without changing any earlier frozen collection.

One Repeat-entry admission and one admission per round are charged alongside
existing body tasks, retries, and nested control work. Replaying a committed
transition or writing result pages does not charge the round again.

Transitions and continuation decisions use the existing conditional journal
transaction, lease, cancellation, and tombstone fences. A prepared but
uncommitted state is not eligible output. Recovered workers reuse committed
body units and transitions; uncertain external effects still require the
existing recovery gate.

## Partial data, authorization, and lifecycle

Partial input is rejected by default. Acceptance requires eligible producer
output, explicit state-slot acceptance, and the relevant body or downstream
binding acceptance. Retain coverage and limitations through subsequent state
and final exports; meeting Until does not relabel partial work as complete.

Failed, invalid, pending, missing-required, or unauthorized results cannot be
made eligible by a partial flag or a manual grant. Current personal/group,
initiator, source-revision, and contributor access is rechecked at the existing
read, continuation, model/tool, and external-effect boundaries.

The exact path must prove every frozen For each membership and admitted Repeat
round with its before-state receipt. A syntactically valid frame, current head,
or cached digest is not historical authorization. State and selected-producer
lineage use bounded, cycle-detecting traversal rather than starting an
unbounded recursive walk for each preceding round.

Cancellation or deletion fences later state, transition, result, continuation,
and publication writes. It does not undo an email, upload, or other completed
external action. Native Analyze retains both workflow and work-unit fences.

Cancellation targets the run's frozen Repeat identities even if the live
workflow definition has since changed. Editing a definition cannot redirect
cancellation to a newer body or strand an older body's approval pause.

## Manual continuation

At an unmet batch limit, the run uses `paused` with a pause gate whose
`reason_code` is `repeat_iteration_limit`. Its choices are
`continue_repeat` and `cancel`; ordinary Resume is not another batch grant.

An authorized decision uses the existing `runtime/decision` endpoint with the
current `expected_version`, `gate_id`, `choice`, and stable `request_id`. The
client cannot submit a new maximum, state value, source, or execution identity.
The gate binds the exact exhausted transition and saved next state.

The read-only gate retains `id`, `unit_id`, `input_digest`, `execution_id`,
`node_id`, `iteration_path`, `attempt`, `definition_revision`, `reason`, and
the safe `repeat` summary alongside its kind/reason code/choices. The path is
the Repeat boundary's enclosing path, and the boundary attempt is 1. These are
server-owned selectors, not additional client decision fields. The V2 request
uses a UUID for `request_id`.

**Continue Repeat for up to another N rounds** grants the same frozen batch
size. It resets only current-batch usage and advances the batch number/start;
lifetime numbering, saved state, cumulative admissions, and elapsed deadline
remain intact. A stale gate cannot grant another batch, and repeated
acknowledgment of the same request does not increment counters again.

Continuation independently rechecks authority, saved contributors, lifecycle,
remaining admissions, and deadline. It does not approve body tasks, authorize
a publication destination, waive invalid output, or clear a different pause.
Global-budget blocker gates offer cancellation only, not another batch.
Schedulers, polling, retries, tool/model text, and readiness checks cannot
issue a manual grant.

## V2 usage and inspection

1. In a personal or group V2 List workflow, enable structured control flow and
   add **Repeat until** after the producers that initialize state.
2. Explicitly choose **Maximum rounds before manual continuation**, considering
   the administrator ceiling and separate global budgets.
3. Add named typed state, select its saved initial output, and declare body
   outputs for every next-state slot. Body tasks use **Current Repeat state**
   rather than a latest-task lookup.
4. Configure **Stop after a round when** using typed next-state fields. Select
   final exports explicitly, and bind later consumers to those exports.
5. Inspect the exact round, batch, attempts, state before/after, condition
   outcome, and remaining budgets. At exhaustion, review retained state before
   explicitly confirming another same-sized batch.

Unsupported definitions and unadvertised capabilities remain intact and
read-only. Invalid moves/removals retain bindings and explain the error rather
than silently selecting another producer. Classic does not gain a reduced
Repeat editor.

Repeat authoring requires advertised `repeat_until` and `repeat_state` support,
a valid current administrator ceiling, and `hard_repeat_iterations: 1000`.
Missing capability metadata does not enable authoring; malformed advertised
limits produce an explicit editor-options error.

A saved maximum within 1-1,000 that exceeds a lowered administrator ceiling
remains visible and editable. The editor reports a new-run policy conflict
without clamping the saved value; choose an allowed maximum before saving.
This is not an unsupported definition and does not change an active run's
frozen batch size.

When a Repeat body task inherits the workflow runner, that runner's picker
also enforces local-loop eligibility. Tasks outside the body retain their
own ordinary runner choices.

Inspection pages are bounded and source-authorized. An uncommitted after-state
is unavailable, not an eligible empty result. Content uses the existing exact
result, record, and provenance readers rather than exposing private locators.
Open a round's body execution to inspect its exact attempts. If that execution
is another loop, **Inspect nested Repeat rounds** or **Inspect nested For each
items** opens that specific loop instance, not all executions of its authored
node.
See [Trigger a workflow](../../guides/trigger-a-workflow.md) for operator steps.

### Read and decision APIs

Personal inspection uses these scoped resources:

```text
GET /api/user/workflows/<workflow_id>/runs/<run_id>/executions/<repeat_execution_id>/iterations
GET /api/user/workflows/<workflow_id>/runs/<run_id>/executions/<repeat_execution_id>/iterations/<iteration>/state
POST /api/user/workflows/<workflow_id>/runs/<run_id>/runtime/decision
```

Group paths replace `user` with `group` and retain the existing explicit
`group_id` query parameter and authorization policy. State inspection selects
`phase=before` or `phase=after`, defaulting to `before`. Pages use opaque
cursors and `limit`, default 50 and supported range 1-100. A separate
response-size bound of about 240 KiB prevents metadata pages from growing
with the full state content.

| Response or entry | Fields |
| --- | --- |
| Iterations page | `iterations`, `total_count`, `next_cursor`, `repeat_execution_id`, `repeat`, `source_snapshot_changed` |
| Iteration entry | `iteration`, `iteration_path`, `batch_number`, `batch_size`, `batch_usage`, `state`, `condition_result`, `execution_ids`, `before_available`, `after_available`, `partial` |
| State page | `states`, `iteration`, `phase`, `available`, `total_count`, `next_cursor`, `repeat_execution_id`; optional `partial` and `source_snapshot_changed` |
| State entry | `name`, `kind`, `workflow_validation`, `coverage`, `limitations`, optional `prior_coverage`, and `source` |
| State source selector | `node_id`, `execution_id`, optional `task_id`, `iteration_path`, `attempt`, `output_name` |

Round `state` is `running`, `completed`, `completed_partial`, or `cancelled`.
`condition_result` is a Boolean or null. A completed round whose condition is
false is still completed; the Repeat head/gate, not that round status alone,
identifies batch exhaustion.

A cursor binds the owning scope/run, exact Repeat execution, immutable
snapshot, page boundary, and iteration/phase where applicable. Every request
rechecks access; neither a cursor nor a result digest is an access grant.
Content selectors are resolved by the server through the existing exact
result, record, and provenance readers. The decision endpoint does not accept
caller-authored state or a replacement batch maximum.

The safe Repeat summary appears as `gate.repeat`, `runtime.repeat_progress`,
and the iteration page's `repeat`. It exposes bounded metadata, not state values:

| Purpose | Fields |
| --- | --- |
| Exact boundary | `execution_id`, `node_id` |
| Lifetime progress | `completed_iteration`, `next_iteration`, `completed_count` |
| Current automatic batch | `batch_number` (zero-based), `batch_size`, `batch_usage` |
| Durable counters | `exhaustion_count`, `continuation_count` |
| Outcome | `state`, `partial` |

The summary's head `state` is `running`, `waiting_manual_continue`,
`completed`, or `cancelled`. `completed_iteration` is -1 before any round has
completed; actual iteration selectors remain zero-based lifetime indexes.

Iteration entries include `condition_result`, `before_available`, and
`after_available`. State entries carry exact saved-source selectors with
`workflow_validation`, `coverage`, and a required `limitations` string array.
Availability flags and selectors do not replace the source authorization check
or make uncommitted state eligible.

An uncommitted after-state reports `available: false`, `states: []`,
`total_count: 0`, and `next_cursor: null`, not an eligible empty value. State
entries may also include `prior_coverage` to retain initial partial coverage
counts after a later output passes validation. This is flat, safe metadata with
primitive values, displayed separately as retained earlier coverage. The V2
reader rejects private or nested prior metadata instead of rendering it. A
later valid result does not erase those earlier limitations or relabel the
carried state complete.

Metadata contains no state values, private `state_ref`, or provider locator.
Read content through the existing exact result, record, and provenance readers
using the returned source selectors.

## Preserve shared saved-record publication

Only a satisfied Repeat boundary can supply its final eligible `records`
export, directly or through an explicit join, to the existing required
`node_output` records binding for **Saved workflow output** publication.
Repeat state/control metadata and a flattened `document_results` bundle are
not records producers.

The M4C-2 [saved-output contract](WORKFLOW_SAVED_OUTPUT_PUBLICATION.md) remains
unchanged: `GeneratedFileExportRequest`, `GeneratedRecordExportSource`,
`GeneratedFileExportStream`, and `build_generated_file_export` use
`exact_records_v1` JSON. Every original object, order, duplicate, nested value,
Unicode value, false, zero, null, and eligible empty collection is retained.

The representation identity binds the frozen definition, actual selected
producer execution/path/attempt, exact output references, partial policy,
profile, and format. A genuinely new producer round is not a retry of an old
source. Retrying a publisher does not select newer data merely because its
display position or publishing attempt changed.

Actual encoded-byte digests, immutable prepare/ready units, stable addresses,
quota enforcement, and private artifact transport remain in use. Never
overwrite different bytes at the same address or expose a quota-breach prefix.
The existing publication service and sole destination ledger own submission,
approval, notifications, and recovery.

Submitted, Approved, and Indexed-and-ready retain their separate completion
rules, immutable fulfilled observations, and readiness proof. A downloadable
JSON file is not destination completion. Repeat adds neither a publish-only
loophole nor a download-only task, and does not expand shared export formats.

## Monitoring included now and deferred follow-up

Committed exhaustion and manual-continuation decisions retain authoritative
counts, actor/time, gate/request correlation, batch size/number, and lifetime
progress. Replays, polls, and duplicate acknowledgments must not increase
those durable counts.

`runtime.repeat_counts` holds `exhaustion_count` and `continuation_count`,
aggregated across all Repeat boundaries in the run. `runtime.repeat_progress`
retains the bounded safe progress summary rather than state values or private
result references.

Structured events `workflow_repeat_batch_exhausted` and
`workflow_repeat_manually_continued` use the existing `log_event` path and
`[WORKFLOW_SCHEDULER]` tag with stable committed-decision event IDs. They
exclude state values, prompts, records, credentials, and private locators.
Telemetry delivery is not
transactionally exactly-once with Cosmos; deduplicate by event ID rather than
treating a logging failure as reversal of a committed grant.

**Not implemented in M4C-3:** the approved future Control Center follow-up
includes personal-workflow monitoring in the personal-user context,
group-workflow monitoring in the group context, and a dedicated **Workflow
Monitoring** section. It must separately decide roles/visibility, cross-run
queries, aggregation, retention, filters, and any alerts/actions. Logs and IDs
do not grant monitoring access. Reuse the existing execution/decision records;
do not create a competing ledger.

M5A read-only Flow comes next in the milestone sequence, followed separately
by M5B accessible visual authoring. Neither is included here, and no graph
library evaluation or installation is part of Repeat. Parallel loops, general
cycles/reducers, hosted-agent loops, and cumulative token/spending caps remain
out of scope.

## Implementation and validation

`functions_workflow_editor.py` advertises `repeat_until`, `repeat_state`, and
`flow_limits.max_repeat_iterations`/`hard_repeat_iterations` without returning
raw settings. `functions_workflow_limits.py` supplies the shared constants and
strict validator. `admin_settings_fields.py`, `functions_settings.py`,
`route_frontend_admin_settings.py`, and the existing Workflow pane keep
Classic/V2 numeric bounds, absent-value preservation, and persistence aligned.

The compiler, identity, structured runner, journal, runtime decisions, and
source-authorized readers remain the implementation boundaries described in
the linked workflow features; Repeat does not replace those services.

`functions_workflow_repeat_execution.py` supplies the serial body transitions,
`functions_workflow_repeat_state.py` binds saved state to sealed admissions,
and `functions_workflow_repeat_history.py` serves the bounded inspection
pages. The existing Flow runner and runtime decision transaction call these
helpers. The existing journal's `journal_commit_many` and `journal_decide`
provide the conditional multi-row transition and human-decision boundaries.
V2's `WorkflowRepeatFields.tsx` and `WorkflowRepeatProgress.tsx` integrate
authoring and progress into the existing List and runtime controls.

`functional_tests/test_workflow_repeat_editor_options.py` covers defaults,
actual 1/1,000 bounds, invalid-value rejection, current scoped editor policies,
safe projection, and Classic validation. `test_workflow_loop_limits.py`
additionally exercises the production settings writer with isolated storage,
and `test_v2_admin_workflow_parity.py` checks both surfaces' fields and bounds.

`ui_tests/test_workflow_loop_admin_limits.py` exercises Classic and V2 admin
controls with closed browser fixtures and the production schema, template,
and normalizer. It covers independent limits, help/ARIA, native validity,
mobile/keyboard use, V2 narrow updates and reload, valid 1,000 saves, retained
invalid drafts without changing saved policy, and unrelated V2 updates that
preserve an absent Repeat key.

`test_workflow_repeat_schema.py` and `test_workflow_repeat_limits.py` cover
typed bindings, mixed ancestry, legacy execution hashes, and independent
limits. The Repeat execution, state, recovery, publication, and route-policy
suites exercise the existing engine, readers, journal, and publication
boundaries. `test_workflow_repeat_dispatcher.py` runs the production dispatcher,
including the committed-task-unit/result-checkpoint crash gap on both result
stores, with no extra execution admissions or repeated provider invocation.
It also verifies cancellation after a live definition edit against the
original admitted Repeat and round.
`ui_tests/test_v2_workflow_repeat_until.py` covers the local V2 surfaces.

### Verified closed-fixture runtime coverage

Runtime coverage exercises actual 1,000-round exhaustion and an explicit grant
into lifetime round 1,001, with the same absolute deadline and no replay
admissions or duplicate body work. Cold history/state reads reauthorize the
saved lineage. Other cases cover frozen policy, typed/pass-through state,
collections larger than 8 MiB, retained partials, three mixed frames, approvals,
lost acknowledgments, lease/cancellation fences, cached-proof source
revocation, cursor scope/phase binding, sanitized logs, and policy preflight.

Native Analyze and exact final-record publication use the existing production
adapters with both Cosmos and Blob fixtures and both nesting directions.
Crashes after destination submission/ledger commitment reuse the same artifact
and destination on restart, without duplicate submissions or changed native
publication fingerprints.

The focused runtime selections verified for this slice are reproducible from
the repository root with an isolated test interpreter and repository-pinned
dependencies, including Flask/Werkzeug:

```powershell
python -m pytest -q .\functional_tests\test_workflow_repeat_execution.py .\functional_tests\test_workflow_repeat_recovery.py .\functional_tests\test_workflow_repeat_state.py .\functional_tests\test_workflow_repeat_publication.py .\functional_tests\route_tests\test_workflow_repeat_policy.py -k 'not real_thousand'
python -m pytest -q .\functional_tests\test_workflow_repeat_execution.py -k real_thousand
```

The first selection passed **64 tests**, with the threshold case deselected.
The separate threshold selection passed **1 test** in approximately **402
seconds**. That duration is local test evidence, not a production performance
guarantee.

**These are fictional, closed fixtures, not live Azure, Cosmos, Blob, model,
or publication-service validation.** They exercise the production runner,
journal, result-store, native Analyze, exporter, and destination-ledger
functions without live-service operations. Settings/options checks alone do
not establish runtime behavior. No live workflow, external publication,
deployment, or permission change was performed as part of this validation.
