# Durable orchestration file outputs

**Implemented in version: 0.261.127**

**Application version owner:** `application/single_app/config.py`

**Issue:** microsoft/simplechat#1509

## Purpose and scope

An explicitly requested file is an independent output of approved orchestration
work. Its input is a complete, authorized retained result, not a preview,
assistant summary, guessed blob path, or a new analysis call. A failed file can
be retried without recreating successful sibling files or rerunning their
reasoning.

This document describes the M6/M7 **service layer**, not an enabled deployment.
The orchestration owner must connect the services to its capability registry,
runtime, authenticated routes, existing scheduler, and output UI. Those
connections are separate from these services. See
[the rendering harness design](ORCHESTRATION_RENDERING_HARNESS.md) for the wider
Gather/Reason/Render contract.

Dependencies are the retained-result contracts/readers, shared generated-file
facade and format catalog, existing generated-chat-artifact transport, and
initialized Cosmos runs and messages containers. There is no new Azure
resource, deployment service, settings owner, model invocation, or artifact-set
transaction.

## Durable identity and ownership

The output ID hashes:

- The original approved work ID and requesting actor/conversation/step/contract.
- The requested safe filename.
- The complete immutable source-reference digest, including its result and
  manifest fingerprints.
- The normalized render specification, profile, renderer version, source policy,
  and admitted serialization bounds.

The current render producer's full identity, run, attempt index, source
`ResultRef`, deadline, byte intents, and lease remain private server records.
Replacing the source, projection, filename, profile, or renderer version creates
a different output identity. A different run attempt cannot adopt the original
producer's admission by merely presenting its work ID.

Safe requested filenames retain any extension explicitly declared by their
shared catalog entry, including `.yml`, `.markdown`, and `.text`. The rendering
specification and committed MIME type still use the canonical format; aliases
do not silently rename files or select a different serializer. Unrelated suffixes
are rejected before output admission. Only bound orchestration artifacts use this
catalog-derived upload allowlist; existing standalone/native/workflow upload
extension rules are unchanged.

Private retained-output downloads use the freshly authorized committed
descriptor's `media_type`, not operating-system filename inference. Filename
aliases and extension casing retain the canonical format's MIME type even when
host registrations are missing or misleading. Invalid committed MIME metadata
is rejected rather than inferred or silently replaced. Active workspace
representations and existing native/workflow MIME inference are unchanged.

Records use `record_type="orchestration_output_v1"` in the **existing runs
container**, partitioned by conversation. The parent run retains
`render_output_ids`; an output missing behind that admission is not recreated.
Deletion leaves a tombstone. There are at most 32 requested outputs per run.

The first version is original-owner, same-conversation only. It does not grant
shared-conversation participants a new private-result audience. Existing native
and workflow file behavior, including shared-file approval rules, remains
separate.

## Individual publication protocol

1. Resolve a named input through the server-owned result service. An opaque
   browser value is not a `ResultRef` or an authorization decision.
2. Persist admission of the first automatic attempt before rendering. Claim a
   bounded output lease; bind the current parent execution lease when present.
3. Open the complete retained source and use the shared
   `build_generated_file_export` facade. The selected serializer validates its
   structure and format-specific contract. The lifecycle verifies the returned
   format/profile, full size and SHA-256, exact record/character counts, and the
   source's `require_complete_consumption()` receipt.
4. Persist an immutable byte intent before transport. It includes a deterministic
   per-intent idempotency key and private artifact address.
5. Upload bytes and create an immutable file message privately. Reauthorize
   ownership, sources, screening, capability, deadline, and lease throughout.
6. Verify the staged message and complete blob, then reauthorize again. A
   same-partition conditional batch compares the parent run and output ETags
   and commits **one output's** exact intent.

The output row's `state="completed"` and `committed_intent` are the only
visibility authority. A message's existence, a successful upload response,
browser event, or native tabular manifest is not that authority. No transaction
spans all requested files.

Byte intents include the attempt number. If an uncommitted render is genuinely
lost, a subsequent attempt has a different private staging address while the
logical output ID remains unchanged. Only one intent can become visible. A
late write to an abandoned intent cannot replace committed bytes.

Successful outputs are immutable. Stop preserves already committed siblings;
explicit output deletion withdraws that output. Source deletion, screening,
ownership changes, superseded work, and deleted result/run records still deny
downloads and history even when a previous commit exists.
When an attempt reuses earlier staged bytes, the byte intent keeps its original
render-attempt binding, while the output separately records the committing
attempt. Earlier failed automatic attempts remain failed in the audit history.

## Retry and crash recovery

There are exactly **three admitted automatic attempts**: the initial attempt and
at most two automatic retries. Counts include durable admissions, so an attempt
can appear as admitted while waiting for its worker. Reloading, duplicate calls,
polling, and process replacement do not reset them.

