# Chat History Grounded Follow-Up Fix (v0.240.055)

Fixed/Implemented in version: **0.240.055**

## Header Information

### Issue Description

Follow-up prompts that referred to previously cited documents could lose grounded retrieval when the user did not re-enable workspace search on the next turn.

The app already replayed prior assistant citation summaries into conversation history, but if that replay was not enough to answer the follow-up, the backend had no exact bounded document set to re-query. That made grounded follow-ups weaker than they should be and risked forcing users to manually reselect the same document context.

### Root Cause Analysis

`application/single_app/route_backend_chats.py` reused prior assistant citation context in history, but it did not persist an exact latest grounded document anchor for later turns.

When workspace search was off, the chat routes could only rely on conversation prose and citation summaries. They could not selectively retry retrieval against the exact previously grounded documents, and they had no explicit no-search grounding instruction to fail closed when prior context was insufficient.

### Version Implemented

`0.240.055`

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_conversation_metadata.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_history_grounded_follow_up_fix.py`

### Code Changes Summary

- Added stable grounded-document persistence in `application/single_app/functions_conversation_metadata.py` via `last_grounded_document_refs`, including stable `document_id`, scope, scope id, filename, and classification.
- Added helper logic in `application/single_app/route_backend_chats.py` to normalize prior grounded refs, derive bounded search parameters, and build the no-search grounding system instruction.
- Updated both non-streaming and streaming chat paths to evaluate whether prior conversation history is sufficient before issuing any new retrieval.
- Added a bounded fallback path that searches only the previously grounded documents when history alone is not enough and workspace search remains disabled.
- Preserved existing explicit workspace-selection behavior by keeping current workspace search authoritative when the user turns it on.
- Updated message and conversation metadata so fallback-grounded turns persist the effective document scope, selected documents, and retrieval query for later follow-ups.
- Bumped the application version to `0.240.055`.

## Validation

### Testing Approach

- Added `functional_tests/test_chat_history_grounded_follow_up_fix.py`.
- Verified stable grounded refs are built from search-backed document usage across personal, group, and public scopes.
- Verified prior grounded refs normalize from `last_grounded_document_refs` first and fall back to document tags when needed.
- Verified bounded fallback search parameters keep retrieval limited to previously grounded documents and preserve scope-specific ids.
- Verified both standard and streaming chat paths contain the history-only assessment, previously grounded document fallback, and no-search grounding prompt wiring.

### Impact Analysis

- Follow-up turns can now stay grounded even when the user asks a short continuation question without re-enabling workspace search.
- Retrieval remains bounded to the exact previously grounded documents instead of widening back out to all available workspaces.
- When history and bounded fallback retrieval are still insufficient, the model is explicitly instructed to ask the user to select a workspace or document instead of improvising.
- The persisted `last_grounded_document_refs` metadata gives later turns a precise anchor for grounded follow-up behavior.