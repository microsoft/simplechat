# Orchestration planner deliverable fields and file-only answers

Fixed/Implemented in version: **0.261.140**, recorded in
`application/single_app/config.py`.

## Issue

Ordinary writing requests and comparisons of selected documents could end with
"The plan could not account for everything you asked to receive," despite the
necessary capabilities being available. The one correction attempt failed too.

A separate file-only planning variant produced valid CSV preparation/rendering
steps but failed result-binding validation because it included
`"final_response": null`.

The selected financial comparison also paired a PDF with a CSV. Planning had
only their display labels, so even a syntactically valid proposal could send
the CSV to narrative-only document comparison and fail during execution.

## Root cause

The planner prompt listed every possible deliverable field in one object shape,
without explicitly distinguishing common fields from fields allowed only for
particular kinds. The validator was more precise:

| Field | Contract |
| --- | --- |
| `format` | Required for files; not a field of an answer, image, chart, or diagram. |
| `quantity` | Optional count of files or images; not a count of answers, records, rows, or pages. |
| `unavailable_reason` | Explains a server-confirmed unavailable deliverable, not a planned one. |

Authorized planner-only reproductions on the configured `gpt-5.6-terra` model
showed the same failure sequence for a writing request and a selected-document
comparison:

1. The model declared an answer with both `format: "markdown-v1"` and `quantity: 1`.
2. Validation reported the first violation, the answer's `format`.
3. The correction removed `format` but kept `quantity: 1`.
4. The remaining violation exhausted the single correction attempt.

The problem was the mismatch between planning guidance and the contract, not a
reason to remove the contract or silently discard requested work.

The file-only variant had another representation mismatch. No chat-text output
is required for a plan that creates a file, but the validator interpreted the
presence of `final_response` as a binding even when its JSON value was null.

Selected-document candidates contained composer labels, not authoritative file
types. The executor already rejects native tabular sources on `document_analyze`
and `document_compare`, but planning did not check that boundary. Another probe
named the PDF only in `analysis_prompt`, omitting the required source IDs/binding.

## Changes

`functions_orchestration_planner.py` now describes required common fields and
kind-specific fields separately, with valid answer and CSV declarations. It
distinguishes named result kinds from downloadable file formats and tells fixed
producers to preserve all their required output declarations.

The correction message explains that validation reports the first failure and
asks the model to recheck the complete declaration, outputs, and bindings.
The correction budget remains one, shared by deliverable violations, known
source-kind mismatches, and missing Analyze source bindings. Invalid proposals
still fail explicitly when that correction cannot produce an admissible plan.

`functions_orchestration_schema.py` treats an absent or null optional
`final_response` as no selected chat-text result and emits the canonical plan
without that field. It does not invent a producer, drop a requested answer, or
turn an empty/malformed object into a valid binding. A declared answer must still
select an actual permitted text/Markdown output.

### Route mixed source types before execution

`functions_orchestration_context.py` now resolves current authorized source
metadata before offering candidates to the planner. The projection adds only
the actual filename and `source_kind`, not storage locators or document contents.
Client labels cannot override that type. Explicit sources are never silently
dropped; inaccessible optional discovery candidates are omitted only after a
definite denial, and operational metadata failures remain errors.

The initial route and plan editor pass these server-owned kinds through planning
and validation. A CSV cannot be assigned to narrative-only Analyze/Compare work.
For a PDF/CSV comparison, the planner can analyze each through compatible
capabilities and compose their named results; bounded document search remains
available for an overview rather than exact tabular computation.

The validator reports `source_kind_invalid` / `narrative_source_required` for
an incompatible assignment. Analyze with neither explicit `document_ids` nor
an input source-set binding reports `source_binding_required` /
`document_sources_required`. These errors receive the same single bounded
correction, with all selected documents and existing capability/authorization
requirements still enforced. Execution rechecks remain in place.

This change works alongside the
[Cosmos response compatibility fix](ORCHESTRATION_COSMOS_RESPONSE_COMPATIBILITY_FIX.md).
Planning a CSV and being able to execute/read its durable attempt were separate
failure paths; both are addressed in this version.

## Validation

The same-model planner-only probes used the production prompt, selected-document
context builder, normalizer, and deliverables compiler. After the change, writing,
comparison, and CSV requests produced valid plans. A repeated CSV case omitted
its required format and was correctly repaired within the existing budget rather
than accepted without one.

Historical raw proposals were not retained, so the reproductions are evidence
of the failure mechanism rather than byte-for-byte copies of those responses.
Comparison document IDs were synthetic; no document contents were analyzed and
no saved conversation, original attempt, Azure configuration, or role assignment
was changed by the probes.

The final mixed-source probe used the production authorized-metadata projection
with synthetic metadata matching the confirmed PDF/CSV file types. It produced
explicitly bound `document_analyze`, `tabular_analyze`, and `compose` steps on
the first attempt, rather than assigning the CSV to narrative-only comparison.

`functional_tests/test_orchestration_deliverables.py` covers:

- The observed format-then-quantity rejection for answers and comparisons.
- A complete correction that retains the answer and both comparison sources.
- File-only null bindings becoming canonical absence.
- Rejection of false, zero, empty string, list, and object bindings.
- Continued rejection of a declared answer with no selected answer producer.

`functional_tests/test_orchestration_cosmos_response_contract.py` starts its
CSV scenario with the null-binding variant and verifies authenticated execution,
saved status, history, and all 50 state/capital records in the downloaded bytes
using real SDK-shaped storage responses.

`functional_tests/test_orchestration_source_kind_planning.py` covers trusted
source-type projection, spoofed labels/types, inaccessible selections, metadata
outages, bounded metadata batches, HTTP planning/repair, source-binding repair,
and plan-editor revalidation without reading contents or executing native work.
