# Structured workflow control flow

Implemented in version: **0.261.116**

Application version tracking: `application/single_app/config.py`.

## Purpose and scope

Structured workflows choose a path from validated data instead of relying on a
model to describe what should happen next. Milestone 4A adds **If/else**, task
**Run when**, explicit branch joins, and restricted forward routing to the
personal and group V2 List editor.

This is useful when an assessment should produce either an explanation or a
review, when an optional task should run only for particular findings, or when
a known later step can safely replace optional intermediate work.

For each, Repeat until, exact Collect, generic aggregate publication, and the
visual Flow editor are not part of this slice. The execution identity and
paged journal are prepared for repeated execution; M4A does not admit loops.

## Dependencies and compatibility

Structured control flow uses the existing workflow runner, durable execution
lease, private result store, source-authorized readers, native Analyze adapter,
and artifact publication service. No second scheduler, Cosmos container, or
external browser library is introduced.

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

| Limit | M4A policy |
| --- | --- |
| Authored tasks | Existing administrator setting: default 50, supported range 1-100 |
| Structural IDs | At most 256 |
| Nested flow depth | At most 4 |
| Predicate size | At most 100 nodes, depth 8, and 16 KiB |
| Execution admissions | Default/maximum 5,000; includes retries, not result-chunk writes |
| Elapsed deadline | Default/maximum 86,400 seconds, including waits |
| Model input | Existing effective catalog/deployment budget; complete required input is never clipped |

Run history distinguishes selected paths, intentionally skipped nodes, output
validation, attempts, and exact consumed-result receipts. Large execution and
decision histories are paginated. Full result content is requested separately;
a byte-range excerpt is a display transport, not a complete-record iterator.

Completion checks selected-path obligations and required final outputs, not
whether every authored branch ran. Accepted partial work remains
`completed_partial`. Exhausted limits and missing required results do not
become Completed.

## Publication boundary

Existing publication tasks use the existing artifact publication service and
destination ledger. In a structured workflow, publication selects its exact
upstream producer explicitly instead of searching whichever task happened to
finish most recently. Source and destination permissions are checked again.

An acknowledgment retry reuses the publication identity. It must not create a
second document or duplicate approval notifications. Existing `queued`,
`pending_approval`, `approved`, `approval_failed`, and `uncertain` states retain
their meanings; none is a new promise that indexing has completed.

New processing/index-readiness policies and publication adapters for generic
aggregates belong to later milestone-4 slices.

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
source checks, and invalid-output inspection.
`functional_tests/test_workflow_structured_publication.py` passes genuine native
Analyze records through a saved join and the existing publication service,
including restart without duplicate publication and later source revocation.

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