Transient transport/storage failures, typed current-source authority or screening outages,
and explicitly retryable renderer I/O failures use bounded exponential backoff
with jitter. Safe numeric service
retry guidance up to 300 seconds is honored, subject to the original deadline.
Access denial, screening holds, partial/invalid results, unsupported
formats/profiles/options, deterministic layout/schema errors, cancellation,
deletion, and supersession do not automatically retry unchanged.
`SourceAuthorityUnavailableError` uses the same bounded retry cycle;
`SourceAuthorityUnverifiedError` indicates a non-transient authority problem
and does not automatically retry. Public output and history reads propagate
both typed failures instead of presenting them as source denial or stale success.

Current directory/token failures preserve `ExternalIdentityServiceError.code`
and its declared retryability. Throttling, timeouts, incomplete responses and
temporary service failures use the same three-attempt automatic budget.
Malformed responses, pagination/size limits and invalid authority callbacks
are nonretryable and return no authorized data. Neither category is proof of
revoked access. Only actual `ResultUnavailableError` denial or
`DocumentHeldError` screening holds are treated as such; other screening
exceptions remain configuration/service failures. Failure progress retains
durable admission/retry facts but withholds rendered counts and artifact IDs
when current authority could not be verified.

Current external configuration reads likewise preserve the separate
`ExternalConfigurationServiceError` type. Codes
`external_configuration_service_unavailable`, `external_configuration_timeout`
and `external_configuration_throttled` share the existing three-attempt file
budget. `external_configuration_metadata_invalid` and
`external_configuration_limit_exceeded` are nonretryable verification failures,
not revoked access. `ExternalConfigurationCancelledError` remains cancellation,
including before file admission and during read-only restoration.

These concrete error families are recognized lazily, only after a matching
exception has been raised. Explicit wrapped causes retain their original
type/code/retryability; an unrelated exception's code string or an earlier
implicit exception context is not authority. Ordinary cold imports and error
handling do not import configuration readers, settings, clients or telemetry.

Output/card/history reads and artifact-factory boundaries propagate current
identity/configuration uncertainty rather than returning cached success or
dropping a source.
The render adapter also withholds saved output/artifact projections when a
subsequent authority check fails. Observing a failed file, a busy writer or a
future retry cannot spend an admission, bypass persisted backoff, or reset the
automatic budget. Lost-lease observations reauthorize current state before
reporting another worker's completion.

After an eligible exhausted cycle, `manual_retry(output_id, request_id)` admits
one separately journaled manual attempt. It **queues**, rather than executes,
that attempt. Repeating the same request ID returns the same admission. A
manual failure never restarts automatic retries. At most 16 distinct manual
admissions are retained per output.

Before replaying transport, reconciliation checks the authoritative commit and
the existing byte intent. A newly admitted attempt can finish a blob-only
upload's missing message or commit existing staged bytes without rerendering.
Failure handling performs read-only transport reconciliation; it does not
silently replay a failed message write. A lost commit acknowledgment is success
only after the exact durable marker is read. If that authoritative read also
fails, the attempt remains recoverable; the service does not assume the upload
failed and spend another attempt.

An expired worker cannot resume writing under its old admission. If no commit
exists, recovery closes that attempt before scheduling the next eligible
attempt, retaining any verified bytes for reuse. This also bounds repeated
worker crashes and persistent message/manifest failures to three automatic
admissions. Read-only reconciliation never becomes an unrecorded fourth
automatic attempt. Output lease tokens, the parent execution token and claim
ID, ETags, stopped/deleted run state, and the approved persistent deadline
fence stale workers.

The parent producer token remains stable across same-attempt continuation, but
its `claim_id` rotates. An output lease privately pins both values; an old
worker cannot renew, stage, commit or advance retry state under a successor
claim. Initial parent leases without a claim ID remain token-fenced. A
parentless output claim also pins the last durable
`continuation_submission.claim_id`, so a parent acquiring and then releasing
its lease cannot make the old output owner valid again. The output's existing
lease still prevents a competing output worker until expiry; bounded
reconciliation can then recover verified staged bytes without duplicating
visibility. Committed files do not depend on a current rendering lease.

Cancelled, deterministically failed, and obsolete intents have bounded cleanup
work. Cleanup is authorized separately from source reading, so an original
owner can remove inaccessible staged bytes without acquiring permission to
read them. A grace period covers the previous lease before cleanup is marked
finished. Retain run/output tombstones until the owning deletion process has
finished this cleanup.

### Cleanup after conversation deletion

Normal rendering factories correctly reject a missing/deleted conversation.
The separate `OrchestrationOutputCleanupService` is a deletion-only boundary,
not a permissive replacement for those factories. An extant conversation
tombstone must still match the original owner. A genuine Cosmos 404 is **not**
deletion authority by itself: the retained parent run must have
`checkpoints_deleted=true`, and its actual `checkpoint:lifecycle` row must be
irreversibly deleted with `token=null`. Cleanup verifies the guard's record
type, checkpoint schema version, original actor, conversation, run, and turn.
The run's `render_output_ids` admission and the immutable output/intent binding
must also match. Cleanup pins the guard's canonical body digest and rechecks it
before destructive operations. An absent reader, missing guard, or changed
proof never becomes a synthetic conversation or a successful cleanup.

