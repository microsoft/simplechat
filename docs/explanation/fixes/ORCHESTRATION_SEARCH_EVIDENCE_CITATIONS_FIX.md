# Search evidence citation handoff

Fixed/Implemented in version: **0.261.365**

Application version: `application/single_app/config.py`.

Current application version: **0.261.366**.

## Issue and root cause

A document-backed orchestration answer could contain the retrieved facts without
an inline passage citation. Search retained real document, chunk and page
metadata, but the shared citation reader exposed that metadata only when a
consumer selected Search's `prepared` output. The equally valid `evidence` output
supplied excerpts and document identities without copyable citation markers.
Compose therefore could not use its existing citation-copying policy for that
input.

The defect was reproduced with real adapters and retained-result readers. It
matches the missing-citation symptom reported by the external FED-17 UI test.
Telemetry confirmed that the reported live run completed and saved an answer,
but its exact saved input binding was not recovered. This fix does not establish
that the reproduced defect was the sole cause of that historical run.

## Technical changes

`application/single_app/functions_orchestration_result_runtime.py` now reads the
Search citation sidecar for either supported content output:

- For `prepared`, it keeps reading the selected structured content.
- For `evidence`, it opens `prepared` from the same producer and exact committed
  manifest digest through the existing authorized result reader.
- It matches each excerpt to its retained hit and citation using the document,
  excerpt identity, text, chunk identifier, page and chunk sequence. Compose
  receives the verified `evidence_id` association alongside ready-to-copy markers.
- It continues to validate source/scope lineage and metadata size. Repeated
  bindings deduplicate passage citations rather than duplicating them solely
  because one binding supplies an excerpt identity.

The stored evidence schema is unchanged. Search is not replayed to repair the
handoff, and unrelated tasks or ambient context do not supply citations. Invalid
sidecar metadata follows the existing typed failure path rather than silently
claiming success.

The ordinary Compose policy, saved `hybrid_citations`, completion event, used
document tracking and V2 citation viewer remain the delivery path. No route,
setting, browser asset, answer-style policy or external qualification harness
was changed.

### Review follow-up in 0.261.366

The Search browser regression declares `@pytest.mark.ui` directly on its test
instead of using the module-level `pytestmark` convention. This retains UI test
selection without CodeQL's unused-global warning. Citation behavior is unchanged.
All four Search browser cases passed when selected with `-m ui`.

## Behavior and compatibility

Before the fix, selecting Search's `evidence` could lose passage references that
the same search's `prepared` binding preserved. Both content bindings now make
the real references available to downstream composition, including another
Compose step and reopening retained results.

People can ask natural questions without adding "include source passages."
The fix does not force quotations, a checklist, a source appendix or a fixed
citation count, and does not remove quotations a person requests.

Sources-only bindings remain document provenance. Historical evidence without
a usable sidecar or hit association remains provenance-only. Missing locations
are not replaced with invented pages, and older citation-free answers are not
rewritten. Showing retained answer provenance does not grant access to open the
underlying source; current viewer authorization remains separate.

## Validation

The regressions use real product adapters, retained storage/readers, composition
and execution with isolated external I/O. They cover:

- Distinct passages on distinct pages and across multiple documents.
- `evidence` and `prepared`, chained Compose, duplicate bindings, source-only
  inputs, source-free answers and unrelated authorized sibling tasks.
- Personal, group, public and conversation source scope; exact sidecar producer
  and manifest digest; malformed or mismatched metadata; unavailable locations.
- Saved messages, completion events, cited-source/used-document tracking and
  delivery-only refresh without another search or model call.
- Actual bundled V2 rendering, exact citation lookup requests, matching passage
  pop-ups and saved-payload reload with enhanced citations enabled or disabled.
  Markdown sources use the existing text-passage fallback.

Relevant product tests:

```powershell
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard functional_tests\test_orchestration_search_citations.py functional_tests\test_orchestration_search_citation_delivery.py functional_tests\test_orchestration_dependency_citations.py functional_tests\test_orchestration_search_result_integrity.py functional_tests\test_orchestration_analysis_citation_delivery.py functional_tests\test_orchestration_analysis_compare_citations.py functional_tests\test_orchestration_citation_persistence.py functional_tests\test_v2_citations.py
python -m pytest -q -p no:cacheprovider ui_tests\test_v2_search_citations.py ui_tests\test_v2_analysis_compare_citations.py
```

The backend command produced **111 passed, 1 failed** with external network access
blocked. The sole failure is the unchanged checkpoint-recovery limitation below;
all new search citation regressions passed. The browser command produced
**6 passed**, including the existing Analyze/Compare interactions.

After adding a stored-sidecar digest corruption case, the final dedicated Search
run passed **28/28** tests in `test_orchestration_search_citations.py` and
`test_orchestration_search_citation_delivery.py`, also with network access blocked.
The V2 browser command was rerun and again passed **6/6**.

Documentation surface coverage passed **7/7** checks and site quality passed
**6/6**. The Cosmos boundary inventory reported **0 review gaps** with no inventory
changes required.

Python tests require the application and functional-test directories on
`PYTHONPATH`; UI tests also need the repository root and the existing V2 test
bundle dependencies. Validation used an isolated interpreter with compatible
OpenSSL dependencies rather than changing the user's global packages.

### Existing limitation

`test_checkpoint_child_keeps_original_grounded_citations_without_replaying_source`
fails in unchanged checkpoint recovery with `result_producer_unavailable`.
It reproduced before the fix and is not attributed to this handoff change.
No checkpoint/recovery implementation was changed to mask it. Production was
not redeployed or modified.
