# Backup Inventory GROUP BY Aggregate Fix

**Fixed in version: 0.260.002**

## Issue Description

The Backup Inventory panel in Admin Settings → Data Management always failed to load. The
UI reported `Backup history is temporarily unavailable. Please try again.` and every summary
tile rendered zeros:

- Available backups: `0`
- Full backups: `0`
- Partial backups: `0`

This happened even when backups had completed successfully, and even when the job list itself
loaded correctly. The `GET /api/admin/data-management/backups` route returned `503`.

## Root Cause

`_get_data_management_backup_global_summary()` computed its counts with a single grouped
aggregate:

```sql
SELECT c.backup_type, c.status, COUNT(1) AS count FROM c
WHERE c.type = @type AND c.operation = @operation
GROUP BY c.backup_type, c.status
```

The `azure-cosmos` Python client does not advertise support for `GroupBy` combined with a
**non-VALUE aggregate** (`COUNT(1) AS count`). During query plan negotiation the service
rejects the request:

```
(BadRequest) {"code":"BadRequest","message":"Query contains the following features,
which the calling client does not support:\nNone GroupBy NonValueAggregate ..."}
```

The `BadRequest` propagated out of `_query_data_management_history_items`, was classified as
a provider failure, and surfaced to the admin as a generic `503`.

This was never a throttling, indexing, or capacity problem. Cosmos Maintenance consistently
reported the composite index as **Aligned / 0 missing / 7 containers checked**, and the
`400` entries with `requestCharge = 0` and sub-millisecond duration visible in
`AzureDiagnostics` are the normal, benign cross-partition query-plan negotiation.

Because the aggregate was part of the summary from the moment the feature shipped, Backup
Inventory had never worked in any deployment.

### Why tests did not catch it

`FakeHistoryContainer` in `functional_tests/test_data_management_history_pagination.py`
implemented `GROUP BY c.backup_type, c.status` in Python and returned grouped rows. The test
double supported a query shape the real client cannot serve, so the suite passed against a
query that always failed in production.

## Technical Details

### Files Modified

| File | Change |
|------|--------|
| `application/single_app/functions_data_management.py` | Replaced the grouped aggregate with bounded `SELECT VALUE COUNT(1)` queries; added `_count_data_management_backups()` |
| `application/single_app/templates/admin_settings.html` | Added retention cleanup tooltip and expandable help panel |
| `functional_tests/test_data_management_history_pagination.py` | Fake now rejects `GROUP BY` / non-VALUE aggregates like the real client; added coverage |
| `application/single_app/config.py` | Version bump |

### Code Changes

A new helper issues a single supported scalar aggregate:

```python
def _count_data_management_backups(extra_clauses=None, extra_parameters=None):
    """Count backups with a VALUE aggregate; the Python client cannot serve GROUP BY here."""
    clauses = ["c.type = @type", "c.operation = @operation"]
    parameters = [...]
    clauses.extend(extra_clauses or [])
    parameters.extend(extra_parameters or [])
    rows = _query_data_management_history_items(
        query=f"SELECT VALUE COUNT(1) FROM c WHERE {' AND '.join(clauses)}",
        parameters=parameters,
    )
    return _safe_int(rows[0], default=0, minimum=0) if rows else 0
```

The summary now issues six bounded counts — `total`, `available`, `running`, `failed`,
`full`, and `partial`. `SELECT VALUE COUNT(1)` is fully supported by the Python client and is
already used elsewhere in this module. The two `SELECT TOP 1 *` queries that resolve
`latest_full` and `latest_partial` were already valid and are unchanged.

This deliberately avoids the alternative of projecting every backup row and aggregating on the
client, which would grow unbounded as backup history accumulates. Each count is served by
Cosmos and returns a single scalar.

### Retention Cleanup Guidance

Admins had no way to tell what **Run Retention Cleanup** did, and a run that deleted nothing
looked like a failure. The button now carries a hover tooltip, and an `(i)` toggle expands an
inline panel explaining that cleanup:

- permanently deletes backups older than the configured retention period, plus their stored artifacts;
- only considers backups in a finished state;
- protects the most recent successful full backup when **Keep latest full backup** is enabled;
- deletes at most 25 backups per run;
- also runs automatically on the configured schedule.

The panel calls out that `found no expired backups to delete` means every backup is still
inside the retention window, which is expected rather than an error.

## Validation

### Test Results

`functional_tests/test_data_management_history_pagination.py` — **14 passed**.

New and updated coverage:

- `test_backup_summary_avoids_unsupported_group_by_aggregates` asserts no emitted history query
  contains `GROUP BY` or `COUNT(1) AS`, and that exactly six `SELECT VALUE COUNT(1)` queries are issued.
- `test_retention_cleanup_button_explains_what_it_does` asserts the tooltip, the `(i)` toggle,
  the collapse target, and the explanatory copy are present.
- `FakeHistoryContainer` now raises the real `BadRequest ... GroupBy NonValueAggregate` error
  instead of emulating `GROUP BY`.

### Regression Probe

The fix was neutralized by restoring a grouped aggregate. Two tests failed with the exact
production error:

```
RuntimeError: (BadRequest) Query contains the following features, which the calling client
does not support: GroupBy NonValueAggregate.
```

- `test_backup_summary_is_global_and_page_independent`
- `test_backup_summary_avoids_unsupported_group_by_aggregates`

The fix was then restored and all 14 tests passed again, confirming the tests fail for the
right reason.

### Before / After

| Behavior | Before | After |
|----------|--------|-------|
| `GET /api/admin/data-management/backups` | `503` | `200` |
| Backup Inventory tiles | Always `0` | Actual counts |
| Backup Inventory table | Error banner | Backup rows |
| Retention cleanup purpose | Undocumented in UI | Tooltip + expandable help |
