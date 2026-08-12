# Tabular Source Descriptor Generalization Fix

Fixed/Implemented in version: **0.250.127**

Related work: Refs #1031

## Issue

Exhaustive per-row CSV requests could fail when the tabular mini-agent selected `filter_rows` or `search_rows`. Those tools returned bounded preview pages but did not attach the replayable, version-pinned source descriptor used by the durable generated-export runner. The export selector therefore rejected otherwise valid partial pages instead of replaying the full source cohort.

## Root Cause

Only `query_tabular_data` produced a durable `query_tabular_data` source descriptor. The generated-output route also accepted descriptors only from that function, even when `filter_rows` or `search_rows` represented an equivalent row-local CSV query.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_csv_query.py`
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_large_result_pagination.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `functional_tests/test_tabular_entity_lookup_mode.py`

### Code Changes

- Added a strict row-local AST allowlist for generated case-insensitive string equality, containment, prefix, and suffix expressions.
- Attached authorized, blob-version-pinned replay descriptors to replayable CSV `filter_rows` and `search_rows` results without changing their bounded preview output.
- Propagated explicit replay errors for semantics such as `normalize_match=true` that cannot be represented equivalently.
- Generalized durable generated-output routing to accept server-issued descriptors from all three row-returning tabular functions.
- Added an exhaustive execution mode for natural phrases such as "for each row," "every row," and "one row per," steering the mini-agent toward a full-cohort `query_tabular_data` call.
- Updated `application/single_app/config.py` from version `0.250.126` to `0.250.127`.

## Impact Analysis

- Exhaustive CSV exports can continue from a bounded `filter_rows` or `search_rows` preview by replaying the complete authorized cohort in the existing durable runner.
- Ordinary previews retain their current pagination and output-trimming behavior.
- Deterministic aggregation remains on the existing direct execution path.
- Group, public, personal workspace, and chat-upload source authorization remains bound to the exact container, blob path, scope, and ETag.
- Non-replayable semantics fail closed and do not publish a partial CSV.

## Validation

- A simulated 3,000-row `filter_rows` request returns a trimmed preview while bounded replay yields all 3,000 rows.
- Two 60-row pages from a 3,000-row cohort queue one source-backed durable run with `expected_row_count=3000`.
- A filtered multi-column `search_rows` request replays the same complete cohort.
- `normalize_match=true` produces an explicit failed-export status and queues no run.
- Existing pagination, source-version, durable retry, cancellation, fencing, and authorization contract tests continue to pass.

## Before and After

Before, an incomplete `filter_rows` candidate ended with a page-gap validation failure because no source replay was available. After this fix, replayable filters and searches queue the full source cohort; unsupported semantics report why replay is unavailable and no partial export is created.