# Orchestration operation capability fix (v0.261.322)

Fixed in version: **0.261.321**, tracked in `application/single_app/config.py`.

Review validation follow-up in version: **0.261.322**.

## Issue and root cause

A request to email information about an event produced a one-step explanation that
email sending was unsupported. The planner explicitly prohibited operations, the action
executor described only information gathering, and M365 step selection removed send,
invitation, and read-state functions. Configured email support elsewhere in SimpleChat
did not override these restrictions.

Two additional gaps prevented a complete fix: integration steps accepted no named
results from earlier research or drafting, and pending delivery assumed either a
chat-selected agent or a saved workflow origin.

The deployed run's captured planner context was not inspected. These code paths explain
the email restriction, but do not establish whether Web Search was offered to that exact
run. No event-specific or email-keyword routing was added.

## Technical changes

Existing `action_invoke` and `agent_invoke` steps accept explicit `execution_intent`
(`gather` or `operate`) and complete text, Markdown, or structured named inputs.
The planner represents requested supported work and gathers missing evidence when needed.
Known M365 enabled-function and delivery metadata is projected without secrets.

The M365 runtime retains the write filter for gathering and old plans, while operation
steps follow existing enabled functions, delegated permissions, and integration policies.
Manual/delayed deliveries carry an orchestration-specific origin, revalidated against the
owned plan and selected resource before delivery.

`functions_orchestration_operations.py` owns bounded input preparation and private
claimed operation receipts. Confirmed calls can be recovered without another effect;
unfinished effects, changed material, and incompatible new calls stop for review.
Opaque remote-agent invocations use conservative receipts. The receipt store does not
promise recipient delivery or provider-independent exactly-once operations.

Adapters retain structured function outcomes and input lineage. V2 shows operation intent
and refreshes existing outgoing cards after integration completion, interrupted streams,
and run reconciliation. Manual review, owner-only controls, and delayed-delivery recovery
are reused, not replaced.

## Files and impact

Core changes are in the orchestration planner, registry, action catalog, adapters,
action executor, result runtime, schema, M365 scopes/runtime/delivery, and local-agent
delegation. Frontend changes are confined to `OrchestrationRunView.tsx` and
`orchestrationController.ts`.

No new admin setting, capability ID, integration type, route, permission bypass, or
deployer change is introduced. Old M365 plans stay read-only until replanned.
Retained document results retain their existing conversation/run authorization and
prepared-snapshot semantics; external-source current checks remain in effect.

## Validation

New functional regressions cover research/preparation/operation dependencies, both
integration capability contracts, invalid intent and input bindings, M365 metadata,
all email and calendar delivery modes, read-state updates, original-plan delivery
reauthorization, changed material, uncertain claims, and wrong-owner receipts.
Receipt-storage or sanitization failures are sticky: even if an SDK catches the
post-call exception, the same step cannot proceed with additional effects.
Complete-input tests cover retained-result access, snapshot preservation, and the
64,000-byte rejection threshold. Generic action replay is tested in the real Semantic
Kernel invocation loop.

The final combined operation/action, M365 approval/delivery, and recovery run passed
**176 tests**, including rejection before model execution when the complete input exceeds
its actual model budget and same-step refusal after a post-write receipt failure. Existing delegation,
source-authority, result-contract, planner, recovery, and chart suites passed
**246 tests**. Browser checks passed **18 action-display tests** and **52 editor,
inline-approval, and outgoing-card tests**. V2 typecheck and production build succeeded.
These overlapping suites are not a unique test-count total.

Microsoft Graph, tokens, storage, and model replies are doubled in functional regressions.
No real email or invitation was sent. Live planner-model selection and the original
deployment still require deployment-level verification.

### Import-cycle review

CodeQL correctly reports cycles in the dependency graph, including
`functions_m365_operations` -> `functions_orchestration_operations` ->
`functions_m365_operations`, and the run reader's path through orchestration
context and the action catalog. Deferred imports do not remove these cycles.
They are execution-time dependencies: loading the catalog does not load operation
storage, and operation inputs and delivery require initialized runtime owners.
Hoisting these imports would introduce startup-order risk.

The review follow-up retains these boundaries rather than attempting a broad
orchestration/M365 dependency rewrite in this feature change.
`test_orchestration_operation_imports.py` adds fresh-process checks of both early
import orders, real web and scheduler bootstrap, normal and optimized Python,
blocked network access, and claimed-result recovery. This verifies lifecycle
safety, not an acyclic dependency graph. Separating delivery/run/input readers
through owner-supplied callbacks remains architectural follow-up work.

Operation claims now resolve `uuid.uuid4` through the module so scoped replacements
are observed. Test fixture imports are explicitly bound without changing their
setup/cleanup, and the unused delivery-test tuple unpacking was removed.
The combined follow-up run passed **187 tests**, including the 11 new import and
UUID-accessor checks. Web startup is tested before scheduler wiring; scheduler
startup is also tested independently, matching the separate production processes.
