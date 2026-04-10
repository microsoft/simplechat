# Content Safety Thread Alignment Fix

## Fix Title
Blocked content-safety replies now reuse the reserved response message id and inherit the active conversation thread instead of being persisted as timestamp-only safety messages.

## Issue Description
When Content Safety blocked a chat turn, the backend created thoughts against the reserved assistant message id but persisted the visible safety response as a separate message with an empty metadata payload. That left the blocked response outside the thread chain and made streamed blocked replies finalize against a temporary placeholder instead of a saved threaded message.

## Root Cause Analysis
- The content-safety branch generated a second `safety_message_id` instead of reusing the already-reserved `assistant_message_id`.
- Persisted safety messages had no `metadata.thread_info`, so threaded conversation ordering treated them as legacy timestamp-only messages.
- The streaming blocked path emitted content and a raw `[DONE]` marker instead of the normal final JSON payload, so the client could not finalize the temporary message onto the correct saved record.

## Version Implemented
Fixed in version: **0.240.076**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/route_backend_chats.py` | Reused the reserved response message id for blocked safety messages, copied the active thread metadata from the user message, and emitted a normal streaming completion payload for blocked responses |
| `application/single_app/static/js/chat/chat-streaming.js` | Finalized streamed blocked replies as safety messages instead of always rendering them as AI replies |
| `functional_tests/test_content_safety_thread_alignment.py` | Added regression coverage for reserved message-id reuse, persisted thread metadata, and blocked-stream finalization |
| `application/single_app/config.py` | Version bump to 0.240.076 |

## Code Changes Summary
- Added a shared helper to load response-thread context from the originating user message.
- Added a threaded safety-message builder so blocked replies persist with the same message id and thread chain as the reserved assistant response.
- Stored the reserved message id and thread metadata with the safety-audit record for consistent traceability.
- Replaced the ad-hoc streamed blocked response terminator with the same final JSON shape used by successful streamed replies.
- Updated the streaming finalizer to render blocked completions with the existing safety-message UI treatment.

## Testing Approach
- Added `functional_tests/test_content_safety_thread_alignment.py`.
- Validated the edited Python and JavaScript files for errors after patching.

## Impact Analysis
- Blocked content-safety replies now stay in the correct retry/thread branch when conversations are reloaded.
- Streamed blocked responses now finalize onto a persisted message id instead of remaining tied to a temporary placeholder.
- Thought records and blocked message persistence now reference the same response id, improving traceability for audits and debugging.

## Validation
- Before: blocked safety replies were ordered by timestamp as legacy messages, and streaming blocked turns could fail to finalize onto a saved threaded message.
- After: blocked safety replies persist on the active thread with the reserved response id, and streaming finalization resolves to the same saved safety message.