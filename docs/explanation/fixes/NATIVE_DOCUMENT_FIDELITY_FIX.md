# Native document fidelity fix

Fixed/Implemented in version: **0.261.424**.
Application version: `application/single_app/config.py`.

## Issue and root cause

Synthetic native-document retests exposed several different failures, not one
OCR problem. Some source details were never collected; others lost their
identity or presence state; an answer also invented native paragraph bindings
that were absent from its tool evidence.

| Area | Root cause | Repair |
|---|---|---|
| PDF properties | Basic metadata reached generic document fields, but the native audit omitted exact Author/Keywords provenance. Empty chunk keywords were unrelated. | Native Info field states, exact values/locations and source digest. XMP is not independently audited by this contract. |
| PDF structure/content | MCID/MCR references were discarded, raster resources stood in for graphics, and Artifact regex counts lost their text and role. | Supported page/stream-scoped bindings, native logical order, raster/vector records, and Artifact text/type/subtype. |
| Excel optional fields | Missing description/title attributes were normalized to empty strings. | Explicit native presence states alongside compatibility fields. |
| Excel controls | FeaturePropertyBag cell-style control bindings were unsupported; a Boolean alone could not prove a checkbox. | Bounded mapper/control-chain decoding with saved checked state; Boolean-only negative controls remain distinct. |
| PowerPoint | Untexted ordinary shapes were omitted; formatting was aggregated without object identity; placeholder content origin was unavailable. | Supported slide-local object identities, decorative markers, object-linked runs, placeholder parts and qualified solid-color contrast. |
| Screened publication | Native enrichment occurred after canonical page capture, and page-mode chunk capture ignored the enriched chunks. | Native supplements enter canonical capture before publication; PDF keyword strings remain valid reviewed list metadata. |
| Native audit answers | Model findings could invent source bindings or field states. | Scoped fact-reference validation and deterministic factual tables, independent of free-text paraphrases. |

## Technical changes

`native_document_evidence.py` defines field states without changing shared Word
XML/comment helpers. `functions_pdf_native_evidence.py` and
`functions_pptx_native_evidence.py` add supported identities and associations;
`functions_accessibility.py` retains existing summaries while exposing the
additional native evidence.

`functions_excel_accessibility.py` preserves native fields, supported cell
controls and bounded saved-style locations. `functions_excel_inventory.py`
versions native pages as 3.0 independently of cell/table manifests.

`functions_native_document_inspection.py` reads local PDF/PPTX source copies and
returns bounded, revision/hash/section-bound continuations.
`functions_search_service.py` obtains bytes through the existing authorized
active-representation reader. Stale original metadata cannot describe a
different sanitized active file. Word comment-only inspection remains separate.
No new public route, cloud service, browser dependency or setting is introduced.

`functions_native_audit.py` builds typed native facts and validates output fact
references. For source-only native-audit composition, the server supplies the
factual values and states; a model cannot substitute a different paragraph
binding or turn absence into a stored blank. Mixed research/computed inputs are
not replaced by this native report. Redacted/bounded transport remains
inaccessible rather than an exact native value.

Value digests detect transport changes without guessing from placeholder text.
`value_sha256` and the compact `fact_set_sha256` answer reference identify native
fact payloads, **not source-file bytes**. `source_sha256` identifies the inspected
file. The compact reference avoids requiring a model to copy a long inventory;
the server retains and renders the values.

## Existing files and reprocessing

Retained authorized active sources can be inspected locally on request. PDF/PPTX
inspection is read-only and does not start new OCR, vision analysis, source edits,
bulk processing or deployment. Existing native Excel inventories are invalidated
by their new inspection schema and rebuilt from permitted retained bytes.

Refreshing missing native evidence is not inherently a full re-ingestion or
re-embedding job. Existing Search chunks still need explicit processing if normal
retrieval must contain the newly collected facts. Missing source bytes can
require an authorized new upload. Holds/revocations must be resolved through
normal authorization, never by falling back to reviewer-only storage.

Legacy snapshots cannot establish exact attribute presence or text bindings.
Re-ingesting an intentionally defective source does not add Alt text, repair its
tags/order, or establish accessibility compliance.

## Validation and before/after controls

The committed ZIP contains only verified synthetic native fixtures, not raw
conversation exports, account metadata or customer documents. Tests verify
their hashes before use and ensure parsing does not modify source bytes.

| Control | Required result |
|---|---|
| C03/C04/C05 PDF | Exact Info Author/Keywords; separate raster/vector evidence; footer Artifact association; tagged/tree state remains distinct from raw marked content. |
| C04 PDF | Step 2 binds before Step 1 in logical order; heading is actually P; the meeting sentence is unmarked. |
| C08/C11 XLSX | Absent description/title attributes are not native empty strings; C11 D3 is a real checked cell control and D4/D5 remain Boolean-only. |
| C09-R3/C10-R3 PPTX | Eight supported displayed objects including the decorative ellipse; slide-local footer/number origin; object-linked formatting. |
| C10-R3 contrast | Meeting text is Arial 18 non-bold `#E8E8E8` on native `#FCFAF6`, ratio 1.18:1; no assumed white background. |
| Word preservation | Existing comment/reply/resolution, reviewer/body separation and comment-free controls remain supported. |
| Answer rejection | Incorrect drafts are corrected or rejected before saved publication; exact native values are rendered from retained facts. |

Regression suites:

- `functional_tests/test_native_document_fidelity.py`
- `functional_tests/test_native_document_fidelity_pipeline.py`
- `functional_tests/test_native_document_fidelity_http.py`
- Existing accessibility/style, Excel inventory/evidence, Word-comment,
  orchestration action/citation, and content-screening suites.

Tests use offline external-I/O doubles, including SDK-default Cosmos point
responses. The changed search module's unchanged storage owners retain reviewed
real-owner SDK evidence in `functional_tests/cosmos_response_boundaries.json`.
The validation record is repository/local evidence, not proof of a deployed
beta repair.

### Recorded local results

| Selection | Result |
|---|---|
| Native fidelity, existing accessibility/style, Excel inventory/evidence, Word comments, native action/lineage/citation and publication regressions | 243 passed |
| Core Cosmos contract suites plus the affected real search/upload storage-owner SDK regression | 246 passed |
| New native fidelity suites plus schema-bound cursor replay under optimized Python | 51 passed |
| Cosmos inventory review | 1,094 owners, 425 doubles, zero review gaps |
| Documentation surface coverage | 7/7 checks passed; generated inventory unchanged/current |
| Documentation site quality | 6/6 checks passed |
| Whitespace check | Passed |

These runs block Python network access and replace external blob/model I/O.
Existing dependency, Swagger and older test-return deprecation warnings remain.
The registry-wide 225-target `--run-contracts` sweep was stopped without
completion; its full result is not claimed. Core contracts and the affected
owner-runtime evidence were run separately as recorded above.

## Limits

Native parents are bounded previews, with separate continuation and coverage.
PDF content decoding, malformed streams, complex tables, unmarked vector-art
grouping and unsupported references can remain partial. PPTX support is not
full rendered/grouped/master-artwork evaluation; unsupported backgrounds or
inheritance cannot establish contrast. Excel inspection does not execute
formulas, macros, ActiveX/OLE or arbitrary controls, and saved-cell/style limits
also bound control discovery. None of these reports is WCAG, Section 508 or
PDF/UA certification.
