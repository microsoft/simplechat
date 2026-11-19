# Native audit reliability and truthful coverage

Fixed/Implemented in version: **0.261.426**.
Application version: `application/single_app/config.py`.
Dependencies: existing native readers, authorized retained results, configured
orchestration models, and private checking checkpoints. No dependency, service,
setting, route, browser asset, or extraction-schema change is introduced.

**Multi-source follow-up (0.261.428):** Native-audit answers can also cite other
authorized named-input documents without treating them as native fact evidence.
See the [multi-source citation delivery fix](NATIVE_AUDIT_MULTI_SOURCE_CITATION_FIX.md)
for the v4 checking contract. The v3 contract below describes the original
0.261.426 change.

## Issue and root cause

A successful native read could still be followed by an answer-format failure or
an explanation that confused a normalized display default with a stored native
value. Separately, a native-only PDF read could be described in planning as a
visual review even though it supplied no rendered-page comparison.

| Observed problem | Supported cause | Repair |
| --- | --- | --- |
| A genuine supporting page citation was rejected by native-answer validation. | The native contract admitted chunk-reading inputs but allowed answer markers only from native-report invocations. | Use the authorized retained citation projection for supporting citations belonging to the inspected document/version. Keep the native table's provenance separate. |
| Every failed preparation received essentially the same correction policy. | Native JSON, envelope, digest and citation failures were collapsed into ordinary `ValueError` feedback. | Typed, content-free validation codes and specific correction hints; preferred closed provider schemas for preparation/correction; unchanged server validation and correction limits. |
| Workbook prose called absent descriptions exact native empty strings. | Model inputs contained both canonical field states and normalized display aliases, plus an action-model paraphrase. Semantic approval did not establish that every prose claim agreed with native facts. | Project one canonical property representation for reasoning/review, omit the competing aliases and action paraphrase from that view, and explicitly review per-object state claims against the canonical facts. |
| A native-only task promised a rendered PDF comparison. | Native record completeness was being confused with rendered evidence coverage. | Expose the evidence modes and explain the actual native-only boundary in planning, tool guidance, composition and review. |

The investigated failed PDF run reached deterministic answer validation after a
successful gather. Semantic review had not started. The supporting-citation
incompatibility was reproduced separately; its existence does not prove that it
was the exact validation subtype in that historical run. The older failure's
private candidate contents were not recovered, and this fix makes no claim to
have established that historical trigger.

## Technical changes

### Preparation and checking contracts

The preparation/checkpoint contract is now `native-audit-answer-v3`. The customer
JSON transport retains the same `native_claims` plus nonempty Markdown `answer`
shape introduced in v2. The fact-set digest is still distinct from the original
file's `source_sha256`.

Preparation and correction request a closed JSON schema that pins the supplied
fact digest. The existing provider-format compatibility helper may negotiate
JSON-object or prompt-only transport when an endpoint refuses a format. Server
validation still runs in every mode; compatibility never accepts an invalid
answer or consumes a semantic approval from another candidate.

Semantic review receives its assessment schema instead of the native-answer
schema and reviews rendered customer Markdown, not the preparation envelope.
A valid digest authenticates the immutable facts; it does not prove that the
free-form explanation is true.

`NativeAuditAnswerError` distinguishes invalid JSON, duplicate keys, invalid
envelope shape, missing explanation, mismatched fact reference, invalid answer
text, and unknown citation. Correction receives the specific safe code and hint.
The existing correction allowance is not increased.

Private native preparation checkpoints retain the current validation code.
Structured diagnostics use the existing `ORCHESTRATION_EXECUTOR` tag, allowed
`validation_code`, hashed run/conversation/step correlations, and existing
check/correction counts. They contain no candidate, source text, citation marker,
account identity, or plaintext cursor.

An explicit new checking retry can upgrade an older failed v2 checkpoint using
still-authorized retained gather results. It does not silently reuse the old
assessment, repeat source reads, replay an ambiguous correction, or repeat an
outgoing effect.

For a current-version check that exhausted format correction without a valid
preparation envelope, an explicit new attempt can prepare again from the same
authorized retained evidence. It does not resume a correction in the stopped
attempt or change the correction limit within any attempt.

### Citation authority

`native_audit_contract()` keeps native owner citations in `citations` for the
server-rendered factual appendix. `answer_citations` additionally admits matching
document/version citations supplied by the existing authorized retained-result
projection. Different native source versions cannot be combined.

Supporting prose citations do not establish native metadata. A marker-looking
string in source text, an action note, or a filename does not grant another
citation. Unselected document markers remain invalid. Allowlist extraction uses
the owner's terminal citation marker, not every marker-like substring in a label.

### Canonical model-facing evidence

`native_audit_model_inputs()` copies the composition inputs without changing
their retained source records. Canonical field state/value/reason/location facts
remain authoritative; structured property containers and their competing display
aliases are omitted from this reasoning view. Compatibility aliases remain in
the original tool results and storage contracts.

Action-model notes are replaced in that view by a direction to interpret the
source records, rather than supplied as a competing native finding. Redacted or
bounded facts retain the canonical inaccessible state and original digest.
Unverified legacy display snapshots are not presented as freshly inspected
native properties.

`absent`, `present_empty`, `present_value` and `inaccessible` stay distinct.
Whitespace, `false` and zero are not stripped into blanks. The native-specific
review policy checks the explanation, including contradictions between prose
and its accurate appendix, and preserves useful findings during correction.
This is not a deterministic natural-language truth detector.

### Native coverage, not a rendered audit

The contract's `evidence_modes` separates available native records, whether all
sources were freshly inspected, rendered-page comparison, and certification.
The current native path performs neither a rendered-page comparison nor
accessibility certification. Logical order and vector-paint counts do not prove
visual reading order or identify an unlabelled vector group as a bar chart.

