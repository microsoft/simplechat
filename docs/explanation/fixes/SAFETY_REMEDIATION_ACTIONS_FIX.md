# Safety Remediation Actions Fix

Fixed/Implemented in version: **0.261.297**

## Issue Description

Two of the four remediation actions on the Safety Violations review did nothing in practice:

- **Warn user** never reached the user in a deployment with one administrator. Saving a warning created a `warn_user` approval request, and since [0.241.030](v0.241.030/APPROVAL_REQUESTER_ACTION_BOUNDARY_FIX.md) a requester can never approve their own request. With nobody else eligible to approve it, the request sat pending until it was automatically denied, and the violation stayed locked while it was pending.
- **Escalate** was only a label. It was stored on the record and counted in the statistics, but nothing escalated anything, which [the remediation feature](../features/v0.241.127/SAFETY_VIOLATION_REMEDIATION_APPROVALS.md) recorded as a known limitation.

A warning that did reach a user was also easy to miss: it was one more notice in the bell, and nothing showed whether the user had read it.

## Root Cause Analysis

All three remediation actions were routed through the same approval workflow so that no single reviewer could act on another user alone. That rule is right for suspensions and blocks, which take away access, but a warning only informs the user, and holding it for a second reviewer meant it was never sent where there was no second reviewer. Escalate was added as an action before any escalation workflow existed, and none was built.

## Technical Details

### Files Modified

- `application/single_app/route_backend_safety.py`
- `application/single_app/functions_safety_remediation.py`
- `application/single_app/route_backend_control_center.py`
- `application/single_app/route_backend_v2.py`
- `application/single_app/templates/admin_safety_violations.html`
- `application/single_app/static/js/admin/admin-safety-violations.js`
- `application/single_app/templates/my_safety_violations.html`
- `application/single_app/templates/profile.html`
- `application/single_app/static/js/profile/profile-tabs.js`
- `application/v2_ui/src/pages/AdminSafetyViolationsPage.tsx`
- `application/v2_ui/src/components/settings/ViolationsTab.tsx`
- `application/v2_ui/src/components/notifications/SafetyWarningDialog.tsx` (new)
- `application/v2_ui/src/lib/safetyWarnings.ts` (new)
- `application/v2_ui/src/lib/useSafetyWarningRuntime.ts` (new)
- `application/v2_ui/src/stores/safetyWarningStore.ts` (new)
- `application/single_app/config.py`

### Warnings are sent when the review is saved

The two-person rule is relaxed for warnings only, because a warning restricts nothing:

- Saving **Warn user** calls `execute_safety_violation_action` straight away. No approval request is created, and the response is `{"message": "Warning sent to the user.", "approval_required": false}`.
- The reviewer's decision is still audited: an activity-log entry (`safety_violation_warning_sent`) and a `[SAFETY_REMEDIATION]` event record who sent it, to whom, and the notification id. These replace the audit trail the approval request used to provide.
- Saving a record whose warning was already sent, for example to resolve it, updates the review without sending the warning again and returns `warning_already_sent: true`.
- If the notification cannot be created, the rest of the review is saved, the record is marked `action_request_status: "failed"`, and the response is a 500 asking the reviewer to save again. No exception text is returned.
- The existing guards remain: a record with a pending approval returns 409, and AI-generated findings cannot be used to warn or restrict a user.

**Suspend user** and **Block user** are unchanged: saving creates an approval request that another eligible reviewer must approve, and the requester can never approve their own request.

A `warn_user` approval created before this version still completes when approved through the Control Center approval path, and is then treated like any other executed warning.

### Warnings must be acknowledged

When a warning executes, by either path, the violation records:

| Field | Meaning |
| --- | --- |
| `warning_requires_acknowledgment` | `true`. Warnings sent before this version do not have it and are never shown again. |
| `warning_notification_id` | The bell notification that delivered the warning. |
| `warning_title`, `warning_message` | Exactly what the user was sent. |
| `warning_issued_at` | When it was sent. |
| `warning_acknowledged_at` | `null` until the user acknowledges it. |

