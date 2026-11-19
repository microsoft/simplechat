# Deployed retest tool-contract fixes

Fixed/Implemented in version: **0.261.439**

Application version tracking: `application/single_app/config.py`.

## Issue and root causes

The deployed retest exposed analogous failures at different boundaries. Some
calculation plans declared only the columns needed for business work where the
native contract required a complete ordered header. Other plans failed native
semantic validation without a useful lower rejection rule. Document-bound
actions requested Word/Excel-only report comments for PDF/PPTX files. Later
answers could correctly disclose preview limits without finishing the requested
calculation.

Separately, the PDF native reader did not expose readable page annotation
contents through its supported native record path, and an unescaped pipe in a
model-authored native-title table cell truncated the rendered value.

These changes repair the known contracts and reader/serialization gaps. They do
not establish that every historical rejection, arbitrary model plan, calculation
or generated file is now correct. In particular, the historical retained-result
context refusal needs its exact condition isolated before guard behavior changes.

## Technical changes

### Complete source schema is not a projection

`datasets[].columns` now describes an optional assertion of the complete ordered
native header. It includes unused source fields. `project` and `output` keep
their existing job of selecting result fields.

Planning checks an assertion against a matching source inspection when the
complete header is known. It does not guess from sample rows, an incomplete
inspection, another worksheet/header row, or a named-table/range selection.
The execution assertion remains intact. Its failure now has the specific
`source_schema_mismatch` public category rather than a misleading missing
named-results message.

Native semantic validation preserves its owned lower rule in a repairable
`plan_arguments_invalid` error. Draft correction uses the existing allowance,
not unlimited retries. A bound, read-only document Gather draft with an invalid
action reference can also correct that reference from the admitted catalog.
This does not make unavailable integrations available or authorize an operation.

### File-aware comment requests

The action's server-owned source profiles now enumerate compatible report
sections. Modern Word and Excel retain their native comments path. PDF/PPTX
report `sections=comments` is explicitly incompatible; its `native_section`
argument is separate.

One known incompatible request can return corrective feedback before source
reading and within the existing function-call budget. Repeated incompatible
requests, source failures, stale cursors, and permission changes still stop.
No outside effect is repeated.

### Source-backed PDF annotations

Native inspection reads page `/Annots` independently of a tag tree. It preserves
decoded contents, optional author/subject/date/name/state fields, flags and
reply-object references. Supported `/OBJR` references bind the actual annotation
contents rather than reporting every annotation as unresolved text.

Absent, stored-empty, present and inaccessible fields stay distinct. Missing
State/StateModel is not a resolution decision. Malformed or undecodable fields
and bounded record/text limits remain explicit partial/inaccessible evidence.
The canonical audit and native page records carry source/page/object identity.
Original PDFs are not changed.

Native pagination schema 1.1 prevents reuse of cursors whose earlier record
layout does not include the new annotation records.

### Coverage, formatting and retained-result diagnostics

Composition and checking distinguish complete extraction, complete returned
page chains, and completed business work. Earlier partial coverage remains
history; it is not automatically a contradiction of a later verified complete
chain for the same source and section.

Native customer-answer serialization escapes literal source-value pipes in
table cells, including inline code, without rewriting ordinary prose, fenced
examples, headings, lists, block quotes, HTML blocks, delimiters or the stored
native value. Block interruptions end table handling; inline HTML inside a valid
table row does not. The versioned
`native-audit-answer-v5` contract requires older checked preparations to be
revalidated during an explicitly admitted retry.

Retained-alias admission and headless preparation preserve the owned refusal
code and hashed alias/producer/consumer identities. They rethrow the same
failure. The conversation, producer, manifest, external-lineage and source
guards are not bypassed.

## Holistic behavior and scope

Document interpretation, native inspection, deterministic calculation and
composition/delivery remain complementary capabilities. A semantic-only request
does not require calculation. A calculation uses complete relevant data. A
mixed request can interpret reviewer claims and separately compute amounts,
then compose their named evidence together.

No blanket tool pruning, arithmetic-engine replacement, new settings, new
routes, new browser runtime libraries, or deployment changes are included.
Word anchors/replies/done-state, Excel saved values and limitations, and
explicit available-information answers retain their existing contracts.

The documented retained-result policy is also preserved: original document
snapshots are provenance, not reread during alias admission. Conversation/run
ownership and external lineage still require current authorization. Tests that
previously assumed document rereading now check the actual retention policy
and the still-required owner/infrastructure boundaries.

## Files changed

| Area | Main files |
| --- | --- |
| Planning and native contracts | `functions_orchestration_planner.py`, `functions_orchestration_schema.py`, `functions_orchestration_registry.py`, `functions_orchestration_source_context.py`, `functions_orchestration_native_results.py`, `functions_tabular_relational.py` |
| Native readers and request compatibility | `native_document_evidence.py`, `functions_pdf_native_evidence.py`, `functions_accessibility.py`, `functions_native_document_inspection.py`, `functions_search_service.py`, `functions_orchestration_actions.py`, `semantic_kernel_plugins/document_search_plugin.py` |
| Composition and diagnostics | `functions_native_audit.py`, `functions_orchestration_composition.py`, `functions_orchestration_services.py`, `functions_orchestration_execution.py`, `functions_appinsights.py` |
| Version and boundary review | `config.py`, `functional_tests/cosmos_response_boundaries.json` |

## Testing and validation

Focused regressions cover incorrect subset-as-header assertions, precise native
semantic correction, admitted action references, schema-specific execution
failures, and complete retained native computation outputs.

Native tests cover tagged and untagged page annotations, exact contents,
reply-object associations, absent versus empty state, existing Word/Excel
comment behavior, and format correction before any native read.

The real V2 renderer checks the complete native title in one Finding cell at
mobile and desktop widths. Native answer tests preserve ordinary prose, fenced
examples, native source values and citation authority.

Real-module planner diagnostics replace the stale AST-only diagnostic fixture.
SDK-default owner tests renew the module-fingerprint review after the logging
and native report changes; point/query consumers, ETags and conditional updates
remain unchanged.

These are offline, controlled regressions and isolated browser tests. Provider
responses are scripted and cloud network calls are blocked in functional runs.
They do not replace a separately approved deployment and unchanged-source live
acceptance retest.

Local validation completed with **1,565 passing SDK contract tests and zero
Cosmos review gaps**, **272 passing focused contract regressions**, **116 passing
native-answer/search-delivery regressions after final refinements**, and
**11 passing real-component browser table checks**. Both documentation checks
passed; added-line XSS and access-control checks found no issues.

The full contract run initially caught a long-input regression from unnecessarily
verbose chronology guidance. Shortening the guidance restored complete-source
delivery without raising token limits or truncating inputs; the full SDK gate
was then rerun successfully.

## Before and after

Before these changes, a valid-looking source-column subset could reach native
execution and fail under a misleading result-name message; an incompatible
comment request could stop useful native work; and a correct raw native title
could lose text in its rendered table.

Afterward, known header mismatches are rejected early with corrective rules,
execution still checks actual headers, compatible readers remain available,
PDF annotation text is exposed, and native title values remain inside their
intended cells. The exact historical retained-result refusal is not claimed
resolved merely because better diagnostics are now present.
