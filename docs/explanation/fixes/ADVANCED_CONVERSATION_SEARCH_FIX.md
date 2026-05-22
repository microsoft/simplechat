# Advanced Conversation Search Fix - Version 0.241.097

## Issue Description

The left sidebar conversation search used client-side partial title matching, while the Advanced Search modal used a backend message-only path with stricter chat type filtering and legacy-only message storage. Searches such as `Chase` could miss recent conversations whose titles or collaborative messages contained related terms such as JP Morgan Chase.

## Root Cause Analysis

Advanced search had three gaps:

* The default modal chat type values did not align with stored values such as `personal_single_user`, `personal_multi_user`, and `group_multi_user`.
* The backend searched `cosmos_messages_container` but did not search collaborative conversations and messages stored in the collaboration containers.
* Results were only built from message matches, so conversation title matches found by the sidebar search path were not included in advanced results.

## Fixed/Implemented in version: **0.241.097**

The application version was updated in `application/single_app/config.py` from `0.241.096` to `0.241.097` for this fix.

## Technical Details

### Files Modified

* `application/single_app/route_backend_conversations.py`
* `application/single_app/templates/chats.html`
* `application/single_app/static/js/chat/chat-search-modal.js`
* `application/single_app/config.py`
* `functional_tests/test_advanced_conversation_search_matching_fix.py`
* `ui_tests/test_advanced_conversation_search_match_mode.py`

### Code Changes Summary

* Added explicit advanced search match modes: contains partial text, all words, any word, and whole word.
* Kept `contains` as the default mode so substring searches such as `Chase` can match larger tokens such as `JPMorganChase`.
* Normalized chat type filters so modal values map to stored personal, group, and collaboration chat type values.
* Included accessible collaborative conversations and `cosmos_collaboration_messages_container` messages in advanced search.
* Included conversation title matches in advanced search results, with title-only results opening the matching conversation.
* Parameterized Cosmos text search queries to avoid interpolating search terms into query text.

### Testing Approach

* Added a functional test for partial matching, match modes, chat type aliasing, parameterized message queries, collaboration search route contracts, and version/documentation alignment.
* Added an optional Playwright UI test that verifies the modal sends the selected match mode and normalized multi-user group filter to `/api/search_conversations`.

## Impact Analysis

Advanced Search now behaves more like the left sidebar search while preserving richer filters. It searches both titles and message content across legacy and collaborative conversation stores, and users can choose narrower whole-word or broader word-token behavior when needed.

## Validation

Before the fix, advanced search could miss recent collaborative/title-only results and could silently filter out stored chat types that did not exactly match modal values.

After the fix, searches such as `Chase` use partial matching by default, include conversation titles, include collaboration messages, and support explicit match modes for broader or narrower searches.