# Streaming Thought Progression Fix

Fixed/Implemented in version: **0.239.185**

## Overview

This fix restores live thought progression in the chat streaming placeholder without reintroducing the previous-message bleed-through regression.

## Issue Description

After the earlier stale-thought isolation work, the active streaming placeholder could stop advancing through new thought updates. Users would often see one early thought remain visible until the assistant began streaming content, even though later thought events had been recorded for the same reply.

## Root Cause

- The live placeholder relied on message correlation state that was not fully reset per placeholder session.
- Pending-thought polling still grouped by the most recent message in the conversation window instead of allowing the caller to request thoughts for a specific assistant message.
- The browser had no dedicated per-placeholder state for deduping and ordering thought updates while still blocking stale events from older messages.

## Files Modified

- `application/single_app/static/js/chat/chat-thoughts.js`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/functions_thoughts.py`
- `application/single_app/route_backend_thoughts.py`
- `functional_tests/test_streaming_thought_finalization.py`
- `functional_tests/test_pending_thought_message_scoping.py`
- `ui_tests/test_streaming_thought_progression.py`
- `application/single_app/config.py`

## Code Changes Summary

- Added explicit per-placeholder reset and dedupe state for live streaming thoughts.
- Preserved the active assistant message guard so stale thoughts from a prior reply are still ignored.
- Added an optional `message_id` query parameter to the pending-thought API and backend helper.
- Returned `message_id` in sanitized thought payloads so callers can verify correlation.
- Restored live SSE emission for agent/plugin invocation thoughts instead of replaying those updates only after the stream completed.
- Added regression coverage for browser placeholder updates and message-scoped pending thought queries.

## Testing Approach

- Functional test coverage validates the message-scoped pending-thought backend contract and the updated live-thought frontend hooks.
- UI test coverage validates that the placeholder advances to the newest thought, does not retain the previous message's thought, and ignores new thought updates once response content starts streaming.

## Impact Analysis

- Streaming replies now keep the latest current-message thought visible until the assistant starts sending response text.
- Reconnect and fallback callers can request pending thoughts for one assistant message instead of reading whichever message updated most recently.
- The stale-thought isolation behavior remains in place for consecutive replies.