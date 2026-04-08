# Chat History Grounded Follow-Up Fix (v0.241.003)

Fixed/Implemented in version: **0.241.003**

## Header Information

### Issue Description

The grounded follow-up fallback correctly kept later turns bounded to previously grounded documents, but the final no-search grounding prompt also ran for brand-new conversations and never-grounded conversations.

That caused general model-only questions to fail closed with messages such as "I do not have enough grounded information from the prior conversation sources" even when no workspace knowledge had been used in the conversation.

### Root Cause Analysis

`application/single_app/route_backend_chats.py` injected the no-search history grounding system message whenever workspace search was disabled for the current turn.

The prompt insertion did not check whether `last_grounded_document_refs` actually existed for the conversation, so the bounded grounded-follow-up rule leaked into ordinary model-only turns.

### Version Implemented

`0.241.003`

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_history_grounded_follow_up_fix.py`

### Code Changes Summary

- Added a dedicated guard in `application/single_app/route_backend_chats.py` so the no-search grounding prompt is only inserted when the conversation already has `last_grounded_document_refs`.
- Kept the existing `last_grounded_document_refs` persistence contract from `application/single_app/functions_conversation_metadata.py` as the anchor for bounded grounded follow-up behavior.
- Preserved the existing bounded fallback behavior that reuses prior citations and searches only previously grounded documents when history alone is insufficient.
- Left explicit workspace search behavior unchanged when the user turns search back on.
- Updated the grounded follow-up functional test to verify the narrower prompt-insertion contract in both standard and streaming chat paths.
- Bumped the application version to `0.241.003`.

## Validation

### Testing Approach

- Updated `functional_tests/test_chat_history_grounded_follow_up_fix.py`.
- Verified the grounding prompt helper returns `False` for new or never-grounded conversations and `True` only when prior grounded refs exist.
- Verified both standard and streaming chat paths still keep the bounded follow-up fallback logic while applying the final grounding prompt only behind the new guard.

### Impact Analysis

- New conversations without prior grounded document refs now answer normally from model knowledge when workspace search is off.
- Conversations that already used workspace grounding still retain the bounded follow-up behavior and can reuse past citations to search only the previously grounded documents.
- The fail-closed "select a workspace or document" behavior remains available, but only for the grounded follow-up scenarios it was designed to protect.