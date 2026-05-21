# URL Access Button State Fix

Fixed in version: **0.241.084**

## Issue Description
The URL Access button could remain selected after a user started a new conversation or switched to another conversation, even when the new composer context did not intentionally enable URL Access.

## Root Cause
URL Access selection was tracked only through the button's local `active` class. Conversation creation and conversation selection updated chat content and conversation metadata, but did not notify the chat input action controls to clear per-message source action state.

## Technical Details
- Added a chat input reset handler that clears URL Access and Deep Research selected state when the active conversation context changes.
- Added a `chat:conversation-context-changed` event from conversation selection and manual new conversation creation.
- Kept URL Access and Deep Research `aria-pressed` values synchronized with their visible selected state.
- Added UI regression coverage in `ui_tests/test_chat_url_access_button_reset.py`.
- Updated `config.py` version to `0.241.084`.

## Validation
- JavaScript syntax validation confirms the changed chat modules parse successfully.
- The UI regression validates that URL Access becomes inactive after selecting another conversation and after clicking New Conversation.

## Impact
URL Access now behaves as a per-message action instead of leaking selected state into unrelated conversation contexts. Users can switch chats or start fresh without accidentally sending URL Access enabled from the prior context.