Logical deletion hides ordinary reads immediately. The conversation may be
physically removed after the retained run deletion fence is durable; it need not
stay live while late writers settle. Keep run, output, and lifecycle guard
records through cleanup and late-writer reconciliation. This service does not
purge those fences or recreate missing records.

Confirmed owner-scope deletion tombstones an uncommitted output in a run/output
ETag-fenced batch, preserving admission counts and completed-attempt history.
`cleanup(output_id)` never implicitly withdraws a committed output, even when
the conversation is gone. The owner must explicitly call
`tombstone(output_id)` for each committed output actually being deleted.
Other committed siblings and their current intents are untouched.
Cleanup waits for the previous output lease's grace period. Each destructive
operation rechecks current retained ownership and the intent; addresses are
recomputed with the same validator used by upload. Blob-only remnants and
already-deleted objects are handled idempotently, and message deletion compares
its ETag. Storage failures do not imply deletion or successful cleanup.

Each transport write first records a private claim-bound staging guard. A late
upload acknowledgment can requeue cleanup for its exact retained intent after
the old lease or an earlier cleanup pass, without changing output state,
visibility, admission counts, or another worker's lease. Cleanup completion
compares the observed cleanup generation so it cannot erase a concurrent
late-I/O notification. These notifications grant no read or delete access;
the cleanup service still independently verifies deletion authority.

No retained result, source ACL, screening provider, model, normal artifact
factory, or live conversation authorization is called on this path. A committed
intent without an explicit output tombstone is never obsolete staging. A
changed owner, missing run/admission/output/guard record, or forged path fails
closed. Do not purge lifecycle fences while recorded writers can still finish;
a cleanup result is not permission to discard late-writer authority.

## Service integration

### Initialized handles and callbacks

`functions_orchestration_output_store.py` provides:

```python
store = OrchestrationOutputStore(
    runs_container,
    user_id=actor_id,
    conversation_id=conversation_id,
    read_conversation=read_current_conversation,
    # Optional: clock=utc_now, lease_seconds=120.
)
```

`runs_container` must support point reads and transactional item batches.
`read_current_conversation(conversation_id)` must return the current server
record, including its actual owner and deletion state. The store uses raw
container ETags, not stripped public run records.

`functions_orchestration_artifacts.py` provides:

```python
transport = OrchestrationArtifactTransport(
    upload=upload_generated_file_artifact_stream_for_user,
    read_message=read_message_by_conversation_and_id,
    open_stream=open_generated_chat_artifact_stream,
    delete=delete_staged_orchestration_chat_artifact_for_user,
    blob_container=private_chat_container_name,
)
```

`read_message(conversation_id, message_id)` is a point read from the initialized
messages container. The other callbacks are the real operations from
`functions_simplechat_operations.py`; they are not recreated by the service.
Only complete, explicit retained TXT/MD can have zero bytes. Legacy callers
retain their empty-file rejection.

`functions_orchestration_rendering.py` provides:

```python
service = OrchestrationRenderingService(
    store,
    authorized_result_service,
    transport,
    authorize_execution=authorize_current_output_execution,
    max_output_bytes=approved_byte_limit,
    # Optional: limits, office_limits, image_resolver, renderer, jitter.
)
```

`authorize_current_output_execution(record, operation=...)` is mandatory. It
must revalidate current capability availability and the server-approved
render/source admission. It raises a typed denial or returns `False` on denial.
Operations are `admit`, `render`, `prepare`, `commit`, `retry`, `read`, and
`publication`. It must not trust route/model-supplied actor IDs, paths, source
manifests, or settings. The result service independently rechecks current source
ACLs and screening.

Register `configure_orchestration_artifact_service(factory)` in the owning web
and scheduler bootstrap. `factory(user_id, conversation_id)` rebuilds an
actor-scoped service from initialized handles and current server state. An
unregistered factory fails closed; the lower-level modules never import
configuration or silently create clients.

### Deletion-only composition root

The application root exposes
`functions_orchestration_bootstrap.build_orchestration_cleanup_service(user_id, conversation_id)`.
It does not call `read_owned_conversation`, the normal rendering factory, or
the model/identity bootstrap before constructing the cleanup service:

```python
cleanup_store = OrchestrationOutputStore(
    runs_container,
    user_id=actor_id,
    conversation_id=conversation_id,
    read_conversation=lambda cid: conversations_container.read_item(
        item=cid, partition_key=cid,
    ),
    read_run_tombstone=lambda run_id: run_steps_container.read_item(
        item="checkpoint:lifecycle", partition_key=run_id,
    ),
)
cleanup = OrchestrationOutputCleanupService(
    cleanup_store,
    messages_container,
    initialized_private_blob_service,
    blob_container=private_chat_container_name,
)
result = cleanup.cleanup(output_id)
```

