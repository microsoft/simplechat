# Control Center Public Workspace Members XSS Fix

Fixed/Implemented in version: **0.241.016**

## Overview

This fix closes finding `f008`, a stored XSS in the Control Center public workspace members modal.

Version implemented:
`config.py` now reports `VERSION = "0.241.016"` for this fix.

## Issue Description

- The Control Center members modal loaded workspace member records from `/api/admin/control-center/public-workspaces/<workspace_id>/members`.
- `WorkspaceManager.loadWorkspaceMembers()` rendered `member.displayName` and `member.email` into `row.innerHTML` without escaping.
- A low-privilege authenticated user could persist malicious member metadata through public workspace membership flows and later trigger script execution when an admin opened the members modal.

## Root Cause Analysis

- The modal renderer treated stored member identity fields as trusted HTML.
- The same module already had safe rendering patterns using `textContent` and `escapeHtml()`, but this modal path still used direct HTML interpolation.
- The backend returns member metadata verbatim from storage, so the browser renderer must treat those values as untrusted input.

## Technical Details

### Files Modified

- `application/single_app/static/js/workspace-manager.js`
- `ui_tests/test_control_center_public_workspace_members_escaping.py`
- `application/single_app/config.py`

### Code Changes Summary

- Replaced the vulnerable `row.innerHTML` path in `WorkspaceManager.loadWorkspaceMembers()` with explicit DOM node creation.
- Bound `displayName` and `email` through `textContent`, which keeps stored markup inert.
- Preserved the existing role badge mapping and styling by continuing to use the local `roleConfig` map for trusted badge classes and text.
- Added a focused Playwright regression that injects malicious member `displayName` and `email` payloads into the members modal API response and verifies they render as literal text instead of executable DOM.

### Impact Analysis

This is a narrow browser-side fix. It does not change authorization, persistence, or the members API contract. It only hardens how existing member metadata is rendered into the Control Center modal.

## Validation

### Testing Approach

- Validated the changed JavaScript file with workspace diagnostics.
- Added a focused UI regression for the exact modal and payload shape involved in the finding.
- Recompiled the new UI test file and the version-updated `config.py` with `py_compile`.
- Ran the new UI regression and the adjacent Control Center escaping regressions.

### Validation Results

- `python -m py_compile ui_tests/test_control_center_public_workspace_members_escaping.py application/single_app/config.py`
- `pytest ui_tests/test_control_center_public_workspace_members_escaping.py -q`
- `pytest ui_tests/test_control_center_group_members_escaping.py ui_tests/test_control_center_public_workspace_escaping.py -q`

The UI tests skipped in the current environment because the authenticated UI test variables were not set, which is the expected fallback behavior for these Playwright checks.

## Before And After

Before:

- Stored member `displayName` and `email` values were inserted into the modal row with `innerHTML`.
- Malicious payloads such as `<img onerror>` or `<svg onload>` could become real DOM nodes in an admin session.

After:

- The members modal renders member identity fields with DOM text nodes only.
- Stored markup is displayed as text and no longer becomes executable DOM inside the Control Center members modal.

## User Experience Improvements

Administrators still see the same member names, emails, and role badges in the modal. Suspicious markup now renders as text instead of executing in the browser.