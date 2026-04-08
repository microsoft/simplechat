# Workspace Plugin Modal Autofill Fix

Fixed/Implemented in version: **0.239.195**

## Issue Description

Opening `workspace.html` could trigger autofill overlay extension errors in the browser console even when the tutorial was not running. The page includes hidden plugin configuration fields for API keys, bearer tokens, passwords, and client secrets, and some autofill extensions attempted to interpret those fields as login inputs.

## Root Cause Analysis

The hidden plugin modal is present in the DOM on page load and contains several `type="password"` inputs that are not part of a login form. Some autofill extensions attempted to process those secret fields, hit login-classification code that assumes a form context, and crashed while classifying them.

## Technical Details

### Files Modified

- `application/single_app/templates/_plugin_modal.html`
- `application/single_app/config.py`
- `functional_tests/test_workspace_plugin_modal_autofill_hardening.py`

### Code Changes Summary

- Marked the hidden plugin modal and its password-like secret fields with common autofill ignore attributes.
- Set the secret inputs to `autocomplete="new-password"` so browsers and extensions do not treat them like normal saved-login targets.
- Wrapped the plugin wizard in an explicit non-submitting form so password-manager overlays no longer see orphaned password inputs with a null form context.
- Added a regression test to verify the hardening markers remain in place.

### Testing Approach

- Added a focused functional regression test for plugin modal autofill hardening.

## Validation

### Before

- Hidden plugin secret fields on `workspace.html` could trigger autofill overlay extension errors in the console during page analysis.

### After

- The hidden plugin modal now signals that its secret fields should be ignored by autofill tooling and provides an explicit form context, reducing the chance of extension crashes during page load.