# Approvals API Load Fix

Fixed/Implemented in version: **0.241.021**

## Issue Description

The approvals page could fail to load the pending approval queue because `/api/approvals?page=1&page_size=20&status=pending` returned HTTP 500. When this happened, the browser rendered `Error loading approvals` and users could not review or act on pending approval requests from `/approvals`.

## Root Cause Analysis

The approvals list helper queried the cross-partition approvals container with `ORDER BY c.created_at DESC`. That made the page dependent on Cosmos DB order-by query support and indexing behavior even though the helper already loaded the matching approvals into memory before applying authorization filtering and pagination.

Legacy or partially migrated approval records could also carry unexpected shapes such as `metadata: null`, and direct role checks could receive a missing or scalar roles value. Those shapes could raise Python exceptions during eligibility checks and convert one bad approval record into a full API failure.

## Technical Details

### Files Modified

- `application/single_app/functions_approvals.py`
- `functional_tests/test_approvals_api_load_fix.py`
- `docs/explanation/fixes/v0.241.021/APPROVALS_API_LOAD_FIX.md`
- `application/single_app/config.py` tracks the current fix version `0.241.021`

### Code Changes Summary

- Removed the Cosmos SQL `ORDER BY` clause from the approvals list query.
- Added local sorting by `created_at` after the cross-partition query returns matching approval records.
- Added normalization helpers for user role lists and approval metadata dictionaries.
- Hardened approval visibility and approval-right checks so missing roles or `metadata: null` do not crash the API.
- Added per-record eligibility error handling so one malformed approval is skipped and logged instead of failing the full approvals list response.

## Testing Approach

- Added `functional_tests/test_approvals_api_load_fix.py` with an in-memory Cosmos-like approvals container.
- Verified the approvals query does not emit `ORDER BY` while still returning newest approvals first.
- Verified authorization helpers tolerate missing roles and legacy `metadata: null` approval records.
- Verified this fix document and the current config version are present.

## Validation

### Before

- `/api/approvals` could return 500 when the cross-partition order-by query failed.
- A single malformed legacy approval record could stop the entire approvals page from loading.

### After

- `/api/approvals` can load pending approvals without relying on Cosmos DB order-by support.
- Legacy approval metadata and missing role values are normalized before authorization checks.
- Malformed individual approvals are skipped with logging while the rest of the page remains usable.

### User Experience Improvement

Approval reviewers can open `/approvals` and load the pending queue reliably, even when older approval documents exist in the container.