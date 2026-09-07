# TABULAR PARITY STALE SETTINGS MIGRATION FIX

Fixed in version: **0.250.198**

## Issue Description

After deploying the "line" terminology + `enable_tabular_hierarchical_analysis` default-activation
fix (`0.250.197`), the customer re-tested the exact same exhaustive per-line prompt
("For each line in this document, I need eight questions answered... Go line by line...")
through both Analyze and Search. Instead of truncating (the prior symptom), the request now
hung indefinitely — the UI showed "Tabular analysis... Current tabular step: Analyzing workbook
evidence (attempt 2 of 3)" frozen at 76-80% for 20+ minutes with no error and no completion.

Production log analysis (`TABULAR_SK_ANALYSIS` tag) confirmed the legacy foreground SK
mini-agent (`run_tabular_sk_analysis()` / `TabularProcessingPlugin`) was running for both the
Analyze and Search test conversations, and continued calling tools (`filter_rows`, `count_rows`)
for 10+ minutes without ever converging on a complete answer for a 200-row x 8-question
exhaustive request. Critically, the string `hierarchical_analysis` did not appear anywhere in
the log — the new durable planner path was never reached at all, even though the prior fix had
already verified (via direct unit-level function calls) that `get_tabular_generated_output_task_type()`
correctly resolves to `hierarchical_analysis` for this exact prompt when
`enable_tabular_hierarchical_analysis` is enabled.

## Root Cause Analysis

`get_settings()` merges the code-level `default_settings` dict into the persisted Cosmos
`app_settings` document via `deep_merge_dicts(default_settings, settings_item)`. Per that
function's own docstring: **it only fills in keys that are *missing* from the existing
document; it never overwrites a key that already exists.**

Four backend-only tabular durable-preflight parity flags (no admin UI toggle) were originally
introduced with conservative `off`/`False` defaults:

- `tabular_request_planner_mode` (was `'off'`)
- `enable_tabular_search_shared_preflight` (was `False`)
- `enable_tabular_analyze_durable_preflight` (was `False`)
- `enable_tabular_hierarchical_analysis` (was `False`)

The very first time `get_settings()` ran in any existing deployment after each of these keys was
introduced, `deep_merge_dicts()` treated the key as "missing," added it to the settings document
with its *then-current* off/False value, and immediately upserted that document back to Cosmos DB.

Later releases raised the code-level defaults to `active`/`True`
(`TABULAR_ANALYZE_SEARCH_PARITY_DEFAULT_ACTIVATION_FIX`, v0.250.186, for the first three; this
session's line-terminology fix, v0.250.197, for the fourth). **Neither change had any effect for
an existing deployment**, because the persisted document already had each key stored with the
old value, and `deep_merge_dicts()` never overwrites an existing key. The customer's environment
had been running SimpleChat long enough that all four flags were already persisted with their
original off/False values, so every settings load kept resolving them back to legacy behavior —
completely independent of what the code-level defaults said.

Both `maybe_queue_search_tabular_generated_output()` (Search, `route_backend_chats.py`) and
`_maybe_execute_pure_tabular_analyze_preflight()` (Analyze, `functions_workflow_runner.py`) gate
the durable preflight on these same settings:

```python
if not _settings_bool(settings, 'enable_tabular_analyze_durable_preflight', False):
    return None
planner_mode = str((settings or {}).get('tabular_request_planner_mode') or '').strip().lower()
if planner_mode not in {'shadow', 'active'}:
    return None
```

With the persisted values stuck at `False`/`'off'`, both code paths returned `None` immediately,
so the request always fell through to the legacy bounded foreground path
(`run_tabular_analysis_with_thought_tracking()` -> `run_tabular_sk_analysis()`), which has its
own internal retry loop (`attempt N of 3`) that is not designed to complete an exhaustive
200-row x 8-question narrative request — it kept calling more tools without ever converging,
producing the observed indefinite hang.

## Version Implemented

- **0.250.198**

## Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_parity_stale_settings_migration.py` (new)
- `docs/explanation/fixes/TABULAR_PARITY_STALE_SETTINGS_MIGRATION_FIX.md` (new)
- `docs/explanation/release_notes.md`

## Code Changes Summary

- Added `TABULAR_PARITY_DURABLE_PREFLIGHT_ACTIVE_DEFAULTS`, a map of the four backend-only
  tabular durable-preflight parity flags to their intended active values.
- Added `normalize_tabular_parity_durable_preflight_defaults(settings)`, which unconditionally
  corrects any of the four flags found with a stale/off value to its active default, mutating
  the settings dict in place and returning whether anything changed. Because these settings have
  no admin UI, any stored value that differs from the active default can only be stale drift,
  never an intentional admin choice — so it is safe to correct unconditionally on every load.
- Wired the new function into `get_settings()`'s existing merge/migration sequence (alongside
  `normalize_key_vault_reminder_settings()` and similar helpers) and included its `changed` flag
  in the upsert-trigger condition, so corrected values are persisted back to Cosmos DB.
