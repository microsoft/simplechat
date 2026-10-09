# Orchestration document derivation reliability fix

**Version: 0.261.309**

Fixed in version: **0.261.309**, recorded in
`application/single_app/config.py`.

## Issue and root cause

A document-derived report could stop before drafting even when Analyze had read
every source page. The native collector correctly refused malformed metadata, but
the window retry loop only retried exceptions: findings-level validation issues
became a partial result without a corrective model attempt. Recovery then reused
that partial producer and retried a complete-only consumer, repeating the refusal.

The investigated Azure incident processed all 20 pages in four windows and
retained 22 of 28 candidate findings. Six candidates had `invalid_caveats`
diagnostics; telemetry did not record the exact malformed field values or types.
Compose rejected the partial input, so the Word renderer was never reached.
This fix addresses the shared handoff, not that document or output format.

## Bounded response correction

`functions_document_analysis.py` gives explicit array-of-string requirements for
qualifications and requests JSON mode through analysis invocation metadata.
For parseable malformed responses, it supplies the original source window,
previous response, and application-owned field paths to a corrective invocation.
Sequential and concurrent windows use the existing per-window retry allowance;
there is no additional unbounded repair loop.

`functions_document_analysis_results.py` validates the correction before collecting
source-grounded candidates. Findings cannot be reordered, dropped, or rewritten.
Valid values and evidence remain unchanged, qualification text must be preserved
verbatim, and malformed values or identities cannot be synthesized. Unknown
support statuses can become only unresolved, not supported. Evidence still has
to match the assigned original source window.

If correction fails, accepted original candidates remain available as partial
results. Missing coverage, unsupported claims, invalid evidence, and recorded
issues still prevent complete-only composition. Cancellation and access loss
abort work rather than publishing the retained fallback.

## Recovery and compatibility

`functions_document_analysis_checkpoints.py` recognizes saved shape diagnostics
and repairs affected ancestor windows in a linked new attempt. Unaffected windows
are reused; completed payloads from the original attempt are never rewritten.
Source snapshots, authorization, request identity, and durable execution fences
remain enforced.

`functions_orchestration_analysis_results.py` records an analysis schema check in
output completeness. `functions_orchestration_recovery.py` follows named
complete-only dependencies, schedules affected partial producers, and invalidates
their dependent retained outputs. Analyze results with complete coverage and
schema-passed but unresolved findings require review or revised instructions;
an unchanged retry is not advertised when it would only repeat that refusal.
Older results without the schema check remain eligible for producer recovery.

Same-attempt continuation retains its immutable partial receipt. A linked manual
retry can attach Analyze parent lineage to a bootstrap-created generic guard only
before request registration and behind the real orchestration execution fence.
`functions_workflow_result_store.py` keeps token, lease, and conditional-write
checks on that transition. `functions_orchestration_schema.py` supplies the safe
unresolved-input recovery explanation.

Ordinary search/RAG chat and the existing Compose correction loop are unchanged.
Explicit native Analyze actions in chat and workflows share the collector and
bounded response correction. This change does not enable partial consumption,
add a setting, change a route, or require a new Azure resource.

## Diagnostics

Correction events report field counts, attempt counts, and corrected/partial/failed
outcomes with hashed conversation and work-unit correlation. They do not include
the private response or source content. Existing analysis validation and coverage
diagnostics still distinguish malformed metadata from genuine incompleteness.

## Validation

`functional_tests/test_orchestration_document_derivation_reliability.py` runs real
collectors, checkpoints, orchestration, and renderers with offline external I/O.
It covers malformed qualifications, preservation of uncertainty and accepted
candidates, bounded failed correction, concurrent execution, cancellation, access
loss, and selective saved-window repair across chat, workflow, and orchestration.

End-to-end cases use both explicitly selected and search-discovered sources and
verify actual Markdown and Word file contents and durable publication. A linked
retry verifies that malformed saved windows are corrected before Compose and
that genuine unresolved findings do not offer a pointless unchanged retry.
Existing evidence, result-store, execution-fence, dependency, Compose, rendering,
and workflow suites provide compatibility coverage.

Local validation results:

| Coverage | Result |
| --- | --- |
| Derivation, analysis evidence/recovery, execution fences, orchestration dependencies/recovery, Compose, and durable workflow suites | 573 tests passed |
| Structured and Office renderers, rendering access failures, check cadence, waiting, and resume suites | 579 tests and 82 subtests passed |
| `python functional_tests/test_docs_app_surface_coverage.py` | 7 checks passed; generated inventory remained current |
| `python functional_tests/test_docs_site_quality.py` | 6 checks passed |
| `git diff --check` | Passed |

These are local offline checks, not a production replay. Deployment and a
controlled production retry remain separate administrative actions.