Both readers must return actual persisted records with their Cosmos metadata.
They must not catch storage failures, fabricate records, or replace failed reads
with `None`. The missing-conversation path requires the existing checkpoint
schema version 1 lifecycle guard and the matching version on its parent run.
No new Azure resource or higher-level checkpoint owner is initialized here.

For an explicitly deleted committed output, call `cleanup.tombstone(output_id)`
before `cleanup.cleanup(output_id)`. Tombstoning is also guarded by current
owner-deletion proof; it cannot withdraw a live successful output arbitrarily.
Normal staging cleanup needs no explicit committed-output withdrawal.

Conversation deletion must schedule this work from each owned v2 run's
`render_output_ids`, not from cached file cards or a message scan. A completed
output normally has `cleanup_pending=false`, so deleting its conversation alone
does not make it a scheduler candidate. After logical deletion and durable
run/checkpoint fencing, explicitly tombstone every admitted output selected for
deletion before purging the conversation. Missing or inconsistent admission
proof and failed fencing must stop that purge; they are not an empty success.
This scheduling step performs no Blob I/O. The scheduler handles the retained
intents after their lease grace, including Blob-only uploads with no message.
The parent deletion CAS must also durably record unfinished output enrollment,
including its retention decision. A later source-cleanup failure or a lost
acknowledgment before the first output tombstone must not strand completed
files outside the output scan. Bounded scheduler recovery must replay that
authoritative admission index without live conversation/source authorization,
and clear enrollment only after the intended per-output fences are durable.
An ordinary synchronous callback after the parent fence is not sufficient.
Establish the real, irreversible `checkpoint:lifecycle` deletion guard before
that parent CAS. If the write commits but its acknowledgment is lost, the pending
enrollment must already have genuine guard proof for missing-conversation replay.
A fabricated guard or one written only after the acknowledgment cannot provide
that crash boundary.

The enrollment contract is separate from file visibility:

```python
intent = build_output_cleanup_intent(owned_run, retain_committed=archiving_enabled)
# Include this field in the same parent CAS that sets checkpoints_deleted.
parent_updates["output_cleanup"] = intent
```

`build_output_cleanup_intent` is a pure helper in
`functions_orchestration_output_store`. Its version 1 intent contains `state`
(`pending` or `completed`), the frozen `output_ids`, and the boolean
`retain_committed` decision. It rejects changed admission indexes or retention
policy on retries. No-admission runs start with completed enrollment.

`enumerate_output_cleanup_enrollments(runs_container, limit=64)` finds bounded
private `{user_id, conversation_id, run_id}` selectors independently of due
output rows. Limits must be integers from 1 through 200. Both this selector and
`enumerate_due_outputs` consume at most `limit` provider rows, without advancing
the iterator once more to discover that the budget is exhausted. The scheduler builds
the existing deletion-only service for each selector and calls
`cleanup.enroll_run_cleanup(run_id)`, including during cleanup-only ticks with
normal run execution disabled. This method checks real retained ownership and
deletion proof, fences each output independently, and only then CAS-marks the
parent intent completed. Partial enrollment, failed writes and uncertain
acknowledgments remain recoverable. A copied index cannot withdraw another
run's valid output. Missing-conversation proof is pinned during enrollment,
and each file CAS also checks the current frozen intent.

Enrollment returns only `run_id`, `enrollment_status`, `output_count`, and
`retain_committed`. Completed enrollment means per-file cleanup is scheduled,
not that bytes have already been deleted. Ordinary due-output cleanup handles
lease grace, conditional message deletion and late-writer notifications.
The conversation-deletion lifecycle must synchronously finish this enrollment
before source-payload cleanup or caller message/conversation purges. A missing
enrollment dependency for nonempty v2 admissions, a missing admitted output, or
either failed fence must fail deletion rather than report empty or successful
cleanup. Keep the durable intent available for scheduler replay after interrupted
parent or per-output acknowledgments. A subsequent source-cleanup failure must
not prevent already-enrolled outputs from progressing independently.

Keep retained-output files out of legacy Blob sweeps and unconditional message
deletion. Their guarded cleanup must verify the deterministic descriptor,
current retained intent and conditional message ETag. Archive retention is a
separate, explicit decision; do not withdraw an otherwise retained committed
file merely to make a cleanup selector return it. Ordinary upload, native and
workflow deletion policies do not change.

Initialized resources remain owned by the application; this service creates no
clients. Its minimal result is
`output_id`, `state`, `cleanup_status` (`complete` or `deferred`),
`cleanup_pending`, and `processed_intents`. It contains no source data or paths.
CAS/message conflicts raise `OutputConflictError`; ownership/binding failures
raise `OutputUnavailableError`; storage faults raise `OutputStorageError`.

In a bounded scheduler tick, call `reconcile` once for a selected expired
`rendering` output and stop processing that output for the tick. Call
`render_attempt` once for due `waiting`/`retry_scheduled` work. Terminal
cleanup-only selections use this deletion-only service, not model execution or
a fabricated live rendering context.