- This runs independently of `_apply_tabular_parity_env_kill_switch()`, which is still applied
  afterwards in `_format_result()` and continues to provide the same emergency rollback path
  (forcing the flags back off at read time) regardless of what is now persisted in Cosmos DB.

## Testing Approach

- New `functional_tests/test_tabular_parity_stale_settings_migration.py` (6/6 passing):
  validates the active-defaults map, confirms stale pre-activation values are upgraded, confirms
  already-active settings are left untouched (no unnecessary Cosmos churn), confirms partial
  drift on a single flag is corrected without disturbing the others, confirms non-dict input is
  handled safely, and confirms the migration is wired into `get_settings()`'s merge and
  upsert-trigger condition via source inspection.
- Re-ran the existing tabular parity/settings regression suite: `test_tabular_analyze_search_parity_default_activation.py`,
  `test_tabular_line_terminology_routing_fix.py`, `test_tabular_shared_request_planner.py`,
  `test_tabular_analyze_shared_preflight_adapter.py`, `test_tabular_search_shared_preflight_adapter.py`,
  `test_tabular_phase8_ui_telemetry_rollout.py`, `test_tabular_execution_settings_sanitization.py`,
  `test_analyze_artifact_phase7_rollout_rollback.py`, `test_tabular_combined_artifact_set_download_visibility.py`,
  `test_tabular_combined_output_schema_deferral_fix.py` — all pass.
- Confirmed two unrelated failures (`test_get_settings_merge_bool_regression.py`,
  `test_settings_deep_merge_persistence_fix.py`) are pre-existing on unmodified `Development` via
  `git stash`/re-run/`git stash pop`; both check exact literal source strings from versions
  0.240.002/0.240.006 that have since evolved (more migration conditions were added to the
  upsert-trigger `if` block over time), unrelated to this fix.
- Compiled `functions_settings.py` with `py_compile`.

## Impact Analysis

- Any existing SimpleChat deployment whose Cosmos `app_settings` document already contains these
  four keys (i.e., any deployment that has been running since before each flag's default was
  raised) will have them corrected to active on the very next settings load, with the correction
  persisted back to Cosmos DB so it survives future reads/restarts.
- This closes the gap left by the prior two "raise the default" fixes
  (`TABULAR_ANALYZE_SEARCH_PARITY_DEFAULT_ACTIVATION_FIX` and this session's line-terminology fix),
  which only changed the code-level default and had no effect on any deployment with a
  pre-existing settings document.
- The env kill switch (`SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT`) continues to work
  unchanged as the sole emergency rollback path.
- New deployments (fresh Cosmos document, no existing `app_settings` item) were never affected by
  this bug — they always read the current code-level defaults directly.

## Validation

### Before

- A settings document persisted before any of the four flags' defaults were raised keeps
  `tabular_request_planner_mode='off'`, `enable_tabular_search_shared_preflight=False`,
  `enable_tabular_analyze_durable_preflight=False`, `enable_tabular_hierarchical_analysis=False`
  forever, regardless of code-level default changes, because `deep_merge_dicts()` never
  overwrites existing keys.
- Exhaustive per-row/per-line Analyze and Search requests silently fall back to the legacy
  bounded foreground SK mini-agent path, which can hang indefinitely on genuinely exhaustive
  requests instead of completing or reporting a clear error.

### After

- `normalize_tabular_parity_durable_preflight_defaults()` corrects all four flags to their active
  defaults on the next settings load for any deployment with stale persisted values, and persists
  the correction back to Cosmos DB.
- `functional_tests/test_tabular_parity_stale_settings_migration.py` passes 6/6.
- Existing tabular parity regression suites remain green.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.250.198**.
