# Orchestration retained-result read amplification

Fixed in version: **0.261.380**, recorded in
`application/single_app/config.py`.

## Issue and observed outcome

A UI acceptance run stopped waiting after 180 seconds with three completed
producer steps and a composition step still reasoning. Persisted application
records subsequently showed all four steps completed and the assistant answer
was saved. The saved composition bindings depended on all three producers;
no dependency-ordering or lost-answer defect was demonstrated.

Application Insights showed 4,648 background GETs of that run document during
execution. Between composition finishing and recorded run completion, there
were 2,258 background run-document GETs and 2,332 background conversation-document
GETs. Those counts were selected by the exact document URLs, not site-wide
container totals.

The application completed approximately 7 minutes 44 seconds after execution
started, including approximately 203 seconds after composition finished.
These observations establish excessive application I/O, not that every second
of latency was caused by it. Model latency and a live post-fix runtime have
not been measured.

Harness-only observations are recorded separately in the investigation's
session artifacts. No harness code, acceptance timeout, Azure configuration,
or deployed application was changed.

## Root cause

Retained-result readers repeatedly reauthorized the same conversation and
producer, reloaded immutable manifests, and expanded the same upstream lineage.
Citation projection added another direct committed-manifest lookup, reopened
coverage sidecars for multiple output names, and repeated reader checks.
Each committed-result lookup also performed the existing low-level
checkpoint, integrity and execution-claim checks.

A small fan-in therefore caused hundreds of authorization callbacks and
storage reads. Shared-parent graphs amplified the same work further.
The problem reproduced offline using the real result owners and lease-bound
store with SDK-shaped storage doubles, independently of browser automation,
model providers and Azure service latency.

## Changes and authority boundaries

`functions_orchestration_results.py` provides a synchronous `read_operation()`
boundary. Within that boundary, result readers reuse immutable committed
manifests by full producer identity and manifest digest, completed lineage
validation by its effective source policy, and initial conversation/run reads.
Every requested output still has its own descriptor validated, including
output name, kind, digest, counts and completeness.

Before the operation returns, its original authority snapshots are discarded.
Committed manifests and external lineage are checked again with live
authorization reads; positive authorization is not cached in that final pass.
Encountered producers are reauthorized after the manifest/lineage reads.
Immutable content reuse is not a replacement for current access.

The boundary has no global cache or TTL. Nested projections share their outer
boundary. Failed and completed operations discard reusable state; copied
contexts cannot keep completed authority or share it with another thread.
Readers used later perform ordinary current checks. Writes through the result
facade are refused inside a read operation.

The integration points are:

- `functions_orchestration_result_runtime.py`: citation projection uses the
  facade's verified manifests and reads a producer's coverage sidecar once,
  including when multiple named outputs share that manifest.
- `functions_orchestration_composition.py`: declared-input materialization,
  image descriptors and input citations share one read operation, ending
  before any provider call.
- `functions_orchestration_execution.py`: initial answer, citation and gathered
  output projection share one operation, ending before screening and publication.

The underlying result store, payload integrity checks, claim/ETag fencing,
post-provider checks and final publication checks are unchanged. Cancellation
continues to prevent effects and writes without deleting access to already
retained inputs. Current and snapshot external-source policies stay distinct.
There are no new routes, settings, public schemas or user-facing controls.

## Deterministic read-count comparison

The same graph fixtures were measured with the original implementations and
the changed implementations. Counts include nested store execution checks.
Both versions return the same deduplicated citation.

| Backend and graph | Lease callbacks, before / after | Container reads, before / after | Conversation reads, before / after | Producer reads, before / after |
| --- | --- | --- | --- | --- |
| Cosmos, 3 producers | 927 / 146 | 493 / 74 | 118 / 20 | 118 / 20 |
| Blob, 3 producers | 777 / 118 | 418 / 60 | 118 / 20 | 118 / 20 |
| Cosmos, 8-producer shared-parent graph | 3,246 / 346 | 1,734 / 174 | 412 / 59 | 412 / 59 |
| Blob, 8-producer shared-parent graph | 2,730 / 278 | 1,476 / 140 | 412 / 59 | 412 / 59 |

