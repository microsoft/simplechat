# Approval Requester Action Boundary Fix

Fixed/Implemented in version: **0.241.030**

## Issue Description

Approval request submitters could see an `Approve & Execute` action for requests they created. Submitters should be able to view their own pending approval requests and deny them to cancel the request, but they must not be able to approve and execute their own request.

## Root Cause Analysis

The approval authorization helper treated the requester as eligible to approve in some cases. The approval list also used approval eligibility as the pending visibility check, and the modal used a single `can_approve` flag to show both approve and deny actions. That combined view, approve, and deny into one authorization concept.

## Technical Details

### Files Modified

- `application/single_app/functions_approvals.py`
- `application/single_app/route_backend_control_center.py`
- `application/single_app/route_backend_safety.py`
- `application/single_app/templates/approvals.html`
- `application/single_app/config.py`
- `functional_tests/test_approvals_route_helper_import.py`
- `functional_tests/test_safety_violation_remediation_approvals.py`
- `ui_tests/test_approvals_requester_action_buttons.py`

### Code Changes Summary

- Split approval and denial authorization by adding a denial-specific check.
- Blocked requesters from approving their own requests in both route authorization and direct approval execution.
- Allowed requesters to deny their own pending requests while preserving view access.
- Added `can_deny` to approval API responses so the browser can show Deny without showing Approve.
- Stopped safety remediation from auto-approving an approval request created by the same actor.
- Updated `application/single_app/config.py` to version `0.241.030` for this fix.

### Testing Approach

- Updated `functional_tests/test_approvals_route_helper_import.py` to validate requester view/deny access, approval denial, route markers, and direct approval execution rejection.
- Updated `functional_tests/test_safety_violation_remediation_approvals.py` to validate safety requesters cannot approve their own requests even with the required review role.
- Added `ui_tests/test_approvals_requester_action_buttons.py` to validate the approvals modal hides `Approve & Execute` while showing `Deny Request` for requester-owned pending approvals.

## Validation

### Before

- Requesters could be treated as eligible approvers for their own approval requests.
- The modal used `can_approve` to show both approval and denial actions.
- Safety remediation could auto-approve a request created by the same actor.

### After

- Requesters can view and deny their own pending approval requests.
- Requesters cannot approve or execute their own approval requests.
- Other eligible reviewers can still approve or deny requests they did not submit.
- Unrelated users remain blocked by the existing approval visibility checks.