# Serial For each and exact Collect

Implemented in version: **0.261.117**

Application version source: `application\single_app\config.py`.

## Purpose and dependencies

For each applies a saved body of tasks to each member of an authorized, frozen
input collection. Collect then reads the body's declared output for every item
and preserves the resulting records in order. This supports document-by-document
review followed by an explanation of the complete findings, without uploading
the findings to a workspace or waiting for indexing.

This extends [structured workflow control flow](WORKFLOW_STRUCTURED_CONTROL_FLOW.md).
It uses definition version 3, the existing durable runner and lease, schema-2
journal, result transport, source authorization, and native Analyze checkpoints.
No second scheduler, database container, or local memory-file store is required.
Existing V1, V2, and non-loop M4A definitions retain their behavior.

## Choose the collection

The List editor supports three input sources:

| Source | What becomes an item | Ordering |
| --- | --- | --- |
| Selected documents | Each explicitly selected, currently authorized document | Selection order |
| Saved collection | Each complete record or per-document result from a declared earlier output | Original record order |
| Workspace query | Each distinct authorized logical document selected when the loop starts | Stable identity order for exhaustive selection, or the selected ranking for Best N |

Searching a workspace does not make every searchable document an item. A search
can cover a large workspace and select 80 documents; processing that selection
creates 80 loop visits.

### Frozen workspace queries

**All matches** means exhaustive metadata/filter or keyword-content matching.
Content matching covers the current searchable, screened representation; it is
not a promise that unindexed files were searched.

**Best N documents** is an explicitly limited selection. It can use
keyword or semantic/hybrid relevance ranking. It is not exhaustive semantic
coverage. Multiple matching chunks of one document do not become multiple loop
items.

Preview shows an authorized advisory selection. Execution evaluates the query
when the loop first starts and freezes the actual selection. Later documents,
different search ordering, or another preview do not change that run's
membership. The capture is not a transactional point-in-time snapshot of an
entire workspace or search index.

Unavailable catalogs, failed continuation, search errors, and failed access
checks are errors, not empty collections.

## Item limits and other budgets

The administrator's **Workflow Loop Item Limit** defaults to **500**, with a
supported range of **1-5,000**. Authors may choose a smaller per-loop maximum.
The effective limit is shown in authoring and run inspection.

Oversized input is rejected before any body task for that loop runs. For
example, a query may report that it found **at least 501 documents** while the
run permits 500. Narrow the query or select 500 or fewer documents; the engine
does not silently take the first 500. Earlier producer tasks may already have
completed before a saved collection's size is known.

Administrator changes apply to new runs. Active runs retain their admitted
policy and frozen inputs. Raising the item ceiling does not increase the
separate execution-admission ceiling or elapsed deadline. A multi-task body can
exhaust those limits before using every permitted item.

Model context capacity is a different limit. It comes from each task's effective
catalog/deployment settings, including instructions, tools, and output
reservation. This slice does not impose a cumulative run-token or spending cap.

## Author a document review

1. Open a personal or group workflow in V2 List and enable structured control
   flow if the draft is still ordered.
2. Add a For each block. Select documents, an earlier saved collection, or a
   workspace query, and review the item maximum.
3. Add tasks inside the body. Bind the current item explicitly; its JSON value
   contains `value`, a stable `key`, and a zero-based `index`. Shared criteria
   remain separate shared-reference documents.
4. For a document loop, set Analyze to the current document. The engine resolves
   that one trusted descriptor instead of repeating the whole original
   selection for every visit.
5. Declare a body output by selecting its exact producer and representation.
   Use an existing If/else join when either branch can supply that output.
6. Add Collect after the loop and select the named body output. Declare any
   required shape, business-key uniqueness, count, or coverage requirements.
7. Bind the collected records to a later task and declare the promised final
   outputs.

Document descriptors come from the authorized document boundary. An arbitrary
saved record with a `document_id` field does not grant permission to Analyze
that document.

Bodies run serially. Nested For each blocks share the existing depth limit of
four regions, counting the root. Hosted-agent loop execution is unavailable;
select an eligible model or local agent. Existing non-loop hosted workflows
remain supported.

### Scope and outputs

Each logical task appears once in the authored tree, but executes separately
for each item. Ancestor outputs can be explicit inputs; another item's latest
reply cannot.

Body results cross the loop boundary through Collect, not through an implicit
last-child output. Nested loop results must cross their own Collect boundary
before an outer body can export them.

Collect supports homogeneous `records` and `document_results` exports and
preserves the selected kind. Text concatenation and arbitrary JSON-object
merging are not implicit collection policies.

## Exact collection and partial results

Collect writes every eligible record in frozen-item order followed by
producer-record order. It does not invoke a model, rewrite record values, or
deduplicate equal-looking records. Contributor ranges retain the exact
producer execution, attempt, output, and original record ordinal.

