# Analyze and Compare document citation handoff

Fixed/Implemented in version: **0.261.356**

Application version: `application/single_app/config.py`.

Current version after base-branch integration: **0.261.358**.

## Issue and root cause

An orchestrated document answer could contain the correct extracted facts and source
quotations without a clickable document citation. This was a provenance handoff
problem, not evidence that document retrieval or extraction failed.

Analyze retained the original passages and chunk/page locations, but the orchestration
citation projection handled detailed Search citations only. Analyze findings therefore
became document-level provenance without a passage identifier. Compose's existing
citation-copying instructions were activated by inline markers, which the raw findings
did not provide. Compare also lost source locators while preparing and combining its
source summaries.

## Changes

- `functions_document_citations.py` provides the shared document marker and location
  formatting used by Search and the new Analyze/Compare projections. The existing
  agent and citation-tracking imports continue to expose the same helpers.
- Analyze builds citation records from accepted evidence and puts supporting markers
  beside the corresponding findings in its report. Public data-row schemas are unchanged.
- Internal Compare opts into source markers when reading document windows. Its existing
  summary, pairwise-comparison, and consolidation calls preserve those references;
  no additional model calls are introduced. Failed windows and targets do not become
  supporting citations for a completed comparison.
- `functions_orchestration_analysis_results.py` retains citation metadata alongside the
  producer's coverage. `functions_orchestration_result_runtime.py` reads this metadata
  from the exact committed producer manifest, validates its source membership, and
  projects the same document citation fields used by Search.
- `functions_orchestration_composition.py` supplies ready-to-copy citations alongside
  each declared input. The existing citation policy, assistant-message persistence,
  done frame, source tracking, and V2 citation viewer remain the delivery pipeline.

Source identities remain separate from filenames. Duplicate filenames, personal/group/
public scope, real zero-valued locations, and source availability checks retain their
existing meaning. Citation projection does not grant permission to open a source.

## User-visible behavior

An answer based on Analyze or Compare can now carry the ordinary inline document
citations. Clicking a citation opens the source passage through the existing viewer.
Compare can reference both the original and revised document. The references remain
available when the saved answer is reopened or its delivery is recovered.

A citation locates evidence; it is not an independent certification of every conclusion.
Existing coverage and uncertainty qualifications still apply. Missing locators are not
replaced with invented pages, and older saved results are not rewritten or regenerated.
The fix does not add automatic source appendices, warning substitutes, new controls, or
citation-specific retry calls. Legacy Analyze callers retain their default behavior;
source-summary enrichment is explicitly enabled by internal Compare.

## Validation

The new regression initially reproduced the Analyze failure: one document-only citation
was returned despite 151 retained passages. After the fix, all 151 indexed references
survive the findings, public-record, and report bindings without changing the public
record fields.

**248 focused backend tests passed** in an isolated environment with the pinned Semantic
Kernel version and compatible OpenSSL dependencies:

```powershell
$env:PYTHONPATH="$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -q --tb=short --disable-warnings -p test_support.cosmos_network_guard functional_tests\test_orchestration_analysis_compare_citations.py functional_tests\test_orchestration_analysis_citation_delivery.py functional_tests\test_document_comparison_source_citations.py functional_tests\test_orchestration_internal_analysis.py functional_tests\test_orchestration_dependency_runtime.py functional_tests\test_orchestration_citation_persistence.py functional_tests\test_orchestration_compose_output_retry.py functional_tests\test_orchestration_reason_render_pipeline.py
```

Coverage includes both Compare sides, multiple targets, partial results, failed windows,
JSON/XML preservation, scope checks, invalid citation metadata, unchanged public row
schemas, complete headless delivery, and delivery-only recovery without another model call.
The existing headless selected-result citation suite also passed all 12 cases.

**Two local browser tests passed** against the real bundled V2 components with synthetic
HTTP boundaries:

```powershell
$env:PYTHONPATH="$PWD;$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -q ui_tests\test_v2_analysis_compare_citations.py
```

These tests open the correct original passages for Analyze and both Compare documents,
then repeat after a browser reload and saved-payload rehydration. The production app was
not mutated or redeployed, and the separate external UI harness was not changed.

### Existing broader-suite limitations

Broader waiting/recovery tests still have baseline failures. Running the relevant suites
against unmodified HEAD application modules reproduced the same 25 failures and 14 setup
errors. Two existing agent-citation AST checks also fail on unchanged chat-route wiring.
These are not reported as passing and are outside this citation-handoff correction.
