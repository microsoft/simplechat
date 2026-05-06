# Generated Artifact Pending Approval Actions Fix

Fixed in version: **0.241.128**

## Issue Description

Pending generated artifact promotions in group and public workspaces could be approved, but they had no matching deny or requester cancel path. That left workspace members with pending shells and approval notifications that could not be cleared without manual cleanup.

## Root Cause

The phase 4 promotion workflow only implemented the approval branch after a pending document shell was created. The backend routes, workspace table actions, and folder views did not expose any denial or requester-owned cancellation path for that same shell.

## Technical Details

Files modified:

- `application/single_app/route_backend_group_documents.py`
- `application/single_app/route_backend_public_documents.py`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/static/js/public/public_workspace.js`
- `functional_tests/test_generated_artifact_workspace_promotion.py`
- `ui_tests/test_workspace_generated_artifact_pending_actions.py`
- `application/single_app/config.py`

Code changes summary:

- Added group and public backend routes to deny pending generated artifact promotions.
- Added requester-only cancel routes for pending generated artifact promotions.
- Cleared matching pending approval notifications when requests are approved, denied, or canceled.
- Added deny and cancel actions to group and public workspace list and folder views.
- Added focused functional and UI regression coverage for the new action matrix.

Testing approach:

- Python compile validation for touched backend files.
- Source-based functional regression for route and UI wiring.
- Playwright UI regression for pending row action visibility.

## Validation

Before:

- Pending promoted artifacts could only be approved.
- Requesters could not withdraw a mistaken promotion request.
- Managers could not explicitly deny a pending promotion.
- Pending approval notifications remained the only visible signal for stalled requests.

After:

- Managers can approve or deny pending generated artifact promotions.
- Requesters can cancel their own pending generated artifact promotions.
- Pending workspace shells and matching notifications are removed when requests are denied or canceled.
- Approval now also clears the matching pending notifications.

## Related References

- Related functional test: `functional_tests/test_generated_artifact_workspace_promotion.py`
- Related UI test: `ui_tests/test_workspace_generated_artifact_pending_actions.py`
- Related feature documentation: `docs/explanation/features/v0.241.127/GENERATED_ANALYSIS_ARTIFACT_WORKSPACE_PROMOTION.md`