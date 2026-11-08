# Orchestration pipeline reliability (v0.261.422)

Fixed/Implemented in version: **0.261.422**, tracked in
`application/single_app/config.py`.

## Issue and root cause

Straightforward document reviews could work in ordinary chat but fail in
Orchestrate. Read-only Application Insights and App Service console investigation
identified separate boundaries, not one general inability to read the files.

| Boundary | Why work stopped | What the failure does not prove |
| --- | --- | --- |
| Planning | A proposed or corrected read step could still omit source wiring or contain another argument/output contract error. The previous shared allowance ended after one correction. | A missing file binding is not evidence that upload extraction or OCR failed. |
| Native Word comments | Valid Word comment requests reached an Excel-only native collector. Ordinary Word style/accessibility metadata was not the structured comment inventory. | A workbook-reader rejection does not mean the Word comments are unreadable. |
| Prepared-answer checking | A checker's evidence reference could fail its transport contract even when useful findings had already been retained. Repair feedback did not provide usable reference labels. | An invalid assessment reference is not itself proof that the prepared answer is factually incorrect. |

Historical generic rejections did not retain every rejected field or raw model
response. This fix does not invent those values or attribute every historical
failure to the same cause.

## Technical details

### Source wiring and bounded plan correction

`functions_orchestration_planner.py` now supplies request-specific source defaults
and fills an absent document binding only when exactly one selection has verified
authorization, available source metadata, and a supported source kind. It acts on
an existing enabled independent reader, including the verified Document Search
action. It does not create a missing step, overwrite explicit IDs, replace dynamic
inputs, narrow multiple selections, or restore disabled work. Editing keeps
explicit source choices.

All normal validators still run on the repaired proposal. The same planner can
then receive at most **two model corrections**, shared across recognized errors:
three total proposals, not two new attempts per error. Repeated unrenderable
clarification uses the remaining original allowance rather than restarting it.
Permission, unavailable-source/capability, provider, and unknown failures remain
terminal.

`functions_orchestration_schema.py` adds owned argument/source rules and bounded
feedback for up to eight safe argument-schema problems in a failing step.
Registered fields or `unknown` are reported instead of arbitrary supplied names
or values. Known incompatible native-comment formats are rejected before
execution.

### Shared Word reader and retained citations

`functions_search_service.py` exposes opt-in `sections="comments"` through the
existing Document Search metadata function. For `.docx`, `.docm`, and `.dotx`,
it uses the existing authorized original-byte service and
`functions_office_media.extract_docx_comments`; no second extraction engine or
new route is introduced. Default stored-metadata calls and default ingestion
parsing preserve their previous behavior.
Comment-only inspection can succeed without stored style metadata; a combined
request still requires its stored sections. A successful comment read cannot
certify absent style or issue metadata as empty.

The strict native path preserves parsed reviewer text and supported replies,
available author/date/resolution, and bounded anchors. A missing resolution flag
stays unknown. Anchors are limited to 300 characters and require an unclipped
closed range to be marked complete. An inspected package without a comments part
is verified empty; missing originals, malformed parts, identity/thread failures,
and resource limits are not successful empty inventories.

`functions_orchestration_excel.py` adds a Word collector alongside the existing
Excel paging/fragment collector. Whole thread records are retained within the
existing budget; over-budget coverage is explicitly partial. The adapter chooses
the collector by source format and rechecks source identity, scope, version, and
revision before retention.

`functions_orchestration_result_runtime.py` supports Word/mixed native evidence
while retaining Excel content-scope compatibility. Native citation resolution
reads the exact committed record with integrity and current source checks, not a
fresh Search fallback. `chat-citations.js`, V2 `CitationChip.tsx`, and its API types
show Word anchors/replies/resolution without worksheet fields or an invalid Excel
preview. Reviewer text remains inert browser text.

### Checker report repair is not answer repair

`functions_task_completeness.py` closes new assessment reference schemas over
the evidence labels actually supplied to that check. Empty evidence permits no
references. Existing compatible exact paths/identifiers still normalize; arbitrary
prose and nonexistent references do not.

One malformed assessment can receive one report repair with allowed labels and
an owned rejection rule. That does not rewrite the candidate or spend an answer
correction merely because the checker named its evidence incorrectly. Genuine
unsupported findings still trigger answer correction and required verification.
Repeated invalid reports, unavailable required checking, and unresolved substantive
deficiencies still block delivery.

`functions_orchestration_composition.py` records content-free checker diagnostics
at both prepared-content and retained-final-answer review boundaries. Existing
checkpoint and answer-correction limits are preserved; they are separate from the
planner's two corrections.

### Privacy and operating diagnostics

The existing planner, adapter, and executor tags record stage, owned rule/code,
actual correction counts, known source format, counts, and applicable hashed
workflow identifiers. Native-reader and checker checkpoints work with debug
logging disabled. Detailed planner snapshots retain their existing debug gate.

