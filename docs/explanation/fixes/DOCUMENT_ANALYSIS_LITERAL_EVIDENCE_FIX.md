# Document analysis literal evidence fix

**Version: 0.261.310**

Fixed in version: **0.261.310**, recorded in
`application/single_app/config.py`.

## Issue and root cause

A document-derived report could stop before drafting even after every source
window was read. An evidence quote existed verbatim in its cited chunk, but the
shared validator removed its contents during presentation normalization before
trying exact matching. HTML comments, including Document Intelligence extraction
annotations such as page footers, normalize to an empty string.

The investigated run read all 20 pages in four windows. One finding had three
matched citations and a fourth quoting a source footer marked "Test Data Only".
The validator classified that fourth quote as `missing_quote`, rejected the
finding, and retained only 24 of 25 findings. Compose then refused the partial
input; Word rendering was never reached.

This was a source-representation problem, not a missing document, an inability
to read the PDF, or a Word renderer failure.

## Shared exact-first matching

`functions_document_analysis_results.py::_locate_analysis_evidence` now checks
the literal quote against the original cited chunks before computing normalized
forms. A source-backed comment, markup fragment, code example or extraction
annotation follows the same exact-match rule as ordinary prose. There is no
footer-specific exception or list of approved annotation formats.

If exact matching fails, the existing normalized and case-folded comparisons
remain available. Empty normalized needles are skipped so they cannot match
unrelated text. Evidence retains the original source text and character offsets.
The existing result contract, matching tiers and `evidence-matcher-v2` identifier
are unchanged.

The shared collector serves explicit narrative Analyze in chat, workflows and
orchestration. Ordinary search/RAG chat is unchanged. The fix introduces no model
calls, additional retries, settings, routes or source reprocessing.

## Safeguards and limitations

A quote must still be a nonblank string with a source-location selector.
All supplied selectors must identify the cited chunk. A quote found only in
another chunk fails; multiple matching cited chunks remain ambiguous.
Normalized matching retains its existing word, number and sign protections.
Other unsupported citations, conflicting findings and incomplete source coverage
still prevent complete-only composition. Findings or failed citations are not
silently discarded to complete a report.

Locating a quote proves that the passage exists in the cited source, not that the
model's entire finding is factually correct or logically entailed by it. This
fix corrects the locator's unnecessary representation restriction; it does not
add a factual-accuracy evaluation or relax the completeness contract.

Old saved attempts and their recovery behavior are unchanged. After deploying
this version, test with a fresh request; this change does not repair or migrate
existing failed runs.

## Files and regression coverage

- `application/single_app/functions_document_analysis_results.py`: exact-first
  matching and an empty-normalized-needle guard.
- `functional_tests/test_document_analysis_evidence_matching.py`: synthetic
  source comments, headers, footers, literal markup and label text; original
  offsets; missing, wrong-location and ambiguous citations; empty fallbacks;
  and real Analyze finalization without repair calls.
- `functional_tests/test_orchestration_document_derivation_reliability.py`:
  fresh Analyze to Compose to Word execution, durable publication, and actual
  downloaded Word content, using the existing offline harness.
- `application/single_app/config.py`: application patch version update.

The existing evidence-matching documentation also links to this correction.
Private production source chunks and model responses are not regression fixtures
and are not committed to the repository.

## Validation

The unchanged saved model responses were replayed locally against the original
20 source chunks. Their recomputed fingerprint matched the failed run.

| Replay | Accepted findings | Unresolved | Status |
| --- | --- | --- | --- |
| Before the fix | 24 | 1 | Partial |
| After the fix, with no response or source edits | 25 | 0 | Valid |

Normal and optimized Python both produced the fixed result. Replay did not invoke
a model, update a saved result or write to Azure.

Local offline validation:

| Coverage | Result |
| --- | --- |
| Evidence matching, final results and document derivation suites | 201 tests passed |
| Saved analysis, workflow durability and execution-fence compatibility suites | 74 tests passed |
| New Word publication cases | Both completed with two extraction calls and one composition call; no correction calls |
| Documentation surface coverage and site quality | 7/7 and 6/6 checks passed; surface inventory unchanged |
| `git diff --check` | Passed |

Tests used an isolated environment with repository-pinned Flask/Werkzeug and
compatible cryptography to avoid the machine's existing OpenSSL import failure.
Global packages and application dependency manifests were not changed.

This validation is not a production deployment or live model replay.
