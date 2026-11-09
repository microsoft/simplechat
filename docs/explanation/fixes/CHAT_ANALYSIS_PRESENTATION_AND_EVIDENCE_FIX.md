# Chat analysis presentation and evidence status fix (v0.261.424)

Fixed/Implemented in version: **0.261.424**, coordinated with
`application/single_app/config.py`.

## Issue

A cited chat answer could be followed by an Analyze step's result card containing
saved-finding counts, structural-validation language, a follow-up action, and a
findings disclosure. This duplicated the answer's visual hierarchy and exposed
processing detail before the user asked to inspect it.

An empty native comment inventory could also produce "No supporting document
evidence returned" even though its complete inventory was itself cited to
support "no comments were found."

## Root cause

Both chat renderers placed every saved-analysis descriptor directly after the
answer. The browser was useful for inspecting all saved records, but its default
placement made its counts look like a second verdict about the answer.

Retained citation projection separately excluded native inventory coverage from
the annotation-record count, then interpreted zero records as missing evidence.
That lost the difference between a completed empty inspection and a search
that returned no supporting passages. A saved Analyze finding count was a third,
independent count, not the number of comments.

## Technical changes

| Area | Change |
| --- | --- |
| `application/v2_ui/src/components/chat/MessageList.tsx`, `MessageInspector.tsx`, `AnalysisResult.tsx` | Move saved-result browsing into the existing message Sources section without adding a replacement result card. |
| `application/v2_ui/src/components/chat/MessageActions.tsx`, `EvidenceStatus.tsx`, `lib/savedAnalysis.ts` | Keep Sources keyboard state explicit, preserve access for unavailable results, and show compact material limitations rather than routine success details. |
| `application/single_app/static/js/chat/chat-analysis-results.js`, `chat-messages.js` | Apply the same Sources placement in classic chat, including saved-result-only messages, cancellation on disclosure close, and masking. |
| `application/single_app/functions_orchestration_result_runtime.py` | Classify native inspection from its retained per-source coverage, keeping annotation counts and separate producer outcomes intact. |
| `application/single_app/config.py` | Record the application patch version. |

Saved results still use the existing authorized readers and immutable result
references. Pagination, evidence, diagnostics, explicit follow-up selection,
downloads, and multiple results from an interrupted plan remain available.
There is no new route, setting, storage resource, or dependency.

Classic chat binds Sources and warning controls to UI-owned nodes rather than
matching class names inside sanitized answer HTML. A denied or stale V2 result
also keeps its safe explanation when Sources is closed and reopened, without
briefly presenting it as an available result again.

Native coverage must identify the inspected document and comments section,
provide valid counts, and explicitly establish a complete inventory without
partial, continuation, or limit flags. Uncertain coverage cannot certify an
empty inventory. Partial native inspection remains partial even if no complete
annotation record fits the retained subset.

The projection still checks the exact producer and retained digest. Source and
conversation authorization boundaries are unchanged; status classification does
not reread the original file.

## Before and after

| Scenario | Before | After |
| --- | --- | --- |
| Successful Analyze answer | A second result card competes with the answer. | The answer and inline citations remain primary; saved findings open through Sources. |
| Complete empty native comment inventory | A cited inventory can still receive a missing-evidence warning. | Completed empty coverage supports the absence claim without inflating the annotation count. |
| Truncated native inventory | Zero retained annotation records can look like missing evidence. | Explicit partial coverage remains partial. |
| Separate Search gap | Counts can be combined without preserving the producer's outcome. | A completed inventory does not conceal another retained Search outcome. |
| Unavailable saved analysis | Hiding the entire action footer can hide the explanation entry point. | Unsafe result actions stay unavailable while Sources remains reachable. |

## Validation

The original regressions were reproduced with the real retained-result readers:
completed empty Word/Excel inventories were labelled `missing`, and a
resource-limited inventory could also be labelled `missing` rather than `partial`.

Regression coverage includes:

- `functional_tests/test_orchestration_attachment_native_evidence.py`: real
  Word/Excel readers, empty/nonempty inventories, reopened evidence, and partial
  or unavailable inspections.
- `functional_tests/test_orchestration_search_citations.py`: separate producer
  outcomes and conservative handling of uncertain native coverage.
- `functional_tests/test_evidence_status.py`: existing aggregation, sanitization,
  export notices, and per-answer scoping.
- `ui_tests/test_chat_saved_analysis.py`: both clients' Sources placement,
  zero-record results, pagination, evidence, follow-ups, downloads, retries,
  masking, stream/history behavior, cancellation on closing Sources, and
  preservation of answer HTML containing control-like class names.
- `ui_tests/test_v2_evidence_status.py`: complete-empty and genuinely limited
  evidence states across narrow/wide and light/dark layouts.

The browser tests use the shared local/Azure Playwright connection and
deterministic transport; they do not qualify a live model or deployment.
The supplied live conversation required sign-in, so this fix does not claim
to have independently inspected that original file.

### Verified checks

For the native harness suites, set the application and functional-test import
paths before running pytest from the repository root:

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests;$PWD"
```

| Check | Result |
| --- | --- |
| `python -m pytest .\functional_tests\test_orchestration_attachment_native_evidence.py .\functional_tests\test_orchestration_search_citations.py .\functional_tests\test_evidence_status.py -q` | 116 passed |
| `python -m pytest .\ui_tests\test_chat_saved_analysis.py .\ui_tests\test_v2_evidence_status.py -q` | 96 passed |
| `python -m pytest .\ui_tests\test_chat_saved_analysis.py -k classic -q` | 39 passed after the final classic DOM-ownership hardening, including its additional regression |
| `npm --prefix .\application\v2_ui run typecheck` and `npm --prefix .\application\v2_ui run build` | Passed |
| `python .\functional_tests\test_docs_app_surface_coverage.py` and `python .\functional_tests\test_docs_site_quality.py` | 7 coverage checks and 6 quality checks passed |
| `python .\scripts\check_cosmos_response_boundaries.py` | No review gaps |

Both changed classic JavaScript modules also passed `node --check`. The
repository XSS scanner's added-line inspection found no issues in the ten
changed application files. Desktop/mobile and light/dark browser inspection
confirmed that normal answers have no analysis card and that saved findings
remain usable in Sources. The full-file design detector's existing typing-dot
animation and dynamic-image/comment matches were reviewed without changing
unrelated interface behavior or adding suppressions.

## Compatibility and limitations

The Sources placement applies when existing messages are rendered again.
Stored historical evidence metadata is not rewritten or dismissed based on
citation presence. Corrected status classification applies when the retained
result lineage is projected; it does not retroactively rerun old conversations.

A complete comment inventory does not prove that the body text was available
or that a broader analysis found every issue. Actual evidence gaps and material
validation limitations remain visible.

See [saved Analyze results](../features/ANALYZE_RESULTS.md) and
[reading and discussing results](../../guides/analyze-results.md).
