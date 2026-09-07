# Tabular Analyze/Search Parity Default Activation Fix

Fixed in version: **0.250.186**

## Issue Description

Customer testing showed Chat/Analyze still answering exhaustive row-by-row tabular requests (for example, "for each row, answer these eight questions") by producing detailed answers for roughly the first row and a half, then stating the remaining rows were unprocessed, truncated, or outside a bounded evidence handoff. This matched the exact failure mode the multi-phase tabular Analyze/Search parity roadmap (`feature/tabular-analyze-search-parity`, `feature/analyze-artifact-output-contract`) was built to eliminate.

## Root Cause Analysis

The durable-preflight parity path (`_maybe_execute_pure_tabular_analyze_preflight` in `functions_workflow_runner.py` for Analyze, and `maybe_queue_search_tabular_generated_output` in `route_backend_chats.py` for Search) is gated by three backend-only settings: `tabular_request_planner_mode`, `enable_tabular_search_shared_preflight`, and `enable_tabular_analyze_durable_preflight`. All three defaulted to `off`/`False` in `functions_settings.py`, and none had an admin UI toggle, so no deployed environment ever ran the durable, exhaustive-coverage path unless an operator manually edited the stored settings document directly (there was no supported way to do this from the Admin Settings UI). Every request instead fell back to the legacy bounded foreground path, which answers using only the tool-call rows that fit in one synthesis turn and explicitly reports the rest as missing/truncated evidence.

## Version Implemented

Fixed in version: **0.250.186**

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/config.py`
- `docs/reference/admin_configuration.md`
- `docs/explanation/features/TABULAR_ANALYZE_SEARCH_PARITY_ROLLOUT.md`
- `functional_tests/test_tabular_analyze_search_parity_default_activation.py`

### Code Changes Summary

- `tabular_request_planner_mode` now defaults to `active` (was `off`).
- `enable_tabular_search_shared_preflight` and `enable_tabular_analyze_durable_preflight` now default to `True` (were `False`).
- Added `_apply_tabular_parity_env_kill_switch()` in `functions_settings.py`, applied in `get_settings()`'s `_format_result()` choke point on every return path. When the environment variable `SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT` is truthy, it forces `tabular_request_planner_mode` back to `off` and both shared-preflight flags back to `False`, regardless of the stored settings document. This gives operators an emergency rollback path without requiring an admin UI toggle or a direct settings edit, consistent with treating always-on behavior as "on unless an operator opts out," not "off until an operator opts in."
- `enable_tabular_mixed_deferred_composition_planning` and `enable_tabular_multifile_execution_unit_planning` remain `False` by default; per existing documentation these are planning-only metadata controls with no implemented durable execution behind them yet, so enabling them would not change runtime behavior.

### Testing Approach

- New functional test asserts the three defaults via AST-based extraction of `get_settings()`'s literal `default_settings` dict (avoids importing the full Flask app), and asserts the env kill switch forces them back off.
- Re-ran the existing tabular parity suites (`test_tabular_shared_request_planner.py`, `test_tabular_analyze_shared_preflight_adapter.py`, `test_tabular_search_shared_preflight_adapter.py`, `test_analyze_artifact_phase7_rollout_rollback.py`, `test_tabular_phase8_ui_telemetry_rollout.py`, `test_tabular_execution_settings_sanitization.py`) to confirm no regressions; all pass unchanged because they construct explicit settings fixtures rather than relying on `get_settings()` defaults.
- Compiled all changed Python files.

## Impact Analysis

Chat, Search, and Analyze now route exhaustive per-row/per-source tabular requests through the durable generated-output path by default, matching the behavior validated across the parity roadmap's Phases 1-9 and the analyze-artifact-output-contract Phases 1-7D. Operators who need to roll back during an incident set one environment variable instead of editing settings directly; no code deploy or Cosmos edit is required to disable, and none is required to re-enable.

## Validation

### Before

- `tabular_request_planner_mode=off`, `enable_tabular_search_shared_preflight=False`, `enable_tabular_analyze_durable_preflight=False` in every environment by default.
- Exhaustive row-by-row Chat/Analyze requests answered a small bounded subset of rows, then reported the remainder as unprocessed/truncated evidence, even though the durable parity infrastructure to answer exhaustively already existed and was fully merged.

### After

- New defaults route exhaustive tabular requests through the durable preflight/generated-output path automatically.
- `functional_tests/test_tabular_analyze_search_parity_default_activation.py` passes 2/2.
- Existing tabular parity regression suites remain green.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.250.186**.
