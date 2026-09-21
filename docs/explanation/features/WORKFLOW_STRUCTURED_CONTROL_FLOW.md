# Structured workflow control flow

Implemented in version: **0.261.116**

Updated in version: **0.261.123**.

Application version tracking: `application/single_app/config.py`.

## Purpose and scope

Structured workflows choose a path from validated data instead of relying on a
model to describe what should happen next. Milestone 4A adds **If/else**, task
**Run when**, explicit branch joins, and restricted forward routing to the
personal and group V2 List editor.

This is useful when an assessment should produce either an explanation or a
review, when an optional task should run only for particular findings, or when
a known later step can safely replace optional intermediate work.

This page describes the M4A foundation. Version **0.261.117** adds
[serial For each and exact Collect](WORKFLOW_FOR_EACH_COLLECT.md) to the same
definition version and journal. Version **0.261.119** adds
[saved-record JSON publication](WORKFLOW_SAVED_OUTPUT_PUBLICATION.md).
Version **0.261.120** adds [Repeat until](WORKFLOW_REPEAT_UNTIL.md), with saved
typed state and explicit manual grants after finite automatic batches.
Version **0.261.121** adds [M5A read-only Flow inspection](WORKFLOW_FLOW_INSPECTION.md)
over the same compiler and runtime. Version **0.261.122** adds M5B accessible
List/Flow authoring of the same supported draft, without changing saved or
frozen-run inspection into an editor. Version **0.261.123** adds shared
unsaved authoring Undo/Redo. M4A itself did not admit loops.

## Dependencies and compatibility

Structured control flow uses the existing workflow runner, durable execution
lease, private result store, source-authorized readers, native Analyze adapter,
and artifact publication service. There is no second scheduler or Cosmos
container. Flow inspection and authoring reuse locally bundled React Flow;
they do not introduce a stored executable graph or change the runtime model.

Definition version **3** is an explicit opt-in and requires durable execution.
Existing version-1 and version-2 definitions keep their previous behavior.
Opening or editing an ordered workflow does not automatically convert it.
Classic can still run and cancel durable workflows; advanced editing requires
V2, and Classic refuses to open an advanced definition in its reduced editor.

## Author a structured workflow

1. Open `/v2/workspace/workflows`, or select the owning group under `/v2/groups`.
2. Create a workflow or open an existing draft. Choose **Enable structured
   control flow**, then **Convert draft**. Nothing is persisted until **Save
   workflow**.
3. On the decision-producing task, choose a JSON output contract. Under
   **Structured decision fields**, add a Boolean such as `pass`, a number, or
   an enum. The task's instructions should request those fields in its final
   JSON object.
4. Add **If/else** after that producer. Bind its saved JSON output under a
   named input, then choose the field, comparison, and typed value.
5. Add tasks inside **Then** and **Else**. Under **Join outputs**, name the
   result that later tasks need and select the exact producer/output for each
   path.
6. Bind later tasks to the named join output. Declare any promised deliverable
   under **Final outputs** so the run cannot complete without it.

For example, an evaluation can return `{"pass": true, "add_note": false}`.
An If/else condition reads `decision.pass`, selects an explanation or review,
and exports the selected text as `report`. A later task consumes that report,
not the last message that happened to be written.

Conversion makes legacy automatic inputs explicit. A continue-on-error
workflow with automatic previous-successful inputs must choose explicit inputs
before conversion: selecting one fixed predecessor would otherwise change its
failure behavior. Shared references and the first task's legacy document action
are retained explicitly.

### Choose List or Flow authoring

In **0.261.122**, **List authoring** is the default, including on narrow
screens. **Flow authoring** offers the same task, If/else, Forward route,
For each, Repeat until, Collect, and typed-binding forms over one version-3
draft. Select a block to configure it; use explicit add/move/remove controls
and choose its destination region and sibling position. Dragging a box changes
temporary layout only, not executable order or containment. Opening Flow
neither converts a workflow nor generates replacement IDs.

Current supported boxes remain editable as **Unvalidated draft** while
configuration is incomplete. Executable arrows require a server compiler
preview matched to the current draft generation; authored relationships are
not proof of an executable path. Unknown executable shapes stay read-only
without losing their original fields.

Surface and selection changes preserve unfinished schema text, field errors,
typed bindings, and the original saved revision. A reference-breaking move or
removal confirms concrete affected selectors, then retains those references
until the author repairs them; it never silently cascades or retargets.
Save remains explicit and blocked by unresolved errors. Version **0.261.123**
adds shared Undo/Redo for common fields, structured edits and unfinished
buffers across List and Flow. Text controls retain native undo, and replay
that removes blocks or affects references requires confirmation.

