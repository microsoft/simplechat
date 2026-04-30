# Chat Stream History Context Fix (v0.240.053)

Fixed/Implemented in version: **0.240.053**

## Header Information

### Issue Description

Follow-up prompts in chat streaming mode could lean too heavily on the latest reply because the streaming route rebuilt model history with a narrower, drifted code path.

When the recent message window was small, older turns were dropped instead of summarized, which made short instructions like "please list the locations out in a single table" lose important context from earlier turns.

### Root Cause Analysis

`application/single_app/route_backend_chats.py` maintained two separate conversation-history builders.

The non-streaming path already supported older-turn summarization, masked-message filtering, inactive-thread filtering, and richer file and image context handling. The streaming path had its own reduced implementation, so the two code paths diverged over time.

### Version Implemented

`0.240.053`

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_stream_history_context_fix.py`
- `application/single_app/static/js/chat/chat-thoughts.js`
- `application/single_app/static/js/chat/chat-messages.js`

### Code Changes Summary

- Added a shared `build_conversation_history_segments` helper inside `application/single_app/route_backend_chats.py`.
- Switched both the streaming and non-streaming chat paths to use the same helper for recent-turn selection, older-turn summarization, masked-content removal, inactive-thread filtering, and file or image context conversion.
- Updated the streaming path to keep the default system prompt insertion summary-aware, matching the non-streaming behavior.
- Added compact `history_context` diagnostics so the backend records which message refs were treated as older, recent, summarized, skipped, and finally sent to the model.
- Emitted the history context into thoughts, assistant metadata, and optional debug citations so follow-up context selection is visible during troubleshooting.
- Kept the thoughts timeline concise by showing only the short history-context summary there, while leaving the detailed refs in message metadata and optional debug citations.
- Hydrated prior assistant citation artifacts and appended tabular-aware, deduplicated citation results to assistant history turns so follow-up questions can reuse exact prior tool outputs instead of only the assistant prose.
- Updated the chat message metadata drawer to render the new history-context detail.
- Bumped the application version to `0.240.053`.

## Validation

### Testing Approach

- Added `functional_tests/test_chat_stream_history_context_fix.py`.
- Verified the shared history builder summarizes older turns when the recent window is smaller than the full conversation.
- Verified masked and inactive messages are filtered before the final payload is sent to the model.
- Verified both streaming and non-streaming routes call the shared helper.
- Verified assistant history turns include prior citation results for follow-up prompts without dropping later file results behind redundant cross-sheet duplicates.
- Verified history-context diagnostics stay available in backend thought and metadata plumbing, while the thoughts UI remains summary-only.

### Impact Analysis

- Streaming follow-up prompts now retain older conversational context through the same summary path already used elsewhere.
- Short follow-up requests are less likely to anchor only on the immediately preceding answer.
- Each assistant response now carries enough history-selection detail to confirm which message ids and roles actually reached the model.
- The thoughts timeline stays readable instead of showing the full right-side history debug payload inline.
- Follow-up questions can now reuse prior citation results, including exact tabular tool outputs that were only visible in the citation drawer before, while preserving distinct values from multiple files.
- Future history-preparation changes now land in one place instead of drifting between two chat execution paths.