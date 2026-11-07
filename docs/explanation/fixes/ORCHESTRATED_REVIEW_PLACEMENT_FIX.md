# Stable orchestrated Microsoft 365 review placement

Fixed in version: **0.261.325**

## Issue and root cause

New email review cards could appear above the request while orchestration was
running, then move when the final answer arrived. The planner saved a different
user-message ID from the optimistic browser ID. The run controller consequently
rejected a correctly scoped creation event, while list discovery found the action
without a visible message reference.

The original regression tests seeded identical browser/server IDs and missed the
normal planning-to-execution transition.

## Changes

The planning event now publishes the saved user-message identity bound to the
conversation, turn, and run. The controller checks all three scopes before
reconciling the optimistic bubble. The pending-action store follows that identity;
it does not guess using timestamps, subjects, or the latest message.

New actions carry server-bound producing-message provenance. List discovery can
therefore attach them before their creation event arrives. They remain beneath
the producing request when the final reply is saved, keeping an expanded card or
open editor mounted. Existing unlinked history keeps its separate conversation
section; this fix does not rewrite historical records.

Preparation summaries point to the action card for current delivery status
instead of claiming a draft is still unsent. This matters when the owner sends
or cancels while the reporting step is still running.

## Files and validation

The identity contract spans `functions_orchestration_events.py`,
`route_backend_orchestration.py`, `orchestration.ts`,
`orchestrationController.ts`, and `chatStore.ts`. Placement is handled by
`m365PendingActions.ts` and `m365PendingActionsStore.ts`.
The application patch version is recorded in `application/single_app/config.py`.

`functional_tests/test_v2_m365_pending_actions_stream.mjs` exercises the real
planner/run controller and stores over mocked HTTP with distinct IDs, list
discovery before SSE, and final publication. It verifies one user bubble, one
card, stable placement, and preserved expansion.
`test_orchestration_conversation_context_routes.py` checks the identity against
the actual saved run on the real Flask planning route.
`test_orchestration_operation_runtime.py` checks historical preparation wording
and that repeated approval does not repeat the draft-send POST.

No validation sends real email or modifies a production mailbox.
