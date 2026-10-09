---
layout: page
title: "Chat message retry reliability"
description: "Canonical saved-input retries, review-first orchestration regeneration, and attempt-scoped progress and errors."
section: "Explanation"
audience: developer
version: "0.261.317"
---

## Issue and root cause

Model and agent retries could reconstruct incompatible or incomplete invocation
selections, discard saved options, or replay wording from a different attempt.
Orchestrated questions saved a turn identity while their Retry action expected a
run identity for checkpoint recovery. Deleting the answer exposed that mismatch.
Progress appended at the conversation tail and conversation-wide errors left old
answers visible during retries and failures visible over successful older answers.

Fixed/Implemented in version: **0.261.317**

Related config.py update: `VERSION = "0.261.317"` in
`application/single_app/config.py`.

## Request reconstruction and durable attempts

`functions_chat_model_catalog.py` shares the authorized chat model catalog.
`functions_chat_retry.py` reconstructs allowlisted inputs, resolves the viewed
question, checks ownership and source fingerprints, reserves and publishes one
prepared question, and admits its invocation once. Model identity includes the
deployment, model ID, endpoint ID, and provider. Agent metadata becomes the
canonical agent request and takes precedence over ordinary model/reasoning fields.

The Retry and Edit routes in `route_backend_conversations.py` use that contract.
`route_backend_chats.py` reauthorizes the saved question before invocation, ignores
browser substitutions, persists terminal attempt state from the worker, and keeps
partial answers on their actual attempt. Identical unconsumed preparations can
be reconciled after a lost response or a Stop race without allocating another
question. Changed requests and consumed attempts cannot reuse that admission.

Logical ordering keeps answers beside their questions and bounds retry context
before the target turn. Later messages are retained, not included as future
context or automatically regenerated. Deleted and inactive answers remain excluded.

## Fresh orchestration planning versus recovery

`POST /api/v2/orchestration/messages/<message_id>/regenerate` resolves owned saved
input intent and prepares a new planning turn. The existing planning SSE route
claims that question once. Input-only `regeneration_of_run_id` lineage stays
separate from checkpoint recovery's `retry_of_run_id`.

Complete inputs and accepted clarification answers are saved on the question so
planning failures without a new run remain retryable. Preparation and invocation
check current authorization and active recovery descendants. Image-generation
intent cannot bypass authorization of the planning model.

`requires_fresh_review` survives planning, clarification, normalization, and plan
revision. Execution requires explicit `reviewed_regeneration: true`. Auto and
administrator approval defaults cannot bypass this review floor. Planning never
restores execution receipts or repeats completed actions; approving the new plan
can repeat actions and does not undo their earlier effects.

The review floor also applies to retrying a planning request retained only in the
browser. After approval, that request executes as an ordinary new turn; the
review flag alone does not invent message-carousel lineage.

## In-place presentation

The V2 `chatRetryAttempts.ts` helpers and `chatStore.ts` own preparation, saved
identity adoption, reply placement, and attempt-local errors. `MessageList.tsx`
hides the selected answer during preparation and anchors progress and the fresh
plan beside its question. Refused preparation restores the old answer and count.
Carousel navigation clears transient errors and reloads the selected attempt's
durable state. Earlier-turn reattachment uses the running question rather than
the last user message. Stop preserves partial output, and late preparation cannot
repopulate a new chat. A content-check block keeps its safe notice and failed
attempt state together; it does not become a successful answer or add a duplicate
generic failure panel.

The classic explicit-selection retry modal sends the full model tuple. Shared
conversation restrictions and workflow-delivery/result retry refusals are unchanged.

## Validation and limitations

Regression coverage uses real application modules and initialized offline HTTP
routes, plus the real V2 stores/controller/components with production CSS:

- `functional_tests/test_chat_retry_request_contract.py`
- `functional_tests/test_chat_retry_attempt_lifecycle.py`
- `functional_tests/test_orchestration_message_regeneration.py`
- `ui_tests/test_v2_chat_retry.py`
- `ui_tests/test_v2_orchestration_planning_retry.py`
- Authenticated route-policy coverage in `functional_tests/route_tests/`

Coverage includes model/agent identity, edited wording, deleted answers, duplicate
requests, prepared reconciliation, failed planning, clarification preservation,
review floors, bounded history, refused preparation, carousel errors, Stop,
earlier-turn placement, reload/reattachment, and late responses.

Final targeted results:

| Area | Result |
|---|---|
| Retry contracts, attempt lifecycle, regeneration, and backend compatibility | 104 passed |
| Retry, planning recovery, checkpoint recovery, streaming, Microsoft 365 approvals, images, and plan editor browser selection | 113 passed |
| Documentation coverage/quality and route-policy inventories | 32 passed |
| Existing unauthenticated route-policy contract | Passed |
| Standalone plan-narrowing and pending-approval restoration harnesses | 5/5 passed in each |
| V2 TypeScript check and production build | Passed; existing large-bundle warning remains |

Provider and storage boundaries are deterministic and external networking is
blocked. No live Azure/model-provider success is asserted. Historical questions
without complete saved planning inputs require a deliberately reviewed new request.

See [Chat controls]({{ '/reference/chat-controls/' | relative_url }}) and
[Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).