### Execution, status, and scheduler APIs

| API | Result and purpose |
|---|---|
| `ensure_output(producer=..., source_ref=..., export_request=..., file_name=..., approved_work_id=..., deadline_at=..., require_current_sources=True)` | Persist/reuse one admission; return the public projection. `deadline_at` is an aware ISO timestamp and cannot be extended by duplicate admission. |
| `render_attempt(output_id, claim=None, worker_id=None)` | Execute at most one admitted attempt or recover prior staged bytes. Return the public projection. A live competing worker is observed, not duplicated. |
| `read(output_id)` | Reauthorize and return one public projection. |
| `list_public_outputs(run_id)` | Reauthorize each output independently; preserve accessible siblings and return safe unavailable placeholders for individually denied sources. Infrastructure failures propagate. |
| `claim_due(output_id, worker_id=None)` | Return a private `OutputClaim`, or `None`; no admission-count reset. |
| `reconcile(output_id, worker_id=None)` | Verify/repair uncertain publication or perform permitted cleanup. Never invokes a producer. |
| `manual_retry(output_id, request_id)` | Reconcile first, then idempotently queue one manual attempt. |
| `cancel(output_id, deleted=False)` | Fence unfinished output, or explicitly tombstone a completed output when `deleted=True`; clean permitted staging. |
| `committed_artifacts(run_id)` | Use the same current per-file authorization as `list_public_outputs`; produce server-owned cards only for available committed records, preserving accessible siblings. |
| `open_download(output_id)` | Context-managed verified private stream with repeated access checks. |
| `enumerate_due_outputs(runs_container, now=None, limit=64)` | Private scheduler selectors: `output_id`, `user_id`, `conversation_id`, `run_id`. Maximum batch size is 200. |

The existing scheduler acquires the current run-level execution lease before
claiming output work, reconstructs the service for each selector, then calls
`render_attempt` or `reconcile` as appropriate. Keep the parent lease heartbeat
active until the output attempt finishes or schedules its next wait and releases
its output lease. A worker never adopts a replaced parent lease. Continuation
preserves the original producer run/attempt and approved persistent deadline.
The pure store's support for an absent parent lease is for injected/test owners,
not a substitute for production scheduler ownership.

The optional injected `execute_render_file` adapter calls the real shared
`build_step_result` factory without importing the executor or adapters. It takes
`service_factory`, `resolve_inputs`, `build_step_result`, `build_failure`,
`settings`, and `user_id`. It expects a v2 context, exactly one resolved retained
reader, and arguments `file_name`, `output_format`, `profile`, and optional
`options` (`columns`, `title`, `sheet_name`). A pending output becomes a
`waiting` StepResult, never a success carrying failure-shaped data. Completed
artifacts alone are attached to a successful StepResult.

### Observation-only Render resumption

Restored output waits use the additive owner callback:

```python
resume_render_file(
    step, context, pending_result,
    service_factory=rendering_service_factory,
    resolve_inputs=resolve_inputs,
    build_step_result=build_step_result,
    build_failure=build_failure,
    settings=settings,
    user_id=user_id,
    cancel_requested=cancel_requested,
)
```

The factory has the same `(context, settings=..., user_id=...)` signature as
initial execution. The current executor's `_context_rendering_service` adapts
the initialized actor-bound `context.rendering_service` to that signature;
a `context.rendering_service_factory` attribute is not required. The helper
does not discover clients or initialize an application owner.
Render capability discovery requires both the initialized service instance and
the real callable `resume_render_file`. A missing or noncallable resumer
withholds `render_file` with `rendering_service_unavailable`; a typed service
alone cannot advertise file readiness. Authenticated export-catalog requests
therefore return `403 rendering_unavailable` when that contract is unavailable.
The saved result may be a waiting or completed
StepResult. Identity comes from `wait.kind="orchestration_output"` and its
`output_id`, or from exactly one public output in `outputs`. If both identify a
file, they must agree. Missing, malformed, conflicting or multiple identities
fail closed; artifact cards alone cannot supply the identity. Cached state,
counts, filenames and cards are not authority.

The resumer verifies the exact current producer, approved work, planned step,
requested format/profile/options/name, retained source reference and immutable
deadline. It performs one authorized observation of that output. Due retries,
live workers and expired render leases remain waiting for the scheduler:
resumption never calls `ensure_output`, `render_attempt`, `reconcile`, a retry
claim, manual admission or a model. Unlike ordinary status reads, resume
observation never persists deadline expiration: it reports
`output_deadline_exceeded` without changing the stored state, counters, lease,
retry journal, retained results or bytes. The scheduler remains the mutation
owner. Existing committed files can still be read after their rendering
deadline.
Ordinary `list_public_outputs` and `committed_artifacts` are not substitutes for
this phase: their status reads can expire a pending target or another file in
the run. The actual saved-Render runtime dispatch must satisfy the same
zero-write contract as the public resumer.

