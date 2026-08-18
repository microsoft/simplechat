> Root cause: every source blob backup compared a `list_blobs()` ETag against a
> `get_blob_properties()` ETag. Azure returns those in different transport formats,
> so the equality check never held and no source blob was ever backed up.

# Source Blob Backup ETag Fix

Fixed in version: **0.250.219**
Tracking issue: [#1271](https://github.com/microsoft/simplechat/issues/1271)

## Issue Description

Every source blob in every Data Management backup failed with:

```
Source blob changed while it was being backed up.
```

The failure rate was exactly 100% across all source blob containers, with zero retries. Backups reported `completed_with_warnings`, so the condition was easy to miss.

Production evidence from job `data_management_partial_20260818T0300Z`:

| Container | Blobs read | Copied | Failed |
|---|---|---|---|
| `user-documents` | 71 | 0 | 71 |
| `group-documents` | 427 | 0 | 427 |
| `public-documents` | 95 | 0 | 95 |
| `personal-chat` | 19,394 | 0 | 19,394 |

Net effect: user documents, group documents, public documents, and all chat attachments had **never** been backed up.

## Root Cause Analysis

`_transfer_backup_source_blob` performs a post-upload consistency check that the source did not change mid-transfer:

```python
current_source_properties = source_blob_client.get_blob_properties()
current_source_etag = _safe_text(_get_backup_blob_property(current_source_properties, "etag"))
if source_etag and current_source_etag != source_etag:
    raise RuntimeError("Source blob changed while it was being backed up.")
```

The two operands originate from different Azure SDK code paths that format ETags differently:

| Value | Origin | SDK path | Format |
|---|---|---|---|
| `source_etag` | `list_blobs()` via `_build_backup_blob_source_item` | `get_blob_properties_from_generated_code()` reads the XML `<Etag>` element | `0x8DE...` |
| `current_source_etag` | `get_blob_properties()` | `BlobProperties(**headers)` reads the HTTP `ETag` header | `"0x8DE..."` |

The HTTP `ETag` response header is an RFC 7232 quoted-string; the List Blobs XML element is not. `azure-storage-blob==12.24.1` performs no normalization in either direction, so the comparison was effectively `0x8DE... != "0x8DE..."`, which is always true.

`RuntimeError` is not retryable under `_is_retryable_backup_blob_error`, so each blob failed immediately. Job telemetry reported `Retries / throttles: 0 / 0`, which corroborates a non-transient, first-attempt failure.

### Why the failure was expensive

The guard runs at the *end* of the transfer, after ranged reads, block staging, and `commit_block_list`. Every blob was therefore fully downloaded, optionally encrypted, and uploaded to the backup container before being discarded as failed. Those artifacts were committed with `pending` metadata and never promoted to `succeeded`, leaving orphaned pending artifacts behind on each run.

The ranged reads also send that same unquoted ETag as an `If-Match` precondition and Azure accepted them, which independently confirms the blobs did not actually change and that only the Python-side string comparison was wrong.

## Technical Details

### Files Modified

| File | Change |
|---|---|
| `application/single_app/functions_data_management.py` | ETag normalization for the equality check; batched source blob checkpoints |
| `application/single_app/config.py` | Version bump to `0.250.219` |
| `functional_tests/test_data_management_backup_source_blob_etag.py` | New regression coverage |
| `functional_tests/test_data_management_backup_cosmos_pagination.py` | Converted to real assertions so pytest reports failures |

### Code Changes Summary

**ETag normalization.** A new `_normalize_backup_etag` helper strips transport quoting and the optional `W/` weak-validator prefix. It is applied only at the comparison site:

```python
source_etag = _safe_text(source_item.get("source_etag"))
normalized_source_etag = _normalize_backup_etag(source_etag)
...
current_source_etag = _normalize_backup_etag(
    _get_backup_blob_property(current_source_properties, "etag")
)
if normalized_source_etag and current_source_etag != normalized_source_etag:
    raise RuntimeError("Source blob changed while it was being backed up.")
```

`source_item["source_etag"]` deliberately retains the exact value returned by `list_blobs()`, so the `If-Match` precondition sent on ranged reads is byte-for-byte unchanged from current production behavior. The guard itself is preserved; a genuine mid-transfer source change still fails.

**Checkpoint batching.** `record_transfer_result` previously called `persist()` for every item, producing one Cosmos write per blob — 19,394 writes for `personal-chat` alone, which capped throughput at roughly 6 items/second and accounted for the 74-minute runtime. A new `maybe_persist` helper checkpoints when the manifest buffer reaches `DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE` (100) or when `DATA_MANAGEMENT_BACKUP_CHECKPOINT_INTERVAL_SECONDS` (15) has elapsed, whichever comes first. The job lease is still asserted on every item, and the existing tail `persist()` continues to flush the final partial batch. Worst-case re-work after an interrupted run stays bounded at 100 items or 15 seconds.

### Scope Check

The migration path contains a visually similar comparison in `_copy_source_blobs_to_target`, but it sources `source_properties` from `get_blob_properties()`, so both operands are already quoted. Migration is **not** affected and was left unchanged.

## Validation

```bash
python -m pytest -q functional_tests/test_data_management_backup_source_blob_etag.py
```

| Test | Assertion |
|---|---|
| `test_etag_normalization_strips_transport_quoting` | Quoted, unquoted, weak, and padded ETags all normalize identically |
| `test_listed_and_fetched_etags_compare_equal` | The raw listed ETag is preserved for `If-Match`, and both formats compare equal once normalized |
| `test_transfer_succeeds_across_list_and_get_etag_formats` | The production transfer path succeeds end to end when the listing is unquoted and the fetch is quoted |
| `test_genuinely_changed_source_blob_still_fails` | A source blob whose ETag changes after download is still rejected |
| `test_verified_artifact_matches_source_version` | Reuse detection still keys off the recorded source version |
| `test_checkpoint_interval_is_bounded` | Checkpoint interval and batch size stay within safe bounds |
| `test_version_is_at_least_fix_version` | `config.py` version floor |

**Regression probe.** Neutralizing `_normalize_backup_etag` causes four of the seven tests to fail, including the end-to-end transfer, which reports the exact production message:

```
Transfer must succeed, got 'failed' ('Source blob changed while it was being backed up.')
```

**Full Data Management suite:** 154 passed, 1 failed. The single failure, `test_data_management_backup_durability.py::test_backup_recovery_and_admin_progress_are_bounded_and_sanitized`, was confirmed pre-existing on `origin/Development` and is unrelated.

### Test reliability fix

While validating, the repository's standard functional-test template was found to hide failures under pytest. Tests written as:

```python
def test_x():
    try:
        assert ...
        return True
    except Exception:
        return False
```

return a value rather than raising, and pytest reports them as **passed** with only a `PytestReturnNotNoneWarning`. A deliberately broken build reported `7 passed` while the underlying transfer was failing.

Both backup test files added in this and the preceding fix now assert directly and return `None`, with the `__main__` block wrapping each call to preserve standalone console output and exit codes. Suite warnings dropped from 13 to 1.

### Before / After

| Behavior | Before | After |
|---|---|---|
| Source blob backup | 100% failure, `Source blob changed while it was being backed up.` | Succeeds |
| Genuine mid-transfer change | Rejected | Still rejected |
| `If-Match` precondition value | Raw listed ETag | Unchanged |
| Checkpoint writes | One Cosmos write per blob | Batched per 100 items or 15 seconds |
| Failing tests under pytest | Reported as passed | Reported as failed |

## Cross-References

- Issue: [#1271](https://github.com/microsoft/simplechat/issues/1271)
- Follow-up (cosmetic): [#1272](https://github.com/microsoft/simplechat/issues/1272)
- Preceding fix: `docs/explanation/fixes/COSMOS_BACKUP_CONTINUATION_TOKEN_FIX.md`
- Functional test: `functional_tests/test_data_management_backup_source_blob_etag.py`
