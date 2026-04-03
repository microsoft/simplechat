# Single App Template JSON Bootstrap Fix

Fixed/Implemented in version: **0.240.020**

## Issue Description

Several `single_app` templates were still bootstrapping server-side JSON with patterns such as `JSON.parse('{{ value|tojson }}')`. That left workspace and admin pages vulnerable to the same control-character and quoting failures already fixed in the chat template.

## Root Cause Analysis

- Jinja `tojson` output was being inserted into JavaScript string literals instead of being assigned directly as JavaScript literals.
- JavaScript string parsing can consume escape sequences before `JSON.parse(...)` runs, which turns otherwise valid JSON into invalid runtime input when values contain newlines, quotes, or other escaped control characters.
- The brittle pattern had spread across personal workspace, group workspace, public workspace, and admin settings bootstraps.

## Technical Details

### Files Modified

- `application/single_app/templates/workspace.html`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/templates/public_workspaces.html`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/config.py`
- `functional_tests/test_single_app_template_json_bootstrap_safety.py`
- `ui_tests/test_single_app_template_json_bootstrap_render.py`

### Code Changes Summary

- Replaced string-wrapped `JSON.parse(...)` bootstraps with direct `tojson` assignments in the affected templates.
- Added `default([], true)` and `default({}, true)` where appropriate so array and object bootstraps stay well-typed when backend values are missing.
- Kept or added lightweight runtime guards for arrays and objects in admin settings where downstream code already expects normalized shapes.
- Added a functional regression test that scans the affected templates for safe and unsafe bootstrap snippets.
- Added a Playwright smoke test that watches for syntax and JSON bootstrap errors while loading the affected pages.

### Testing Approach

- Functional regression: `functional_tests/test_single_app_template_json_bootstrap_safety.py`
- UI regression: `ui_tests/test_single_app_template_json_bootstrap_render.py`

## Validation

### Before

- Workspace and admin page bootstraps could fail in the browser when serialized values contained escaped control characters or quoting edge cases.

### After

- The affected templates now emit direct JavaScript literals from Jinja `tojson` output.
- Escaped values remain encoded within the serialized payload instead of being reinterpreted by an intermediate JavaScript string literal.
- The added regression tests help prevent `JSON.parse('{{ ...|tojson ... }}')` from being reintroduced in these templates.