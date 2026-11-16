# Orchestration email review flow fix

Fixed in version: **0.261.324**

## Issue and root cause

An orchestrated email request could create an Outlook draft and its pending action,
then report that draft creation failed. The review card could appear above the
conversation instead of beside the request.

These were separate problems:

- The operation journal copied a Cosmos SDK point response without normalizing
  its outer `CosmosDict`. `deepcopy` preserves that subclass. The strict JSON
  receipt validator rejected it **after** the draft and pending action existed.
- Orchestration's Microsoft 365 request bridge did not pass the producer's
  request-owned pending-action references to the owning run and final message.
  Without those references, the UI treated the card as an unlinked record.
- Preparation, owner review, send acceptance, and overall run completion were
  independent states but their presentation did not explain the distinction.

The earlier Cosmos compatibility fix in 0.261.140 covered then-existing storage
boundaries. The operation journal introduced in 0.261.321 missed that pattern.
See [Cosmos response compatibility](ORCHESTRATION_COSMOS_RESPONSE_COMPATIBILITY_FIX.md)
for the expanded boundary inventory and prevention checks.

## Technical changes

### Receipt persistence

`functions_orchestration_operations.py` normalizes the trusted point response
before copying it. Document fields and `_etag` remain available for conditional
replacement. Strict JSON validation is unchanged.

If receipt persistence or sanitization really fails after an effect, the journal
and action wrapper retain `operation_recovery_required`. An unfinished claim is
not permission to repeat the effect.

### Live and durable linkage

`functions_orchestration_m365.py` binds the run's producer callback **inside**
each action or agent step's Microsoft 365 request bridge. The producer records
only an already-saved action's ID, owner, conversation, and stable request ID.

`functions_orchestration_adapters.py` forwards that reference with the run and
step locator. `functions_orchestration_execution.py` validates its owner,
conversation, and step request, saves minimal action IDs on the run, and resolves
current authorized card data before publishing a creation event.

The final assistant message saves `metadata.m365_pending_action_ids`, including
when later work fails. Terminal responses and existing history hydration resolve
current cards, not private receipts or model-supplied snapshots. Send/cancel
authorization remains in the pending-delivery owner.

Transport loss does not cancel owning-worker finalization. A card refresh failure
retains the minimal references and reports that outgoing actions should be
reloaded, rather than inviting the user to recreate the email.

### User experience

New, correctly linked actions appear beside the originating turn while work is
running, then beneath its saved assistant reply. Successful manual preparation
is **Ready to review — not sent**. Sending remains an explicit owner action.
**Accepted for sending** does not assert recipient delivery.

If later reporting fails, its failure remains visible without hiding the prepared
email or pretending the whole run succeeded. The retained Outlook draft warning
remains relevant to reviewing and sending the saved content.

## Scope and compatibility

- No existing conversations, historical attempts, or pending actions are migrated,
  relinked, rewritten, or replayed.
- Stable step request IDs, conditional receipt updates, configured manual/delayed/
  automatic policies, and explicit send/cancel controls are preserved.
- No new setting, route, or delivery policy is introduced.
- `application/single_app/config.py` advances from 0.261.323 to 0.261.324.
- No real email or production mutation is needed for the regression tests.

## Validation

`functional_tests/test_orchestration_operation_runtime.py` covers actual SDK and
plain-dictionary receipt responses, all delivery modes, cached recovery, unknown
outcomes, and saved references surviving receipt or UI-publication failure.

`functional_tests/test_orchestration_email_review_flow.py` reuses the real offline
headless harness to test creation-time linkage, final message persistence,
authoritative terminal refresh, later model failure, disconnected streams, foreign
references, and unavailable card queries.

The focused backend run passed **57 tests**, including validation with the
application's pinned Cosmos 4.9.0 and Semantic Kernel 1.39.4 dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest functional_tests\test_orchestration_email_review_flow.py functional_tests\test_orchestration_operation_runtime.py functional_tests\test_orchestration_catalog_auto_execution.py functional_tests\test_m365_action_card_references.py -q --tb=short --disable-warnings
```

Frontend streaming, placement, and review coverage is documented in
[V2 pending-action cards](../features/V2_M365_PENDING_ACTION_CARDS.md).
The related Node suites passed **119 tests**, the mocked desktop/mobile
Playwright suite passed **14 tests**, and frontend wiring/documentation checks
passed **27 tests**, with no skips. The V2 production build also passed.
