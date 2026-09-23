# Orchestration Checkpoint Recovery

**Version: 0.261.129**

Implemented in version: **0.261.105**, recorded in
`application/single_app/config.py`.

Plan-contract v2 retained-reference recovery implemented in version:
**0.261.127** (Refs #1509). Same-attempt waiting claims and native/result
continuation were added in **0.261.127**. These are explicitly admitted internal
runtime APIs used by the opt-in harness. Initial-claim recovery,
output-acknowledgement handling, and default cleanup enrollment were hardened
in **0.261.129**; see
[runtime boundary hardening](../fixes/ORCHESTRATION_RUNTIME_BOUNDARY_HARDENING_FIX.md).

## Overview

An orchestration failure should explain what could not finish without discarding
work that already succeeded. Checkpoint recovery saves completed step results and
uses them when the user chooses **Retry from failed step**.

For example, if document search succeeds and a later agent call times out, retry
uses the saved search result instead of searching again. The failed agent step
runs again, its dependents can proceed, and the answering step uses the combined
results.

Recovery applies to the V2 orchestration interface. New plans use contract 2
only when both administrator orchestration settings are enabled; saved plans
retain their recorded contract. These additions do not change ordinary-agent
chat or select a replacement agent. The harness's per-file automatic attempts
are separate from retrying a failed orchestration plan.

## Dependencies and configuration

The existing `enable_chat_orchestration` setting enables the workflow. Each
capability, source, agent, action, and model must still be enabled and accessible
to the user. Retry does not grant additional permissions.

Checkpoints use the existing `orchestration_runs` and
`orchestration_run_steps` Cosmos containers. No separate Blob Storage connection,
new deployment resource, or recovery preference is required.

Existing execution limits apply to newly executed work. Reusing a saved result
is not another tool invocation. Retry does not raise the failed step's timeout.

## Understand the failure before retrying

The conversation and Run view identify the failed operation and its known
reason. An observed time limit is reported as a timeout, not as cancellation by
the user. A provider status can be included when the runtime actually received
it; the application does not guess that a service is offline from error prose.

Authorized partial results remain available. If the answering model also fails,
an application-generated status explanation reports the incomplete work rather
than leaving an empty assistant turn.

If message storage is unavailable, the interface explicitly marks the visible
explanation as not saved. It does not claim that an unsaved message will survive
a reload.

A run can reach a terminal execution status before its final message finishes
saving. The interface keeps checking during that interval. If the worker stops
before publication can be confirmed, the interface reports that uncertainty
rather than claiming that a message was definitely not saved.

**Stop** requests server cancellation. Losing the browser connection is different:
the server may still be working. The interface reconciles the saved run before
offering recovery instead of automatically starting another execution.

## Resume a failed request

1. Read the failure explanation in the conversation or open its Plan/Run view.
2. Select **Retry from failed step** when saved progress is recoverable.
3. Review which completed steps will be reused and which work will execute.
4. If an agent or action may have already changed an external system, acknowledge
   the warning before retrying that step.
5. Follow the new attempt. Reused steps are labelled **Reused saved result**, and
   the answer is generated from saved and newly completed work.

Retry creates a linked attempt of the same effective plan. It retains the
original question, chosen agent and model, accepted clarification answers, source
restrictions, and saved conversation context. It does not duplicate the user
message or ask the planner to choose a different approach.

The original resolved request is retained, including a time window resolved
during planning. Ask a new question when a different time range or different
approach is needed.

Retries require an explicit user action even when normal plan approval is Auto
or countdown-based. Reloading a conversation does not approve a retry. Earlier
attempts remain inspectable, but cannot create competing branches after a newer
attempt exists.

If a retry was prepared but not yet executed when the connection was lost, it
stays paused. Open it and use **Run prepared retry** to start that saved attempt.
**Check saved status** reconciles uncertain execution state, while **View current
attempt** and **View previous attempt** navigate history without executing work.

## External effects and checkpoint boundaries

A checkpoint represents one completed orchestration step. An agent step can
contain several internal tool calls; recovery does not restore that internal
tool loop.

If an agent changed an external record and then failed, retrying that agent step
could repeat the change. The same uncertainty exists if external work completed
but saving its checkpoint failed. The confirmation explains this before
execution. Unknown replay safety is treated conservatively rather than inferred
from an integration's name or the wording of the task.

Previously completed plan steps are not silently reexecuted. If one of their
checkpoints is no longer valid, recovery stops with an explanation instead of
turning Retry into a full-plan restart.
This also applies when a retry worker stops before copying inherited results:
completed work remains bound to its saved checkpoint in an earlier attempt.

## Durable state and validation

The [retained-result foundation](ORCHESTRATION_RENDERING_HARNESS.md), implemented
in **0.261.125** (Refs #1509), stores large original datasets in private result
sections and exposes small immutable descriptors. M4 adds version-dispatched
runtime/checkpoint consumers of these descriptors. Existing v1 state
serialization, input fingerprints, source-bound Analyze references, phase
repairs and terminal answering remain unchanged. A private result descriptor
alone is still not proof that a step completion checkpoint was saved.

Legacy completed results include their evidence, notes, citations, artifact references,
required context changes, and execution provenance. A summary alone cannot
reconstruct these values.

Payloads are split into bounded records and published through a committed
manifest. Reconstruction checks their identity, schema, size, completeness, and
integrity. An incomplete or damaged payload is not treated as an empty successful
result. Each checkpoint is limited to 8 MiB of serialized payload across at most
64 chunks. Exceeding that bound fails checkpoint persistence explicitly rather
than truncating the result.

Each legacy checkpoint is bound to its effective plan, step inputs, dependency context,
and relevant sources. This includes context an adapter actually consumes, such
as earlier findings supplied to an action, not just declared step dependencies.

Current authorization is checked before reuse and before publication of the
answer. Changes to referenced conversation messages, source availability, agent
or action definitions, or model access can make recovery unavailable. The
application does not substitute a source or model to bypass that failure.

Runtime clients, credentials, callbacks, and raw saved-memory prompts are not
checkpoints. Runtime identity and authorized memory are rebuilt for each
attempt. Private payloads remain server-side; browser responses expose safe
status and recovery summaries.

Checkpoint payloads are removed when the owning conversation is deleted,
including bulk deletion and archive-and-remove. Existing archived messages keep
their normal behavior, but archived conversations do not retain executable
recovery state.

### Initial claims and early interruptions

Since **0.261.129**, approval of a v2 run saves its original `started_at`,
`execution_deadline_at`, and lease in one conditional write. The budget comes
from the server's `chat_orchestration_total_timeout_seconds` setting using the
same policy as execution, including the existing 600-second fallback.
Preparation and source acquisition consume that original budget. Changing
settings or restarting the worker does not create a new same-attempt deadline.

A scheduler continuation can also recover an interruption before the first
execution checkpoint. Its current owning execution claim may establish the
first context binding only when the run has no prior execution state or private
input, waiting, or completion checkpoint manifest. The existing lease performs
the conditional write and confirms uncertain acknowledgements before adopting
that exact binding. Stop and other progress changes are checked again if the
write races. Ownership, plan, attempt, and timing remain immutable; this is not
permission to replace an existing binding or rerun completed work.

An expired original budget prevents new work. A started record whose saved
timing is missing or invalid is refused rather than assigned a fresh budget.
Separately approved manual plan retries remain new attempts with their own
initial claims; they are not same-attempt continuation.

### Durable retained-file cleanup

Since **0.261.127** (Refs #1509), v2 conversation deletion also enrolls retained
files using the run's authoritative `render_output_ids`, not visible message
cards or the set of outputs already marked `cleanup_pending`. This covers
completed files whose ordinary output scan would otherwise have no cleanup
work to discover.

`cleanup_conversation_checkpoints` accepts an optional server callback
`output_cleanup(run_id)` and the explicit archive policy `retain_committed`.
Since **0.261.129**, when the callback is omitted or `None`, recovery lazily binds
`build_orchestration_cleanup_service(user_id, conversation_id).enroll_run_cleanup(run_id)`.
Initialization occurs after every run's deletion fence and cleanup intent are
durable, and one initialized service handles the conversation's admitted runs.
The existing single and bulk route callbacks remain supported. Legacy runs and
empty admission indexes do not initialize this output service.

The shared enrollment method uses `prepare_cleanup(tombstone=True)` for the
default deletion policy, verifying each output's exact run, frozen admission
index and retained deletion proof. It schedules cleanup without Blob I/O and
preserves committed intents; recovery does not duplicate that per-output logic.
An initialization failure leaves the durable parent intent pending and prevents
payload purge, so the existing deletion or scheduler path can retry safely.

Before removing retained payloads, recovery writes the permanent checkpoint
deletion guard, then conditionally saves `checkpoints_deleted` and the canonical
`output_cleanup` intent together on the parent run. The intent freezes the full
admitted output index and retention policy; a parent CAS retry rereads the index
rather than dropping a racing admission. Enrollment begins only after every
discovered owned run has its intent persisted. Recovery confirms both the
callback's result and the actual persisted enrollment before sweeping source
results or checkpoint payloads. A missing service, failed fence or unconfirmed
enrollment stops that sweep.

The scheduler discovers pending parent intents independently through its
`max_cleanup_runs` budget. If the process stops after the parent deletion CAS
but before individual outputs are fenced, the intent remains discoverable even
when those outputs still have `cleanup_pending: false`. The deletion-only
service verifies the retained owner/run identity and genuine permanent
checkpoint tombstone when the conversation is already absent. It does not
fabricate a live conversation, reopen source results or invoke a model.

Completed enrollment means output fencing and cleanup scheduling are durable,
not that file bytes have already been removed. Existing output cleanup applies
its staging grace period and generation fences, including uploads that finish
late. Archive-and-remove freezes `retain_committed: true` so committed files
remain intact while abandoned staging is cleaned; a later retry cannot change
that policy.

`test_orchestration_deletion_enrollment.py` covers lost parent acknowledgments,
missing-conversation replay, failed fences and complete admission indexes.
`test_orchestration_output_deletion_pipeline.py` exercises both actual deletion
routes, archive retention and late-upload cleanup.

## Internal dependency checkpoints

The checkpoint envelope remains version **1**. A plan with
`planner_contract_version: 2` adds `plan_contract_version: 2` inside its
checkpoint state. An absent marker continues to mean legacy behavior, not an
instruction to reinterpret an old plan.

| State field | Meaning |
| --- | --- |
| `task_results` | Step ID to serialized typed `TaskResult`, containing immutable named `ResultRef` descriptors rather than datasets. |
| `result_aliases` | Server-admitted aliases to exact authorized result references, including explicitly admitted cross-attempt reuse. |
| `pending_results` | Bounded server-owned native, retained-result or output waits; never previews, clients, credentials or worker callbacks. |
| `execution_deadline_at` | The attempt's timezone-aware total deadline, preserved across same-attempt restart. |

Large text, records, excerpts and provenance remain in the existing private
result store. V2 checkpoints exclude incidental sibling evidence, notes and
message bodies, retaining compact source snapshots and typed references.
The existing 8 MiB checkpoint limit, transactional lifecycle guard and
immutable completed manifests still apply.

New step fingerprints include declared bindings and exact result digests,
arguments, source versions, model/settings/memory bindings, the selected
capability definition, including its string `result_contract_version`, and any
selected prepared-content profile. A changed producer contract blocks v2 reuse;
it never rewrites stored producer identities or changes legacy v1 fingerprints.
Unrelated sibling notes, artifacts or task outputs are not step inputs. Whole-plan
approval/context binding remains an additional guard.

Since **0.261.127**, v2 context and step fingerprints exclude only
`enable_chat_orchestration_harness`, the switch for admitting new plans.
Disabling new-plan admission does not change the inputs of an already approved
run or force its completed producers to run again. Actual execution settings,
capability restrictions, source/model/memory bindings, and the original
deadline remain enforced. Legacy v1 hashes are unchanged. Coverage in
`test_orchestration_admission_fingerprints.py` includes exact legacy hashes,
execution-policy changes and real same-attempt waiting continuation in both
directions across the admission toggle.

Since **0.261.127**, v2 execution saves an immutable
`checkpoint-input:<step-digest>` manifest before invoking a producer. This uses
the existing chunked checkpoint store and lifecycle fence, not a second store.
Its payload contains the exact original `result_producer`, input fingerprint,
and compact pre-execution state. A failure to save this input checkpoint stops
the step before model or producer work. No input manifest is added to legacy
v1 execution.

Adapters obtain the declaration fingerprint through
`context.result_input_fingerprint_for_step(step_id)`, not by hashing expanded
runtime arguments or model output. It is bound before an Analyze source-set
input becomes a native document selection. Composition and Gather retention
forward it to the foundation's atomic complete/partial completion receipt;
the native bridge receives the same fingerprint through its existing callback.
Native dispatch pins that already-captured value on the scoped bridge; it does
not derive a replacement from scoped source metadata, default settings, or the
native job's separate `request_fingerprint`. Resume checks current declared
inputs against the saved digest before opening the original job.

Recovery can reuse an independent successful producer after an earlier sibling
failed; it no longer assumes that all successful work forms one linear prefix.
Every restored reference is reauthorized against current ownership, sources,
screening and producer state. The original actor, run and attempt on a result
are never rewritten. An old-attempt reference is admitted under an exact
server-generated alias before a new-attempt consumer can read it.

Since **0.261.127**, a failed step can retain its authorized `task_result`
descriptor in the saved step record and step event for diagnosis. For example,
an all-failed Compare task can retain `comparison` and `coverage` references.
These remain unavailable to result readers, dependent steps and final answers.
They are not added to the reusable `task_results` checkpoint state, do not set
`checkpoint_available`, and cannot prevent an independent successful step from
being reused. Producer identity, role and registered output names/kinds are
validated without opening failed output data; provider error prose is still
replaced with a safe failure message.

A same-attempt restart keeps the actual owning lifecycle token and deadline.
It does not rewrite an already committed completion manifest just because an
unrelated sibling has since finished. A separately approved child retry gets
its own attempt budget and token; restoring inherited references cannot reset
that child deadline or copy a parent's finished message into an unstarted run.
This is reuse support, not permission to bypass existing retry approval or
revision claims.

### Waiting and uncertain completion

Complete and explicitly partial tasks use immutable
`checkpoint:<step-digest>` manifests. Pending native tasks instead use
`checkpoint-wait:<step-digest>` with `record_type: checkpoint_wait_manifest`.
The separate guarded wait manifest cannot masquerade as a completed result or
prevent a later ready manifest from being committed. Dependents remain waiting
and no native work is resubmitted by the runtime.

Manual checkpoint retry of a waiting task is blocked with `result_not_ready`.
Ordinary waiting continuation uses the same run and attempt; it must not call
`prepare_retry`. The runtime does not add a scheduler or request-thread polling loop.
The native bridge persists only its validated server-owned wait descriptor,
never a runtime reader or a completed-looking preview:

```json
{
  "kind": "native_tabular_compute",
  "handle": {
    "version": "native-tabular-compute-v1",
    "job_id": "<server-owned UUID>",
    "request_fingerprint": "<server-owned 64-character digest>"
  }
}
```

### Claim one same-attempt continuation

Implemented in version: **0.261.127**, tracked in
`application/single_app/config.py`.

The owning route or scheduler can call
`claim_waiting_continuation(run_id, user_id, data, authorize=...,
message_container=...)`. `data` contains exactly `conversation_id`,
`submission_id`, and the current `expected_version` from `recovery_version`.
This operation is not a read/hydration API and must not run merely because a
conversation or status page was opened.

The result is `{"acquired": bool, "record": private_run_record}`. Only an
`acquired: true` result authorizes worker dispatch. Repeating the same submission
and original expected version returns `acquired: false`; it does not create
another worker. Do not send the private returned record directly to the browser.

The claim requires an approved v2 plan, intact waiting checkpoints, a matching
revision, current ownership, and no cancellation, deletion, successor or live
lease. An expired owner can be replaced through run-record compare-and-swap.
Unknown in-flight producer work remains `result_commit_unconfirmed`, not
permission to replay. A missing, malformed or expired total deadline cannot
be replaced with a new budget.

The run ID, `attempt_index`, original producer contracts, actual lifecycle token,
and `execution_deadline_at` remain unchanged. A new server execution
`claim_id` fences older lease, checkpoint and publication writers without
retagging the native job or retained results. The publication guard is reused
through compare-and-swap and preserves existing publication metadata. A revoked
guard cannot be revived. Partial claim-fencing failure dispatches no worker;
a later event can acquire the expired claim without changing the producer.

Construct `ExecutionLease` from the claimed record and the same publication
container, start it, then bind the initialized services to that lease's checks
and actual guard. `ExecutionCheckpoints(record, context, settings, lease)`
recognizes the persisted continuation claim and restores pending work from the
current run, including a retry child that itself began waiting. It never changes
the child back into its parent attempt.

Execute normally with those checkpoints. Each saved wait is refreshed once
through `resume_waiting_dependency_step`; ordinary adapter resolution is not
entered. Pending stays waiting. Ready results are fully retained and checkpointed
before dependents proceed. Failed/cancelled steps are not automatically retried,
and older sibling snapshots cannot resurrect a terminal pending result or
downgrade completed work. At another waiting outcome, release the execution
lease without cancelling the native computation or revoking its result guard.

Besides the native handle above, a retained-result wait has exactly
`{"kind":"orchestration_result","input_fingerprint":"<original server digest>"}`.
It accompanies the original empty pending `TaskResult` and queries the exact
foundation completion receipt once. An absent receipt remains pending;
unreadable or invalid retained content fails safely.

Output waits contain only `{"kind":"orchestration_output","output_id":"..."}`,
not a typed data task or a cached delivery claim. The central read-only bridge
uses the initialized `context.rendering_service` and its existing
`list_public_outputs`, `store.get` and `committed_artifacts` APIs. It verifies the original producer,
retained source, approved work, normalized filename, explicit render request
and unchanged deadline before accepting the current file outcome. Completed
file checkpoints use the same bridge, rather than trusting saved artifact
cards. A read cannot claim a render attempt, enqueue a retry, call a model or
publish an artifact. The scheduler and route
owner remain responsible for event delivery, service binding, safe terminal
handling of ownership failures, and final publication.

Saved step progress also writes the run's `task_results`, `pending_results`
and deadline through the owning lease. These fields contain current
descriptors and bounded waits, never full content. The checkpoint lookup
interface remains `_completed_checkpoint(record, step_id, authorize,
visited=None, result_service=...)`; pass the initialized result service when
receipt-backed recovery is needed. Admission and reads must use this verified
lookup, including chained reuse, rather than inferring a reference from a
run summary or guessing a digest.

### Scheduler and headless integration API

Implemented in version: **0.261.127** (Refs #1509). These are callable integration
boundaries, not an instruction to enable new-plan admission. External Gather
availability is separately gated on its complete authorization/capture bindings.

Render metadata is versioned. Use
`get_capability("render_file", contract_version=2)` and
`resolve_available_capabilities(..., contract_version=2,
request_context={"rendering_service": service}, export_catalog=...)`.
`service` must be the initialized `OrchestrationRenderingService`, not a Boolean,
dictionary or factory. The default v1 catalog intentionally omits Render.
`normalize_plan` and `plan_request` accept `contract_version=2`, authorized
`existing_results`, `composition_profiles` and `export_catalog`; validation and
edits preserve the saved contract and recheck the same format/profile admission.
An explicitly empty export catalog admits no files.

The executor uses `context.rendering_service`, sharing the exact initialized
`context.result_service`, and its default versioned dispatch. Do not add Render
to or force the legacy adapter table. Non-Render adapter selection delegates to
the shared `get_adapter(name, contract_version=2)`, which resolves composition
lazily and excludes legacy terminal `respond`. Render stays an executor-owned
extension. A Render step binds one complete named
`source`, declares `outputs: []`, and returns file `outputs`/artifacts or a
compact wait, never a fabricated typed data `TaskResult`.

The scheduler-facing ownership and reconciliation functions are in
`functions_orchestration_continuation.py`:

| Callable | Contract |
| --- | --- |
| `claim_run_continuation(run_id, user_id, conversation_id, *, authorize, message_container, mode="execute")` | Returns `None` for live, no-longer-eligible or CAS-losing work; otherwise returns `(fresh_private_record, actual_ExecutionLease)`. The lease is not started by this call. |
| `ContinuationCheckpoints(record, context, settings, lease)` | Restores exact retained checkpoints, receipts and native/result waits under the current claimed execution. It is the four-argument factory accepted by the headless runner. |
| `bind_orchestration_result_store(record, *, store, lease)` | Returns the initialized execution-scoped store view bound to the actual token and `lease.read`. Install the returned view, not the original store. `bind_continuation_result_store` remains a compatibility alias. |
| `reconcile_run_checkpoints(record, *, lease)` | Guardedly persists verified manifest-backed step/task/pending state after a lost run-row acknowledgement. It does not execute a producer. |
| `reconcile_run_outputs(record, *, services, lease)` | Calls checkpoint reconciliation, validates actual file producers and current visibility, updates Render progress and eligible completion checkpoints, and returns the guarded-persisted aggregate run. It performs no rendering, model invocation or native polling. |

Claim modes select the work, not a new producer attempt. `execute` admits
unfinished approved DAG/native work. `outputs` also permits an explicitly queued
file retry on a previously failed or completed parent. `delivery` permits pending
publication, including terminal runs whose `finalization_status` is `pending`;
it does not recompute their already saved outcome. Claims preserve run/attempt,
start time, deadline, approved arguments/bindings and assistant identity.
They retain the lifecycle token and rotate only the server `claim_id`.

For eligible native waits, `claim_run_continuation(..., mode="execute")`
delegates to the existing `recovery.claim_waiting_continuation(...)` claim.
That native API remains supported for direct headless consumers; the scheduler
facade does not replace it or introduce another native restore engine. Call
one claim entry point, not both. File-only, delivery and stopped-run handling
belong to the continuation facade and do not submit a replacement native job.

Start the returned lease once before output work. Continuation startup reuses
the checkpoint and publication guards through CAS and starts the existing
heartbeat. Output ownership compares both the parent token and claim epoch.
A stale or released execution-scoped result-store view cannot be reused;
ordinary committed-result reads use a fresh authorized service.

Generic retained results have a separate claim fence: binding the current
execution CAS-adopts each step lifecycle's `execution_claim_id`, even when the
lifecycle token is unchanged. Store views capture their claim independently;
rebinding a new view never retags an old producer. A cached token alone cannot
write through an unbound store once that lifecycle has an execution-claim fence.
Result and checkpoint writes include the lifecycle ETag in their transactional
batch, so a batch prepared before takeover cannot commit after adoption of the
new claim. This does not rotate a native child's lease, reconstruct its compute
context, or change its producer, attempt, job handle or input fingerprint.

`test_orchestration_result_claim_fencing.py` covers cached-token rejection and
takeover between lifecycle read and batch submission for Cosmos and Blob result
storage, preserving existing receipts and pending checkpoints. Blob payload bytes
are not themselves a completion receipt; a rejected commit cannot make those
bytes an authorized retained output.

For scheduler-driven DAG/native continuation, pass the claimed lease and
`checkpoint_factory=ContinuationCheckpoints` to
`prepare_harness_execution(record, ..., lease=lease, checkpoint_factory=...)`.
The runner starts an unstarted lease and owns its cleanup. Do not call
`prepare_retry`, `claim_plan_run` or manual-recovery `validate_resume` merely
because an existing attempt is waiting. Direct native-wait consumers may
continue using the existing `ExecutionLease`/`ExecutionCheckpoints` path.
Both paths use the same core-owned one-shot native resumer.

For a file-only tick, claim with `mode="outputs"`, start/heartbeat the lease,
perform one due output attempt or expired-output reconciliation, and call
`reconcile_run_outputs` under that same lease. Only then call
`refresh_harness_delivery(reconciled_record, *, services, settings, lease)` from
`functions_orchestration_execution.py`. The refresh publishes the same assistant
identity and closes the accepted lease. The caller releases its lease on errors
before transfer; do not release it twice.

The reconciled record has authoritative `execution_steps`, `pending_results`,
`status`, `outcome`, `failure`/`failures`, `error`, `completed_at`,
`finalization_status: "pending"` and `message_saved: false`. Its typed task
references, execution binding and original deadline are preserved. Any pending
native or unfinished non-render step keeps the run waiting even when all files
are ready. A queued manual file retry does not itself reopen the run or steps;
the existing claim/reconciliation path does that without replaying reasoning.

These boundaries are exercised by `test_orchestration_export_catalog_admission.py`,
`test_orchestration_render_waiting_runtime.py`,
`test_orchestration_render_read_failures.py`,
`test_orchestration_output_parent_claim.py` and the real tick cases in
`test_orchestration_harness_scheduler.py`. Backend/editor and HTTP consumers are
covered by `test_orchestration_v2_plan_backend.py` and
`test_orchestration_harness_routes.py`.

### Verification failures

Since **0.261.127**, v2 checkpoint verification distinguishes storage outages
from missing proof and access changes. The error is a `CheckpointError`; its
`.code` and `.failure` contain only application-owned safe text. The original
exception remains server-side in `__cause__`.

| Code | Meaning at the saved-result verification boundary |
| --- | --- |
| `checkpoint_storage_unavailable` | A checkpoint, inherited run, retained completion receipt or retained-result storage read could not complete. Keep this as an infrastructure failure eligible for a bounded retry of verification, not an access denial. |
| `checkpoint_unavailable` | Required saved proof is absent. Do not substitute the newest result or rerun its producer. |
| `checkpoint_invalid` | Saved identity, structure, digest or provenance is invalid. |
| `context_unavailable` | The conversation authorizer denied access, recovery data was deleted, or the inherited run is unavailable to the caller. |
| `recovery_changed` | Approved inputs or checkpoint lineage no longer match. |
| `ownership_lost` | The current execution no longer owns its guarded writes. |
| `result_unavailable` | Retained source access was denied, integrity or ownership validation failed, or a definite screening hold applies; no preview may replace it. |

Render authorization must translate `checkpoint_storage_unavailable` to its
storage/service-unavailable path rather than returning `False` or raising an
access-denied error. Unexpected exceptions from current-identity callbacks must
also propagate; lack of an authorization decision is not proof of denial.
Retrying verification never creates another producer, result, plan or attempt.
If whole-run retry validation encounters this outage, `prepare_retry` raises
`RecoveryError` with the same `checkpoint_storage_unavailable` code and
`status_code: 503`; it does not publish a child attempt.
V1 retains its existing error codes. `CheckpointStore` accepts an optional
`plan_contract_version` defaulting to 1; the recovery factory supplies the
record's actual contract without adding fields to persisted checkpoints.

`test_orchestration_checkpoint_error_mapping.py` covers these distinctions
using real checkpoint/recovery/result services and isolated storage faults.

Source-authority and screening-service failures are not checkpoint denials.
Since **0.261.127**, v2 dispatch, saved waits, final answer verification and
receipt/reference recovery propagate non-hold `ScreeningError` instances
unchanged. This preserves `SourceAuthorityUnavailableError` as retryable and
`SourceAuthorityUnverifiedError` or screening configuration errors as
non-retryable, without erasing pending work or discarding committed results.
The caller uses their safe `public_message`, `code` and `retryable` fields;
exception strings remain private. Known access denials and document holds
retain their existing outcomes, and legacy v1 behavior is unchanged.

Composition applies this distinction inside its adapter, before ordinary
model-error mapping. Typed directory and configuration failures use the existing
initialization-independent `OrchestrationInvocationServiceError` and
`OrchestrationInvocationCancelledError` contracts. Dispatch preserves the
original exception so the headless owner can retain its retryability or honor
cancellation, rather than recording an access denial or generic model failure.
Ordinary model timeouts, invalid content and definite access denials keep their
existing safe step-failure codes.

An invocation can fail after its immutable input checkpoint and running-step
record are already durable. Service uncertainty preserves those start facts and
any previously retained work; it does not rewind the run to its pre-invocation
snapshot, invent a completed result or run an independent model step.
`test_orchestration_composition_metadata_recovery.py` exercises actual
current-configuration SDK failures during a second composition. The complete
first result remains readable through a fresh authorized service after lease
release, with unchanged references, attempt and deadline and no final message
or file publication.

Headless owners span source decisions and model work with the existing
`strict_source_authority()` scope. V2 Gather/Reason dispatch checks that
scope's fence before entering an adapter and after it returns, so an adapter
cannot turn a caught authority failure into a terminal result or allow another
model step. Receipt lookup also checks the fence before accepting a cached
result or treating an absent result as permission to run its producer.
No second scope, persisted callback or new authorization service is
introduced. `test_orchestration_source_authority_runtime.py` covers direct and
caught failures, actual composition model boundaries, typed metadata-service
and cancellation errors, pending waits, final verification, exact recovery
boundaries, and ordinary-model/known-denial controls.

V2 run `result_outputs` is an internal retained-data availability projection;
`outputs` is reserved for actual public file outcomes. A prepared retry clears
both projections so an unstarted child cannot inherit a parent's delivery
claims. File cards and current file states are read from the initialized
rendering service, not reconstructed from a typed result reference.

An initial Render invocation can admit or commit its output before an
acknowledgement read fails. If the renderer returns a retryable wait with a
canonical admitted output ID but withholds the public DTO, the executor retains
that compact wait and `output_error`; it does not turn the missing DTO into
`result_invalid` or fabricate a `TaskResult`. The wait contains no artifact or
completion claim. Later reads reauthorize the original output, and a committed
file resumes without another model call, render or upload. An empty output list
without a valid retryable wait still fails validation.

Saved Render reads use `list_public_outputs(run_id)` after verifying the original
producer, source binding, approved arguments and deadline. A completed file can
be currently unavailable without changing its immutable commit. Genuine source
denial or a screening hold retains its safe requested-file metadata, clears
links and counts, and leaves accessible siblings visible. Restoring access
reopens the same committed file without rendering or generating content again.
Storage/network failures, screening-service or authority-configuration failures,
and missing required source readers propagate instead of becoming denied-file
placeholders. The saved-step checkpoint and pending wait remain recoverable;
observing a read failure does not spend another output attempt. Coverage is in
`test_orchestration_render_read_failures.py`, implemented in **0.261.127**.

Focused coverage is in `test_orchestration_waiting_continuation.py` and
`test_orchestration_native_waiting_continuation.py`: duplicate and racing claims,
expired-owner fencing, guard reuse/revocation, partial fencing failure,
cancellation races, fixed deadlines, child-attempt restoration, and actual
native pending-to-complete resumption without another job or model request.
`test_orchestration_render_waiting_runtime.py` uses real rendering and artifact
services to cover pending reads, scheduler-owned retry, unchanged retained
content, completed-checkpoint reopening, changed-identity rejection and
multiple file waits. A later sibling checkpoint cannot resurrect an already
completed file.

Since **0.261.127**, the continuation owner can call
`resume_native_dependency_step(step, context, settings=..., user_id=...,
input_fingerprint=..., emit=None, cancel_requested=None)`. Restore the original
pending `TaskResult`, wait descriptor and source snapshots from the guarded
checkpoint, then inject initialized services, the actual owning guard and
`native_bridge_for_step`. The required fingerprint is the original checkpoint's
`input_fingerprint`, not a browser value or a fresh guess.

This entrypoint compares current declared inputs with that saved fingerprint,
rechecks capability admission, ownership, source access and the attempt
deadline, and opens the existing native handle once. It neither selects a
model nor builds or submits another native request. Full readers are retained
before a completed result is returned; changed sources, lost access, stale
guards and incomplete results fail closed.

The entrypoint returns a typed `StepResult` for a verified native outcome; it
does not mutate the caller's pending task map or commit orchestration
checkpoints/run status.
The continuation owner must install/checkpoint that result under the existing
lease, then allow dependency execution to continue. Pending remains pending.
This is not automatic scheduler admission or a new background worker.

Native operational failures raise instead of becoming failed-step or denied-source
outcomes. Both the producer bridge and the v2 executor's dispatch/saved-wait
boundaries use the same
`raise_native_orchestration_infrastructure_failure(error)` classifier.
Recognized database, network, checkpoint and retained-storage outages, including
explicit authorization wrappers, preserve a retryable `OutputStorageError`.
Typed authority, configuration and cancellation signals retain their existing
contracts. Genuine denial, holds, missing data, invalid calculations, integrity
failures and lost ownership keep their safe native failure diagnostics.

For already waiting work, an operational exception leaves the original pending
`TaskResult`, native handle, producer, lifecycle token and deadline intact.
Acquiring a continuation legitimately marks the run `running`; preserving the
wait checkpoint does not mean rolling back that claim or inventing a successful
poll. After the owner releases the lease, another authorized same-attempt refresh
can open the original job. Initial retention failures do not invent a wait or
authorize resubmission when no wait was saved.

`test_orchestration_native_infrastructure_runtime.py` covers real foreground
retention failures and durable pending-poll/ready-retention recovery with direct
and wrapped I/O faults. Recovery completes the original job, reopens all retained
rows and creates no additional job, model call or file publication. Required
source-reader configuration errors also leave saved waiting work intact.
Actual scheduler ticks preserve the wait on transport failure and finish it
after recovery, with native request construction and resubmission entrypoints
forbidden throughout the refresh.

If a private complete or partial result committed before its completion
checkpoint was saved, recovery opens the guarded input checkpoint and calls
`recover_task_result(producer=..., input_fingerprint=...)` with its original
identity. The facade verifies the exact receipt, current ownership/access,
screening and the full retained output contents. Recovery reconstructs a
reference-only completion payload without invoking an adapter or model.
The active attempt commits that payload through its existing lease; child and
chained retries retain the original producer and explicitly authorized aliases.
Partial results remain partial. Missing historical usage is not reconstructed
from a replacement model call.

`validate_resume` uses the initialized service on its context. A read-only
route projection can use
`reconcile_checkpoints(record, authorize, result_service=results)` to recognize
the same receipt-backed completion; omitting that service cannot resolve an
uncertain producer. Neither function publishes files or creates a scheduler.
Already saved completion checkpoints also remain reconcilable when their
later run-row update was lost.

The optional `RunContext.export_catalog` is live server admission metadata, not
checkpoint state or a saved permission grant. Rebind the currently admitted
catalog before resuming. An explicit empty catalog admits no file representation;
`None` retains the shared-catalog behavior of existing direct callers.
`validate_resume` refuses a now-excluded planned format/profile with
`context_unavailable`, before restoring its work. Dependency execution and the
read-only saved-Render bridge also recheck the exact pair without invoking a
producer or selecting a replacement format. Focused continuation and no-replay
coverage is in `test_orchestration_export_catalog_admission.py`.

Missing input checkpoints or missing exact receipts on interrupted work still
block replay with `result_commit_unconfirmed`. Corruption, changed inputs,
lost authorization and removed lifecycle state fail explicitly, never as a
missing receipt or an empty success. The runtime does not scan for a plausible
result, guess its digest, or repeat uncertain work. Native pending waits still
require their separate same-attempt continuation; a content receipt is not a
replacement for native wait ownership or final file-publication readiness.

## Attempts and concurrency

Retry preparation is idempotent. Repeating the same submission after a lost
response returns the saved attempt rather than creating another one. Conditional
writes prevent two tabs from preparing competing retries of the same attempt.

Execution ownership is renewed while work is running. Recovery cannot take over
a live execution, and an expired worker cannot publish a competing result into a
replacement attempt. A browser disconnect alone is not evidence that ownership
expired.

Terminal messages have a deterministic per-attempt identity. If a message write
commits but its acknowledgement is lost, publication is reconciled against the
saved message and its guard before reporting a storage failure. This avoids
blocking an otherwise valid retry merely because the write response was lost.

These safeguards do not promise exactly-once execution in an external service.
Already submitted remote work may continue after a local timeout or Stop, which
is why uncertain agent/action retries require confirmation.

## API and file structure

All endpoints use the existing authenticated orchestration Blueprint and check
ownership. A caller cannot submit a replacement plan or checkpoint payload.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v2/orchestration/runs/<run_id>` | Read a saved plan, outcome, and safe recovery eligibility without approving or starting work. |
| `GET /api/v2/orchestration/runs/<run_id>/steps` | Read step status, failure, and reused-result information, not private checkpoint contents. |
| `POST /api/v2/orchestration/runs/<run_id>/retry` | Prepare one linked attempt using a submission ID, expected recovery version, and any required external-effect confirmation. |
| `POST /api/v2/orchestration/run` | Execute the saved attempt after the user's explicit retry action. |
| `POST /api/v2/orchestration/cancel/<run_id>` | Request server-side cancellation. |

Retry preparation accepts `conversation_id`, a stable `submission_id`,
`expected_version` from the current recovery detail, and
`confirm_external_effects`. The server derives the executable plan and
checkpoint set; these fields cannot replace step arguments or broaden access.
Executing the prepared child omits `edits` and uses the new child's returned
`plan.edit_version` as `expected_version` when present. Do not substitute the
source plan's version or the recovery token used during preparation. The normal
conditional execution claim still prevents stale or duplicate approvals.

Execution terminal events and saved assistant metadata retain the run, turn,
attempt, outcome, safe failure, and recovery information. A completed answer
message does not erase a partial or failed execution outcome.

Modern terminal run projections also expose `finalization_status`: `pending`
while publication is in progress, `saved` after confirmed persistence, `failed`
after an explicit persistence failure, or `interrupted` when a worker expired
without confirmed publication. `message_saved` is a boolean only when the result
is known. Clients must not stop reconciling merely because the execution
`status` is terminal while finalization is still pending.

| File | Responsibility |
| --- | --- |
| `functions_orchestration_schema.py` | Shared step results and failure information. |
| `functions_orchestration_executor.py` | Execution reasons, checkpoint restore, dependency order, and final reporting. |
| `functions_orchestration_checkpoints.py` | Private checkpoint payloads, manifests, and integrity checks. |
| `functions_orchestration_recovery.py` | Attempt ownership, conditional recovery, and replay-safety decisions. |
| `functions_orchestration_result_runtime.py` | Named reader resolution, typed checkpoint codecs and exact cross-attempt aliases. |
| `functions_orchestration_composition.py` | One-call content preparation over full authorized retained inputs. |
| `route_backend_orchestration.py` | Retry API, safe projections, and persistent assistant messages. |
| `orchestrationController.ts` and `orchestrationStore.ts` | Live and restored recovery state in the V2 interface. |

## Coverage and limitations

`functional_tests/test_orchestration_checkpoint_recovery.py` exercises measured
timeouts, explicit Stop, safe error content, model-independent failure reporting,
completed-step reuse, checkpoint integrity, storage failures, concurrent retry
claims, chained worker interruptions, lost message-write acknowledgements, and
current authorization. The existing executor and run-hydration
regressions continue to protect ordering and browser projection boundaries.

`ui_tests/test_v2_orchestration_recovery.py` uses the existing Playwright harness
for visible failures, confirmation, retry, reused results, and restored history.
It also covers terminal publication still in progress after a disconnect or
reload, including confirmation of the final saved message without another click.
`ui_tests/test_v2_orchestration_recovery_backend.py` forwards real component
requests through the Flask routes using
`functional_tests/test_support/orchestration_recovery.py`. It covers checkpoint
reuse and visible failures when answer-message storage is unavailable. Service
boundaries are deterministic; tests do not depend on an unavailable production
integration.

The v2 runtime, planner and recovery suites use the real compiler, composition,
result facade/readers, private store, leases and checkpoints with isolated
external I/O. They cover interleaved dependencies, multiple outputs,
source-free structures, full collections, partial/pending/failure truth, denied
file publication, independent fingerprints, restart, current access, and
receipt-backed recovery and blocking replay when exact proof is unavailable.
`test_orchestration_dependency_commit_recovery.py` covers both private Cosmos
and blob storage, commit/checkpoint and lost-acknowledgment windows, same-attempt
and chained reuse, partial completeness, access changes, corrupt receipts,
original producer identities and source-set fingerprint propagation.
`test_orchestration_native_checkpoint_receipts.py` compares actual durable input
and completion checkpoints with committed native completion receipts and full
recovered results under the real owning lease. It covers inline and same-attempt
resumed query/transform work, including a still-pending refresh with no receipt,
unchanged producer/deadline/lifecycle token, and no producer resubmission.
Run them without provider
credentials:

```powershell
python -m pytest -q .\functional_tests\test_orchestration_dependency_runtime.py .\functional_tests\test_orchestration_dependency_planner.py .\functional_tests\test_orchestration_dependency_recovery.py .\functional_tests\test_orchestration_dependency_commit_recovery.py .\functional_tests\test_orchestration_dependency_imports.py
```

Checkpoints add storage writes proportional to completed output size. Large
results are chunked rather than silently truncated. Reuse avoids repeating
completed model/tool work, but each retry can incur costs for its newly executed
steps.

Older runs without full checkpoints cannot be retroactively resumed. Their
history remains readable, and the interface explains why a new plan is required.
There is no automatic full-plan fallback, internal agent tool-call continuation,
or guarantee that remote effects can be undone.

## Related

- [Chat orchestration](CHAT_ORCHESTRATION.md)
- [Error communication fix](../fixes/ORCHESTRATION_ERROR_COMMUNICATION_FIX.md)
- [Review, edit, and recover plans](../../guides/review-and-edit-orchestration-plans.md)
- [Orchestration settings](../../admin/orchestration.md)
