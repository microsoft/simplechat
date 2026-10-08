# Safety Remediation Approval State Fix

Fixed in version: **0.261.298**

## Issue Description

Three problems made a safety violation's remediation state unreliable, and blocked reviewing violations in bulk:

1. **Denied and expired requests left the violation locked.** Saving **Suspend user** or **Block user** creates an approval request and marks the violation `action_request_status: pending`, which refuses edits (409) and deletion. Denying the request in **Approval Requests**, or letting it expire after three days, never updated the violation, so it stayed pending and locked for good.
2. **Re-saving an applied suspension or block requested it again.** Saving a violation whose suspension or block was already approved or requested, with the same action, created a second approval request, even when the reviewer only changed the status or notes.
3. **A review save could overwrite a user's acknowledgment.** The single-record save and the feedback review save read the record, changed it, and upserted the whole document without checking its version. A user acknowledging a warning between the reviewer's read and write lost the acknowledgment.

## Root Cause Analysis

1. `deny_request` in `functions_approvals.py`, used by both `POST /api/approvals/<id>/deny` and the expiry sweep `auto_deny_expired_approvals`, recorded the decision on the approval only. Nothing linked the decision back to the violation named in its `metadata.safety_log_id`, and a pending request that Cosmos removed by TTL left nothing to look up.
2. `update_safety_log` created a request whenever the saved action was a suspension or block, without comparing it to the action the violation already had.
3. `update_safety_log` and `feedback_review_update` used `upsert_item` with the copy they had read.

## Technical Details

### Files Modified

- `application/single_app/functions_safety_remediation.py`: `write_safety_log_updates` (ETag merge with retries and an optional guard), `release_safety_log_after_approval_decision`, `reconcile_pending_safety_logs` and `reconcile_pending_safety_log`, request state constants, `SafetyLogConflict`; `update_safety_log_action_state` now writes conditionally.
- `application/single_app/functions_approvals.py`: `deny_request` releases the violation of a denied or auto-denied warn, suspend or block request.
- `application/single_app/route_backend_safety.py`: the save is shared by PATCH and the bulk API, reconciles first, requests a restriction only when the action changes or `reissue` is sent, and writes conditionally; list, detail, delete and stats reconcile; archive and delete are conditional.
- `application/single_app/route_backend_feedback.py`: review, archive and delete are conditional on the stored version.
- `application/single_app/functions_review_center.py`: `replace_review_record`, the conditional replace the feedback routes use.

### Code Changes Summary

**Releasing a decided request.** When a warn, suspend or block request is denied by a reviewer, `deny_request` records `denied` on the violation; when the expiry sweep denies it, `expired`. Either sets `action_request_decided_at` and clears `action_execution_error`, and the violation can be edited, re-actioned or deleted again. The write only applies while the violation is still waiting on that very request, so denying an older request never unlocks a violation that has moved on to a newer one. A failure here is logged and does not undo the denial.

**Settling stale requests.** Listing violations, opening one, saving, deleting and the dashboard first settle any violation still marked pending, with one batched lookup of the requests they name:

| The request is | The violation becomes |
| --- | --- |
| `denied` | `denied` |
| `auto_denied` or `expired` | `expired` |
| `executed` | `executed` |
| `failed` | `failed`, with a generic error that points to the request |
| still `pending`, or `approved` and running | unchanged, still locked |
| gone, and requested at least three days ago | `expired` |
| gone, and requested less than three days ago | unchanged |

A lookup that fails changes nothing. A violation is never unlocked while its request can still be decided.

**Requesting a restriction once.** A suspension or block is requested only when the action changes, or when the save carries `reissue: true`. Otherwise the save keeps the existing request and answers with `remediation_already_applied: true` for one that was applied, or `remediation_unchanged: true` with `remediation_status` for one that was denied, expired or failed. The V2 violation editor offers **Request this suspension again** (or block) for that case. A violation with a pending request is still refused with 409 `remediation_pending`, so a pending request is never duplicated.

**Conditional writes.** Review saves merge only the fields they change onto the stored version and replace it on the condition that it has not changed, retrying on a fresh read after a conflict. A user's acknowledgment, or any other concurrent change, survives. A save that sends the version it read as `etag` and finds the record changed is refused with 409 `record_changed`, and the V2 editors offer to reload. A save that keeps conflicting is refused the same way rather than written blindly.

## Testing Approach

`functional_tests/test_safety_remediation_approval_state.py` runs the real modules in fresh processes with network access blocked, under normal and optimized Python:

- the real `deny_request` and `auto_deny_expired_approvals` release the violation as `denied` and `expired`, which can then be edited and deleted;
- an older request's denial leaves a newer pending request locked;
- one list settles decided, executed and long-gone requests in one lookup, keeps genuinely pending and recently requested ones locked, and a failed lookup changes nothing;
- re-saving an applied suspension or a denied block requests nothing, `reissue` and a changed action request once, and a pending request is never duplicated;
- a reviewer's save and an archive keep a concurrent acknowledgment, a stale `etag` is refused, and feedback saves behave the same way.

`functional_tests/test_review_center_bulk_and_dashboards.py` covers the same rules through the bulk APIs.

## Validation

### Before

- A denied or expired suspension request left its violation pending: edits were refused with 409 and **Delete** was disabled, with no way to recover it from the interface.
- Saving notes on a violation with an applied suspension created another approval request for the same suspension.
- A warning acknowledged while a reviewer was saving could be lost.

### After

- Denied and expired requests unlock their violation, at decision time or the next time it is listed or opened.
- An applied or decided suspension or block is requested again only on purpose.
- Review writes never overwrite a newer version; a conflicting save is refused with a code the interface can act on.

Related: [V2 Admin Review Center](../features/V2_ADMIN_REVIEW_CENTER.md), [Safety Remediation Actions Fix](SAFETY_REMEDIATION_ACTIONS_FIX.md).
