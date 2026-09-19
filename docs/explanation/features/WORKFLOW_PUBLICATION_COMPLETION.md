# Workflow publication completion

Implemented in version: **0.261.118**.

Saved-output integration implemented in version: **0.261.119**.

Application version tracking: `application/single_app/config.py`.

## Purpose and scope

A workflow can submit an existing Analyze artifact, or explicitly render and
submit saved records, without waiting for the destination to be searchable.
It can instead require approval and index readiness before continuing.
The completion policy makes that choice explicit. Closing the browser or
restarting a worker does not create a new publication request.

This feature applies to **definition-version-3 durable workflows** in personal
and group workspaces. Both source paths use the existing publication receipt
ledger, workspace approval routes, native document processing, screening, and
workflow runner. It adds no scheduler, Cosmos container, administrator setting,
or model call.

Since **0.261.119**, **Saved workflow output** creates exact JSON through the
shared Generated File Export Framework before entering this same completion
service. It requires one eligible, explicitly bound records output from a task,
Collect, or explicit join. Generic records are never relabeled as native
Analyze artifacts. See
[Saved workflow output publication](WORKFLOW_SAVED_OUTPUT_PUBLICATION.md)
for source eligibility, partial acceptance and file materialization.

## Choose the completion level

In the V2 List editor, enable **Publish a workflow file** and choose **Existing
Analyze file** or **Saved workflow output**. Bind exactly one eligible output,
choose a supported format and explicit destination, then select **Complete
publication when**. Servers without the new source capability retain **Publish
an existing analysis artifact** and native behavior.

| Level | When the workflow can continue | What remains outside the promise |
| --- | --- | --- |
| Submitted | The destination request and required submission stages are confirmed. Personal publication has a processing handoff; group/public publication has an approval request. | Approval, completed processing, and search readiness. |
| Approved | The existing destination approval has completed, including its processing handoff. Personal workspaces report approval as **not required** and complete at confirmed submission. | Completed processing, screening clearance, and search readiness. |
| Indexed and ready | The original-content destination revision completed its native processing, is currently available under screening rules, and its complete expected native index projection is visible. | Future availability or guaranteed semantic relevance. |

For example, choose **Submitted** when the deliverable only needs to enter a
review queue. Choose **Indexed and ready** when a later task relies on the
published document being available for workspace retrieval.

New publication tasks select Submitted when the server advertises support.
Existing tasks without a completion policy display their existing behavior
and keep the field absent until the author changes it. Their prior behavior
is not silently converted into a new policy.

Destination approval is separate from both a workflow's optional
pre-execution task approval and a content-screening review. Choosing Approved
does not manufacture a personal-workspace approval step or authorize the
workflow to approve its own shared destination.

## Definition and receipt identity

The policy is one optional enum on the existing publication object:

```json
{
  "publication": {
    "artifact_format": "md",
    "workspace_scope": "group",
    "group_id": "explicit-destination-id",
    "completion_policy": "indexed_ready"
  }
}
```

Allowed values are `submitted`, `approved`, and `indexed_ready`. Null and
unknown values are rejected. Version-1/2 definitions do not support this
field. Editor options advertise `supported_publication_completion_policies`;
unsupported saved definitions remain intact and read-only.

The example intentionally omits `source_kind`, preserving native Analyze
publication. Generic records require `source_kind: "saved_output"`,
`artifact_format: "json"` and one required `node_output` records binding.
Source options are advertised separately in `publication_source_capabilities`;
they do not change the meaning or omission behavior of completion policies.

For native artifacts, the existing receipt binds the artifact, immutable byte
digest, exact native producer execution/attempt, selected saved output,
destination, actor and policy. The publishing execution includes the run,
definition revision and loop path. Retrying that publishing execution does
not create a new document merely because its publishing attempt changed.

Native receipt identities are unchanged. For saved-output files, the same
ledger binds the validated generic source instead of a native
`analysis_producer`. The version-3 request remains
`workflow-publication:v3:{publishing_execution_id}:{producer_execution_id}:{producer_attempt}`.
File materialization has its own deterministic source/representation key,
independent of publishing attempt and destination; its existing journal units
do not replace destination receipts.

A private `artifact_publication` continuation points back to this receipt.
It is persisted with the existing task checkpoint, not in a second job
system. IDs, previews and receipts do not confer permissions.

## Waiting and recovery

Run inspection shows the requested level and separate submission, approval,
processing, screening and index observations. The waiting task remains
ineligible for downstream use.

| Observation | Workflow behavior |
| --- | --- |
| Destination approval pending | Waits for the existing workspace review. Workflow task Approve/Reject controls do not decide this request. |
| Native processing, screening/review, or index visibility pending | Remains waiting for output and releases the worker. |
| A remote operation may have happened but its acknowledgement is missing | Pauses with the existing receipt. Rechecking does not blindly repeat the operation. |
| Source or destination access cannot be confirmed | Withholds sensitive details and pauses; restore access before rechecking. |
| Rejection, request cancellation, unavailable destination, or unsupported readiness | Does not report success or create a replacement copy. |
| Screening changes/remediates the original content | Pauses rather than silently accepting the altered derivative. |