It returns the same real StepResult projection and `outputs` as execution;
only currently authorized committed descriptors can produce artifact cards.
No synthetic file TaskResult is created. Current authority or storage
uncertainty propagates a typed read failure rather than returning a replacement
StepResult. This includes nonretryable invalid metadata, required source-reader
or authorizer configuration, and explicit wrapped infrastructure causes. The
owner must preserve the existing checkpoint/wait and report a safe operational
error; inability to verify current access is neither permission to replay work
nor a terminal denial. No cached success, links or replacement uncertainty DTO
are returned. A later successful observation returns freshly authorized facts.
Genuine denial or a document hold, after verifying the exact saved binding,
returns a failed StepResult with the current safe `available=false` projection:
artifact identity, counts and retry controls are withheld. Cancellation remains
cancelled, and identity/spec/deadline disagreements remain explicit failures.
Changes to current execution limits do not create a new file identity during
observation.
The same observation path reauthorizes an already-completed file checkpoint
before its card is displayed. It works with
`context.allow_generated_files=False`: permission to perform file-creation
effects is not needed for observation, while current source access,
capabilities and publication visibility are still enforced. A completed saved
status never makes an unfinished or unavailable current output ready.

### Finalized wire projection

`public_output` formats current authoritative output facts. It does not perform authorization;
routes and history use `service.list_public_outputs(run_id)`, or strict
`service.read(output_id)` when a denial should fail that request:

| Field | Meaning |
|---|---|
| `output_id`, `step_id` | Stable file identity and requesting step. |
| `file_name`, `output_format`, `profile` | Validated public file description. |
| `state` | `waiting`, `rendering`, `retry_scheduled`, `completed`, `failed`, or `cancelled`. |
| `available` | Whether current checks allow access to this output. A completed file can be temporarily unavailable without changing its persisted completion state. |
| `attempt_count`, `automatic_attempts`, `max_automatic_attempts` | Durable admission counts; maximum automatic count is always 3. |
| `next_retry_at` | Next automatic attempt's aware ISO timestamp, otherwise `null`. |
| `can_retry` | Whether another explicit manual admission is currently eligible. |
| `error_code`, `message` | Stable safe code and fixed user-facing status text; never exception text. |
| `artifact_message_id` | Present only for a committed, currently available output; otherwise `null`. |
| `row_count`, `character_count`, `size_bytes` | Verified rendered counts when available; `null` before preparation or when source access is withheld. |

No path, container, source reference, raw manifest, lease token, settings, or
provider exception is included. Final assistant publication must use
`committed_artifacts`, not saved `run.artifacts`, model-generated links, or
staged upload responses.

If one source is revoked, held for screening, deleted, changed under the current
snapshot policy, or no longer has a readable retained result, the list preserves
the other files. The unavailable entry keeps only its safe requested-file
description, identity, persisted state, and admission counters. It sets
`available=false`, `can_retry=false`, and clears the artifact ID, retry time,
and all rendered counts. Its existing `error_code` and `message` fields contain
the current stable reason and fixed safe explanation; there is no separate
reason field. Restored access restores the committed link without rerendering
or modifying that output's successful record.

These overlays distinguish genuine `DocumentHeldError` from screening
configuration/service errors. Storage failures, network failures, missing
source-reader configuration, and unexpected callback failures propagate.
They are not reported as ordinary source denials. Owner/conversation denial
also fails the overall list rather than returning another owner's file metadata.
Orchestration file-message and card history use the same infrastructure-failure
distinction; legacy workflow history behavior remains unchanged.

Bare `PermissionError` raised while reading the output index, output row, parent
run or committed-file metadata is a backing-store fault, not a source-access
decision. Those specific metadata reads translate it to `OutputStorageError`
before public projection or delivery can invent a denial. Typed ownership,
deletion and missing-record errors remain unchanged. Source-authorization
callbacks are outside this translation, so actual source denials and screening
holds still produce unavailable-file projections; the context-free permission
classifier is not broadened.
Saved Render resumption uses the same metadata-read boundary for its initial
output record and current parent-run reads, before checking their immutable
bindings. Neither read can bypass the operational-error classification.

The actual checkpoint error `checkpoint_storage_unavailable` is operational,
including when its provider cause is absent. Known explicit checkpoint,
retained-result, and output wrappers preserve that classification as retryable
`OutputStorageError`; current output lists, file bindings, publication, history,
downloads and saved Render observation do not turn it into missing content or
access denial. Missing, invalid, denied or fenced checkpoint proof without an
operational cause keeps its existing meaning. Arbitrary provider code strings
and implicit exception context cannot grant storage retryability. Type recognition
is lazy so ordinary output bootstrap does not import checkpoint owners.

### Private source binding and visibility dispatch

`generated_artifact_source` has exactly these fields:

```text
version: 1
kind: orchestration_retained_output
producer: full server-owned ProducerIdentity dictionary
output_id
intent_id
attempt_number
source_digest
spec_digest
```

