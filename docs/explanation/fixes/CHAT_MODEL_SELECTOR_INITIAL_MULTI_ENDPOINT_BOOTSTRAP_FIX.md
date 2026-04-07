# Chat Model Selector Initial Multi-Endpoint Bootstrap Fix

Fixed in version: **0.240.069**

## Issue Description

When multi-endpoint model selection was enabled, the chat page initially rendered the legacy GPT or APIM model label from server-side template defaults. A few seconds later, the client-side selector restored the saved multi-endpoint selection from user settings and replaced the visible label.

## Root Cause Analysis

The chats page already had both the user settings and the full multi-endpoint catalog available on the server, but the template ignored that information and rendered a legacy fallback label instead. The hidden `#model-select` element also started with legacy option values, so there was a brief startup window where the visible model and underlying selected option did not match the saved multi-endpoint preference.

## Technical Details

### Files Modified

- `application/single_app/route_frontend_chats.py`
- `application/single_app/templates/chats.html`
- `application/single_app/config.py`
- `functional_tests/test_chat_model_selector_initial_multiendpoint_bootstrap.py`

### Code Changes Summary

- Added a chats-route helper that resolves the initial preferred multi-endpoint selection from `preferredModelId`, `preferredModelDeployment`, and the prebuilt chat model catalog.
- Updated the chat template to render the selected multi-endpoint model label and matching hidden select option on first paint when multi-endpoint mode is enabled.
- Exposed the bootstrapped model selection to page scripts for future client-side startup use.

### Testing Approach

- Added `functional_tests/test_chat_model_selector_initial_multiendpoint_bootstrap.py` to verify the chats route and template include the new bootstrap logic.

## Validation

### Before

- The chat composer briefly showed the legacy GPT/APIM model label before switching to the user’s saved multi-endpoint model.
- Fast interactions during startup could read the old hidden select value before the async restore completed.

### After

- The chat composer renders the saved multi-endpoint model immediately on first paint.
- The hidden select starts with matching multi-endpoint metadata, so the initial visible label and selected model stay aligned.

## Impact

- Removes the visible model-label flip during chat page startup.
- Reduces the chance of early interactions reading a legacy model value before the multi-endpoint selector hydrates.