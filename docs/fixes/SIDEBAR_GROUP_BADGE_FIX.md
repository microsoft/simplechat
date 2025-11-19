# Sidebar Group Badge Fix (v0.233.162)

## Summary
- **Issue:** Group conversations in the sidebar list were indistinguishable from personal chats, making it hard to spot shared threads quickly.
- **Root Cause:** The sidebar rendering logic ignored conversation metadata (`chat_type` / group context) and never added a visual indicator.
- **Fixed/Implemented in version:** **0.233.162**
- **Related configuration:** `config.py` (`VERSION`)

## Technical Details
- **Files modified:**
  - `application/single_app/static/js/chat/chat-sidebar-conversations.js`
  - `application/single_app/config.py`
- **Key changes:**
  - Capture group context metadata when building sidebar entries and insert a Bootstrap badge labeled `group` between the title and dropdown.
  - Ensure the conversation title still truncates correctly by wrapping it with a flex container.
- **Tests added:**
  - `functional_tests/test_sidebar_group_badge_fix.py`

## Validation
- **Automated tests:** `functional_tests/test_sidebar_group_badge_fix.py`
- **Manual verification:** Load the chats page with a conversation whose `chat_type` starts with `group` and confirm the sidebar shows a `group` badge before the options menu.
