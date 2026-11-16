# V2 Admin Review Center

Implemented in version: **0.261.298**

## Overview and Purpose

The V2 interface had two separate administrator pages for review: **Feedback Review** and **Safety Violations**. Each was a statistics strip, a filter bar and a table, and every review opened in a pop-up dialog. A reviewer could act on one record at a time, could not see trends over time, and lost their place in the list whenever a dialog closed. Safety reviewers also had nowhere to see the warn, suspend and block requests waiting for a second reviewer except the full list of approval requests.

The **Review center** replaces both pages with one admin surface laid out like V2 Approvals: a rail of each section's pages, a dashboard per section whose figures open the records they count, a workbench that lists records beside the selected record's detail and acts on many records at once, and full-page editors with **Back** instead of pop-ups. The Approvals page gains a **Dashboard** and a **Safety remediation** category on the same rail.

Related changes in the same version:
- Denied and expired remediation requests unlock their violation, re-saving an applied suspension or block no longer requests it again, and review writes are ETag-conditional. See [Safety Remediation Approval State Fix](../fixes/SAFETY_REMEDIATION_APPROVAL_STATE_FIX.md).
- Builds on [Access Restricted Sign-In Screen](ACCESS_RESTRICTED_SIGN_IN_SCREEN.md) and the immediate warnings in [Safety Remediation Actions Fix](../fixes/SAFETY_REMEDIATION_ACTIONS_FIX.md), both 0.261.297.

Dependencies:
- `application/single_app/functions_review_center.py` (new)
- `application/single_app/route_backend_feedback.py`
- `application/single_app/route_backend_safety.py`
- `application/single_app/functions_safety_remediation.py`
- `application/single_app/functions_approvals.py`
- `application/single_app/route_backend_control_center.py`
- `application/single_app/functions_review_lifecycle.py`
- `application/single_app/functions_chat_content_review.py`
- `application/single_app/functions_notifications.py`
- `application/single_app/route_backend_users.py`
- `application/v2_ui/src/pages/review/` (new)
- `application/v2_ui/src/components/review/` (new)
- `application/v2_ui/src/components/layout/CategoryRail.tsx` (new)
- `application/v2_ui/src/components/dashboard/DashboardParts.tsx` (new)
- `application/v2_ui/src/lib/reviewAccess.ts`, `reviewCenter.ts`, `reviewCenterApi.ts`, `reviewSelection.ts` (new)
- `application/v2_ui/src/pages/ApprovalsPage.tsx`, `components/approvals/ApprovalsDashboard.tsx` (new), `GenericApprovalsPanel.tsx`

## Technical Specifications

### Access

The Review center mirrors the server's decorators in `lib/reviewAccess.ts`; the server stays the authority for every request.

| Section | Who | Turned on by |
| --- | --- | --- |
| Feedback | `FeedbackAdmin` when **Require Feedback Admin Role** is on, otherwise `Admin` | `enable_user_feedback` |
| Safety | `SafetyViolationAdmin` when **Require Safety Violation Admin Role** is on, otherwise `Admin` | `enable_content_safety` or `enable_content_screening` |

The account menu shows one **Review center** entry when either section is open to the user. A user with neither sees a not-available state; a user who follows a link to a section they can't open sees that section's not-available state, and the page sends no request for it.

### Routes

| SPA path (under `/v2`) | Page |
| --- | --- |
| `/admin/review` | Redirects to the first section the user may open |
| `/admin/review/feedback` | Feedback dashboard |
| `/admin/review/feedback/queue` | Feedback workbench |
| `/admin/review/feedback/queue/:recordId` | Feedback editor |
| `/admin/review/safety` | Safety dashboard |
| `/admin/review/safety/violations` | Violations workbench |
| `/admin/review/safety/violations/:recordId` | Violation editor |
| `/admin/review/safety/unchecked` | Unchecked chat content |

`/admin/feedback-review` and `/admin/safety-violations` redirect to the workbenches and keep their query. The classic pages (`/admin/feedback_review`, `/admin/safety_violations`) are unchanged and use the same APIs, which only gained fields and parameters.

The rail's collapsed state is the user setting `v2ReviewRailCollapsed`, allowlisted in `route_backend_users.py`.

### Rail registration

`pages/review/reviewCenterSections.tsx` lists the rail's entries. Each `ReviewEntry` names its section, the address segment after it (`''` for the dashboard), its label, accessible label, description and icon, a `render(context)` for the page, an optional `renderRecord(recordId, context)` for its editor, and an optional `available(input)` that narrows who sees it. `ReviewCenterPage` reads only this list, so a new page of a section is a new entry. The shared rail is `CategoryRailPage` in `components/layout/CategoryRail.tsx`, which the Approvals page uses too.

### APIs

All new routes carry `@swagger_route(security=get_auth_security())` and the same decorators as the single-record routes beside them.

| Route | Purpose |
| --- | --- |
| `GET /feedback/review`, `GET /api/safety/logs` | Now also take `search`, `user_id`, `date` (YYYY-MM-DD) and `days` (7, 30, 90); safety adds `status=open`, `category`, `severity`, `request`, `warning` and `restricted=1`, and `archive=all` works on both. Rows carry the user's display name and email, looked up in one batch per page. |
| `GET /feedback/review/ids`, `GET /api/safety/logs/ids` | The ids matching the list filters, for "select all matching": `{ids, total, capped, cap}`, at most 500 ids. |
| `GET /feedback/review/stats?days=`, `GET /api/safety/logs/stats?days=` | Every existing field, plus the dashboard for the window when `days` is given. |
| `GET /api/safety/logs/<id>` | One violation for the editor: the record, `etag`, the user's name, current access state and number of other violations. |
| `POST /feedback/review/bulk`, `POST /api/safety/logs/bulk` | Up to 100 operations per call, each reported on its own. |
| `GET /api/approvals/stats?days=` | The Approvals dashboard, over the requests `GET /api/approvals` shows the caller. |
| `GET /feedback/review/export`, `GET /api/safety/logs/export` | Now take the same filters as the list, so an export matches it. |

