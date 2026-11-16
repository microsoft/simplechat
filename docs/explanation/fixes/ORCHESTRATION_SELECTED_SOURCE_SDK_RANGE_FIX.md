# Selected-source Azure SDK range fix

Current version: **0.261.369**

Fixed in version: **0.261.369**

Application version: `application/single_app/config.py`.

## Issue and root cause

An available selected spreadsheet could fail orchestration source preparation
before a plan was shown. The shared reader supplied a bounded `length` to
`BlobClient.download_blob` without supplying `offset`. Azure Blob SDK
`12.24.1`, pinned by the application, rejects that combination with a
`ValueError` before sending a download request.

The screening boundary wraps downloader failures as `DocumentHeldError`.
Consequently, the user saw the safe source-preparation error rather than the
underlying SDK argument error. This did not establish that the uploaded file
had failed screening, that a model had failed, or that a chart/export operation
had run.

The defect was reproduced offline through the production reader and the real
SDK. Production telemetry corroborated successful upload, authorized source
resolution and successful blob-property reads followed by `DocumentHeldError`.
The original inner exception and deployed commit were not recorded, so the
telemetry alone does not prove that exception's origin.

## Technical changes

`application/single_app/functions_orchestration_bootstrap.py` now supplies
`offset=0` alongside `length=max_bytes + 1`. The same reader supports selected
tabular sources across personal, group and public workspaces; the correction is
not specific to a filename, prompt, fixture or requested output format.

The read still checks blob size before download and uses
`MatchConditions.IfNotModified` with the expected ETag. Its per-source and
aggregate budgets, timeouts, retry policy, current actor authorization,
screening release proof, content-hash validation and metadata revision fences
are unchanged. Failed reads do not become empty successful previews.

Planning samples remain discovery data, not full execution input. Totals,
charts and original-row exports must still use complete native records.
Review-mode execution and file creation continue to require approval.

## Debug diagnostics

When **Enable Debug Logging** is enabled, the existing `log_event` debug-only
console path emits `[ORCHESTRATION_CONTEXT]` source-read diagnostics:

| Field | Meaning |
| --- | --- |
| `operation` | `selected_source_read` |
| `stage` | Metadata, blob properties/download, source integrity or final revision check |
| `status` | Read stage started, read completed or read failed |
| `max_bytes` / `content_bytes` | Numeric read budget and completed byte count |
| `conversation_id_hash` | Hashed correlation supplied by the orchestration service owner |
| `error_type` | Exception class for a failed read |
| `reason` | Immediate underlying exception class, when screening wrapped an error |

These details help distinguish an SDK download failure from a held source,
integrity failure or revision change without disclosing exception messages.
They are available in the application's console logs, not a new
Application Insights forwarding path. Existing ordinary failure telemetry
continues unchanged.

The new diagnostics are silent when debug logging is off. They contain no
filenames, storage paths/URLs, ETags, source bytes, table samples, prompts,
credentials or raw identity values. Errors are re-raised without changing
their screening or client-visible behavior.

## Usage and impact

Deploy the corrected application code before retrying a new selected-file
request. No data migration, old-conversation repair, fixture-specific handling,
new capability or setting is required. The fix does not replay failed turns
or perform historical artifact creation.

See [Create files with orchestration](../../guides/create-files-with-orchestration.md)
and the earlier [selected-source planning fix](ORCHESTRATION_SELECTED_SOURCE_PLANNING_FIX.md).

## Validation

`functional_tests/test_orchestration_selected_source_sdk.py` executes the real
reader, screening boundary, parsers and Azure Blob SDK with an in-memory HTTP
transport and blocked network access. It verifies range and ETag headers,
returned bytes, CSV/XLSX inputs, workspace scopes, exact size limits,
storage/revision failures, screening holds and hashes, debug gating and
Review-mode HTTP planning.

The existing `test_orchestration_selected_source_planning.py` separately covers
the complete CSV/XLSX input/output matrix, original rows beyond preview samples,
native totals/subtotals, chart data and approval boundaries.
`test_orchestration_source_access.py` covers current authority failures.

With the application and functional-test directories on `PYTHONPATH`, the final
SDK-backed suite passed **30 cases** using:

```powershell
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard --tb=short --disable-warnings functional_tests\test_orchestration_selected_source_sdk.py
```

After merging the latest V2 base and aligning the application version to
**0.261.369**, the combined SDK, selected-source planning, source-access,
orchestration Cosmos-response, external-bootstrap, cleanup-bootstrap,
image-reader, workflow chat-execution and streaming-telemetry checks passed
**326 cases**:

```powershell
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard --tb=short --disable-warnings functional_tests\test_orchestration_selected_source_sdk.py functional_tests\test_orchestration_selected_source_planning.py functional_tests\test_orchestration_source_access.py functional_tests\test_orchestration_cosmos_response_contract.py functional_tests\test_orchestration_external_bootstrap.py functional_tests\test_orchestration_cleanup_bootstrap.py functional_tests\test_orchestration_deliverables.py::test_the_image_reader_refuses_a_deleted_or_moved_image functional_tests\test_workflow_chat_execution.py functional_tests\test_appinsights_streaming_context.py
```

The earlier cold action-credentials bootstrap suite also passed **9 cases**.

The SDK regression failed before the correction with the SDK's missing-offset
`ValueError`, wrapped by the unchanged screening boundary. Afterward it observes
the bounded `x-ms-range` and `If-Match` headers and receives the original bytes.
The storage-boundary inventory was refreshed and its six affected bootstrap
owners reviewed; unchanged Cosmos normalization and mapping consumers retain
their contracts.

`python scripts\check_cosmos_response_boundaries.py --run-contracts` reported
**1,067 owners, 413 doubles and zero review gaps**. The repository-wide runtime
phase stopped on an unrelated missing Yamcs test dependency after nine passing
tests. Restoring the pinned dependency in the isolated test environment made
that failing shared-chat case pass; the entire runtime set was not rerun.

Documentation checks passed with:

```powershell
python functional_tests\test_docs_app_surface_coverage.py
python functional_tests\test_docs_site_quality.py
```

Results were **7/7** coverage checks and **6/6** site-quality checks.

Broader document-transform tests exposed two delivery-only recovery failures
that also reproduce using the unchanged HEAD bootstrap factories. They are
outside this fix and were not suppressed or repaired here.

Production investigation was read-only. Local deterministic tests do not claim
successful deployed UI or live-model execution.
