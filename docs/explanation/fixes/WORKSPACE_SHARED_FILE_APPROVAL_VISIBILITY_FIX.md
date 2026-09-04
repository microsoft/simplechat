# Workspace Shared File Approval Visibility Fix

Fixed in version: **0.261.009**

Related config.py version update: `application/single_app/config.py` was incremented to `0.261.009`.

## Issue Description

Files shared into personal or group workspace approval flows could fail to appear in approval-facing views even when they were waiting for approval.

The impact was that approvers could not reliably see pending files to review, which blocked the expected approve or deny workflow.

## Root Cause Analysis

The document access index scope projection candidate query filtered strictly on granted access:

- `c.access_granted = true`

Pending approval records are expected to remain ungranted until an approver acts. Those records carry a pending approval state, so the strict granted-only filter excluded them from candidate projection rows.

## Technical Details

Files modified:

- `application/single_app/functions_document_access_index.py`

Code changes summary:

- Updated `_query_candidate_projection_rows_for_scope` to include pending approval rows in addition to granted rows.
- Added the `@approval_not_approved` query parameter bound to `DOCUMENT_ACCESS_APPROVAL_NOT_APPROVED`.

Updated query predicate:

- From: `AND c.access_granted = true`
- To: `AND (c.access_granted = true OR c.approval_status = @approval_not_approved)`

This preserves existing constraints for source scope, scope key, current-version records, and projection schema version while restoring visibility for pending approval artifacts.

## Validation

Validation performed for this change set included:

- Python compile checks for changed files and `application/single_app` compile sweep.
- Security guardrails for changed Python files:
  - `scripts/check_xss_sinks.py`
  - `scripts/check_broken_access_control.py`

Additional branch validation:

- Updated and re-ran `functional_tests/test_sql_container_odbc_runtime.py` to align assertions with current SQL ODBC default behavior (3/3 passed).

Recommended follow-up coverage:

- Add a dedicated functional test that asserts pending approval records are included in document access index scope projections for approver-visible queues.

## Before and After

- Before: Pending approval shared files could be missing from approval visibility surfaces because only granted access rows were projected.
- After: Pending approval shared files are included in projection candidates and remain visible to approvers while still ungranted until approval.