The safety dashboard reports open violations, remediation awaiting approval, users restricted now, warnings sent and acknowledged, unchecked chat content, violations per day by category, the severity and action mix, and repeat users. The feedback dashboard reports feedback awaiting review, negative feedback and the acknowledgement rate in the window, archived feedback, feedback per day by rating and the oldest feedback awaiting review. Window figures count archived records too.

### Bulk operations

```json
{
  "operations": [
    {"id": "log-1", "op": "update", "changes": {"status": "Resolved"}, "etag": "optional"},
    {"id": "log-2", "op": "archive", "archived": true},
    {"id": "log-3", "op": "delete"}
  ]
}
```

`update` carries the same fields as the record's PATCH and runs through the same function, so a bulk Warn user sends the warning at once and a bulk Suspend or Block creates an approval request. `archive` and `delete` run through the same functions as their single routes, with the same audit entries. Every write is conditional on the stored version and writes only the fields the operation changes. An operation that sends `etag` must match it, and is then written on that version or not at all: a conflict is reported as `record_changed`, never merged onto a newer version. A violation waiting on a remediation request, or whose warning is being sent, is left unchanged, and a suspension or block that can't be recorded on the violation as it was read is withdrawn. Unknown fields are refused, and a second operation on the same record is refused with `duplicate_operation`.

The response is `{results, succeeded, failed}`: one result per operation, in request order, holding the single route's response with `ok`, `status`, `index`, `id`, `op` and, on failure, a `code` such as `record_changed`, `not_found`, `remediation_pending` or `invalid_operation`. The accepted operation keys are `REVIEW_BULK_OPERATION_KEYS` in `functions_review_center.py`; a later attribution field is added there on purpose.

### Workbench and editors

The workbenches follow the Workflows workbench: one-line rows with a status chip, Up/Down/Home/End navigation, a detail pane with ARIA tabs, filters, page, page size and the selected record in the address. Checkboxes follow `lib/listSelection.ts` (click toggles, Shift+click selects a range) through `lib/reviewSelection.ts`, which also holds "every matching record" for the filters it was resolved for and prunes checked rows after each reload. `ReviewBulkBar` frames the actions, runs them in batches of 100 with progress, and reports each record it could not change; only those stay checked.

Editors use `WorkspaceEditorFrame`: **Back** returns to the workbench with its filters and the record selected, leaving with unsaved changes asks first, a save returns to the list with a saved notice, and a save refused because the record changed offers **Reload**. The frame's side panel slot is free for an editor assistant.

The feedback editor records the reviewer as `adminReview.analyzedBy` (`{id, displayName}`), which `GET /feedback/my` never returns to the user. **Notify the user** sends a `feedback_response` notification with the response to the user, linking to `/profile?tab=feedback`, which V2 opens as **Settings > Feedback**.

The violation editor prefills the notification title and message from the server's standard text and keeps them in step until edited, offers 24 hours, 7 days, 30 days or a custom time for a suspension, and offers **Request this suspension again** (or block) whenever the violation already records that action and no request is waiting, as the classic review does.

### Approvals

The Approvals rail adds **Dashboard** (waiting on me, my pending requests, expiring within 24 hours, decided in the window by outcome, pending by type and the oldest waiting on me) and **Safety remediation** (warn, suspend and block requests), shown to `Admin`, `ControlCenterAdmin` and `SafetyViolationAdmin`. **All requests** stays the landing category, and **Group requests** no longer includes safety requests. The request list reads `status`, `type`, `show` (`mine` or `requested`) and `expiring=1` from the address, so a dashboard figure opens it filtered.

## Usage Instructions

Open **Review center** from the account menu. See [Use the Review center](../../guides/admin-review-center.md) for the reviewer's workflow, [Review user feedback](../../guides/admin-review-feedback.md), [Review safety violations](../../guides/admin-review-safety-violations.md) and [Recheck chat content](../../guides/recheck-chat-content.md).

## Testing and Validation

- `functional_tests/test_review_center_bulk_and_dashboards.py`: bulk caps, per-item results, etags, the pending guard, audit, ids cap, search by display name, stats windows with legacy fields kept, feedback notify and `analyzedBy`, section authorization.
- `functional_tests/test_approvals_dashboard_stats.py`: the approvals summary counts only visible requests; route decorators.
- `functional_tests/test_safety_remediation_approval_state.py`: the three remediation fixes.
- `functional_tests/test_v2_review_center_logic.mjs`: access rules, filters, remediation state, notification defaults, selection.
- `functional_tests/test_v2_admin_review_pages.py`: routes, redirects, menu entry and API wiring.
- `functional_tests/route_tests/`: policy coverage for every new route.
- `ui_tests/test_v2_review_center.py` and `ui_tests/test_v2_approvals_dashboard.py`: rail access per role, dashboard deep links, selection and bulk reports, the editor's dirty guard and conflict reload, the violation editor, sequential rechecks, and the Approvals categories.

Known limitations: "select all matching" stops at 500 records and says so; the list endpoints still read every matching record before paging, as they did before.
