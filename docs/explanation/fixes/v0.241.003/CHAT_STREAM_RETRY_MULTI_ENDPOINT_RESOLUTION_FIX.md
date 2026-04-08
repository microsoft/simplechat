# Chat Stream Retry Multi Endpoint Resolution Fix

Fixed/Implemented in version: **0.241.003**

Related config.py update: `VERSION = "0.241.003"`

## Overview

Streaming retries that route through the legacy compatibility bridge now reuse the in-app multi-endpoint GPT resolver instead of failing during model initialization with undefined helper names.

## Issue Description

When `/api/chat/stream` handled a retry request, it switched into the compatibility bridge and delegated the actual response generation to `/api/chat`. In multi-endpoint environments, that path could fail before any streamed content was returned with `Failed to initialize AI model: name 'resolve_multi_endpoint_gpt_config' is not defined`.

## Root Cause Analysis

`application/single_app/route_backend_chats.py` had been updated to use in-app streaming helpers for live streaming requests, but the legacy `/api/chat` path still referenced script-only helper names that were never defined in the Flask app module:

- `resolve_default_model_gpt_config`
- `resolve_multi_endpoint_gpt_config`
- `build_multi_endpoint_client`
- `get_foundry_api_version_candidates`

That left the compatibility bridge with a split implementation where normal streaming requests worked, but retry/edit compatibility requests could still raise `NameError` during GPT client setup.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_stream_retry_multiendpoint_resolution_fix.py`

### Code Changes Summary

- Updated `/api/chat` to call `resolve_streaming_multi_endpoint_gpt_config(...)` with the current `user_id`, validated `active_group_ids`, and default-model fallback flag so the compatibility path shares the same endpoint/model resolution logic as `/api/chat/stream`.
- Added an in-app `get_foundry_api_version_candidates(...)` helper so Foundry compatibility retries can enumerate fallback API versions without importing script-only code.
- Updated the non-streaming Foundry retry block to use `build_streaming_multi_endpoint_client(...)` for in-app client reconstruction.

## Testing Approach

- Added `functional_tests/test_chat_stream_retry_multiendpoint_resolution_fix.py` to verify that `/api/chat` now uses the shared multi-endpoint resolver, no longer references the removed helper names, and keeps the fix documentation/version aligned.

## Impact Analysis

- Retry and edit flows in `/api/chat/stream` keep working when they fall back to the compatibility bridge.
- Multi-endpoint GPT selection is now resolved consistently between `/api/chat` and `/api/chat/stream`.
- Foundry compatibility retries no longer depend on helper functions that only exist in `scripts/resolve_multiendpoint_gpt.py`.

## Validation

- Before: compatibility-mode streaming retries could terminate immediately with undefined-name errors before any SSE content arrived.
- After: compatibility-mode retries reuse the in-app model-resolution and Foundry fallback helpers, so GPT initialization proceeds through the same supported code paths as the primary streaming route.