# Safety Violation Remediation Approvals

Overview

Implemented in version: **0.241.127**

This feature lets Safety Violation admins send warning notifications, temporary suspensions, and permanent access blocks from the safety review modal while reusing the same approval authority model as Control Center restrictions.

Dependencies

- `application/single_app/route_backend_safety.py`
- `application/single_app/route_backend_control_center.py`
- `application/single_app/functions_approvals.py`
- `application/single_app/functions_safety_remediation.py`
- `application/single_app/functions_notifications.py`
- `application/single_app/templates/admin_safety_violations.html`
- `application/single_app/static/js/admin/admin-safety-violations.js`
- `application/single_app/templates/approvals.html`

Technical Specifications

Architecture overview

- Safety remediation actions now use explicit approval request types for warn, suspend, and block operations.
- Reviewer eligibility follows the existing `require_member_of_control_center_admin` setting so the same app-level approval authority applies to both Control Center restrictions and safety remediation.
- Safety admins who already have the required reviewer role can submit and approve their own remediation request in one step.
- Safety admins without the required reviewer role create a pending approval request instead of executing the remediation immediately.
- Shared execution helpers now send the user-facing notification and, for suspend or block, write the same `settings.access.status` and `settings.access.datetime_to_allow` payload that Control Center access restrictions already enforce.

Safety review modal behavior

- Selecting `Warn user`, `Suspend user`, or `Block user` reveals a notification field for the affected user.
- Selecting `Suspend user` also reveals a restore date field that maps to `datetime_to_allow`.
- The safety review table now shows when a remediation action is pending approval or failed during execution.
- Successful saves show whether the action executed immediately or created a pending approval request.

Shared approvals behavior

- The approvals page now exposes `Warn User`, `Suspend User`, and `Block User` filters and labels.
- User-targeted safety approvals are described as a generic `Target` instead of assuming a group-only workflow.
- The reviewer guidance copy now reflects eligibility-based approval rules instead of only self-request denial language.

Usage Instructions

User workflow

- Open a safety violation from the admin review table.
- Select `Warn user`, `Suspend user`, or `Block user`.
- Enter the notification that should be delivered to the affected user.
- For a suspension, set the restore date and time.
- Save the violation.
- If the actor has the required reviewer role, the remediation executes immediately.
- Otherwise, the request appears in the shared approvals page until an eligible reviewer approves it.

Testing and Validation

Functional coverage

- `functional_tests/test_safety_violation_remediation_approvals.py`

Validation performed

- Python `py_compile` across the touched backend files
- `node --check` on `application/single_app/static/js/admin/admin-safety-violations.js`
- VS Code diagnostics on the touched backend and frontend files

Known limitations

- `Escalate` remains unchanged because the repository does not currently include a downstream escalation workflow beyond the existing label.