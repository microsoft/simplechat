# Collaboration Reply And Avatar Fix (v0.241.014)

Fixed/Implemented in version: **0.241.014**

## Issue Description

Shared conversations still felt incomplete in three visible ways:

1. Other participants could show a broken or collapsed avatar inside shared message bubbles, even when a profile image existed.
2. Shared join, removal, and role-change toasts could replay when a user re-opened the same shared conversation because the event stream cached historical events.
3. Shared chats did not expose a reply workflow, so users could not quote and answer a specific participant message from the conversation timeline.

## Root Cause Analysis

The collaboration UI already loaded participant avatars in the conversation details modal and persisted `reply_to_message_id` in the collaboration route, but the chat transcript and composer did not reuse either capability.

- Shared message rendering used a custom collaborator avatar wrapper instead of the same top-level avatar image styling used elsewhere in chat.
- The collaborator avatar flex item could shrink under the shared-message layout, which caused profile images to collapse into a thin strip on the left edge of the row.
- The collaboration event client reattached to a replayable event cache without suppressing historical events, so stale toasts were shown again on re-entry.
- The compose area had no reply target state, no reply preview container, and no user-message action for selecting a reply target.

## Files Modified

1. `application/single_app/static/js/chat/chat-collaboration.js`
2. `application/single_app/static/js/chat/chat-messages.js`
3. `application/single_app/static/css/chats.css`
4. `application/single_app/templates/chats.html`
5. `ui_tests/test_chat_collaboration_ui_scaffolding.py`
6. `functional_tests/test_collaboration_reply_and_avatar_fix.py`
7. `application/single_app/config.py`

## Code Changes Summary

1. Added composer-level reply state for collaborative conversations, including a dismissible reply preview panel above the chat input.
2. Added a Reply action to collaborator message menus and rendered quoted reply context inside shared user and collaborator bubbles.
3. Reused the existing per-user profile image endpoint to hydrate collaborator avatars in shared message bubbles, with initials as the fallback state.
4. Switched hydrated collaborator avatars onto the same top-level avatar image element used by the standard chat rows and locked the avatar slot to a fixed flex width so it cannot collapse.
5. Added replay-event suppression in the collaboration event client so cached invite, removal, and role-change events do not re-toast each time a shared conversation is reselected.
6. Updated the collaboration UI regression and added a functional regression file that locks in the reply-preview, avatar, and replay-suppression hooks.

## Testing Approach

1. Updated `ui_tests/test_chat_collaboration_ui_scaffolding.py` to validate the reply preview container and reply selection behavior.
2. Added `functional_tests/test_collaboration_reply_and_avatar_fix.py` to verify the relevant collaboration UI hooks remain present.
3. Ran file diagnostics on the modified JavaScript, CSS, HTML, and Python files.

## Validation

### Before

1. Collaborator bubbles showed the generic avatar even when profile images were available.
2. Reopening a shared conversation could replay old green collaboration toasts from the cached SSE session.
3. Users had no targeted reply workflow in shared chats.

### After

1. Shared collaborator bubbles can show the participant profile image when one exists and otherwise fall back to initials, without collapsing the avatar width.
2. Historical collaboration events are ignored when reconnecting to a shared conversation, which prevents repeated join or role-change toasts.
3. Users can reply to another participant, see the quoted reply target above the composer, and keep the quoted context in the resulting shared message bubble.

## Related Tests

1. `functional_tests/test_collaboration_reply_and_avatar_fix.py`
2. `ui_tests/test_chat_collaboration_ui_scaffolding.py`