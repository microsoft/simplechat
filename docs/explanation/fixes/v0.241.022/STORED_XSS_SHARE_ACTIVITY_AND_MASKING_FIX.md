# Stored XSS Share Activity And Masking Fix

Fixed in version: **0.241.020**

## Issue

Several remaining stored XSS paths were still present after earlier chat and workspace hardening. Personal and group document share modals rehydrated attacker-controlled names through inline button handlers and toast HTML, the manage-group activity timeline rendered document names into HTML and raw JSON into a modal with `innerHTML`, and chat masking metadata trusted a client-supplied display name while the renderer interpolated it into attributes.

## Root Cause

The affected surfaces still mixed trusted markup with untrusted values inside template-string HTML and inline event handlers. The masking API also accepted `display_name` from browser JSON instead of deriving it from the authenticated user on the server.

## Files Modified

- `application/single_app/static/js/chat/chat-toast.js`
- `application/single_app/static/js/workspace/workspace-documents-sharing.js`
- `application/single_app/static/js/workspace/group-documents-sharing.js`
- `application/single_app/static/js/group/manage_group.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_stored_xss_share_activity_and_masking_fix.py`
- `ui_tests/test_document_share_modal_escaping.py`

## Code Changes Summary

- Replaced the shared chat toast HTML insertion with DOM creation and `textContent` assignment.
- Removed inline add/remove handlers from personal and group share modal results, switched both renderers to DOM-safe text nodes, and hardened their local toast helpers.
- Escaped group activity timeline descriptions, stored activity objects via jQuery data instead of serialized HTML attributes, and rendered the raw-activity modal with `textContent`.
- Rebuilt masked chat spans with DOM nodes instead of interpolated HTML attributes.
- Derived the masking display name from `get_current_user_info()` on the server instead of trusting request JSON.

## Testing Approach

- Functional regression: `functional_tests/test_stored_xss_share_activity_and_masking_fix.py`
- UI regression: `ui_tests/test_document_share_modal_escaping.py`
- Targeted diagnostics on each touched JavaScript file plus `py_compile` on `route_backend_chats.py`.

## Impact

- Stored group names, user names, emails, descriptions, activity file names, and masked-range display names now render as inert text in the remaining live browser sinks covered by findings f022, f042, and the residual masking portion of f037.
- The masking audit trail now reflects the authenticated server-side user instead of attacker-controlled browser input.

## Validation

- Before: share modals could rehydrate attacker markup through inline button handlers and toast bodies, activity rows and raw JSON modal views could inject HTML, and masking metadata could store a forged display name.
- After: those surfaces use DOM-safe text rendering, delegated click handling, and server-derived masking identity.