New user routes, which require a signed-in, unrestricted User session and are deliberately not gated on the content checks report, so a warning already sent stays acknowledgeable:

- `GET /api/safety/warnings/pending` returns `{"warnings": [...], "count": n}`, oldest first, `Cache-Control: no-store`. Each warning holds only `id`, `violation_id`, `title`, `message`, `issued_at`, `acknowledged_at` and `triggered_categories`.
- `POST /api/safety/warnings/<id>/acknowledge` records `warning_acknowledged_at` and marks the delivering notification read. Repeating it changes nothing and returns `already_acknowledged: true`. A record that isn't the caller's own executed warning returns 404 `Warning not found.`, the same answer as a record that doesn't exist. The write is conditional on the record's ETag and retried, so a reviewer saving the record at the same moment is never overwritten.

V2 bootstrap carries `safety_warnings.pending`, the count of waiting warnings. The V2 interface reads the warnings only when that count is above zero, after bootstrap loads and again whenever the tab comes back to the front, so a user with nothing to acknowledge makes no extra request. A modal dialog, **A warning from your administrators**, shows each warning's title, message, when it was sent and its flagged categories. It has no close button, and Escape or a click outside it leaves it open; **I understand** acknowledges the warning and shows the next one. It appears again in any tab, on any device, until acknowledged.

Reviewers see the state on the record: the admin list and detail JSON add `warning_acknowledgment_status` (`pending`, `acknowledged`, `not_tracked` for a warning sent before this version, or `null` for anything else) beside the fields above. The V2 review dialog shows "Warning acknowledged *date*" or "Not yet acknowledged", and the user's V2 **Settings > Violations** tab shows whether they acknowledged it.

### Escalate is no longer an action

- It is removed from the action choices and filters in the V2 and classic admin pages and the users' violation lists.
- The API rejects a change to `Escalate` with 400. A record that already carries `Escalate` still saves with it unchanged, so it can be resolved or noted; it can be moved to another action, but not back.
- Records that carry it are labelled **Escalated (legacy)**. `escalate_count` stays in the statistics JSON. The V2 tile that read "Escalated or blocked" now reads **Blocked** and mentions legacy escalations only when there are any; the classic page's **Escalated** tile is now **Blocked**.

### Testing Approach

- `functional_tests/test_safety_warning_acknowledgment.py`
- `functional_tests/test_safety_escalate_removal.py`
- `functional_tests/test_safety_violation_remediation_approvals.py` (updated to run offline, and to cover the second-reviewer rule and the restriction notice)
- `functional_tests/test_v2_access_restriction_and_safety_warning_logic.mjs`
- `ui_tests/test_v2_access_restricted_and_safety_warning.py`
- `ui_tests/test_classic_safety_review_and_access_restricted.py` (the classic review page offers no Escalate, labels a legacy record, explains which actions need a second reviewer, shows whether a sent warning was acknowledged, and shows Blocked statistics)
- `functional_tests/route_tests/` policy inventories for the two warning routes

## Validation

### Before

- In a deployment with one administrator, **Warn user** created a request nobody could approve, and the warning was never sent.
- A delivered warning was one more notice in the bell, with no record of whether it was read.
- **Escalate** could be chosen and did nothing.

### After

- A warning is sent as the review is saved, is not sent again when the record is saved later, and is audited.
- The user has to acknowledge it before carrying on in the V2 interface, and reviewers can see whether they have.
- Suspensions and blocks still need a second eligible reviewer.
- **Escalate** can't be chosen; existing records keep it, labelled as legacy.

Related: [Access Restricted Sign-In Screen](../features/ACCESS_RESTRICTED_SIGN_IN_SCREEN.md), which shows a suspended or blocked user why at sign-in.
