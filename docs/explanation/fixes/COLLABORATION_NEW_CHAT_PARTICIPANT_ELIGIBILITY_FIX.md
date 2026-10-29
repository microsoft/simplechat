# Collaboration New Chat Participant Eligibility Fix (v0.261.047)

Fixed and implemented in version: **0.261.047**

## Issue Description

Starting a chat from a personal workspace file creates a fresh personal conversation and preselects the file for grounded chat. Before the first prompt was sent or the conversation was reloaded from server metadata, the browser stored that conversation with the transient `new` chat type. The collaboration UI treated `new` as ineligible for participant management, so **Add participants** did not appear even when collaborative conversations were enabled.

## Root Cause Analysis

The backend creates new personal conversations with `chat_type: "new"` until metadata collection classifies the conversation. The collaboration participant picker and conversation action menu only allowed already-normalized personal and group chat types. That left a short-lived but user-visible gap for document-launched personal chats.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/static/js/chat/chat-conversation-details.js`
- `application/single_app/static/js/chat/chat-sidebar-conversations.js`
- `application/single_app/route_backend_conversations.py`
- `functional_tests/test_chat_type_normalization.py`
- `ui_tests/test_chat_collaboration_ui_scaffolding.py`
- `application/single_app/config.py`

### Code Changes Summary

- Normalized transient `new` chat types to `personal_single_user` for participant-flow eligibility in the chat UI.
- Updated conversation list action rendering so freshly created personal chats can show **Add participants** immediately.
- Updated sidebar and conversation details rendering so the same action is available without leaving or reloading Chat.
- Updated backend conversation metadata normalization so details payloads do not keep stale `new` chat types after normalization.

### Testing Approach

- Extended chat type normalization coverage to assert the `new` to `personal_single_user` eligibility contract.
- Extended collaboration UI scaffolding coverage to exercise `openParticipantPicker()` against a mocked fresh `new` conversation item.
- Ran JavaScript syntax checks for the changed chat modules.

## Validation

### Test Results

- `node --check application/single_app/static/js/chat/chat-collaboration.js`
- `node --check application/single_app/static/js/chat/chat-conversations.js`

### Before And After

- Before: a personal workspace file-launched chat could remain marked as `new` in the browser, hiding **Add participants** until Chat was fully reloaded.
- After: the transient `new` placeholder is treated as a personal single-user chat for participant eligibility across the main list, sidebar, picker, and details modal, while backend ownership and collaboration checks remain authoritative.

### User Experience Improvements

- Users can invite participants into a newly created personal file chat without needing to send a message, reload, or reselect the conversation first.