The binding contains no source path or source manifest. The source reference is
loaded privately from the matching output row. The strict validator rejects
unknown fields, versions, mixed native bindings, guessed paths, changed byte
intents, and mismatched producers.

`functions_generated_artifact_sources.py` dispatches preparation, download,
history, approval, and promotion authorization to this distinct source kind.
The existing published-artifact guard uses the output commit authority rather
than inventing a tabular run ID. History replaces unavailable/staged file
messages and cards with safe placeholders and strips private bindings from
authorized history. An inert `generated_artifact_origin` marker survives
history caching so every hydration still performs an authoritative lookup,
including after access is revoked or restored.

The headless assistant-message shape stores the lifecycle list at
`metadata.orchestration.outputs`, bound to its `run_id`, and sanctioned cards at
top-level `generated_artifacts`. History refreshes the nested list with
`list_public_outputs` through the registered actor/conversation service even when
there are no file messages or cards. Saved artifact IDs, retry controls, counts,
and availability are never initial-hydration authority. Top-level orchestration
cards are rebuilt from `committed_artifacts`; unrelated artifact kinds retain
their existing handling.

Source denial affects only that file's current projection. An unavailable
owning run/conversation clears the cached output list and orchestration cards;
storage, network, missing service configuration, and unexpected read failures
propagate instead of returning cached success. Metadata-only history reads do
not import route owners, and their screening checks restore request-local
screening state so one withheld source does not hide accessible siblings.

## Validation and limitations