If an `identity_field` is declared, missing or duplicate business keys invalidate
the aggregate with explicit diagnostics. They do not cause records to disappear.

| Outcome | Meaning |
| --- | --- |
| Empty input | No body calls; an empty aggregate is valid only if its output contract permits it |
| Completed item, zero records | A successful empty result, recorded separately from a skip |
| Skipped optional export | An explicit coverage omission, not an invented empty result |
| Completed accepted partial output | Usable only through explicit partial policies; limitations remain visible |
| Failed, invalid, pending, or unreadable result | Cannot become eligible through approval or a partial flag |

For optional/partial body exports, explicitly allow partial Collect output and
do not require complete collection coverage. Downstream bindings must also
accept partial data. The result remains `completed_partial`, not an unqualified
complete result.

## Complete data and large model inputs

Full records and receipts remain in the existing private result store. Record
pages and bounded hierarchical indexes prevent Collect from building one
unbounded in-memory list.

For qualitative explanations, the explicit **Saved-record report** processing
mode can consume every saved record in bounded model calls. It retains original
records, page coverage, intermediate checkpoints, and source-linked support.
This mode requires text output, declared collection inputs, no document action
or publication, and a locally metered runner.

Ordinary full-input tasks do not silently become summary tasks. If the complete
input cannot fit and cannot safely be split for the requested operation, the
run pauses with the original data retained. Compact interpretations are not a
lossless substitute for the dataset or a general reducer for numeric
calculations and arbitrary transformations.

Native Analyze retains its own supported source-window processing. Neither
approach saves loop control state into general fact memory or uses model prose
as an execution cursor.

## Resume, approval, and inspection

The frozen manifest records membership, order, stable keys, count, source
snapshots, and exact upstream receipts before body execution. A continuation
uses the saved item cursor and completed executions rather than rerunning
successful siblings or querying the workspace again.

An iteration path contains one frame per enclosing loop:

```json
[
  {"loop_id": "each_source", "item_id": "<stable digest>", "index": 7},
  {"loop_id": "each_finding", "item_id": "<nested stable digest>", "index": 2}
]
```

A retry retains its execution ID and advances its attempt. Approval and recovery
bind the exact item, execution, attempt, input digest, and gate. Approval for
item A cannot authorize item B, even when their data looks identical.

V2 inspection pages show frozen items, their executions and attempts, complete
record pages, and contributor receipts. Byte excerpts remain separate transport
views and may show index metadata; they are not semantic record pages.

Inline record inspection has a bounded response size. An oversized individual
record produces an explicit retained-data error, not a shortened record.

Every read and continuation rechecks the relevant source boundary. Changed
source revisions or revoked permissions cannot become optional absence.
Cancellation/deletion fences subsequent writes, including Analyze preparation.
It does not undo external actions that already completed.

Interrupted Collect writes do not expose an eligible prefix. Recovery can
rebuild private aggregate pages from saved per-item outputs without reinvoking
the body.

## API and implementation

Personal and group workflow APIs retain their existing prefixes; group calls
use explicit `group_id` scope. The new inspection resources are:

```text
POST .../workflows/loop-inputs/preview
GET .../runs/<run_id>/executions/<loop_execution_id>/items
GET .../runs/<run_id>/executions/<execution_id>/attempts/<attempt>/records
GET .../runs/<run_id>/executions/<execution_id>/attempts/<attempt>/provenance
```

Pages carry `next_cursor` and bounded counts. Cursors identify a page within an
authorized snapshot; they are not access grants.

The main implementation extends the workflow compiler/identity, flow runner,
structured execution/journal, and existing result readers. Focused
`functions_workflow_iterations.py`, `functions_workflow_collections.py`,
`functions_workflow_collect.py`, `functions_workflow_loop_inputs.py`, and
`functions_workflow_reporting.py` reuse those boundaries rather than creating a
separate engine.

## Testing and limitations

Functional coverage includes 0/1/10/100/500-item runs, nested scopes, frozen
restart, item-specific approvals, exact zero/multiple-record collection,
business-key errors, per-document native Analyze, source revocation, storage
integrity, and histories beyond 1,000 executions. Browser coverage uses the
actual local V2 bundle and closed API fixtures.

Key tests include `test_workflow_for_each_execution.py`,
`test_workflow_loop_native_analysis.py`, `test_workflow_collection_pages.py`,
`test_workflow_loop_inputs.py`, `test_workflow_loop_reporting.py`,
`route_tests\test_workflow_loop_policy.py`, and
`ui_tests\test_v2_workflow_loops.py`.

Repeat until, parallel iteration, hosted-agent loops, generic aggregate
publication, publication/index-readiness continuation, cumulative spending
caps, and the visual Flow editor are not included. Original native Analyze
artifacts still use the existing publication service and destination ledger;
Collect is not relabeled as native Analyze to bypass that boundary.

Validation uses fictional data and isolated services. It is not evidence of a
live deployment or permission change.
