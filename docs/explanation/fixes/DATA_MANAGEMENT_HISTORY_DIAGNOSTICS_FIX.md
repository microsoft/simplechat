# Data Management History Diagnostics Fix

Fixed in version: **0.250.220**
Tracking issue: [#1275](https://github.com/microsoft/simplechat/issues/1275)

## Issue Description

`GET /api/admin/data-management/backups` returned **503** and the Backup Inventory panel showed the generic message *"Data Management history could not be loaded. Please try again later or review application logs."*

The instruction to review application logs was not actionable: the only log line emitted was

```
[DEBUG][ERROR][Log] [DATA_MANAGEMENT] Data Management history could not be loaded. --
 {'history_list': 'backups', 'reason': 'history_provider_unavailable',
  'maintenance_required': False, 'error_type': 'CosmosHttpResponseError'}
```

`error_type` is the exception class name only. The provider status code and message were discarded, so the failure could not be classified from telemetry.

## Root Cause Analysis

Two separate defects.

**Provider detail was dropped at the raise site.** `_raise_data_management_history_unavailable` constructed `DataManagementHistoryUnavailableError` without retaining the originating status code or message, and `_data_management_history_unavailable_response` logged only `type(original_error).__name__`.

**Classification was too narrow.** `_is_data_management_history_index_error` required status `400` *and* the literal substring `"composite index"`. Any other provider failure — including throttling — fell through to the generic branch, producing an identical opaque 503 regardless of cause.

There was also no retry for throttled reads beyond the Cosmos SDK default, and no way for the UI to distinguish a transient condition from a permanent one.

### Investigation notes

Several candidates were eliminated before concluding that the instrumentation itself was the blocking problem:

| Candidate | Outcome | Evidence |
|---|---|---|
| Missing composite index | Ruled out | Cosmos Maintenance reports Indexing Policy Status **Aligned**, 7 containers checked, **Missing Expected Indexes: 0**. `data_management_jobs` is among the checked containers. |
| Parameterized `TOP` unsupported | Ruled out | `SELECT TOP @parameter` is valid Cosmos NoSQL. |
| Cosmos diagnostic `400` entries | Red herring | `400` with `requestCharge 0` and sub-millisecond duration is the normal cross-partition query-plan negotiation. It appears on every cross-partition query, including `tabular_export_runs` and `settings`, while those code paths log success. |

The remaining candidates are throttling or another non-`400` `CosmosHttpResponseError`. `data_management_jobs` was observed oscillating 1,000 to 5,000 RU on `container_utilization_above_threshold`, and Admin Settings issues a burst of Cosmos-heavy admin calls on page load.

## Technical Details

### Files Modified

| File | Change |
|---|---|
| `application/single_app/functions_data_management.py` | Retain provider detail, classify throttling, broaden index detection, bounded history query retry |
| `application/single_app/route_backend_data_management.py` | Log provider status and message; expose a `retryable` flag |
| `application/single_app/config.py` | Version bump to `0.250.220` |
| `functional_tests/test_data_management_history_pagination.py` | New regression coverage; replaced a brittle exact deployer-version assertion |

### Code Changes Summary

**Provider detail retained.** `DataManagementHistoryUnavailableError` now carries `provider_status_code`, `provider_message`, and `retryable`. The route logs `status_code` and `error` alongside the existing fields. Provider text is confined to operator logs and never enters the browser payload; `safe_message` remains a fixed, non-reflective string.

**Throttle classification.** `_is_data_management_history_throttle_error` matches status `429`/`503` or the text "request rate is large" / "too many requests", and raises with `DATA_MANAGEMENT_HISTORY_BUSY_MESSAGE` plus `retryable=True`. The route surfaces `retryable: true` so the UI can offer a retry rather than pointing at logs.

**Broader index detection.** `_is_data_management_history_index_error` still requires status `400`, but now also matches `ORDER BY` combined with "does not have a corresponding" or "not served", so maintenance guidance survives provider wording drift.

**Bounded retry.** `_query_data_management_history_items` retries up to `DATA_MANAGEMENT_HISTORY_QUERY_MAX_ATTEMPTS` (3) for throttled and transient transport errors, with jittered backoff capped at `DATA_MANAGEMENT_HISTORY_QUERY_MAX_RETRY_DELAY_SECONDS` (4). Non-retryable errors fail on the first attempt as before. Each retry logs the attempt, status code, delay, and provider message.

## Validation

```bash
python -m pytest -q functional_tests/test_data_management_history_pagination.py
```

`12 passed`

| Test | Assertion |
|---|---|
| `test_history_index_errors_match_alternate_provider_wording` | Index guidance still triggers when the provider omits the word "composite" |
| `test_history_throttling_is_retried_then_reported_as_busy` | A `429` retries exactly `DATA_MANAGEMENT_HISTORY_QUERY_MAX_ATTEMPTS` times, then reports `history_provider_throttled` with `retryable=True` and no provider text in the safe message |
| `test_history_failures_capture_provider_detail_for_operator_logs` | `provider_status_code` and `provider_message` are populated, absent from `safe_message`, and a non-retryable `403` does not retry |
| `test_history_provider_index_errors_are_actionable` | Existing coverage still passes |

**Regression probe.** Neutralizing `_is_data_management_history_throttle_error` fails `test_history_throttling_is_retried_then_reported_as_busy`, confirming the test exercises the new classification rather than passing incidentally.

**Full Data Management suite:** 150 passed, 1 failed. The failure, `test_data_management_backup_durability.py::test_backup_recovery_and_admin_progress_are_bounded_and_sanitized`, is pre-existing on `origin/Development` and unrelated.

### Drive-by test fix

`test_deployers_apply_the_data_management_history_index` asserted `deployer_version == "1.0.24"` and began failing when `deployers/version.txt` advanced to `1.0.25`. This is the exact brittle pattern the repository instructions prohibit for version assertions. It now uses `compare_simplechat_versions(deployer_version, "1.0.24") >= 0`, preserving the intent — the deployer must include the history index change — without breaking on future bumps.

### Before / After

| Behavior | Before | After |
|---|---|---|
| Log content on failure | Exception class name only | Class name plus provider status code and sanitized message |
| Throttled read | Immediate generic 503, "review application logs" | Retries up to 3 times, then retryable busy guidance |
| Index error wording drift | Generic 503 | Maintenance guidance |
| Browser payload | Generic error string | Same string, plus `retryable` when applicable |
| Provider text exposure | Not exposed | Still not exposed |

## Follow-up

The underlying provider failure is still unconfirmed. Once this ships, the next occurrence will record the status code and message directly, which should identify it in a single log line. If it proves to be throttling, the bounded retry added here may resolve it outright; the source blob checkpoint batching in `0.250.218` also reduces sustained write pressure on the same containers.

## Cross-References

- Issue: [#1275](https://github.com/microsoft/simplechat/issues/1275)
- Related: `docs/explanation/fixes/DATA_MANAGEMENT_HISTORY_INDEX_500_FIX.md`
- Functional test: `functional_tests/test_data_management_history_pagination.py`
