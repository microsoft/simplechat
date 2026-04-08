# FACT MEMORY STREAMING RETRIEVAL FIX

Fixed/Implemented in version: **0.240.081**

Related config.py update: `VERSION = "0.240.081"`

## Issue Description

Streaming chats could ignore saved fact memories for plain GPT requests such as `who am i?`, even when fact memory was enabled and user memories existed.

## Root Cause Analysis

- The streaming `/api/chat/stream` path defaulted `user_enable_agents` to `False` when the per-user setting was missing, while the non-streaming path used backward-compatible default `True`.
- Fact memory recall only ran inside the agent-enabled branch, so plain GPT requests skipped fact-memory augmentation entirely.
- When fact memory did run, it injected all saved memories into the prompt instead of searching for request-relevant matches, and it did not emit its own visible thoughts and citations.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-thoughts.js`
- `application/single_app/config.py`
- `functional_tests/test_fact_memory_profile_and_mini_sk.py`
- `functional_tests/test_fact_memory_streaming_retrieval_fix.py`

### Code Changes Summary

- Aligned `/api/chat/stream` with the non-streaming agent default and request-agent override behavior.
- Moved fact memory recall outside the agent-only branch so plain GPT requests can still use saved memory when the admin toggle is enabled.
- Replaced full fact-memory prompt injection with request-scoped retrieval that selects only relevant saved facts.
- Added a dedicated `fact_memory` thought step and `Fact Memory Recall` citation so users can see when fact memory was used or when no relevant memory matched.

### Testing Approach

- Functional regression: `functional_tests/test_fact_memory_streaming_retrieval_fix.py`
- Feature regression refresh: `functional_tests/test_fact_memory_profile_and_mini_sk.py`

## Validation

### Before

- `who am i?` could go through the plain GPT streaming path without loading saved fact memories.
- Saved fact memories were either hidden prompt stuffing or completely invisible to the user.

### After

- Streaming plain GPT chats can retrieve relevant saved fact memories even without an explicit agent selection.
- Fact memory retrieval is visible in thoughts and citations.
- Only relevant saved memories are added to the prompt instead of every saved memory.