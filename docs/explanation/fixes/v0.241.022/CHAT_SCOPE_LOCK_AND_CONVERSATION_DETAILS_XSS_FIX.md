# Chat Scope-Lock And Conversation Details XSS Fix

Fixed in version: **0.241.019**

## Issue

Stored group and public workspace names, along with conversation metadata fields, were being inserted into chat modal HTML with raw string interpolation. A malicious workspace name or metadata value could render executable markup in the scope-lock picker or the conversation-details modal.

## Root Cause

The affected chat renderers mixed trusted static markup with untrusted names and metadata inside template-string HTML. The scope-lock modal built list items with raw `${name}` interpolation, and the conversation-details modal rendered multiple metadata fields and source links without consistently escaping or normalizing them.

## Files Modified

- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/static/js/chat/chat-conversation-details.js`
- `application/single_app/config.py`
- `functional_tests/test_stored_xss_chat_scope_and_conversation_details_fix.py`
- `ui_tests/test_chat_scope_lock_and_conversation_details_escaping.py`

## Code Changes Summary

- Replaced the scope-lock modal workspace list HTML assembly with DOM node creation and `textContent` assignment.
- Escaped dynamic conversation-details fields before they are injected into modal HTML.
- Normalized web source links so only valid `http` and `https` URLs remain clickable.
- Added focused functional and UI regressions for both modal surfaces.

## Testing Approach

- Functional regression: `functional_tests/test_stored_xss_chat_scope_and_conversation_details_fix.py`
- UI regression: `ui_tests/test_chat_scope_lock_and_conversation_details_escaping.py`
- Targeted diagnostics on both touched chat modules after editing.

## Impact

- Workspace names, conversation titles, participant labels, document labels, semantic tags, scope-lock names, and summary metadata now render as inert text in the affected chat modals.
- Unsafe web source payloads no longer create clickable `javascript:` links.

## Validation

- Before: malicious workspace names and conversation metadata could create executable DOM in chat modal surfaces.
- After: the same values are encoded before rendering, and non-HTTP web sources are downgraded to plain text.