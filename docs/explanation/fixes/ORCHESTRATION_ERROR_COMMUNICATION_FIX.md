# Orchestration Error Communication Fix

**Version: 0.261.105**

Fixed in version: **0.261.105**, recorded in
`application/single_app/config.py`.

## Issue

An orchestration plan could correctly choose an agent, encounter a time limit or
execution failure, and leave the conversation with no explanation. The Run view
could show the agent and answering step as cancelled even when the user had not
pressed Stop.

The equivalent direct-agent request could explain the service failure. The gap
was in orchestration execution and reporting, not in selecting a particular
integration.

## Root cause

The executor combined the user's cancellation signal with step and total
deadlines in one callback. Scoped agent execution interpreted that callback as
`AgentExecutionCancelled`, and the adapter returned a cancelled step.

A cancelled step cancelled the rest of the plan, including `respond`. The route
then returned its cancellation event before reaching the normal assistant-message
save path. Other execution failures were replaced by a generic error event, and
failed-step details were not consistently available to final synthesis.

The browser compounded the gap: empty cancellations added no message, failures
used a transient stream error, and a settled inline plan card could disappear.
Its completion handler also treated a final message as successful completion
regardless of the server's execution outcome.

## Changes

Execution now distinguishes explicit Stop, measured deadlines, and unexpected
interruption. Failure information uses application-owned reason codes and safe
messages. Provider detail is included only when structured metadata supports it;
there are no integration-specific branches or error-text keyword rules.

The main conversation and Run view retain an explanation of incomplete work.
Safe failure context reaches normal answering, with an application-generated
status explanation when the answering model cannot finish. Authorized partial
results can remain useful without falsely marking every step successful.

Execution outcome and attempt identifiers travel through terminal events, saved
assistant metadata, and run-history projections. A dropped browser stream does
not prove server cancellation. Stop uses the server cancellation path, while
connection recovery checks the already-running attempt.

Reconciliation also waits for final-message publication, not just a terminal
execution status. A committed message whose write acknowledgement was lost is
confirmed from durable storage rather than incorrectly reported as unsaved.

The associated [checkpoint recovery feature](../features/ORCHESTRATION_CHECKPOINT_RECOVERY.md)
adds **Retry from failed step** without silently replaying successful plan steps.
Retries of agents/actions with uncertain external effects require confirmation.

## Affected components

| Component | Change |
| --- | --- |
| Agent execution context/runtime | Distinguish a measured delegation deadline from a user cancellation. |
| Orchestration schema, adapters, and executor | Retain structured failure facts, safe final reporting, and completed-step recovery state. |
| Orchestration routes and event builders | Save failure/status messages and expose consistent live/history outcomes. |
| V2 orchestration transport/controller and chat stores | Preserve failure messages and actual outcomes rather than dropping empty cancellations or hardcoding success. |
| Plan/Run views and message actions | Keep explanations and guarded retry controls available after execution settles. |

## Coverage and impact

`functional_tests/test_orchestration_checkpoint_recovery.py` uses fake providers
and clocks to distinguish timeout from user Stop. It also exercises failed final
synthesis, successful text that merely mentions errors, secret-bearing exception
sentinels, history restoration, and retry invocation counts.
Crash-boundary coverage checks inherited completed results across multiple
attempts and terminal-message writes with lost acknowledgements.
`ui_tests/test_v2_orchestration_recovery.py` and
`ui_tests/test_v2_orchestration_recovery_backend.py` cover the visible recovery
workflow and real browser-to-Flask integration. Existing
`functional_tests/test_orchestration_executor.py`,
`functional_tests/test_orchestration_adapter_contract.py`, and
`functional_tests/test_orchestration_run_hydration_routes.py` cover the shared
execution and projection boundaries.

| Before | After |
| --- | --- |
| A deadline could cancel the answering step and leave an empty turn. | The affected operation has an honest failure/timeout status and an explanation independent of the answering model. |
| An execution error could disappear when the browser reloaded. | Saved outcome metadata and conversation messages support restored failure feedback. |
| A final message implied that the whole run succeeded. | Partial/failed execution remains distinguishable from successful completion. |
| The apparent retry path could resend ordinary chat or require asking again. | Recoverable orchestration failures use saved completed steps and a linked attempt. |
| Losing a browser stream looked like stopping the server. | The interface reconciles server state and does not automatically replay potentially active work. |
| A terminal status could be mistaken for finished message persistence. | The interface continues checking until publication is saved, explicitly failed, or interrupted. |

Ordinary direct-agent chat and agent selection remain unchanged. Older runs
without recorded reasons or checkpoints remain readable, but the application
does not invent a historical cause or reconstruct missing results from summaries.
