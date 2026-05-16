# Chat Document Dropdown Viewport Fit Fix

Fixed in version: **0.241.009**

## Issue Description

The chat document selector could open downward from the grounded-search controls when the controls were close to the bottom of the browser viewport. On short desktop windows and mobile-influenced layouts, the dropdown extended below the visible screen and made document selection difficult.

## Root Cause Analysis

The shared chat search-filter dropdown sizing helper enforced a minimum dropdown height even when less space was available below the trigger. The document dropdown also had its own viewport adjustment after the dropdown was already shown, so placement was not chosen before Bootstrap/Popper calculated the menu position.

## Version Implemented

Implemented in version: **0.241.009**

The application version was updated in `application/single_app/config.py` from `0.241.008` to `0.241.009`.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/config.py`
- `ui_tests/test_chat_document_dropdown_viewport_fit.py`

### Code Changes Summary

- Added viewport-aware dropdown placement for grounded-search dropdowns.
- Configured Bootstrap/Popper to prefer upward placement when there is not enough room below the trigger.
- Replaced fixed minimum dropdown heights with available-space clamping.
- Routed the document selector through the shared dropdown sizing helper instead of maintaining separate post-show sizing logic.

### Testing Approach

- Added a Playwright UI regression test that opens the chat document selector in a short desktop viewport and verifies the dropdown stays inside the visible browser area.
- The test also verifies that the document list remains internally scrollable when the dropdown is constrained.

## Impact Analysis

The fix is scoped to the chat grounded-search dropdowns for scope, tags, and documents. It does not change document selection state, backend search behavior, or chat message payloads.

## Validation

Before the fix, the document dropdown could extend below the browser viewport when opened near the bottom of the screen. After the fix, the dropdown selects the best available vertical direction and clamps its menu/list height to the viewport.