See the published [Create a workflow guide](https://microsoft.github.io/simplechat/guides/create-a-workflow/)
for the editing procedure. `WORKFLOW_FLOW_AUTHORING.md` records the M5B
architecture; `WORKFLOW_AUTHORING_UNDO_REDO.md` explains M5C history,
retention and session boundaries.

### Skip an optional task

Enable **Run when** on the task and select a condition using its named inputs.
A false condition records an intentional skip before approval, Analyze
preparation, or model/tool invocation. A skipped task produces no result.

If a later task consumes that output, mark the binding optional or supply a
required branch-join output instead. Required bindings cannot silently consume
a different reply. Removing or moving a producer retains existing bindings and
shows dependency errors rather than retargeting them.

### Route forward

Add **Forward route**, bind its condition inputs, and choose a later sibling
under **Route when true**. Within a branch, the route can instead exit that
branch to its join. False continues to the next node.

Backward routes, entry into another branch, unmatched region crossings, and
bypasses that remove a required input are rejected. Routing is not a substitute
for a loop, and a model cannot supply a destination ID.

## Definition contract

The version-3 `tasks` array is a catalogue of existing authorized task
configurations. `flow` is the only executable ordering and nesting structure.
Each task configuration appears in exactly one logical task node. Derived
indexes are not a second stored graph.

| Structure | Authored fields |
| --- | --- |
| Root region | `id`, ordered `nodes`, and final `outputs` bindings |
| Branch region | `id` and ordered `nodes` |
| Task node | `id`, `kind: "task"`, `task_id`, optional `run_when` |
| If/else node | `id`, `kind: "if"`, `inputs`, `condition`, `then`, `else`, `join` |
| Join | Stable `id` and named `exports`, each selecting a Then and Else producer/output |
| Forward route | `id`, `kind: "route"`, `inputs`, `condition`, `target` |
| Route target | A later sibling `node_id`, or the current branch's `exit_region_id` |
| Repeat until node (0.261.120) | `id`, `kind: "repeat_until"`, required `max_iterations`, typed `state`, `body`, post-body `until`, and explicit final `exports` |

A version-3 binding is explicit:

```json
{
  "name": "decision",
  "source": {
    "kind": "node_output",
    "node_id": "evaluate",
    "output": "json",
    "scope": "current"
  },
  "required": true,
  "expected_kind": "json",
  "allow_partial": false
}
```

Missing inputs normalize to an empty list; `null` is not a version-3 automatic
input mode. Version-1 and version-2 omitted/null predecessor behavior remains
unchanged. Definitions cannot supply result-store references or choose another
run's execution.

Inside Repeat, an explicit `repeat_state` source names an enclosing `loop_id`,
`state_name`, and `scope: "current"`. It selects the saved state admitted for
that exact round, not another iteration's latest task output. Until reads
validated next-state slots, and downstream consumers use the Repeat node's
named final exports only after the condition succeeds. See
[Repeat's state contract](WORKFLOW_REPEAT_UNTIL.md#definition-contract).

The server validates versions, executable fields, node kinds, unique IDs,
region depth, routing, and producer availability. Advanced saves retain the
existing definition-revision and active-run protections.

## Condition semantics

The bounded language supports `exists`, `eq`, `ne`, `lt`, `lte`, `gt`, `gte`,
`all`, `any`, and `not`. Operands select a named input field using a JSON
pointer or declare a finite scalar literal. Normal authoring uses controls,
not an expression or JSON editor.

Equality does not coerce strings, numbers, or booleans. Numeric ordering
requires numbers. Missing is different from null: `exists` is true for a
present null value. An unguarded missing field is an error; use an existence
guard when absence is allowed. `all` and `any` evaluate in authored order and
short-circuit.

Authorization and output eligibility precede predicate evaluation. Revoked
source access, invalid results, and pending producers cannot become optional
absence. Partial data needs explicit acceptance and retains its limitations.
Human approval cannot make invalid or unfinished output eligible.

Output schema validity is not factual correctness. Analyze producer validation
and workflow output requirements remain separate. Ordinary model prose such
as "PASS" or "complete" is never an engine command.

## Durable execution and results

A saved branch/skip/routing decision includes its input digest and exact
consumption references before the next task begins. Resume reauthorizes saved
inputs and follows that decision. Changed sources cannot silently change the
selected path.

New structured results use `workflow-result-v2`. Their identity contains the
workflow, run, logical node, server-derived `execution_id`, `iteration_path`,
and attempt. Real task results also retain `task_id`; engine results do not
invent task IDs. M4A iteration paths are empty.

For each adds unchanged `{loop_id, item_id, index}` frames. Repeat adds the
distinct `{loop_id, iteration}` shape in **0.261.120**, with a zero-based
lifetime round index that survives manual continuation. Mixed paths must prove
their ordered ancestry and exact frozen/admitted membership. Engine-boundary
results retain their actual selected-producer receipts.

Retries retain the execution ID and advance the attempt. Approval and recovery
decisions bind the exact execution, attempt, gate, definition, and input
digest. Receipts retain the actual producer and representation. Branch-control
provenance remains part of the access boundary.

The versioned runtime control row keeps bounded state, while execution,
attempt, and decision records are paged in the existing run partition.
Writes use the existing lease and conditional-write fence. Native Analyze
also retains its producer/work-unit fence. Private rows are not ordinary
history items, and deletion preserves lifecycle tombstones.

## Limits and inspection

| Limit | Structured policy |
| --- | --- |
| Authored tasks | Existing administrator setting: default 50, supported range 1-100 |
| Structural IDs | At most 256 |
| Nested flow depth | At most 4 |
| Predicate size | At most 100 nodes, depth 8, and 16 KiB |
| Execution admissions | Default/maximum 5,000; includes retries, not result-chunk writes |
| Elapsed deadline | Default/maximum 86,400 seconds, including waits |
| Repeat automatic batch (0.261.120) | Required authored maximum; administrator default 25, range 1-1,000; new runs above policy are rejected, not clamped |
| Model input | Existing effective catalog/deployment budget; complete required input is never clipped |

At an unmet Repeat batch maximum, an authorized manual decision can grant the
same frozen batch again. Only batch usage resets; lifetime round identity,
execution admissions, and elapsed deadline do not. Ordinary Resume cannot make
this grant or clear the global limits.

Run history distinguishes selected paths, intentionally skipped nodes, output
validation, attempts, and exact consumed-result receipts. Large execution and
decision histories are paginated. Full result content is requested separately;
a byte-range excerpt is a display transport, not a complete-record iterator.

Completion checks selected-path obligations and required final outputs, not
whether every authored branch ran. Accepted partial work remains
`completed_partial`. Exhausted limits and missing required results do not
become Completed.

### Read-only Flow inspection

M5A in **0.261.121** introduced separate Flow sources for saved definitions,
compiler-checked List draft previews, and selected runs' verified frozen
definitions. M5B in **0.261.122** replaces only the editor's preview-only
entry with List/Flow authoring. Saved and run viewers remain read-only.
Run evidence is never overlaid on a newer saved definition or an unsaved draft.
Exact node-and-mixed-path lookup uses the frozen revision rather than guessing
the latest task with a matching name.

The layout follows normalized region order, preserves explicit joins and
boundary IDs, and represents each loop body once. Selected-page typed bindings
are distinct from control connections. Shared inspectors retain exact attempts,
frozen items, Repeat state, complete records, and publication observations.

Layout is temporary viewing state, excluded from executable definitions and
revision hashes. Viewing, expanding, moving a box, and refreshing cannot
approve, resume, continue, publish, or restart a run. See
[the inspection contract](WORKFLOW_FLOW_INSPECTION.md) for APIs, bounds, source
isolation, accessibility, and offline coverage.

## Publication boundary

Existing publication tasks use the existing artifact publication service and
destination ledger. In a structured workflow, publication selects its exact
upstream producer explicitly instead of searching whichever task happened to
finish most recently. Source and destination permissions are checked again.

An acknowledgment retry reuses the publication identity. It must not create a
second document or duplicate approval notifications. Existing `queued`,
`pending_approval`, `approved`, `approval_failed`, and `uncertain` states retain
their meanings; none is a new promise that indexing has completed.

Version **0.261.118** adds an optional
[publication completion policy](WORKFLOW_PUBLICATION_COMPLETION.md) for existing
native Analyze artifacts: Submitted, Approved, or Indexed and ready. Unmet
policies retain the existing receipt and wait or pause rather than creating
another copy. Omitted policies retain the previous behavior.

In **0.261.119**, explicitly choosing **Saved workflow output**
(`publication.source_kind: "saved_output"`) renders one required `node_output`
records binding from a real task, Collect, or explicit join as exact JSON
through the shared Generated File Export Framework. The Publish task creates
the downloadable file and submits it to the chosen destination using the same
completion policies. It is not a download-only task or a native Analyze
artifact. Omitting the source choice preserves existing native publication.

In **0.261.120**, a satisfied Repeat boundary can expose a final records export
to the same required records binding. The selected body producer remains real,
with its exact path/attempt and retained partial coverage. An exhausted batch
has no eligible final export, and Repeat does not add a different renderer,
file format, or destination ledger.

Saved-record serialization rechecks current scope and the exact source attempt
every 100 records. Reusing a materialized file still verifies its exact ready
checkpoint. Generic destination approval rechecks current source and destination
authority after the conditional decision write and before its external effect.

Generic CSV, Markdown, Word/DOCX, PDF, PowerPoint/PPTX and XML mappings remain
future extensions of the **same framework**, not separate workflow exporters.
Existing native formats are unchanged. See the
[shared format roadmap](GENERATED_FILE_EXPORT_FRAMEWORK.md#shared-format-roadmap)
and [saved-output contract](WORKFLOW_SAVED_OUTPUT_PUBLICATION.md) for exact
record preservation, partial acceptance and source eligibility.

## Regression coverage and boundaries

The existing isolated workflow definition, runtime, result, Analyze, and
publication suites provide the backend regression boundaries. Browser coverage
uses the real locally built V2 SPA and closed API fixtures, including production
definition validation.

`ui_tests/test_v2_workflow_control_flow.py` covers normal control authoring,
joins, skipped dependencies, retained conflict drafts, unsupported definitions,
explicit conversion, group scope, and keyboard/mobile editing.
`ui_tests/test_workflow_classic_advanced_guard.py` exercises the actual Classic
edit guard without loading runners or changing drafts.

`functional_tests/test_workflow_structured_flow.py` covers persisted path
decisions, exact identities, selected joins, skip/routing behavior, more than
1,000 paged journal records, cancellation/deletion fences, and complete
consumption lineage beyond 256 ancestors.
`functional_tests/test_workflow_structured_edges.py` covers real save
round-trips, limits, missing/null predicates, frozen shared references, gate
source checks, invalid-output inspection, and complete paged per-document
outputs retaining their `document_results` type in legacy and structured reads.
`functional_tests/test_workflow_structured_publication.py` passes genuine native
Analyze records through a saved join and the existing publication service,
including restart without duplicate publication and later source revocation.

M5B coverage objectives add shared-command and compiler parity in
`functional_tests/test_workflow_flow_authoring_commands.js` and
`functional_tests/test_workflow_flow_authoring.py`, plus real-bundle
List/Flow, buffer, focus, save, and request-isolation scenarios in
`ui_tests/test_v2_workflow_flow_authoring.py`. These objectives are not a
claim of fresh passing results.

Local regression fixtures do not deploy the application, run private production
workflows, or publish documents. Live acceptance requires a separately
authorized deployment matching the integrated code.

## API and implementation

Existing save, run, cancellation, and gate-decision endpoints remain in use.
Editor options advertise supported definition versions and node kinds. Saves
retain `definition_revision` concurrency protection; runtime `version` remains
the mutable gate-decision revision, separate from runtime `schema_version`.

Structured run inspection adds these authorized read paths:

```text
GET /api/user/workflows/<workflow_id>/runs/<run_id>/executions
GET /api/user/workflows/<workflow_id>/runs/<run_id>/executions/<execution_id>/attempts
GET /api/user/workflows/<workflow_id>/runs/<run_id>/executions/<execution_id>/attempts/<attempt>/result
GET /api/user/workflows/<workflow_id>/runs/<run_id>/runtime/decisions
```

Group paths replace `user` with `group` and use the existing explicit `group_id`
query parameter. History pages accept `cursor` and a bounded `limit`; they
return the named collection and `next_cursor`. Result pages retain byte offsets,
digests, and complete/partial transport indicators. No endpoint accepts a
caller-provided result-store locator.

`functions_workflow_flow.py` validates the canonical structure and typed
predicates. `functions_workflow_flow_runner.py` traverses it around the existing
task dispatcher. `functions_workflow_identity.py`, `functions_workflow_journal.py`,
and `functions_workflow_structured_execution.py` provide exact identities and
fenced checkpoints. `functions_workflow_node_results.py` and
`functions_workflow_execution_history.py` share source-authorized result and
inspection boundaries.
