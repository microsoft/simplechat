# Safety Remediation Approval State Fix

Fixed in version: **0.261.298**

## Issue Description

Four problems made a safety violation's remediation state unreliable, and blocked reviewing violations in bulk:

1. **Denied and expired requests left the violation locked.** Saving **Suspend user** or **Block user** creates an approval request and marks the violation `action_request_status: pending`, which refuses edits (409) and deletion. Denying the request in **Approval Requests**, or letting it expire after three days, never updated the violation, so it stayed pending and locked for good.
2. **Re-saving an applied suspension or block requested it again.** Saving a violation whose suspension or block was already approved or requested, with the same action, created a second approval request, even when the reviewer only changed the status or notes.
3. **A review save could overwrite a user's acknowledgment.** The single-record save and the feedback review save read the record, changed it, and upserted the whole document without checking its version. A user acknowledging a warning between the reviewer's read and write lost the acknowledgment.
4. **A suspension or block could be recorded over another save's work.** Creating the approval request takes time, and the save then wrote the request onto the violation whatever had happened meanwhile. A warning sent by another reviewer in that window was overwritten and its acknowledgment lost, or recorded over the new request; two suspension or block saves at once left one request approvable that the violation no longer referred to.

## Root Cause Analysis

1. `deny_request` in `functions_approvals.py`, used by both `POST /api/approvals/<id>/deny` and the expiry sweep `auto_deny_expired_approvals`, recorded the decision on the approval only. Nothing linked the decision back to the violation named in its `metadata.safety_log_id`, and a pending request that Cosmos removed by TTL left nothing to look up.
2. `update_safety_log` created a request whenever the saved action was a suspension or block, without comparing it to the action the violation already had.
3. `update_safety_log` and `feedback_review_update` used `upsert_item` with the copy they had read.
4. The write that records a request checked neither the version the save read nor whether the violation had moved on, and nothing at approval time checked that the violation still waited on the request.

## Technical Details

### Files Modified

- `application/single_app/functions_safety_remediation.py`: `write_safety_log_updates` (ETag merge with retries and an optional guard), `release_safety_log_after_approval_decision`, `reconcile_pending_safety_logs` and `reconcile_pending_safety_log`, `safety_remediation_state`, `safety_log_awaits_request`, request state constants, `SafetyLogConflict`; `update_safety_log_action_state` now writes conditionally.
- `application/single_app/functions_approvals.py`: `deny_request` releases the violation of a denied or auto-denied warn, suspend or block request; `withdraw_approval_request` denies a request its creator could not record and removes the notices it sent.
- `application/single_app/route_backend_safety.py`: the save is shared by PATCH and the bulk API, reconciles first, requests a restriction only when the action changes or `reissue` is sent, writes only the fields it changes, and records a request only on the violation as it read it, withdrawing the request otherwise; list, detail, delete and stats reconcile; archive and delete are conditional.
- `application/single_app/route_backend_control_center.py`: an approved suspension or block is carried out only while its violation waits on it.
- `application/single_app/route_backend_feedback.py`: review, archive and delete are conditional on the stored version.
- `application/single_app/functions_review_center.py`: `replace_review_record`, the conditional replace the feedback routes use.
- `application/single_app/templates/admin_safety_violations.html`, `application/single_app/static/js/admin/admin-safety-violations.js`: the classic review offers **Request this suspension again** (or block).
- `application/v2_ui/src/lib/reviewCenter.ts`, `application/v2_ui/src/pages/review/SafetyEditorPage.tsx`: the same choice and wording in the V2 editor.

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

**Requesting a restriction once.** A suspension or block is requested only when the action changes, or when the save carries `reissue: true`. Otherwise the save keeps the existing request and answers with `remediation_already_applied: true` for one that was applied, or `remediation_unchanged: true` with `remediation_status` for one that was denied, expired or failed. Both reviews offer **Request this suspension again** (or block) whenever the violation already records that action and no request is waiting: the classic **Save Review** dialog and the V2 violation editor. Until it is ticked, they say where the last request stands, hide the notification and restore time that would not be used, and send neither; ticking it sends `reissue: true` with them. The classic dialog offers a previous restore time again only while it is still ahead, and refuses one in the past. A violation with a pending request is still refused with 409 `remediation_pending`, so a pending request is never duplicated.

