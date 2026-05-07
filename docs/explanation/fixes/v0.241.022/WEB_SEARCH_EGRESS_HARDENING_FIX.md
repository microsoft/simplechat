# Web Search Egress Hardening Fix

Fixed/Implemented in version: **0.241.008**

## Overview

This fix hardens the Bing Grounding web-search boundary so external web search only receives the current user message, not a history-derived rewrite or summarized conversation context. It also corrects the admin and user-facing disclosure text so the UI now matches the implemented data egress behavior.

Version implemented:
`config.py` was updated to `VERSION = "0.241.008"` for this fix.

## Issue Description

The web-search path previously reused the general-purpose `search_query` variable from chat processing. That variable supports internal workspace search behavior, including history-grounded follow-up rewrites and an optional summarized-history branch.

That reuse created two problems:

- The external web-search call could send a query derived from recent conversation context instead of only the user's current typed message.
- The default disclosure text incorrectly told users that only the current message was sent, even when the backend could derive a history-based query.

## Root Cause

The root cause was a missing boundary between:

- Internal search-query construction for workspace and follow-up retrieval behavior.
- External web-search egress to the Azure AI Foundry agent that fronts Bing grounding.

Because both behaviors shared the same variable and call path, history-derived internal context could cross the external web-search boundary.

## Technical Changes

### External Web Search Query Separation

The backend now uses a dedicated helper, `build_web_search_query_text(user_message)`, to define the only chat content allowed to leave the app for external web search.

Changes implemented:

- Added `build_web_search_query_text(user_message)` in `application/single_app/route_backend_chats.py`.
- Updated both `/api/chat` and `/api/chat/stream` to pass `web_search_query_text` into `perform_web_search(...)`.
- Stopped `perform_web_search(...)` from reading the generic internal `search_query` variable.
- Updated web-search thought text to reflect the explicit outbound query value.

Files involved:

- `application/single_app/route_backend_chats.py`

Security outcome:

External web search is now current-message-only, even when internal workspace-search logic still uses history-derived search behavior.

### Foundry Metadata Minimization

The web-search boundary previously attached a metadata payload containing identifiers and context fields such as conversation id, user id, scope, and the search query itself.

Changes implemented:

- Replaced the previous `foundry_metadata` payload with an empty metadata dictionary for the web-search invocation path.

Files involved:

- `application/single_app/route_backend_chats.py`

Security outcome:

The Foundry web-search invocation no longer sends the previous identifier metadata blob by default.

### Search Summary Hardening

The optional summarized-history branch for internal search could summarize raw stored messages, including persisted system augmentation content.

Changes implemented:

- Filtered the search-summary input to `user` and `assistant` roles only.
- Reused `build_assistant_history_content_with_citations(...)` for assistant turns so the summary path follows the same bounded history shape used elsewhere in chat history preparation.

Files involved:

- `application/single_app/route_backend_chats.py`

Security outcome:

Persisted system augmentation messages are no longer part of the optional search-summary input.

### Disclosure Text Corrections

The default web-search notice text and admin-facing copy now match the implemented boundary.

Changes implemented:

- Updated the default `web_search_user_notice_text`.
- Updated the admin settings default and textarea placeholder text.
- Updated the chat banner fallback text.
- Updated the admin consent modal warning text.

Files involved:

- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/chats.html`

User-facing outcome:

Users and administrators now see copy that states the current message is sent for web search, conversation history is not sent for web search, and sensitive content pasted into that message may still be sent.

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/chats.html`
- `application/single_app/config.py`
- `functional_tests/test_web_search_current_message_only.py`
- `ui_tests/test_web_search_notice_copy.py`

## Validation

Testing approach:

- Added a functional regression test for the outbound web-search boundary.
- Added a lightweight Playwright UI regression for the updated admin disclosure copy.
- Validated the touched Python files with targeted `py_compile` runs.

Validation results from this implementation pass:

- `functional_tests/test_web_search_current_message_only.py`: passed.
- `ui_tests/test_web_search_notice_copy.py`: passed in collection/execution and skipped cleanly in the current environment because authenticated UI environment variables were not present.
- `python -m py_compile application/single_app/route_backend_chats.py`: passed.
- `python -m py_compile application/single_app/functions_settings.py application/single_app/route_frontend_admin_settings.py`: passed.

## Before And After

Before:

- External web search could reuse a history-derived internal `search_query`.
- The optional search-summary branch included raw stored-message roles beyond `user` and `assistant`.
- The default notice text claimed only the current message was sent, even though the backend could derive a history-based outbound query.
- The Foundry web-search call included a larger metadata payload than necessary.

After:

- External web search only uses the current user message.
- Internal history-based search behavior remains separate from the external web-search boundary.
- The search-summary branch excludes persisted system augmentation messages.
- The admin and user-facing notice text matches the implemented behavior.
- The Foundry web-search call no longer includes the previous identifier metadata blob by default.