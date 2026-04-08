# FACT MEMORY STREAMING CONTEXT FIX

Fixed/Implemented in version: **0.240.051**

Related config.py update: `VERSION = "0.240.051"`

## Issue Description

Saved fact-memory entries were present in the `agent_facts` Cosmos DB container, but normal chat usage still behaved as if fact memory was empty.

## Root Cause Analysis

- The standard `/api/chat` path prepended fact memory into the model context before agent execution.
- The main `/api/chat/stream` path did not prepend the same fact-memory system message, so streaming conversations skipped saved facts entirely.
- The fact lookup helper also overwrote the caller-provided agent id with the default configured agent id, which could break per-agent fact scoping.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_fact_memory_streaming_context_fix.py`

### Code Changes Summary

- Removed the fallback-to-default-agent overwrite inside the fact lookup helper so it now respects the selected agent id supplied by the current chat path.
- Added a shared `inject_fact_memory_context(...)` helper that prepends both fact memory and conversation metadata into the model history.
- Moved the fact-memory helpers into the shared `register_route_backend_chats(...)` scope so both `/api/chat` and `/api/chat/stream` can resolve them at runtime.
- Wired that helper into both the standard chat path and the streaming chat path so agent conversations use the same fact-memory context assembly.
- Bumped the application version to `0.240.051`.

### Testing Approach

- Functional regression: `functional_tests/test_fact_memory_streaming_context_fix.py`

## Validation

### Before

- Facts could be stored successfully in Cosmos DB, but streaming chat requests still reached the model without a `<Fact Memory>` system message.
- Fact lookup could silently use the default agent id instead of the selected agent id.

### After

- Both chat execution paths prepend the same fact-memory and conversation-metadata context before agent invocation.
- Fact lookup preserves the selected agent id passed by the caller.
- Saved facts in `agent_facts` now reach the streaming chat path instead of only the non-streaming route.