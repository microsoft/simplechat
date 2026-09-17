# Durable Workflow Execution

Implemented in version: **0.261.111**

Application version tracking: `application/single_app/config.py`.

Structured control-flow integration in **0.261.116** adds an opt-in version-3
definition and execution-scoped, paged journal records. The ordered version-2
behavior described below remains supported. See
[Structured workflow control flow](WORKFLOW_STRUCTURED_CONTROL_FLOW.md).

## Purpose

Durable execution separates a workflow run from the browser request that
submitted it. Completed operation checkpoints, approval decisions, pending
output references, and the run's definition snapshot are stored in the existing
Cosmos and Blob infrastructure.

This is useful for multi-task work that may outlive a page, wait for a human
decision, or require a background result before the next task can begin. It
extends the existing runner; it is not a second workflow engine.

## Enable durable execution

In the V2 workflow editor, enable **Durable execution**. New native workflows
start with this option enabled. Existing workflows retain their stored setting;
an absent setting does not silently change legacy synchronous execution.

Task details can optionally require approval before execution. An approval
message explains what the reviewer should inspect. Task approvals require
durable execution.

The serialized definition remains version 2:

```json
{
  "definition_version": 2,
  "durable_execution": true,
  "tasks": [
    {
      "id": "review",
      "name": "Review findings",
      "type": "instructions",
      "instructions": "Explain the accepted findings.",
      "approval": {
        "required": true,
        "message": "Review the inputs before allowing this task to run."
      }
    }
  ]
}
```

Approvals are server-owned decisions about a specific task/input fingerprint.
Text in a document, generated result, or run-memory summary cannot approve a
task, change its destination, or enable additional tools.

## Submission and background processing

Durable workflows use the existing personal/group run endpoints. A submission
returns HTTP 202 with its queued run ID rather than keeping the request open
until the model finishes. Clients can include a stable `request_id` UUID so a
retry of the same submission identifies the same logical run.

The existing background scheduler discovers active durable runs. A small,
bounded worker pool executes independent runs while Cosmos leases arbitrate
ownership across processes. Waiting approvals release the worker; closing the
browser does not cancel or forget the run.

Scheduled workflows retain a single active run. An interval that becomes due
while the run is waiting does not start overlapping work. File Sync remains
part of the run's preparation and uses its existing authorization and trigger
rules.

## What is checkpointed

The private runtime journal stores small control metadata and immutable
references, not credentials or serialized Flask sessions. Full values use the
same scoped result store as task outputs.

Checkpoint boundaries include preparation, task invocation, final assistant
publication, and notification operations. The original workflow definition is
snapshotted at submission. Shared references are frozen and reauthorized on
continuation, and completed task outputs retain their exact producer identities
and consumption receipts.

On continuation, an unchanged completed checkpoint supplies its saved value
instead of invoking the model or tool again. Changed inputs cannot silently
reuse an old checkpoint. A later edit to the saved workflow is not substituted
into an existing run.

These are operation-boundary checkpoints. They do not reconstruct an unfinished
provider response or make an arbitrary external tool transactional.

## Run states and gates

| State | Meaning |
| --- | --- |
| `queued` | Accepted and waiting for a worker. |
| `running` | A live worker owns the execution lease. |
| `waiting_approval` | A task is blocked on an authorized human decision. |
| `waiting_output` | A submitted background operation has not produced the required final output. |
| `waiting_recovery` | An interrupted or failed operation may have performed external actions; review is required before replay. |
| `paused` | Changed inputs, unavailable access, or an unsupported continuation needs attention. |
| `completed` / `completed_partial` | The normal output-validation policy determines the final deliverable outcome. |
| `failed` / `invalid` / `incomplete` | A task or deliverable requirement was not satisfied. |
| `cancelled` | Cancellation fenced further checkpoint/publication work. |
| `skipped` | File Sync found no changes and the existing continuation policy skipped execution. |

### Human approval

Approving a task queues continuation of the same run. Rejecting it cancels that
run. The request includes the current journal version and gate ID, and a stable
decision request ID makes a repeated acknowledgment idempotent.

A decision from an old tab cannot approve a replacement gate. Current personal
ownership or group management rights are checked at the decision endpoint.
Readers without decision rights can inspect authorized progress but cannot
approve or resume it.

### Readiness

Pending output is not task success. The run retains the original child-run
reference and waits for its producer's completion contract. It does not repeat
Analyze submission merely to obtain a newer status.

Completion alone is not enough to invent final data: a missing final
representation, failed output, or unsupported mixed-source continuation remains
explicitly unavailable or paused. Presentation summaries and diagnostic Markdown
are not substitutes for the authoritative final result.

### Recovery and cancellation

An interrupted operation with no possible external side effects can retry
within a bounded automatic attempt policy. Operations that may have performed
external actions require an explicit recovery decision. The warning remains
important even if the original worker disappeared before reporting an error.

Cancellation revokes the journal's execution ownership. It cannot undo a
previously completed email, upload, or third-party action. A delayed worker
cannot commit another task checkpoint after its lease is lost or the run is
tombstoned.

## Run memory and inspection

The run inspector shows the current gate, checkpoint units/attempts, progress,
and decision history. **Run memory** is a read-only projection of durable state,
not an editable Markdown file and not an authority for validation or approval.

Full task results continue to use their scoped, source-authorized readers.
Internal journal rows, lease tokens, request payloads, and checkpoint control
records are excluded from ordinary task-item lists.

Private lifecycle tombstones survive run cleanup. Deletion removes result
payloads without allowing a late worker to recreate the deleted run.

## Runtime API

Use the corresponding personal or group prefix:

```text
GET  /api/user/workflows/<workflow_id>/runs/<run_id>/runtime
POST /api/user/workflows/<workflow_id>/runs/<run_id>/runtime/decision
POST /api/user/workflows/<workflow_id>/runs/<run_id>/runtime/resume
```

Group endpoints replace `user` with `group` and support the existing explicit
`group_id` query parameter. Selecting a group does not alter the user's active
workspace setting.

Runtime reads return a safe `runtime` projection and `can_decide`. Decisions
carry `expected_version`, `gate_id`, `choice`, and `request_id`. Resume requests
carry `expected_version` and `request_id`. Lease tokens are never client inputs.

## Implementation and verification

`functions_workflow_runtime_store.py` owns the Cosmos journal and renewable
lease. `functions_workflow_execution.py` provides operation-boundary checkpoints
around the existing dispatcher. `functions_workflow_runtime.py` handles
submission, continuation, runtime controls, and progress projections.

Functional coverage exercises recreated workers/stores, approval persistence,
input changes, interrupted external actions, stale decisions, cancellation,
claim races, checkpoint integrity, pending outputs, and private-record
visibility. Native V2 tests cover queued responses, run-memory/approval recovery
after reload, and explicit decision permissions.

No new Cosmos container or external workflow service is required. Structured
If/else, Run when, and restricted forward routing are available through the
version-3 List editor. General For each, Repeat until, exact Collect, and visual
Flow authoring remain later milestones.
