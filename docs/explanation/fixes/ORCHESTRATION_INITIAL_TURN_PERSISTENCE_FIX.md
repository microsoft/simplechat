# Initial orchestration turn persistence

**Version: 0.261.415**

Fixed/Implemented in version: **0.261.415**, tracked in
`application/single_app/config.py`.

Issue: [microsoft/simplechat#1893](https://github.com/microsoft/simplechat/issues/1893).

## Issue and root cause

A new Orchestrate question could disappear after switching conversations or
refreshing during planning. The sidebar could retain its title while the thread
showed no messages. A planning error, or even a legitimate clarification, could
leave the question available only in the browser that submitted it.

The browser rendered an optimistic user message, but the normal server path
saved that message only after producing a valid plan. Planning failures were
reported through the event stream without saving an initial-turn failure.
Reopening a conversation replaced the optimistic message with server history;
there was no saved question to restore. Existing run recovery could not help
because a failed initial planning pass had not created a run.

Planning also belonged to the response generator, and Auto execution was
initiated by the browser after receiving the plan. Saving the question alone
would therefore not make authorized Auto work continue after the page closed.

Read-only Application Insights and App Service console investigation identified
a selected-requirements validation failure in the reported turn on application
version 0.261.410. Its HTTP request was recorded as 200 because the failure was
inside an SSE response. HTTP transport success was not evidence that a plan or
question had been committed.

## Durable admission

The accepted user question now anchors a versioned planning attempt in the
existing messages container. Authorization, request validation, and required
content checks precede acceptance. The question and its initial state are
created together before slow planning work; an early `user_message_persisted`
event acknowledges the actual saved question ID.

The stored attempt retains canonical replay inputs, a submission identity,
conditional ownership, and an expiring planning lease. A repeated submission
observes its existing state rather than taking ownership again. Changed inputs
cannot reuse an accepted submission. Explicit initial-planning retries preserve
the question and its original selections and require fresh manual review.

Saving early does not insert the current question into its own prior-history
snapshot. The existing stable message identity and content fingerprint remain
the association between question, clarification, plan, and run.

## Browser-independent planning and execution

An authenticated background worker owns planning and its resources. The SSE
connection observes the worker; disconnecting the observer does not dispose the
planner. Idle connections receive keepalive frames, and the worker maintains its
conditional lease while planning.

Auto plans already authorized by the original submission pass through the same
execution-admission and run-claim boundary as reviewed plans. The browser follows
that execution instead of submitting a second run. Manual/timed approvals,
approval floors, plan-edit holds, source checks, and integration delivery policies
remain authoritative.

Explicit Stop is different from navigation. A submission-scoped cancellation
record can be saved even before the question acknowledgement arrives. These
typed records use the existing orchestration container, are not executable runs,
and are excluded from normal run listings. They cannot be overwritten by an
unrelated conversation update. Cancellation and publication fencing prevent a
late planner from starting Auto work. If execution already started, the existing
run cancellation/reconciliation path remains responsible for its outcome.

A process restart or expired planning lease produces a recoverable interruption,
not an indefinite claim that planning is still active. The application does not
silently replay uncertain external effects or promise transparent recovery from
every process failure.

## Reopening and retrying

Normal conversation history contains the saved question and public lifecycle
hints, not private claim tokens or canonical input records. A small authenticated
turn-status API restores planning, clarification, review, failure, and execution
state. The browser can recover without a session-storage copy of the prompt.

| API | Purpose |
| --- | --- |
| `GET /api/v2/orchestration/turns/<turn_id>` | Read an owned question's authoritative status; explicit canonical-input reads support deliberate retry. |
| `POST /api/v2/orchestration/turns/<turn_id>/cancel` | Record Stop for one submission, including the pre-acknowledgement interval. |
| `POST /api/v2/orchestration/plan` | Admit a new planning submission or continue/retry an authorized saved question. |
| `POST /api/v2/orchestration/run` | Preserve the existing reviewed-run API and shared execution-admission boundary. |

Conversation and question ownership are checked at the read/write boundaries.
Deleted, masked, changed, or inaccessible questions cannot be used to recover an
older unreviewed request. A status outage is shown as uncertainty while the saved
question remains visible; it is not permission to start another execution.

Restored countdown/automatic review proposals wait for manual approval. Reopening
a page does not create a new approval. A Stop that races with completion follows
the saved result instead of falsely reporting that a completed answer was stopped.

## Files and validation

The backend lifecycle lives in `functions_orchestration_planning.py` and
`route_backend_orchestration.py`. Conversation history strips its private fields,
and retry preparation does not copy an old worker's ownership into a new attempt.
The V2 transport, orchestration controller/resume code, chat store, and existing
message error/status surfaces implement restoration and saved-ID reconciliation.

Regression coverage includes:

- `functional_tests/test_orchestration_planning_persistence.py`: real
  authenticated routes and SDK-default storage for early persistence, provider
  failure, clarification, disconnect, Auto completion, duplicate delivery,
  conditional claims, interruption, cancellation, ownership, and explicit retry.
- `ui_tests/test_v2_orchestration_planning_persistence.py`: production components
  and CSS for desktop/mobile navigation, fresh browser contexts, persisted errors
  and clarifications, canonical retries, Stop, review holds, completion races,
  status outages, and absence of duplicate run POSTs.
- Existing clarification, conversation-context, regeneration, run recovery,
  hydration, shared-conversation, and route-policy suites.
- Selected-source clarification checks keep exactly one saved question across
  added sources and repeated continuation requests. Follow-up citation checks
  retain authorized answer provenance without admitting unrelated user text;
  their prior-message fixtures precede the newly accepted question.

The session-only diagnostic first reproduced three missing-question failures
(planning, planner failure, clarification) with a successful-plan control.
The regression tests assert the corrected durability contract rather than
preserving those failure expectations.

### Validation results

The complete `scripts/check_cosmos_response_boundaries.py --run-contracts`
bank passed **2,002 tests** and **431 subtests** with network access blocked
and zero inventory review gaps after merging the 0.261.414 base. The combined
selected-document correction, durable planning/Auto, and guided-input backend
selection passed **96 tests**.

The merged navigation, planning-retry, guided-input, and attachment-isolation
browser selection passed **72 tests** using local Chromium. Existing elicitation
and run-hydration scripts passed **6/6** and **7/7** with their required standalone
setup. The attachment ownership Node contract, TypeScript checking, production
UI build, route policies, and documentation checks passed.

The base's guided answer-review flow, document-planning corrections, and
conversation attachment isolation are preserved. Planner-only fixtures now
separate side-effect-free planning from the approved Auto execution handoff;
browser fixtures cover the new pending-input reads and durable Stop acknowledgement
without relaxing unexpected-request checks. These are local validation results,
not evidence of deployment to Azure.

## Compatibility and limitations

No new deployment resource, administrator toggle, or legacy-plan migration is
required. Existing capability gates and source permissions still apply, and a
planner rejection is not bypassed to make a question appear successful.

This fixes newly admitted turns. It does not reconstruct questions that an older
version never saved, or fabricate a plan rejected before creation. Server
acceptance also cannot guarantee preservation of a request that never reached
the server or failed its required admission checks.
