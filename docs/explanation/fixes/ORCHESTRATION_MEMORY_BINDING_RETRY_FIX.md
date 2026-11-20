# A run that recalled saved memory could never be retried or resumed

Fixed in version: **0.261.468**

## Issue

With "Recover From Step Failures" on, the server follows a failed run with its next attempt.
On 0.261.463 it prepared that attempt once and refused it 11 times. On 0.261.467, which logs
the refusing check, all 10 refusals in the rerun of 19-20 November 2026 were the same one:

- `validation_rule`: `execution_binding_changed`
- `error_site`: `functions_orchestration_recovery.py:1388` (`validate_resume`)

The user saw a failed run keep its failure where a second attempt was allowed and expected.

## Root cause

A run saves a fingerprint of what it was approved to run with (`context_binding`): the plan,
the request inputs, the model, the catalogs, the settings and saved memory. Before a next
attempt, `validate_resume` rebuilds that context and refuses if the fingerprint differs.

The memory part was a fingerprint of the whole memory context, including its citations. A
citation built by `functions_fact_memory_context.py` carries:

- `timestamp`: the time of the read (`datetime.utcnow()`), different on every read;
- `similarity` on each recalled fact: scored against a query embedding generated for that
  read.

Neither is memory content. Reading unchanged memory twice gave two fingerprints, so every run
that had recalled any instruction or fact was refused. This applied to a clicked retry and to
resuming a waiting run as well as to the server's own next attempt, since all three pass
through the same check.

Telemetry agrees with the code. The one next attempt that was ever prepared belonged to a
conversation whose memory read was `empty` (no citations). Every refused one had memory
`available` with 2 instructions and 1 fact selected, and the counts were identical between the
original read and the read before the refusal.

Tests did not catch it because they replace the memory reader with one that returns fixed
citations.

## Change

`functions_orchestration_checkpoints.py`: `_memory_fingerprint` fingerprints saved memory
without the citation `timestamp` and the per-fact `similarity`. Everything else stays in:
audience, scope, status, notices, the messages the model reads, and each cited fact's id,
value, type and update time. A change to what memory says still changes the binding.

Both places that fingerprint memory use it: the run binding (`context_binding`) and the step
binding used for checkpoint reuse.

Memory with no citations fingerprints exactly as before, so runs saved by earlier versions
with empty or disabled memory keep their binding. Runs saved by earlier versions that had
recalled memory could not be retried before and still cannot; new runs can.

No prompt, plan, fence or setting was changed.

## Files modified

- `application/single_app/functions_orchestration_checkpoints.py`
- `functional_tests/test_orchestration_server_continuation.py`
- `functional_tests/cosmos_response_boundaries.json` (module hashes only; no storage call
  changed)
- `application/single_app/config.py`

## Validation

- `test_reading_unchanged_memory_again_does_not_change_the_binding`: builds two reads with the
  real citation builders at different times and with different similarity; the binding is the
  same. A changed fact value changes it. Memory with no citations fingerprints as before.
- Recovery, continuation, ledger, memory, checkpoint-error and route test files: 270 passed;
  the continuation file: 4 passed.

## Not verified

- **Not run against the deployed application.** Memory is the only part of the binding shown
  to differ, by the code and by the empty-memory case that succeeded. If another part also
  differs on a live run, the same log line will still say `execution_binding_changed`; it
  cannot yet say which part.
- What a second attempt then does with these failures (mostly `result_invalid` in tabular
  analysis) has not been observed, because no second attempt has run for them.