`functional_tests/test_orchestration_output_lifecycle.py` exercises real
production persistence/readers, serializers, upload/open/delete functions,
source dispatch, and download route helpers with cloud-I/O doubles. It uses
the existing transactional Cosmos fixture and retained-result fixtures.
`functional_tests/test_orchestration_output_cleanup.py` adds physical and
logical conversation deletion, source-independent cleanup, honest 404 versus
outage handling, retained ownership/admission checks, deterministic paths,
conditional message deletion, and uncertain cleanup acknowledgments. It also
executes the real initialized cleanup factory with deleted conversations while
rejecting any call to the live authorization/rendering factory. Missing
conversations require a real deletion guard produced by `CheckpointStore`;
tests reject ordinary runs, mismatched or replaced guards, missing tokens and
readers, and storage outages. Real upload threads cover data arriving after
logical deletion and lease grace, and generation checks preserve late cleanup
notifications. Committed siblings require their own explicit tombstones.
Card-free assistant history independently exercises current source denial,
screening holds, logical deletion, and infrastructure errors without cached
success or replaying producers.
`functional_tests/test_orchestration_output_identity.py` verifies every current
identity-service error code at rendering, commit, artifact-factory, public
output/card and history boundaries, including explicit wrapped causes,
three-attempt exhaustion, idempotent manual recovery, observation-only polling,
real cancellation/denial/hold distinctions, and suppression of cached
completion facts after authority failure.
`functional_tests/test_orchestration_output_configuration.py` exercises the real
current metadata attestor through output admission/render/commit failures,
publication and private download checks, current/cached history, read-only
resumption, explicit wrappers and cancellation. It verifies the unchanged
automatic/manual budgets and preserves genuine denial and screening holds.
Fresh-process probes also exercise the actual configuration classes inside
`offline_app_imports`, in both import orders and normal/optimized Python.
Direct, result-wrapped, checkpoint-wrapped and nested failures must preserve
their service code, validated retryability and original exception identity at
the shared classifier and public-read failure boundary. Implicit exception
context cannot turn a genuine denial into an infrastructure retry.
`functional_tests/test_orchestration_output_checkpoint_storage.py` exercises
actual checkpoint storage reads, cause-free operational checkpoint errors,
known explicit wrapper chains, and already-translated output storage failures.
It checks all current file projections, publication, history, downloads and
saved Render boundaries without writes or cached-success fallback. Negative
cases preserve missing, invalid, denied and fenced proof semantics and reject
spoofed provider codes, implicit context and cyclic causes. Render/commit cases
retain the three-admission budget; fresh-process probes cover both import orders
and normal/optimized Python.
`functional_tests/test_orchestration_output_metadata_reads.py` separates bare
metadata-I/O permission faults from typed owner/deletion failures and genuine
source denials. Index, row, parent, message and second-read faults must propagate
without cached facts or persistent changes. The unchanged scheduler
`test_scheduler_preserves_saved_render_read_uncertainty` cases verify that actual
delivery preserves waiting/completed aggregates, files and results and returns
`message_not_saved` without final frames or replay.
`functional_tests/test_orchestration_render_resume.py` verifies observation-only
wait restoration, current committed facts, exact producer/source/request/deadline
binding, revoked or held sources, transient and malformed authority, cancellation,
completed-checkpoint reauthorization, conflicting saved identities, empty
source-free aliases and unchanged retry journals. The tests explicitly
forbid rendering, reconciliation, admission, retry claims, staging, uploads,
deletion and storage writes, and compare persistence/transport counters even on
expired deadlines and error paths. Real `RunContext` and
`_context_rendering_service` coverage uses the registry's actual producer
contract under read-only file policy. Boundary cases include equality with the
deadline, active render leases, automatic exhaustion and separately admitted
manual work.
Discovery cases also remove or replace the resumer with noncallable values and
verify that the actual service instance cannot bypass admission.
`functional_tests/test_orchestration_output_resume_runtime.py` uses the real
two-file compiler/executor setup, then compares the public resumer and actual
saved-file dispatch with identical immutable snapshots and mutation traps.
It covers both an expired requested file and a completed requested file whose
independent sibling has expired; observing either must not persist expiration.
Waiting and completed dispatch cases also wrap the real public resumer and
require exactly one call with the full saved result and owning callbacks.
Presence checks alone do not prove that the advertised resumer is executed.
Actual metadata-attestor failures cover invalid metadata and exceeded limits,
both directly and through retained-result wrappers. Even though those errors
are nonretryable, dispatch must preserve the original operational exception,
saved result, context and storage without producing an ordinary failed output.
Direct output-record and parent-run I/O faults are also checked through the
actual saved waiting/completed dispatch. Bare metadata permission failures must
raise `OutputStorageError` with their original cause, while typed domain denials
remain safe failures. Each path invokes the shared resumer exactly once.
`functional_tests/test_orchestration_output_parent_claim.py` uses real
continuation leases and checkpoint/publication guards to cover same-token
claim replacement, parentless acquire/release races, commit-CAS cutover,
unchanged heartbeat ownership and recovery of already-staged bytes. An exact
expired-parent/still-live-output case holds the output lease for 120 seconds,
replaces a 45-second parent lease after 46 seconds without changing its token,
and rejects both stale ownership and renewal. It also covers an initial parent
without a claim ID transitioning to a claimed continuation.
`functional_tests/test_orchestration_output_enrollment.py` covers the real
initialized root, independent admission-index discovery, interrupted enrollment,
uncertain completion acknowledgments, preserved committed files under explicit
archive retention, foreign/corrupt ownership, changed proof and CAS-time policy
changes. Enrollment performs no transport deletion or source access.
`functional_tests/test_orchestration_output_deletion_pipeline.py` exercises the
authenticated single and bulk conversation-delete routes, real recovery and
checkpoint fences, initialized cleanup root, due-output scan and scheduler.
Requests contain only the conversation ID, never preselected output IDs. Cases
cover completed files that were not previously due, Blob-only and message-stage
interruptions, card-free history, foreign actors, failed-fence retry, missing
admissions, unchanged ordinary uploads and uploads finishing after cleanup.
Immediate deletion scheduling is isolated with `max_cleanup_runs=0`, so deferred
enrollment cannot conceal a missing synchronous admission-index fence. Tests use
the actual query double and initialized cleanup factory, preserve both raw root
readers, and advance the fixture clock beyond each persisted `cleanup_after`.
They forbid live execution preparation, publication refresh, failure finalization,
parent lease claims and aggregate reconciliation, including calls whose errors
the scheduler catches. Explicit archive-policy cases retain successful sibling
descriptors, messages and bytes while cleaning uncommitted staging.
Process-loss cases interrupt the real parent CAS acknowledgment, source cleanup
and output CAS acknowledgment; scheduler recovery must finish those files
without another conversation-delete request. Those cases alone enable a bounded
`max_cleanup_runs=1` replay and require the frozen retention policy and admission
index to be present in the actual persisted parent fence before recovery. The
test never manufactures that intent. This is a separate integration gate;
component cleanup-root and scheduler coverage alone does not satisfy it.

Coverage includes CSV and JSON from one source, a real PDF report, empty TXT/MD,
independent sibling success, exactly three automatic attempts and one
idempotent manual admission, restart, duplicate/concurrent/stale workers,
parent lease replacement, deadline and bounded retry guidance, source and
screening revocation, capability disablement, Stop/deletion, integrity failures,
blob-only/message/commit crash points, uncertain acknowledgments, safe history,
independently revoked/deleted/changed source projections, restored access,
infrastructure-error propagation, bounded admission, cleanup, and owner-free
cold imports in normal and optimized Python. Required setup and I/O occur
outside assertion expressions.

Run from the repository root with the application and functional-test
directories on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -q `
    functional_tests\test_orchestration_output_lifecycle.py `
    functional_tests\test_orchestration_output_cleanup.py `
    functional_tests\test_orchestration_output_enrollment.py `
    functional_tests\test_orchestration_output_deletion_pipeline.py `
    functional_tests\test_orchestration_output_identity.py `
    functional_tests\test_orchestration_render_resume.py `
    functional_tests\test_orchestration_export_sources.py
```

The service never reruns analysis or composition. It can rerender an
uncommitted file only when its previous complete bytes are genuinely absent.
Existing format-specific suites own binary layout and serializer fidelity
coverage. Production route/scheduler/runtime/UI wiring and rollout validation
remain the orchestration owner's responsibility.
