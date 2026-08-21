# Tabular Artifact Routing and Startup Fix

Fixed in version: **0.250.149**

Related issue: **microsoft/simplechat#1031**

## Issue Description

An exhaustive 200-row tabular request generated the correct downloadable CSV shape but also emitted all rows into the assistant response. A separate 300-row durable export returned a concise handoff, but remained at zero processed rows for several minutes before its first checkpoint.

The behavior was inconsistent across prompt wording and input file formats. Direct durable replay was limited to CSV sources, while Excel workbooks fell back to foreground tabular analysis.

## Root Cause

Three independent orchestration problems combined:

- Tabular routing used a narrower CSV format detector than the shared generated-file pipeline, so valid wording such as `complete downloadable CSV` could bypass the durable route.
- A direct-source preparation error returned control to foreground synthesis, allowing exhaustive generated rows to be placed in chat.
- Shadow schema planning ran synchronously even though its schema was not activated. The runner then generated the full first batch alone to discover the production schema, creating two serial model waits before any row checkpoint.

The durable replay descriptor and stager were also hard-coded to `.csv`, despite the shared tabular plugin already supporting CSV and Excel formats.

## Technical Details

### Files Modified

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/functions_settings.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`

### Generic Source Contract

The version-pinned source descriptor now records the configured tabular source format and deterministic worksheet scope. Supported formats are read from `TABULAR_EXTENSIONS`, currently:

- `csv`
- `xlsx`
- `xls`
- `xlsm`

Workbook rows replay in workbook sheet order. Resume uses the saved physical source position, and source ETags are checked before and after workbook replay. CSV replay remains chunked and bounded-memory.

### Artifact-Only Responses

Tabular CSV output recognition now consumes the shared generated-file format decision. Once an exhaustive tabular artifact request is recognized, direct preparation failures produce safe failed-artifact metadata with assistant-table suppression. They do not fall through to inline exhaustive generation.

### Faster Startup

Shadow planning no longer invokes a model on the production critical path. Active planning remains unchanged when explicitly selected by rollout configuration.

For unplanned source-backed structured exports, the server snapshots a small schema-probe batch size, checkpoints that first batch, and then uses the normal model-aware batch size under configured concurrency. The public status reports `Preparing Source`, `Planning Output`, or `Starting` before the first completed batch.

## Validation

Coverage verifies:

- the previously missed `complete downloadable CSV` wording uses durable artifact routing;
- CSV, XLSX, XLS, and XLSM descriptors share one replay contract;
- multi-sheet workbook rows preserve workbook order and resume position;
- source preparation failures suppress inline exhaustive output;
- shadow planning performs no blocking model call;
- schema-probe estimates match first and subsequent batch limits;
- startup status text is safe and phase-specific.

Validated with:

```bash
python -m py_compile application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py application/single_app/route_backend_chats.py application/single_app/functions_tabular_generated_exports.py application/single_app/functions_settings.py application/single_app/config.py functional_tests/test_tabular_row_orchestration_scale.py
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -q
python -m pytest functional_tests/test_tabular_background_generated_exports.py -q
```

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.148** to **0.250.149** for this generic tabular artifact routing and startup fix.