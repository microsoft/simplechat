# Orchestration foundation integration fixes

**Version: 0.261.125**

Fixed in version: **0.261.125** on the foundation review branch, recorded in
`application/single_app/config.py`. This corrective commit does not independently
bump the application version; the parent integration owns the next version.

Refs [#1509](https://github.com/microsoft/simplechat/issues/1509).

## Issue and root cause

M2/M4 integration exercised three boundaries that the initial result foundation
did not yet handle:

| Boundary | Root cause | Correction |
| --- | --- | --- |
| A resumed native Analyze step retains its generic result. | Generic preparation called `prepare_analysis_attempt()` with the default `resume_from=None`, conflicting with the existing non-null native resume binding. | Reuse the active same-token guard without resetting request, source, or resume metadata. |
| A result commits, then the worker stops before its runtime checkpoint saves the digest. | Only digest-keyed commits existed; the runtime had no exact authenticated producer/input lookup. | Atomically commit an immutable producer/input receipt with the digest pointer and recover it without replaying producer work. |
| Gather uses web, URL, deep research, an agent/action, or permitted memory. | Source-free or document/upstream-only lineage could not truthfully describe these sources. | Explicit bounded external descriptors, server-catalog admission, and injected current reauthorization in an opt-in lineage version. |

## Technical changes and scope

`functions_orchestration_result_contracts.py` adds external-source descriptors
and receipt binding validation without changing public v1 task/reference fields.
`functions_orchestration_results.py` adds optional `input_fingerprint` and
`external_sources` persistence arguments, `recover_task_result()`, and external
access injection. `functions_workflow_result_store.py` reuses native lifecycle
guards and supports an immutable receipt plus digest commit in one existing
conditional transaction.

Same producer/attempt/input and same digest is idempotent. A different digest
is an explicit `OrchestrationResultConflictError`, not a latest-result choice.
Only a missing exact receipt returns `None`; corrupt, deleted, unauthorized or
unavailable results fail. Readable payloads are fully verified during recovery.
Original attempt identities remain intact across later sibling failures;
cross-attempt consumption still needs an explicit authorized alias.

External provenance contains original capability, opaque reference, audience,
and digest/revision information. It contains no credentials, fetchable URL
instructions, runtime callbacks or raw Fact Memory prompts. Current callbacks
are required for every external type, including public web capability checks.
Historical snapshots do not bypass current integration access or memory
audience restrictions. The durable bindings can be restored after restart
without treating an in-memory catalog as the source of truth.

Unused extensions preserve the exact published v1 result bytes and existing
checkpoint fingerprints. Standalone/workflow APIs, runtime/adapters, routes,
artifact/rendering modules, and user-facing feature activation are not changed.

See [the foundation API reference](../features/ORCHESTRATION_GATHER_REASON_RENDER.md)
for exact signatures, private manifest/lineage versions, limits and collision
semantics.

## Validation

`functional_tests/test_orchestration_result_recovery.py` uses the real native
work-unit lifecycle, including completed-unit reuse with `resume_from`, actual
owner tokens, cancellation, deletion and stale-worker rejection. It also covers
Cosmos/Blob restart recovery, receipt transaction rollback, competing writers,
corrupt receipts/data, original output ordering, partial output status, and
published-v1 byte fingerprints.

`functional_tests/test_orchestration_external_results.py` covers all six external
source types, server-only alias admission, restored catalogs, strict descriptors,
current capability/resource/audience denial, revision/digest changes,
historical snapshots and inherited lineage.

`functional_tests/test_orchestration_result_imports.py` executes real modules and
the new repair paths in fresh normal and optimized interpreters with network
blocked. Required operations and explicit subprocess checks still execute
under `-O`. Existing storage, native work recovery, source access, orchestration
checkpoint and exact-record JSON regressions remain part of the focused matrix.

All validation uses external-I/O doubles; it does not claim live provider or
cloud throughput. These fixes recover retained data and provenance, not an
activated orchestration renderer or a completed epic.
