# Microsoft Graph Calendar Invites And Capabilities Fix

Fixed/Implemented in version: **0.241.037**

## Overview

The built-in Microsoft Graph action could read calendar data, mail, and directory information, but it could not create calendar invites, create Microsoft Teams meetings, or expose action-level and agent-level capability toggles like the built-in SimpleChat action.

## Root Cause

- `msgraph_plugin.py` only exposed read-oriented operations plus mail read-state updates, so there was no Graph action for calendar invite creation.
- Microsoft Graph actions did not have a shared capability definition, normalization, or runtime overlay path, so per-action defaults and per-agent overrides were unavailable.
- The workspace action modal and agent modal only rendered capability controls for SimpleChat, leaving Microsoft Graph on the generic endpoint/auth flow.

## Files Modified

- `application/single_app/functions_msgraph_operations.py`
- `application/single_app/semantic_kernel_plugins/msgraph_plugin.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/static/js/agent_modal_stepper.js`
- `application/single_app/templates/_plugin_modal.html`
- `application/single_app/templates/_agent_modal.html`
- `functional_tests/test_msgraph_plugin_operations.py`
- `functional_tests/test_msgraph_agent_action.py`
- `ui_tests/test_workspace_msgraph_action_modal.py`
- `ui_tests/test_agent_modal_msgraph_capabilities.py`

## Code Changes Summary

1. Added shared Microsoft Graph capability definitions plus helpers for action defaults and per-agent runtime overlays.
2. Added `create_calendar_invite` to the Microsoft Graph plugin, including support for Teams meetings via `isOnlineMeeting` and `onlineMeetingProvider`.
3. Expanded invite attendee resolution so an action can include members from the current or specified SimpleChat group while deduplicating attendees and skipping the organizer.
4. Applied Graph capability overlays in `semantic_kernel_loader.py` so agent `other_settings.action_capabilities` can narrow the enabled Graph functions at runtime.
5. Updated the workspace action modal to treat Microsoft Graph as a built-in action with default capability toggles instead of exposing a user-editable endpoint.
6. Updated the agent modal to render per-agent Microsoft Graph capability toggles alongside the existing SimpleChat controls.

## Validation

- Functional test: `functional_tests/test_msgraph_plugin_operations.py`
- Functional test: `functional_tests/test_msgraph_agent_action.py`
- UI test: `ui_tests/test_workspace_msgraph_action_modal.py`
- UI test: `ui_tests/test_agent_modal_msgraph_capabilities.py`

## Impact

- Agents can now create Microsoft Graph calendar invites, optionally add current group members as attendees, and create Microsoft Teams meetings in one action.
- Workspace creators can set default Microsoft Graph capabilities per action, and agents can narrow those defaults per assignment.
- Microsoft Graph actions now behave like other built-in actions in the workspace and agent modals instead of falling back to the generic external-plugin flow.