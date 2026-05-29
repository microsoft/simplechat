# Chat Capability Usage Metadata Fix (v0.241.123)

Fixed in version: **0.241.123**

## Issue Description

Chat metadata made document and web grounding visible only indirectly. User messages stored some button states, but Deep Research was not shown in the drawer, and assistant responses required readers to infer Web Search or Deep Research usage from website citations or source-review payloads.

## Root Cause Analysis

- Standard and streaming chat responses persisted citations and compact Deep Research details, but did not persist a shared explicit capability usage block.
- Analyze and Compare document-action messages had action-specific metadata, but did not expose the same Search / Analyze / Compare usage shape as standard workspace search messages.
- The metadata drawer showed Web Search button state for user messages and web citation counts for assistant messages, but did not render explicit Web Search used or Deep Research used fields.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_capability_usage_metadata.py`
- `ui_tests/test_chat_capability_metadata_drawer.py`

### Code Changes Summary

- Added a shared `capability_usage` metadata object for user and assistant messages.
- Tracked workspace action usage as `search`, `analyze`, or `compare` across standard chat, streaming chat, and document-action chat paths.
- Added explicit Web Search and Deep Research enabled/used fields to assistant response metadata.
- Updated the metadata drawer to show URL Access, Deep Research, and capability usage labels directly.
- Updated `config.py` from `0.241.122` to `0.241.123` for traceability.

### Testing Approach

- Added a functional regression that validates the helper output for Search, Analyze, Compare, Web Search, and Deep Research metadata.
- Added a Playwright UI regression that mocks message metadata payloads and verifies the drawer displays explicit capability usage labels.

## Validation

### Test Results

- `python functional_tests/test_chat_capability_usage_metadata.py`
- `python -m py_compile application/single_app/route_backend_chats.py functional_tests/test_chat_capability_usage_metadata.py`
- `node --check application/single_app/static/js/chat/chat-messages.js`

### Before / After

- Before: assistant metadata showed web citations but did not clearly state that Web Search or Deep Research was used.
- After: both user and assistant metadata include `capability_usage.web_search` and `capability_usage.deep_research` with explicit `enabled` and `used` values.
- Before: Analyze and Compare metadata was action-specific but not normalized with Search metadata.
- After: `capability_usage.actions` consistently records `search`, `analyze`, and `compare` usage.

### User Experience Improvements

- Users and admins can inspect a message and see exactly whether a response used workspace search, Analyze, Compare, Web Search, URL Access, or Deep Research.
- Web citations remain available, but they are no longer the only signal that a response used web grounding.