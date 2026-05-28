# Conversation Feed Pagination

Implemented in version: **0.241.112**

## Overview

Conversation Feed Pagination reduces chat startup work by loading a prioritized first page instead of sending every accessible conversation to the browser. The first feed response includes pinned conversations, unread conversations, and the first page of recent conversations. Additional recent conversations load through a cursor when the user clicks **Load more conversations** or scrolls near the bottom of the list.

## Dependencies

- Flask conversation APIs in `application/single_app/route_backend_conversations.py`
- Feed merge helpers in `application/single_app/functions_conversation_feed.py`
- Chat list rendering in `application/single_app/static/js/chat/chat-conversations.js`
- Sidebar conversation rendering in `application/single_app/static/js/chat/chat-sidebar-conversations.js`
- Collaboration notification read state from the notifications container

## Technical Specifications

The `/api/conversations/feed` endpoint returns a merged feed payload with:

- All visible pinned conversations on the first page
- All visible unread conversations on the first page
- A cursor-paged window of recent non-priority conversations
- A hidden conversation count for the show-hidden control
- A `next_cursor` value when more recent conversations are available

The backend merges legacy personal conversations and collaborative conversations into one response shape. Hidden conversations are excluded unless `include_hidden=true` is passed. Quick title search is sent to the backend so it searches beyond the currently loaded page.

## Usage Instructions

Users do not need to enable the feature. Opening the chat page loads the first prioritized feed automatically. More conversations can be loaded from the list control or by scrolling near the bottom of the conversation list.

## Testing and Validation

- Functional coverage: `functional_tests/test_conversation_feed_pagination.py`
- UI coverage: `ui_tests/test_chat_sidebar_single_startup_load.py`

Known limitation: phase one still uses the existing collaboration access loaders internally. A future feed index can further reduce backend reads for users with very large collaborative conversation histories.