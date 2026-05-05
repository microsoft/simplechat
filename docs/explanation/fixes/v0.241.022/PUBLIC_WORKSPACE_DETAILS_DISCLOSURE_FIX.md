# Public Workspace Details Disclosure Fix

## Overview

Fixed/Implemented in version: **0.241.013**

This fix closes an authorization disclosure in `GET /api/public_workspaces/<ws_id>` where any authenticated user could receive the full Cosmos DB workspace document. The route now returns a role-aware projection instead of the raw document.

## Issue Description

Non-member callers could enumerate public workspace ids through the discovery flow and then request the workspace details endpoint to receive sensitive fields that were meant to stay restricted to workspace members or managers.

Affected data included:

* `pendingDocumentManagers`
* `admins`
* `documentManagers`
* `metrics`
* owner and manager email data beyond what the public directory needed

## Root Cause Analysis

The backend route returned `jsonify(ws)` directly from the stored Cosmos DB document. That bypassed the more restrictive role checks already used elsewhere in the same module for pending requests, workspace statistics, and member management.

The public directory only needed a small public subset of the workspace record, but the shared route contract had grown into a raw document read without response shaping.

## Technical Details

### Files Modified

* `application/single_app/functions_public_workspaces.py`
* `application/single_app/route_backend_public_workspaces.py`
* `application/single_app/static/js/public/manage_public_workspace.js`
* `application/single_app/static/js/public/public_directory.js`
* `functional_tests/test_security_authorization_hardening.py`
* `application/single_app/config.py`

### Code Changes Summary

* Added explicit response-shaping helpers for public workspace details.
* Updated `GET /api/public_workspaces/<ws_id>` to return:
  * a public-safe summary for non-members
  * a member payload for `Owner`, `Admin`, and `DocumentManager` callers
* Added `userRole` and `isMember` to the member-facing contract so the manage page no longer infers permissions from raw `admins` or `documentManagers` arrays.
* Updated the public directory to use owner display name only instead of falling back to owner email.
* Added a regression test to lock down the projected payload and prevent a return to `jsonify(ws)`.

### Impact Analysis

* Non-members can still view public workspace summary information needed by the public directory and landing page flows.
* Member-only data such as `pendingDocumentManagers` is no longer disclosed to non-members.
* Existing member workflows continue to work through the explicit `userRole` contract.

## Validation

### Testing Approach

* Updated `functional_tests/test_security_authorization_hardening.py` to validate the projected response shape.
* Confirmed that the shared authorization hardening test still covers the separate history-grounded fallback protections in chat routes.

### Expected Results

* Non-members receive only public workspace summary fields.
* Members receive the fields needed by the manage page, including `userRole`.
* Sensitive manager-only arrays and metrics are absent from non-member responses.

## Related References

* Functional regression: `functional_tests/test_security_authorization_hardening.py`
* Backend route: `application/single_app/route_backend_public_workspaces.py`
* Shared helpers: `application/single_app/functions_public_workspaces.py`