The Image composer control generates illustrations; it does not enable PDF
inspection. Building source-bound rendering/vision remains a separate feature.
Existing authorized originals can still be inspected on request, without a
bulk re-ingestion or source-file edit.

## Files and impact

| File | Change |
| --- | --- |
| `functions_native_audit.py` | Typed answer failures, preparation schema, canonical projection, citation authority, evidence-mode and review contracts. |
| `functions_orchestration_composition.py` | Shared projected inputs, stage-appropriate schemas, targeted correction, private validation reason and safe diagnostics. |
| `functions_orchestration_planner.py` | Native versus rendered evidence guidance. |
| `semantic_kernel_plugins/document_search_plugin.py` | Consistent manifest and actual tool descriptions. |
| `config.py` | Application patch version 0.261.426. |
| Native reliability/delivery/HTTP functional suites | Real-contract unit cases and source-backed routing, retention, checking, recovery and delivery controls. |

Authorization, active-source screening, source/continuation binding, immutable
fact rendering, parser and response bounds, secret redaction, Word comments,
Excel inventory schema, and Office saved-state limitations are unchanged.
No global sanitizer, general completeness policy, source document, deployment,
or customer reprocessing is changed.

## Validation and before/after comparison

The focused regressions cover native-plus-chunk citations, spoofed/unselected
markers, source-version conflicts, specific correction reasons, provider format
negotiation, private failed-format checkpoints, legacy checking retry, and
canonical absent/blank/value/inaccessible states. Source-backed HTTP cases
exercise the actual readers, Auto routing, retention, configured checking and
publication with only external I/O and provider replies isolated.

Before the fix, a genuine extra citation could invalidate an otherwise useful
native answer and ambiguous empty aliases could compete with source absence.
After the fix, authorized citations are usable, invalid candidates receive a
specific correction rule, and model-facing native properties have canonical
states. A native-only PDF answer must disclose its visual boundary instead of
claiming a rendered comparison. Genuine access or contract failures still fail
explicitly and never publish an unchecked candidate.

Primary suites:

- `functional_tests/test_native_audit_reliability.py`
- `functional_tests/test_native_audit_answer_delivery.py`
- `functional_tests/test_native_document_fidelity_http.py`
- Existing native fidelity/request, Excel persistence, action lineage/Auto,
  completeness, plugin identity and privacy regression suites.

### Recorded local validation

The following selections passed on the completed 0.261.426 implementation.
Their counts overlap and are not added into a unique-test total.

| Selection | Result |
| --- | --- |
| Focused native contracts, real-source readers, delivery and preservation | 154 passed |
| Shared action binding/lineage, Auto routing, completeness and canonical plugin identity | 151 passed |
| Native reliability/delivery/request contracts under optimized Python | 95 passed |
| Legacy telemetry privacy, isolated process | 5 passed |
| Cosmos boundary inventory verification | 1,094 owners, 425 doubles, zero review gaps |
| Documentation surface coverage / site quality | 7/7 and 6/6 checks passed |
| Changed Python syntax / filename headers | 9 files passed |
| Whitespace check | Passed |

Functional selections used the existing network guard and:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH="$PWD\application\single_app;$PWD\functional_tests"
python -m pytest .\functional_tests\test_native_audit_reliability.py .\functional_tests\test_native_audit_answer_delivery.py .\functional_tests\test_native_inspection_request_contract.py .\functional_tests\test_native_document_fidelity.py .\functional_tests\test_native_document_fidelity_pipeline.py .\functional_tests\test_native_document_fidelity_http.py .\functional_tests\test_excel_inventory_persistence.py -x -q --tb=short -p test_support.cosmos_network_guard -p no:cacheprovider --disable-warnings
python -m pytest .\functional_tests\test_orchestration_document_action_end_to_end.py .\functional_tests\test_orchestration_document_action_lineage.py .\functional_tests\test_orchestration_document_action_binding.py .\functional_tests\test_orchestration_catalog_auto_execution.py .\functional_tests\test_task_completeness_engine.py .\functional_tests\test_task_completeness_runtime.py .\functional_tests\test_plugin_discovery_identity.py -x -q --tb=short -p test_support.cosmos_network_guard -p no:cacheprovider --disable-warnings
python -O -m pytest .\functional_tests\test_native_audit_reliability.py .\functional_tests\test_native_audit_answer_delivery.py .\functional_tests\test_native_inspection_request_contract.py -x -q --tb=short -p test_support.cosmos_network_guard -p no:cacheprovider --disable-warnings
python -m pytest .\functional_tests\test_privacy_logging_telemetry_audit.py -q --tb=short -p test_support.cosmos_network_guard -p no:cacheprovider --disable-warnings
python .\scripts\check_cosmos_response_boundaries.py
python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_site_quality.py
git --no-pager diff --check
```

No storage-owner or double fingerprints changed, so the complete registered
Cosmos contract sweep was not rerun. Existing dependency, Swagger and SWIG
deprecation warnings remain. Early test failures identified outdated expectations
about the model-facing action notes and missing external Search setup; the final
selections above passed with the real ownership and checkpoint guards intact.

Controlled provider replies establish contract behavior, not that a live model
will always interpret an arbitrary document correctly. Deployed-build identity
and fresh live acceptance require separate authorization. Export-only nested
value/digest differences do not establish a loss stage and are not used to
justify a broad sanitizer change.

Related fixes: [Native audit answer delivery](NATIVE_AUDIT_ANSWER_DELIVERY_FIX.md)
and [Native document fidelity](NATIVE_DOCUMENT_FIDELITY_FIX.md).
