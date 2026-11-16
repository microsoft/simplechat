# Orchestration progress, native workbook citations, and cleanup fix

Fixed/Implemented in version: **0.261.417**
Current application version: **0.261.417**, tracked in
`application/single_app/config.py`.

## Issues and root causes

Successful running-status reconciliation incorrectly restored `transportUnknown`.
The inline progress row prioritized this flag and generic answer-check activity
over the actual confirmed task. A running record was therefore displayed as an
uncertain execution even after a successful status read.

Native Excel annotation references used `Worksheet cell`, outside the canonical
source-marker grammar, and synthetic colon-delimited IDs that were not Search
chunks. Merely accepting the label would still misidentify the document or open
an unrelated worksheet preview instead of the cited reviewer evidence.

Saved-analysis cleanup passed conversation ID, message ID, and user ID into
`delete_thoughts_for_message(message_id, user_id)`. Permissive test callbacks
accepted the extra argument and concealed the production TypeError.

## Technical changes

### Confirmed progress and recovery

The V2 controller clears connection uncertainty after an admitted successful
status read. Live scoped step events clear disconnection warnings and advance
the recovery revision, fencing older status/step reads. Existing attempt and
output revisions remain in place. Reconciliation performs read-only polling,
not automatic retries or duplicate execution.

`OrchestrationPlanCard.tsx` keeps the task/phase headline while check-stage detail
remains in the expanded activity. Genuine disconnection shows reconnecting and
last-known progress. Saving the final response is distinct from confirmed
publication, waiting, failure, or cancellation.

### Exact retained native evidence

The native adapter emits canonical `Location` references, preserves structured
worksheet/cell and annotation metadata, and keeps inventory coverage separate.
`functions_orchestration_result_runtime.py` projects the exact committed
prepared-result reference alongside explicit document identity and source version.
The reference survives lineage traversal, saved publication, streamed completion,
and delivery reconciliation. Composition excludes transport descriptors from
model input while supplying the literal source marker.

The existing authenticated `/api/get_citation` route has a native-evidence branch.
It validates owner/conversation, producer, committed digest, output kind, exact
citation/record pairing, and source lineage. Current workbook access, screening,
version, and revision are checked before returning evidence. It never searches
by cell or splits a synthetic annotation ID to guess a document.

V2 and classic citation handling recognize historical `Worksheet cell` markers
only with exact retained metadata. Missing/conflicting evidence remains visibly
unavailable. Source tracking requires the exact native citation ID instead of
selecting multiple same-cell annotations from a filename/location hint.

The evidence view shows reviewer text, author, worksheet/cell, available
timestamps/reply status, and saved cell values separately. Workbook preview is
an explicit second action, not a substitute for cited comment evidence.

### Scoped message cleanup

`functions_saved_analysis.py` now passes only message ID and user ID to the
actual thought helper. Signature-accurate tests cover legitimate owner partitions,
other messages, foreign owners, mirrored/workflow references, archive/permanent
deletion, and required-result cleanup failures. Authorization and upstream-result
retention policies are unchanged.

## Validation

### Changed implementation files

- `application/single_app/config.py`
- `application/single_app/functions_saved_analysis.py`
- `application/single_app/functions_orchestration_adapters.py`
- `application/single_app/functions_orchestration_result_runtime.py`
- `application/single_app/functions_orchestration_composition.py`
- `application/single_app/functions_citation_tracking.py`
- `application/single_app/route_backend_documents.py`
- `application/single_app/static/js/chat/chat-citations.js`
- `application/v2_ui/src/lib/orchestrationController.ts`
- `application/v2_ui/src/stores/orchestrationStore.ts`
- `application/v2_ui/src/components/chat/OrchestrationPlanCard.tsx`
- `application/v2_ui/src/components/chat/OrchestrationRecoveryNotice.tsx`
- `application/v2_ui/src/lib/citations.ts`
- `application/v2_ui/src/lib/endpoints.ts`
- `application/v2_ui/src/lib/types.ts`
- `application/v2_ui/src/components/chat/CitationChip.tsx`

Related documentation updates are in `docs/guides/inspect-excel-workbooks.md`,
`docs/guides/review-and-edit-orchestration-plans.md`,
`docs/reference/chat-controls.md`, `docs/reference/logging-tags.md`, and
`docs/explanation/features/CHAT_ORCHESTRATION.md`.
The regenerated application-surface inventory has no semantic change.
`functional_tests/cosmos_response_boundaries.json` refreshes the affected module
fingerprints; unchanged storage-owner bodies retain their reviewed contracts and
real SDK runtime evidence.

### Local validation results

Run Python commands with:

```powershell
$env:PYTHONPATH="$PWD\application\single_app;$PWD\functional_tests"
```

The final functional bundle passed **128 tests**:

```powershell
python -m pytest functional_tests\test_saved_analysis_cleanup.py functional_tests\test_saved_analysis_cleanup_http.py functional_tests\test_orchestration_attachment_native_evidence.py functional_tests\test_orchestration_native_citation_delivery.py functional_tests\test_orchestration_search_citation_delivery.py functional_tests\test_orchestration_analysis_citation_delivery.py functional_tests\test_orchestration_citation_persistence.py functional_tests\test_orchestration_dependency_citations.py functional_tests\test_orchestration_followup_citation_provenance.py functional_tests\test_v2_citations.py functional_tests\test_v2_enhanced_citations.py functional_tests\test_saved_analysis_cosmos_owner_contract.py functional_tests\test_v2_public_source_owner_sdk.py -q --disable-warnings --basetemp=.test-artifacts\functional-final --tb=short --maxfail=2
```

The final browser bundle passed **93 tests**:

```powershell
python -m pytest ui_tests\test_v2_orchestration_recovery.py ui_tests\test_v2_orchestration_quiet_activity.py ui_tests\test_v2_stream_citation_delivery.py ui_tests\test_v2_excel_citation_inspection.py -q --disable-warnings --basetemp=.test-artifacts\ui-final --tb=short --maxfail=2
```

Node regression checks passed **42 tests**:

```powershell
node --test functional_tests\test_native_workbook_citation_parser.mjs functional_tests\test_v2_orchestration_progress_lane.mjs functional_tests\test_v2_orchestration_run_progress_status.mjs functional_tests\test_v2_stream_citation_delivery.mjs functional_tests\test_v2_web_iq_citations.mjs
```

Additional completed checks:

- `npm --prefix .\application\v2_ui run build`: passed; existing bundle-size warning.
- `npm --prefix .\application\v2_ui run build -- --outDir ..\..\.test-artifacts\v2-final`:
  final-source production build passed with the same existing warning; isolated
  output avoids modifying the application preview while other checks run.
- `python functional_tests\route_tests\test_route_blueprint_policy_inventory.py`: **15/15 passed**.
- `python functional_tests\route_tests\test_route_unauthenticated_policy_contract.py`: **10/10 passed**.
- `python functional_tests\route_tests\test_route_policy_test_coverage.py`: **3/3 passed**.
- `python scripts\build_docs_inventory.py`: regenerated successfully.
- `python functional_tests\test_docs_app_surface_coverage.py`: **7/7 passed**.
- `python functional_tests\test_docs_site_quality.py`: **6/6 passed**.
- `python scripts\check_broken_access_control.py application\single_app\route_backend_documents.py application\single_app\functions_orchestration_result_runtime.py application\single_app\functions_saved_analysis.py`: passed.
- `python scripts\check_xss_sinks.py application\single_app\static\js\chat\chat-citations.js application\v2_ui\src\components\chat\CitationChip.tsx application\v2_ui\src\lib\citations.ts`: passed.
- `node --check application\single_app\static\js\chat\chat-citations.js`: passed.
- The Impeccable mechanical detector returned no findings for the three changed
  citation/progress components.

The full Cosmos response-boundary gate passed **2,005 tests and 431 subtests**,
with **0 review gaps** across 1,094 owners and 425 doubles. The command used a
workspace-local argument-file directory and pytest scratch location:

```powershell
$env:PYTEST_ADDOPTS='--basetemp=.test-artifacts\cosmos-pytest'
python -u -c "import pathlib,runpy,tempfile; tempfile.tempdir=str(pathlib.Path('.test-artifacts').resolve()); runpy.run_path('scripts/check_cosmos_response_boundaries.py',run_name='__main__')" --run-contracts
```

This executes the repository's unmodified `--run-contracts` checks with its
network guard, including the reviewed real-owner SDK evidence.

Two unrelated checks exposed existing baseline failures:
`test_citation_revision_lookup_fix.py` still expects obsolete public-lookup
wiring, and `test_logging_tag_standardization.py` finds seven existing
mixed-case logging tags. The affected assertions/tags were reproduced against
unchanged `HEAD`; this change does not alter those behaviors or expand scope
to repair them.

Targeted coverage is in:

- `functional_tests/test_orchestration_attachment_native_evidence.py`:
  real paged inventories, notes, threaded roots/replies, repeated cells on
  different sheets, partial/empty inventories, stale versions/revisions,
  denied/held sources, uncommitted references, and authenticated native lookup.
- `functional_tests/test_orchestration_native_citation_delivery.py`:
  real producer-to-saved-message and replayed-delivery identity.
- `functional_tests/test_native_workbook_citation_parser.mjs`:
  canonical/historical markers, unavailable/ambiguous metadata, exact locators,
  and ordinary document/web/Microsoft 365 regression coverage.
- `functional_tests/test_saved_analysis_cleanup.py` and
  `functional_tests/test_saved_analysis_cleanup_http.py`:
  actual two-argument helper and deletion routes, including optimized Python.
- `ui_tests/test_v2_orchestration_recovery.py`,
  `ui_tests/test_v2_orchestration_quiet_activity.py`, and
  `ui_tests/test_v2_stream_citation_delivery.py`:
  real controller/components, status-read failure/recovery, stale-read fences,
  task/check-stage separation, desktop/mobile native evidence, keyboard opening,
  saved reload, separate preview, and explicit denied evidence.

These are local/offline regression tests, not production verification. No
deployment, production data mutation, run replay, or historical-answer
regeneration is part of this fix.