**Recording a request on the violation as it was read.** A suspension or block save creates its approval request and then records it on the violation. That write is applied only while what the save decided from still holds: the violation waits on the same request, no warning is being sent, and no warning was recorded since (`safety_remediation_state`). If another save sent a warning, claimed the violation to send one, or created a request meanwhile, the save is refused with 409 `record_changed`, and its request is withdrawn (`withdraw_approval_request`): denied with a comment saying why, written only while still pending, and with its notices to reviewers and the requester removed. A save that stopped while sending a warning can't record it over a request made after its claim went stale, because recording the request clears the claim. Should withdrawing fail, the request is still never carried out: the Control Center executes an approved warn, suspend or block request only while its violation waits on that very request (`safety_log_awaits_request`), and otherwise marks it failed without changing anything.

**Conditional writes.** Review saves write only the fields they change, onto the stored version, on the condition that it has not changed. A save that doesn't name a version is retried on a fresh read after a conflict, so a user's acknowledgment, or another reviewer's change to a different field, survives. A save that names the version it read as `etag` -- as the V2 editors and bulk operations from the workbench can -- is written on that version or not at all: a conflict is refused with 409 `record_changed`, never merged onto the newer version. This holds for PATCH, archive and the bulk `update` and `archive` operations, for feedback and safety alike, and the V2 editors offer to reload. A save that keeps conflicting is refused the same way rather than written blindly, and an archive that would land on a warning being sent waits for it with 409 `safety_warning_in_progress`.

## Testing Approach

`functional_tests/test_safety_remediation_approval_state.py` runs the real modules in fresh processes with network access blocked, under normal and optimized Python:

- the real `deny_request` and `auto_deny_expired_approvals` release the violation as `denied` and `expired`, which can then be edited and deleted;
- an older request's denial leaves a newer pending request locked;
- one list settles decided, executed and long-gone requests in one lookup, keeps genuinely pending and recently requested ones locked, and a failed lookup changes nothing;
- re-saving an applied suspension or a denied, expired or failed one requests nothing, `reissue` and a changed action request once, and a pending request is never duplicated;
- a reviewer's save and an archive keep a concurrent acknowledgment, a stale `etag` is refused, and feedback saves behave the same way;
- overlapping saves leave one consistent request: a warning saved, or a send claimed and recorded late, while a suspension request is created; two suspension or block saves at once; and another reviewer's notes landing meanwhile, with and without `etag`. Each refused save's request is withdrawn with its notices, nothing approvable is left that the violation doesn't wait on, and a stale claim can't record its warning over a later request;
- when withdrawing fails, the Control Center's executor, run from its source, refuses the orphaned request without changing the violation or the user's access, and still carries out the request a violation waits on;
- a save that names its version is never retried onto a newer one, for PATCH, archive and bulk update and archive on both feedback and safety, while one that doesn't keeps the other save's change.

Mutating the guard, the withdrawal or the single attempt back to the earlier behaviour makes these probes fail.

`functional_tests/test_review_center_bulk_and_dashboards.py` covers the same rules through the bulk APIs. `ui_tests/test_classic_safety_review_and_access_restricted.py` and `ui_tests/test_v2_review_center.py` cover **Request this suspension again** in both reviews.

## Validation

### Before

- A denied or expired suspension request left its violation pending: edits were refused with 409 and **Delete** was disabled, with no way to recover it from the interface.
- Saving notes on a violation with an applied suspension created another approval request for the same suspension.
- A warning acknowledged while a reviewer was saving could be lost.
- A suspension saved while another reviewer's warning was being sent could leave the violation marked applied, linked to a request still waiting for approval, with the warning untracked; two suspension saves at once left an approvable request nothing linked to.

### After

- Denied and expired requests unlock their violation, at decision time or the next time it is listed or opened.
- An applied or decided suspension or block is requested again only on purpose, from either review.
- Review writes never overwrite a newer version; a conflicting save is refused with a code the interface can act on.
- Overlapping saves leave one request that matches the violation; a request that couldn't be recorded is withdrawn, and is never carried out even if withdrawing fails.

Related: [V2 Admin Review Center](../features/V2_ADMIN_REVIEW_CENTER.md), [Safety Remediation Actions Fix](SAFETY_REMEDIATION_ACTIONS_FIX.md).
