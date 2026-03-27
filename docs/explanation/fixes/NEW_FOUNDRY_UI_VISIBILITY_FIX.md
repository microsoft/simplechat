# NEW_FOUNDRY_UI_VISIBILITY_FIX.md

# New Foundry UI Visibility Fix

Fixed in version: **0.239.177**

## Issue

New Foundry had already been wired into backend fetch and streaming paths, but the browser UI no longer exposed it in the agent modal or the model endpoint modal. Frontend endpoint sanitization also filtered `new_foundry` out of the visible provider list, which prevented saved New Foundry endpoints from appearing in user-facing workflows.

## Root Cause

- The New Foundry agent type radio in `_agent_modal.html` was wrapped in a disabled `{% if false %}` block.
- `_multiendpoint_modal.html` only exposed `aoai` and classic Foundry in the provider selector.
- `is_frontend_visible_model_endpoint_provider()` in `functions_settings.py` still treated `new_foundry` as unsupported for frontend use.

## Files Modified

- `application/single_app/templates/_agent_modal.html`
- `application/single_app/templates/_multiendpoint_modal.html`
- `application/single_app/functions_settings.py`
- `functional_tests/test_chat_tagging_and_endpoint_provider_visibility.py`
- `functional_tests/test_new_foundry_fetch_support.py`
- `functional_tests/test_new_foundry_ui_visibility.py`
- `ui_tests/test_agent_modal_dual_foundry_modes.py`
- `ui_tests/test_model_endpoint_request_uses_endpoint_id.py`
- `application/single_app/config.py`

## Validation

- Functional coverage now verifies the New Foundry agent type is present in the agent modal template.
- Functional coverage now verifies the endpoint modal exposes `new_foundry` and frontend endpoint sanitization allows it.
- Existing UI tests were updated to expect New Foundry to be visible in both agent and endpoint modal workflows.

## Impact

Users can configure New Foundry endpoints again and select the New Foundry agent type in the browser, which restores the UI path needed to test the REST-based streaming backend.

The agent modal now also displays fetched published versions in the application selector and inherits the Responses API version from the selected endpoint configuration instead of asking the user to type version metadata manually.