Use the existing workspace review surface for destination decisions. Where
the runtime offers Resume/check again, it examines the same publication.
Confirmed copies and notifications are not resent. An unconfirmed started
effect without durable evidence remains uncertain, even after repeated Resume.

An explicit policy cannot be skipped by **continue on error**. Waiting time
counts toward the existing elapsed deadline, and Resume does not reset that
deadline or execution limits. A scheduled trigger does not overlap the waiting
run.

Once a requested weaker level has successfully completed, later destination
lifecycle changes do not retroactively reopen that task. Its saved result
records the level actually achieved; Submitted never means Indexed and ready.

A saved successful completion observation is immutable. Recovery rechecks
current source/artifact/destination authorization separately instead of
rewriting that observation when approval or processing advances. Pending
observations can still refresh within the same exact attempt.

## What proves index readiness

The observer checks the exact destination document, receipt and native
revision, not a filename or one convenient search hit. Native ingestion records
the original input binding and completed indexed-chunk count. The observer
requires the full expected count in the exact document/version/destination
scope and rechecks current availability.

Both fresh availability reads reject a revision that has been archived or
replaced while readiness was being checked. Permission to read a historical
copy does not make it the current searchable publication.

Screened documents additionally require the native scan/release proof for
unchanged content. Pending review, incomplete scanning, errors and stale
clearance cannot qualify. Ordinary clearance or approval-with-flags may qualify
when the published bytes are unchanged.

"Processing complete - no content indexed" is not index readiness. The native
projection is format-specific: a tabular document may have a schema-oriented
search representation rather than an individual search chunk for every row.
This policy does not replace the native indexing contract with a promise of
exhaustive semantic retrieval.

A valid exact JSON file, including an empty array, therefore does not prove
index readiness. Saved-output publication uses the same native worker and
original-content evidence, not a new saved-record indexer.

If complete native proof is unavailable, the workflow reports that limitation;
it does not reconstruct an artifact with a model or infer success from prose.

Reconciliation does not make an underlying native upload resumable or blindly
requeue a lost native job. If an acknowledged handoff produces no completion
evidence, the workflow remains waiting within its existing deadline. An
unacknowledged operation remains uncertain until its exact outcome can be
confirmed.

An already-enqueued native screening job can finish independently of the upload
worker. Its authoritative, unchanged-content release proof can confirm the
original handoff even if that worker never recorded a processing marker.

## Authorization and cancellation

Current workflow, source, artifact and destination access is checked at
sensitive operations and continuation. The recorded initiating actor remains
the publisher, including group workflows where that actor differs from the
workflow owner. Another manager's Resume does not transfer their permissions
to the run.

Destination reviewers use their existing roles. Positive approval rechecks
the original publisher's source/destination authority and the original bytes.
A rejection or cancellation retains a receipt outcome before the pending
document is removed.

Workflow viewers do not inherit access to a private personal destination.
Public status projections exclude internal artifact locators and processing
evidence; normal document mutations cannot supply that evidence.

Cancel stops subsequent workflow work and fenced checkpoint writes. It cannot
undo a native processing job, copy or notification already handed off. Published
workspace copies have independent destination permissions and are not deleted
when a workflow or its private run results are deleted.

## Implementation and validation

| Component | Responsibility |
| --- | --- |
| `functions_workflow_artifacts.py` and `functions_generated_file_exports.py` | Authorized saved-record materialization before entering the existing publication service. |
| `functions_generated_artifact_sources.py` | Source-specific authorization without weakening native Analyze provenance. |
| `functions_artifact_publication.py` | Existing receipt stages, policy evaluation, authorization and shared destination decisions. |
| `functions_artifact_publication_readiness.py` | Compact native ingestion evidence and read-only index/availability observations. |
| `functions_workflow_readiness.py` and existing runner/runtime | Exact typed continuation, wait/requeue and same-receipt recovery. |
| Group/public document routes | Existing approval, denial and cancellation surfaces. |
| V2 workflow editor and run inspectors | Completion choice and safe, exact execution/attempt status. |

Regression coverage includes real native Analyze adaptation through a saved
join; personal/group/public publication; both Cosmos and Blob result storage;
delayed approval/index visibility; restart and repeated Resume; screening and
original-byte checks; lost acknowledgements; source/destination revocation;
notification deduplication; and no-policy compatibility.

Principal tests are `test_workflow_publication_completion.py`,
`test_workflow_structured_publication.py`, `test_publication_native_processing.py`
and `ui_tests/test_v2_workflow_publication_completion.py`. They use closed
fictional service boundaries and the actual local V2 bundle. They do not
constitute live deployment acceptance or publish test documents to real
workspaces.

Saved-output integration is targeted by
`functional_tests\test_workflow_collect_publication.py`,
`functional_tests\test_workflow_saved_output_artifacts.py` and
`ui_tests\test_v2_workflow_saved_output_publication.py`, alongside those native
regressions. Coverage includes both result backends, exact source retry
identity and unchanged completion levels; see the
[validation commands](WORKFLOW_SAVED_OUTPUT_PUBLICATION.md#testing-and-validation).
