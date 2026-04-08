# Admin Multi Endpoint Persistence Guard Fix

Fixed/Implemented in version: **0.239.199**

## Overview

This fix prevents admin settings saves from disabling multi-endpoint model management after it has already been enabled.

## Root Cause

Once the admin enable toggle was hidden by Jinja, later form submissions no longer included the checkbox value. The admin settings POST handler interpreted the missing field as `False`, which caused the save pipeline to treat multi-endpoint as disabled again.

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/config.py`
- `functional_tests/test_admin_multi_endpoint_persistence_guard.py`
- `functional_tests/test_chat_scope_selector_sync.py`
- `functional_tests/test_chat_searchable_selectors.py`
- `functional_tests/test_public_prompt_visibility_and_editor_theming.py`

### Code Changes Summary

- added a shared coercion helper so `enable_multi_model_endpoints` behaves as a one-way setting once enabled
- updated the admin settings POST handler to preserve the existing enabled state before any dependent save logic runs
- added a second backend guard in `update_settings()` so later callers also preserve the enabled state
- bumped the application version to `0.239.199`

## Validation

### Tests

- `functional_tests/test_admin_multi_endpoint_persistence_guard.py`
- `functional_tests/test_chat_scope_selector_sync.py`
- `functional_tests/test_chat_searchable_selectors.py`
- `functional_tests/test_public_prompt_visibility_and_editor_theming.py`

### User Experience Improvements

- once multi-endpoint management is enabled, future admin saves no longer turn it off implicitly
- the admin toggle can remain hidden without relying on frontend workarounds to preserve the saved state