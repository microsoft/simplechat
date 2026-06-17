# Public Workspace Manage Asset Versioning Fix (v0.242.058)

Fixed/Implemented in version: **0.242.058**

Related config.py version update: `application/single_app/config.py` now sets `VERSION = "0.242.058"`.

## Issue Description

Users could continue seeing `Uncaught SyntaxError: Unexpected token '&'` from `manage_public_workspace.js` after the earlier script syntax fix had already landed. The current source parses cleanly, but the Manage Public Workspace template requested the script without an application-version query string, allowing browsers or intermediate caches to reuse an older broken copy after deployment.

## Root Cause Analysis

The referenced `&bull;` line in the current script is valid JavaScript because it is inside a template literal. The previous syntax fix removed malformed fragments that caused the parser to report the ampersand as the failing token, but the page still loaded `manage_public_workspace.js` from an unversioned URL. That made stale client-side assets a plausible path for the same browser error to persist for individual users.

## Technical Details

### Files Modified

- `application/single_app/templates/manage_public_workspace.html`
- `application/single_app/config.py`
- `functional_tests/test_public_workspace_manage_asset_versioning.py`
- `ui_tests/test_public_workspace_manage_script_parse.py`
- `docs/explanation/fixes/PUBLIC_WORKSPACE_MANAGE_ASSET_VERSIONING_FIX.md`

### Code Changes Summary

- Added `?v={{ config['VERSION'] }}` to the `manage_public_workspace.js` script URL.
- Bumped `config.py` to `0.242.058` so the deployed script URL changes.
- Added source-level regression coverage for the versioned script reference and retained parser checks for the current JavaScript.

## Validation

### Testing Approach

- Verified `manage_public_workspace.js` parses cleanly with Node.js.
- Added a functional regression that confirms the template no longer contains the unversioned script URL.
- Extended the UI parser regression to check the same cache-busting contract.

### Before/After Comparison

- Before: browsers could request `/static/js/public/manage_public_workspace.js` and reuse an old cached copy.
- After: browsers request `/static/js/public/manage_public_workspace.js?v=0.242.058`, forcing a fresh asset URL after deployment.

### Test Results

- `node --check application/single_app/static/js/public/manage_public_workspace.js`
- `python functional_tests/test_public_workspace_manage_asset_versioning.py`