Every category improves by at least 80%. These are I/O-count improvements,
not an end-to-end latency percentage or a promise of completion within
180 seconds. The regression also imposes linear budgets on a deeper,
12-producer lineage.

## Validation

`functional_tests/test_orchestration_result_read_amplification.py` covers both
payload backends, fan-in, shared parents, deeper lineage, named-output reuse,
authority changes during the body and final validation, claim takeover,
checkpoint deletion, failed-operation cleanup, copied contexts, forged
descriptors, write refusal, integrity failures and agent/action revocation.

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest .\functional_tests\test_orchestration_result_read_amplification.py -q --disable-warnings --tb=short
```

Result: **45 passed**.

```powershell
python -m pytest .\functional_tests\test_orchestration_result_read_amplification.py .\functional_tests\test_orchestration_results.py .\functional_tests\test_orchestration_dependency_citations.py .\functional_tests\test_orchestration_dependency_runtime.py .\functional_tests\test_orchestration_result_claim_fencing.py -q --disable-warnings --tb=short
```

Result: **227 passed, 1 pre-existing failure**:
`test_checkpoint_child_keeps_original_grounded_citations_without_replaying_source`
raises `result_producer_unavailable` during retry receipt reconciliation.
It was reproduced before application changes.

```powershell
python -m pytest .\functional_tests\test_orchestration_harness_execution.py .\functional_tests\test_orchestration_continuation.py .\functional_tests\test_orchestration_external_results.py -q --disable-warnings --tb=short
```

Result: **751 passed, 4 pre-existing failures**. Three evidence-citation
publication cases expect one citation but receive two; a native continuation
case is missing `pending_results["compute"]` after a producer-availability
failure. All four reproduce with the unchanged original application modules.
They are not suppressed or changed by this performance fix.

The Cosmos response inventory is regenerated and reviewed. Real SDK
`CosmosDict` point responses, plain nested domain values, ETags and transactional
storage behavior remain intact.

### SDK-owner coverage and environment limitation

The full `python .\scripts\check_cosmos_response_boundaries.py --run-contracts`
attempt was interrupted after widespread setup errors and stalled import-heavy
checks. Fail-fast isolation identified an incompatible default environment:
Flask 2.2.5 calls the removed `werkzeug.__version__` attribute in Werkzeug 3.1.4.
A standalone `Flask(...).test_client()` reproduces this without importing
SimpleChat.

The shared installation was not changed. An isolated validation interpreter
restored the repository's Flask 3.1.3 and Werkzeug 3.1.6 pins. Using that
interpreter as `$python`, the affected storage owners were checked with network
access blocked:

```powershell
& $python -m pytest -p test_support.cosmos_network_guard `
    .\functional_tests\test_orchestration_result_read_amplification.py `
    .\functional_tests\test_orchestration_result_claim_fencing.py `
    .\functional_tests\test_orchestration_cosmos_response_contract.py `
    .\functional_tests\test_action_credentials_orchestration_continuation.py `
    .\functional_tests\test_orchestration_conversation_sources.py `
    .\functional_tests\test_orchestration_message_regeneration.py::test_regeneration_forces_review_despite_auto_and_disabled_approval_override `
    .\functional_tests\test_orchestration_harness_execution.py::test_selected_result_citations_reach_headless_message_cache_and_delivery `
    .\functional_tests\test_orchestration_harness_execution.py::test_context_edit_after_composition_does_not_publish_stale_content `
    .\functional_tests\test_orchestration_harness_execution.py::test_delivery_refresh_reuses_real_saved_results_without_any_execution `
    .\functional_tests\test_orchestration_failure_telemetry.py::test_durable_execution_outcome_is_recorded_once_not_on_sse_replay `
    -q --disable-warnings --tb=short
```

Result: **152 passed, the same 3 pre-existing evidence-citation failures**.
HTTP/SDK ownership, conversation updates, delivery refresh, regeneration,
conditional publication and the new scope regressions execute against the real
owners. The complete repository-wide contract gate was not completed.

```powershell
& $python -O -m pytest -p test_support.cosmos_network_guard .\functional_tests\test_orchestration_result_read_amplification.py -q --disable-warnings --tb=short
```

Result: **45 passed** under optimized Python. Required reads and mutations are
performed before assertions.
