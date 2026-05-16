# Standard Chat Document Action Payload Fix

Version: 0.241.075

Fixed/Implemented in version: **0.241.075**

## Issue Description

After the chat action selector was added, the default `Search Documents` option still serialized disabled `document_action` and `analyze` payload blocks. The underlying standard chat route is supposed to keep the legacy prompt flow, but this changed the request shape for normal chat turns and made tabular questions more likely to fall back to schema-only behavior.

## Root Cause Analysis

The chat client always built the shared document-action payload, even when the selected action type was `none`. That meant the default document-search path no longer matched the legacy request contract that tabular analysis had already been tuned around.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_standard_chat_document_action_payload_fix.py`
- `functional_tests/test_document_analysis_feature.py`

### Code Changes Summary

- Changed chat payload assembly so `document_action` is only sent when the user explicitly selects an opt-in action.
- Limited the legacy `analyze` compatibility payload to analysis runs only.
- Added a focused regression test that verifies `Search Documents` keeps the normal payload shape while opt-in actions still serialize their action-specific fields.

## Testing And Validation

- Functional regression: `functional_tests/test_standard_chat_document_action_payload_fix.py`
- Updated wiring check: `functional_tests/test_document_analysis_feature.py`

## Impact Analysis

- `Search Documents` now preserves the legacy request contract again.
- Document analysis and comparison continue to use the shared document-action routes.
- Tabular questions in the default document-search path are less likely to degrade into schema-only fallbacks caused by the changed request shape.