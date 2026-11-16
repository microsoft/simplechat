# Orchestration publication verification after Cosmos numeric round trips

Fixed/Implemented in version: **0.261.380**, recorded in
`application/single_app/config.py`.

## Issue

An orchestration plan could complete all its steps and save its answer, then
report **The explanation could not be saved**. The current stream did not show
the answer, while reloading the conversation revealed the saved answer alongside
a failed-run notice.

This was confirmed in a selected-document search followed by composition on
version 0.261.379. It was a publication-verification failure, not a failure to
retrieve the selected document or generate the answer.

## Root cause

Publication checks compared fingerprints of the expected and persisted message
JSON. Python encodes `0.0` and `0` differently. Cosmos can return an integral
floating-point number as an integer after persistence.

In the investigated run, the publication guard pointed to the saved assistant
message. Restoring just one citation score from the persisted `0` to `0.0`
exactly reconstructed the guard's original document fingerprint.

Two checks were affected:

- Normal execution and model-free delivery refresh checked the saved message
  against the expected document after transactional publication.
- Lost-acknowledgement recovery checked whether a transactional publication had
  committed despite an exception from the write.

Both could misclassify equivalent numeric representations as changed content.

## Changes

`functions_orchestration_checkpoints.py` provides
`publication_documents_match`, a strict JSON comparison used only at the
publication boundary. It compares an exactly integral finite float with its
identical integer value recursively through objects and arrays.

`functions_orchestration_execution.py` uses it for saved-message readback.
`functions_orchestration_recovery.py` uses it for the committed-publication
probe after a lost acknowledgement.

The comparison does not modify either document, round fractional values, coerce
strings or booleans, discard domain fields, or accept invalid JSON values.
Large integers are never converted to floats, so precision loss still fails
verification.

Existing fingerprints and publication-guard digests are unchanged. The guard
must still bind the expected publication to its run, owner, conversation,
message, token and claim. Transactional ETags, source authorization,
cancellation, administrator retractions and genuine storage-failure handling
are unchanged.

No new setting, dependency, database migration, frontend exception or
document-specific rule is required.

## Testing and validation

`functional_tests/test_orchestration_harness_execution.py` exercises real
execution, leases and publication with external I/O doubled. A local storage
callback simulates Cosmos numeric round trips without changing the shared test
harness.

The regression reproduces failure before the fix for both normal execution and
model-free delivery refresh, with and without a lost acknowledgement.
Fractional-score controls pass before the fix.

Coverage includes:

- A completed terminal event with a saved message identity and completed durable
  run after equivalent numeric round trips.
- One transactional publication, no duplicate answer and no repeated model or
  search execution.
- Model-free refresh without producer or checkpoint changes.
- Nested numbers, negative zero, fractional values, large integers and
  non-mutating comparisons.
- Rejection of changed content, changed numbers, boolean substitutions, missing
  fields, invalid JSON and mismatched publication guards.

The focused publication suite passes **82 tests**, and
`functional_tests/test_orchestration_recovery_safety.py` passes **39 tests**,
including existing ownership, retraction and ambiguous-publication checks.
With the application's pinned Cosmos SDK 4.9.0, Flask 3.1.3 and Werkzeug 3.1.6,
all **52 numeric-publication regressions and 39 recovery tests** also pass with
network access blocked before collection.
The Cosmos boundary inventory records the reviewed storage consumers and their
runtime evidence.

The complete Cosmos contract gate is not green: a fail-fast run reached 962
passing tests and 32 passing subtests before an existing citation-count assertion
failed. The same assertion fails against the original pre-fix sources. Citation
behavior and that assertion were not changed by this fix.
The remaining contract targets, starting with the orchestration execution
suite and excluding only that pre-existing citation-test family, pass 943 tests
and 112 subtests; 12 cases are explicitly deselected. This supplemental run
does not constitute a passing complete gate.

Read-only verification against the incident's actual stored reply also confirms
that its reconstructed expected document matches the unchanged guard digest,
the old comparison rejects it, and the new comparison accepts it. This check
does not publish a reply, repair the run or change any live record.

Before the fix, equivalent JSON numbers could turn a saved answer into a failed
run. After the fix, that answer is delivered as completed; genuinely different
or unconfirmed publications still fail.

## Existing failed runs

This change prevents the false failure for subsequent publication attempts. It
does not rewrite historical failed statuses or automatically rerun models,
searches or external actions. A deployment is required before live acceptance
testing; the investigation did not modify the original conversation or its run.
