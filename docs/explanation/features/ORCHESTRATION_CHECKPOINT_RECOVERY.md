# Orchestration Checkpoint Recovery

**Version: 0.261.105**

Implemented in version: **0.261.105**, recorded in
`application/single_app/config.py`.

## Overview

An orchestration failure should explain what could not finish without discarding
work that already succeeded. Checkpoint recovery saves completed step results and
uses them when the user chooses **Retry from failed step**.

For example, if document search succeeds and a later agent call times out, retry
uses the saved search result instead of searching again. The failed agent step
runs again, its dependents can proceed, and the answering step uses the combined
results.

Recovery applies to V2 orchestration. It does not change ordinary-agent chat,
select a replacement agent, or add automatic retries.

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

Completed results include their evidence, notes, citations, artifact references,
required context changes, and execution provenance. A summary alone cannot
reconstruct these values.

Payloads are split into bounded records and published through a committed
manifest. Reconstruction checks their identity, schema, size, completeness, and
integrity. An incomplete or damaged payload is not treated as an empty successful
result. Each checkpoint is limited to 8 MiB of serialized payload across at most
64 chunks. Exceeding that bound fails checkpoint persistence explicitly rather
than truncating the result.

Each checkpoint is bound to its effective plan, step inputs, dependency context,
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
