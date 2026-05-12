# Collaboration Invite Toast Button Fix

Fixed/Implemented in version: **0.241.153**

## Issue Description

Pending collaboration invite notifications displayed the intended Review invite button as literal HTML text. Users saw markup such as `<strong>` and `<button>` inside the toast instead of a clickable action.

## Root Cause Analysis

The collaboration invite code passed an HTML string into the shared chat toast helper. The toast helper correctly rendered normal string messages with `textContent`, so the markup was escaped and shown as text. That protected the page from unsafe HTML injection, but it also meant intentional action content could not render.

## Files Modified

- `application/single_app/static/js/chat/chat-toast.js`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `functional_tests/test_collaboration_invite_toast_button_fix.py`
- `ui_tests/test_chat_collaboration_invite_toast_button.py`
- `application/single_app/config.py`

## Code Changes Summary

- Updated the shared chat toast helper to accept a DOM `Node` message while keeping string messages rendered with `textContent`.
- Rebuilt the pending collaboration invite toast with DOM APIs instead of an interpolated HTML string.
- Assigned the conversation title through `textContent` so markup-looking titles remain inert.
- Bound the Review invite click handler directly to the generated button.
- Updated `application/single_app/config.py` to version `0.241.153` for this fix.

## Testing Approach

- Added a functional regression test that verifies the collaboration invite code uses DOM construction and that the toast helper keeps string messages as text.
- Added a Playwright UI regression that renders a DOM-based toast message, confirms the Review invite button is clickable, and verifies a markup-looking conversation title does not create executable DOM nodes.

## Impact Analysis

- Pending collaboration invites now show a proper Review invite button in the toast.
- Existing plain text toasts continue to render safely as inert text.
- Collaboration conversation titles remain protected from XSS when rendered inside invite notifications.

## Validation

- `node --check application/single_app/static/js/chat/chat-toast.js`
- `node --check application/single_app/static/js/chat/chat-collaboration.js`
- `python -m py_compile functional_tests/test_collaboration_invite_toast_button_fix.py ui_tests/test_chat_collaboration_invite_toast_button.py`
- `python functional_tests/test_collaboration_invite_toast_button_fix.py`
- `python -m pytest ui_tests/test_chat_collaboration_invite_toast_button.py`