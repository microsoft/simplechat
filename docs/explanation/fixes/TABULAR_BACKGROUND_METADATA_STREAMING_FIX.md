# Tabular Background Metadata Streaming Fix

Fixed in version: **0.250.145**

Related issue: **microsoft/simplechat#1031**

## Issue Description

After a durable tabular run was accepted, the foreground SSE response could end with `Something went wrong while streaming the response. Please try again.` instead of returning the background status card metadata. The failure affected structured export, hierarchical analysis, and combined modes.

Production evidence showed the stream remained open without content and then failed while constructing accepted-run metadata:

```text
NameError: name 'row_count' is not defined
build_background_tabular_generated_output_metadata
```

The same exception was caught earlier by direct source-backed queueing, which caused 300, 3,000, and 30,000-row requests to fall back to the slower foreground orchestration path.

## Root Cause

`build_background_tabular_generated_output_metadata(...)` added a `requested_row_count` field but referenced a local `row_count` variable that had never been initialized. The safe public status already contained the authoritative run row count, but the metadata builder did not normalize it into the local scope.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`

### Code Changes

The metadata builder now derives one normalized row count from `_build_run_public_status(...)` and uses it for `requested_row_count` and all queued-run summary variants. The change does not alter SSE framing, durable queue semantics, source authorization, or background execution.

### Impact Analysis

- Accepted durable runs can complete their foreground handoff instead of emitting a stream error.
- Direct source-backed queueing no longer falls back because metadata construction raised `NameError`.
- Export, analysis-only, and combined handoff payloads retain the same public schema and wording.

## Validation

An executable regression calls the production metadata builder for structured export, hierarchical analysis, and combined modes and verifies that the requested row count comes from public run status.

Validated with:

```bash
python -m py_compile application/single_app/functions_tabular_generated_exports.py application/single_app/config.py functional_tests/test_tabular_row_orchestration_scale.py
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -k "background_metadata or phase_two" -q
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -q
```

Before the fix, the focused regression reproduced the production `NameError`. After the fix, accepted-run metadata is returned with the expected row count and handoff mode.

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.144** to **0.250.145** for this streaming handoff fix.