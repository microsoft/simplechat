# Admin Review Record Lifecycle

## Overview

Administrators can archive, restore, and permanently delete records from the Feedback Review and Safety Violations pages. Archiving removes a record from active admin queues and the affected user's profile history while preserving it for later review.

Implemented in version: **0.250.075**

### Dependencies

- Azure Cosmos DB feedback, safety, and activity log containers
- Existing FeedbackAdmin and SafetyViolationAdmin role gates
- Bootstrap 5 modals and alerts

## Technical specifications

### Record lifecycle

Feedback and safety documents use these backward-compatible fields:

- `is_archived`: Current archive state. Missing values are treated as active.
- `archived_at` and `archived_by`: Most recent archive timestamp and administrator.
- `unarchived_at` and `unarchived_by`: Most recent restore timestamp and administrator.

Admin list, statistics, pagination, and CSV export requests accept `archive=active` or `archive=archived`. The default is `active`. User profile list, statistics, and export APIs always return active records only.

### APIs

| Record | Archive or restore | Permanent delete |
|---|---|---|
| Feedback | `PATCH /feedback/review/{id}/archive` with `{"archived": true\|false}` | `DELETE /feedback/review/{id}` |
| Safety violation | `PATCH /api/safety/logs/{id}/archive` with `{"archived": true\|false}` | `DELETE /api/safety/logs/{id}` |

All lifecycle routes require login, Swagger authentication metadata, the record-specific admin role, and the corresponding feature setting.

Safety violations with a pending remediation approval return HTTP 409 when deletion is requested. Completed approval and activity records are stored separately and remain available after the violation is deleted.

### Audit behavior

Every successful archive, unarchive, and delete attempts to write an `admin_action` activity record. The audit stores the administrator, lifecycle action, record ID, target user ID, prior archive state, and relevant conversation/message or safety approval identifiers. User-generated prompt, response, and violation message content is not copied into the audit record.

Cosmos cannot atomically mutate the source and activity containers. If activity logging fails, the lifecycle mutation remains successful, Application Insights records the failure, and the API returns an `audit_warning` for the admin UI.

### Files

- `application/single_app/functions_review_lifecycle.py`
- `application/single_app/route_backend_feedback.py`
- `application/single_app/route_backend_safety.py`
- `application/single_app/templates/admin_feedback_review.html`
- `application/single_app/templates/admin_safety_violations.html`
- `application/single_app/static/js/admin/admin-feedback-review.js`
- `application/single_app/static/js/admin/admin-safety-violations.js`

## Usage

1. Open Feedback Review or Safety Violations and select **All Data**.
2. Use the **Records** filter to switch between active and archived records.
3. Select **Archive** to remove an active record from both admin and user history.
4. Select **Unarchive** in the archived view to restore the record.
5. Select **Delete**, review the destructive confirmation, and choose **Permanently Delete**.

Archive, restore, and delete actions refresh the current list/card view, statistics, pagination, and export scope. Audit persistence warnings appear as Bootstrap warning alerts without reporting the completed record mutation as failed.

## Testing and validation

- `functional_tests/test_admin_review_record_lifecycle.py` covers lifecycle metadata, query filters, audit payload minimization, route authorization markers, and pending remediation safeguards.
- `functional_tests/test_backend_feedback_swagger_integration.py` covers all feedback route decorators and role gates.
- `ui_tests/test_admin_review_list_card_views.py` covers archive actions, delete confirmation and cancellation, audit warnings, and pending safety deletion errors.

The UI tests require an authenticated admin Playwright storage state and a configured `SIMPLECHAT_UI_BASE_URL`.

### Known limitations

- Lifecycle changes and activity log writes are separate Cosmos operations. Audit failures are surfaced but do not roll back the requested lifecycle action.
- Permanent deletion cannot be undone. Only archive and unarchive are reversible.