No raw failed reference, prompt, source text, filename, ID, or provider exception
message is added to those diagnostics. See the
[logging reference](../../reference/logging-tags.md#native-comments-and-checker-report-repair)
for `Properties.sc_message` queries and the distinction between a reader
checkpoint and a confirmed terminal execution outcome.

## Validation and impact

Regression coverage uses real planner/compiler, Word parser, shared metadata
service, collector, retained result, checker, citation HTTP, and browser rendering
boundaries with external storage/model transport isolated.

| Regression area | Coverage |
| --- | --- |
| Planning | Unambiguous local wiring; immutable explicit/dynamic/disabled work; ambiguous and unavailable selections; mixed errors sharing two corrections; valid third proposals and exhaustion. |
| Native reading | DOCX/DOCM/DOTX comments/replies; absent metadata; empty, missing, malformed, partial, and unsupported inventories; clipped/unclosed anchors; source revocation/change. |
| Answer checking | Legacy and canonical assessment schemas; one invalid-reference repair without candidate rewriting; real serialized diagnostics; repeated unsupported findings still blocked. |
| Citation delivery | Exact retained Word records and replies; HTTP lookup and source checks; desktop/mobile classic and V2 text safety; unchanged Excel preview and saved identities. |
| Storage and imports | Renewed affected Cosmos owner-runtime reviews, real SDK contracts with network blocked, and canonical plugin identity. |

Key suites are `test_orchestration_attachment_native_evidence.py`,
`test_orchestration_planner_contract_recovery.py`,
`test_orchestration_document_planning_recovery.py`,
`test_orchestration_source_kind_planning.py`, `test_task_completeness_engine.py`,
`test_task_completeness_runtime.py`, and `test_orchestration_failure_telemetry.py`.
Browser coverage is in `ui_tests/test_v2_stream_citation_delivery.py` and the
existing Excel/inline-citation suites.

### Verified local results

These runs overlap; their counts are not an aggregate end-to-end success rate.

| Check | Result |
| --- | --- |
| Combined planner, checker, native-reader, action, and citation regressions | 343 passed. |
| Selected-source, conversation-scope, and durable planning-failure regressions | 93 passed. |
| Coupled action, composition, source-integrity, import, extraction, and registry regressions | 262 passed; 3 subtests passed; 1 confirmed baseline case deselected. |
| Classic/V2 Word, Excel, and reopened-citation browser regressions | 30 passed. |
| Affected Search Service owner test using real SDK document shapes with network blocked | 1 passed. |
| Full network-blocked Cosmos contract gate | 2,026 passed; 431 subtests passed; 1,094 owners and 425 doubles reviewed with 0 review gaps. |
| V2 TypeScript/Vite build | Passed. |
| Impeccable detector on the two changed citation clients | Passed; no findings. |
| Documentation inventory coverage and site quality | 7/7 and 6/6 passed, respectively. |

The coupled regression command is:

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -q -p no:cacheprovider --disable-warnings --tb=short --show-capture=no `
    .\functional_tests\test_orchestration_selected_source_planning.py `
    .\functional_tests\test_orchestration_plan_revision_planner.py `
    .\functional_tests\test_orchestration_document_action_binding.py `
    .\functional_tests\test_orchestration_document_action_end_to_end.py `
    .\functional_tests\test_orchestration_composition_metadata_recovery.py `
    .\functional_tests\test_orchestration_compose_output_retry.py `
    .\functional_tests\test_orchestration_retained_analysis_publication.py `
    .\functional_tests\test_orchestration_search_result_integrity.py `
    .\functional_tests\test_orchestration_result_imports.py `
    .\functional_tests\test_plugin_discovery_identity.py `
    .\functional_tests\test_document_accessibility_extraction.py `
    .\functional_tests\test_excel_document_accessibility_extraction.py `
    .\functional_tests\test_orchestration_registry_contract.py `
    -k "not test_an_endpoint_refusing_json_mode_is_asked_again_without_it"
```

The excluded test has an unchanged exact-log expectation that omits the
`requested_format` and `next_format` fields already emitted by the endpoint
client. A separately attempted legacy planner-diagnostics suite also has ten
setup errors because its AST-only harness omits the imported
`STORAGE_FAILURE_CODE`. Both limitations were reproduced against unmodified
HEAD; neither was changed or treated as a product fix. These scoped exclusions
do not waive the full network-blocked storage contract gate.

The full storage gate passed with:

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python .\scripts\check_cosmos_response_boundaries.py --run-contracts
```

The remaining reproducible build/documentation checks are:

```powershell
npm --prefix .\application\v2_ui run build
python .\scripts\build_docs_inventory.py
python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_site_quality.py
```

The documentation quality check verifies source templates and search indexing
contracts; a full Jekyll site build was not run.

This is an offline implementation and contract-verification result, **not a 100%
deployed-model success-rate claim**. Deployment and live replay require separate
approval. The change does not automatically replay historical failures, repair
corrupt input files, certify accessibility compliance, widen source access, or
replace existing Analyze and OCR/vision paths.
