# Locked Scope Selector And Endpoint Toggle Visibility Fix

Fixed/Implemented in version: **0.239.197**

## Overview

This fix cleans up two related UI issues in the chat and endpoint management surfaces:

- chat agent and model selectors now remove unavailable options after a conversation scope is locked instead of leaving them visible but disabled
- personal and group endpoint tabs now only render when multi-endpoint management is enabled
- the personal and group admin-controlled multi-endpoint toggle remains in the markup for future reuse but is hidden from users
- the admin multi-endpoint enable toggle is no longer rendered after migration is already enabled

## Root Cause

The chat selector code already knew which options were invalid for an existing conversation, but the rebuild step still rendered those options and only disabled them. Separately, endpoint tab buttons were gated less strictly than their tab panes, so users could still see dead tab affordances before multi-endpoint management was enabled. The admin settings page also continued rendering the one-way enable toggle even after the system had already migrated.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-agents.js`
- `application/single_app/static/js/chat/chat-model-selector.js`
- `application/single_app/templates/workspace.html`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_searchable_selectors.py`
- `functional_tests/test_endpoints_tab_order_visibility.py`
- `functional_tests/test_public_prompt_visibility_and_editor_theming.py`
- `ui_tests/test_chat_grouped_selectors.py`

### Code Changes Summary

- filtered agent and model optgroups at rebuild time for non-new conversations so only selectable options remain
- aligned personal and group endpoint tab button conditions with the existing tab-pane conditions
- hid the personal and group admin-controlled toggle with Bootstrap's `d-none` instead of deleting the markup
- wrapped the admin enable toggle in Jinja so it is omitted after multi-endpoint mode is already enabled
- updated the admin endpoint initializer so it keeps working when that toggle is absent from the DOM
- bumped the application version to `0.239.197`

## Validation

### Tests

- `functional_tests/test_chat_searchable_selectors.py`
- `functional_tests/test_endpoints_tab_order_visibility.py`
- `functional_tests/test_public_prompt_visibility_and_editor_theming.py`
- `ui_tests/test_chat_grouped_selectors.py`

### User Experience Improvements

- existing conversations now show a cleaner agent/model list that only contains valid choices for the locked scope
- endpoint tabs no longer appear before the feature is actually usable
- admins are no longer shown a migration toggle after the system has already moved to multi-endpoint management