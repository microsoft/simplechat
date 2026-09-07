# Cosmos Backup Continuation Token Fix

Fixed in version: **0.250.209**
Tracking issue: [#1258](https://github.com/microsoft/simplechat/issues/1258)

## Issue Description

Scheduled and manual Data Management backups silently omitted every Cosmos container that held more than one page of documents. Affected containers were recorded as failed resources and were absent from the backup artifact set entirely, while the job itself reported `completed_with_warnings`.

In practice this meant the two largest containers in most deployments — `personal_conversations` and `personal_messages` — were never backed up, and the failure was easy to overlook because the overall job still reported success-with-warnings.

Observed in App Service console logs:

```
[DATA_MANAGEMENT] Cosmos backup source page read failed. -- {'container': 'conversations', 'status_code': 400,
 'error': '(BadRequest) Invalid Continuation Token ActivityId: d009399c-468b-44b2-94a8-8c4515e0cf79,
 Microsoft.Azure.Documents.Common/2.14.0'}
```

## Root Cause Analysis

`_iter_backup_cosmos_source_items` rebuilt the Cosmos query on every page and replayed the previous pager's continuation token into the new pager:

```python
continuation_token = None
while True:
    source_iterable = container.query_items(          # new query object per page
        query="SELECT * FROM c ORDER BY c.id",
        enable_cross_partition_query=True,
        max_item_count=DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE,  # 100
        ...)
    page_iterator = source_iterable.by_page(continuation_token=continuation_token)
    ...
    continuation_token = getattr(page_iterator, "continuation_token", None)
```

A cross-partition Cosmos query is merged client side by the SDK. The continuation token surfaced by the pager belongs to the underlying per-partition request and is not valid for resuming the merged query. Rebuilding `query_items(...)` each iteration additionally discarded the SDK's cross-partition execution context, so the merge state could not be restored regardless of the token.

Page one always succeeded; page two always failed with `BadRequest: Invalid Continuation Token`. Because `400` is non-retryable in `_is_retryable_backup_cosmos_error`, the resource failed immediately with zero retries.

The 100-document boundary matched `DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE` exactly:

| Container | Documents | Pages | Result |
|---|---|---|---|
| `public_documents` | 84 | 1 | completed |
| `personal_documents` | 59 | 1 | completed |
| `group_documents` | 39 | 1 | completed |
| `collaboration_messages` | 21 | 1 | completed |
| all other containers | <= 21 | 1 | completed |
| `personal_conversations` | > 100 | 2+ | failed |
| `personal_messages` | > 100 | 2+ | failed |

### Contributing observability gaps

Two logging gaps made the defect far harder to diagnose than it should have been:

1. Per-item source blob transfer failures were never logged. `_run_backup_source_blob_transfer` folded every exception into a `failure_summary` string written only to the backup state document (last 50 entries) and the encrypted manifest. A run with 19,978 failed blobs produced zero log lines; a 47 MB console log export covering the whole backup window contained 72,465 `[DEBUG][Log]` lines and none containing "backup".
2. Application Insights carried no message text. `_build_logger_extra` reduced every string property to a length and the emitted trace message was always the constant `[SIMPLE_CHAT_LOG_EVENT]`, so traces could not identify which event fired.

## Technical Details

### Files Modified

| File | Change |
|---|---|
| `application/single_app/functions_data_management.py` | Drain a single Cosmos pager; add source blob failure logging and bounded failure-reason rollup helpers |
| `application/single_app/functions_appinsights.py` | Retain sanitized message text and allowlisted diagnostic keys in log properties |
| `application/single_app/config.py` | Version bump to `0.250.209` |
| `functional_tests/test_data_management_backup_cosmos_pagination.py` | New regression coverage |

### Code Changes Summary

**Cosmos source pagination.** The query is now built once and a single pager is drained to exhaustion. Retries call `next()` on the same pager so the SDK's cross-partition execution context is preserved, and no continuation token is ever passed to `by_page()`. Page normalization, client-side sorting, cutoff filtering, cancellation checks, and RU/retry telemetry are unchanged. The non-paged fallback used by lightweight test doubles is retained and now shares the same page-finalization helper.

**Source blob failure logging.** `_execute_backup_source_blob_resource` now logs the first failure for a resource, logs enumeration failures, and emits one rollup at resource completion containing failure counts and the distinct failure reasons. Two new helpers keep this bounded:

- `_record_backup_failure_reason` tallies distinct reasons up to `DATA_MANAGEMENT_BACKUP_MAX_LOGGED_FAILURE_REASONS` (10) and aggregates the remainder into an `Other backup failures.` bucket.
- `_summarize_backup_failure_reasons` renders the tally as a single frequency-ordered string.

This keeps 19,000 failures at a handful of log lines rather than one line per item.

**Application Insights properties.** `_build_logger_extra` now emits `sc_message` containing the sanitized message text, and preserves the sanitized value of an explicit allowlist of non-sensitive diagnostic keys (`job_id`, `resource`, `resource_name`, `container`, `container_name`, `error`, `error_type`, `failure_summary`, `failure_reasons`, `index_name`, `operation`, `service`, `stage`, `status`, `step`, `task_name`, `reason`, `attempt`). Values are truncated to `LOGGER_SAFE_TEXT_MAX_LENGTH` (1024) and message text to `MAX_LOG_STRING_LENGTH` (8192). Sensitive keys still collapse to a `_present` boolean, all other strings still reduce to a length only, and `sanitize_log_message` redaction is unchanged.

### Testing Approach

`functional_tests/test_data_management_backup_cosmos_pagination.py` uses a fake pager that raises `400 Invalid Continuation Token` if any continuation token is supplied, reproducing the production failure directly.

## Validation

Focused suite:

```bash
python -m pytest -q functional_tests/test_data_management_backup_cosmos_pagination.py
```

| Test | Assertion |
|---|---|
| `test_multi_page_cosmos_source_drains_a_single_pager` | 300 documents across 3 pages stream fully; query built exactly once; `by_page` only ever receives `None` |
| `test_cutoff_and_unpaged_fallback_still_stream` | Cutoff epoch drops exactly the out-of-range document; non-paged fallback streams every item |
| `test_failure_reason_rollup_is_bounded` | Distinct reasons stay bounded, overflow aggregates, summary is frequency-ordered |
| `test_logger_extra_retains_sanitized_diagnostics` | Message text and allowlisted diagnostics retained; secret value never emitted |
| `test_version_is_at_least_fix_version` | `config.py` version floor |

Regression suite across all `functional_tests/test_data_management_*.py` files: **147 passed, 1 failed**. The single failure, `test_data_management_backup_durability.py::test_backup_recovery_and_admin_progress_are_bounded_and_sanitized`, was confirmed pre-existing on `origin/Development` by stashing these changes and re-running it. It is unrelated to this fix.

### Before / After

| Behavior | Before | After |
|---|---|---|
| Container with <= 100 documents | Backed up | Backed up |
| Container with > 100 documents | `400 Invalid Continuation Token`, resource failed, absent from artifact set | Fully streamed and backed up |
| Blob transfer failures | No log output at all | First failure logged plus bounded rollup with counts and distinct reasons |
| App Insights trace | `[SIMPLE_CHAT_LOG_EVENT]` with lengths only | Sanitized message text plus allowlisted diagnostic values |

## Cross-References

- Issue: [#1258](https://github.com/microsoft/simplechat/issues/1258)
- Feature documentation: `docs/explanation/features/DATA_MANAGEMENT_BACKUP_MIGRATION.md`
- Functional test: `functional_tests/test_data_management_backup_cosmos_pagination.py`
