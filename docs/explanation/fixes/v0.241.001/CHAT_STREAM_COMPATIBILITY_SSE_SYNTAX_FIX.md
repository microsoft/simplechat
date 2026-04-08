# Chat Stream Compatibility SSE Syntax Fix

Fixed/Implemented in version: **0.239.134**

## Issue Description

The compatibility branch inside the streaming chat route emitted image-generation thought events through multi-line f-strings that embedded `json.dumps({...})` directly inside the interpolation expression.

In CI, that block was parsed as an unterminated string literal in `route_backend_chats.py`, which stopped the job before runtime tests could begin.

## Root Cause Analysis

The SSE compatibility bridge assembled dictionary literals inline inside an f-string expression across multiple lines.

That formatting is fragile and parser-hostile in this file, especially in automated validation paths that compile the module directly.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_stream_compatibility_sse_syntax.py`
- `functional_tests/test_chat_stream_background_execution.py`
- `functional_tests/test_streaming_only_chat_path.py`
- `functional_tests/test_chat_completion_notifications.py`

### Code Changes Summary

- Replaced the three multi-line SSE `yield` statements in the compatibility image-generation path with explicit payload dictionaries stored in local variables.
- Kept the emitted SSE payload shape unchanged while making the code parser-safe.
- Added a regression test that compiles `route_backend_chats.py` and verifies the new payload-variable pattern.
- Bumped the application version to `0.239.134`.

### Testing Approach

- Added `functional_tests/test_chat_stream_compatibility_sse_syntax.py` to compile the route module and verify the fixed compatibility SSE block.
- Updated existing streaming-related functional tests so their version checks align with the current app version.

## Validation

### Before

- The compatibility SSE branch embedded multi-line dictionary literals directly inside f-string interpolation.
- CI could fail during parsing with `SyntaxError: unterminated string literal` near the first compatibility image-generation event.

### After

- The compatibility SSE branch builds JSON payload dictionaries first and interpolates only the serialized variable into the SSE frame.
- The route module compiles cleanly and preserves the same thought-event content for image-generation compatibility mode.

### Impact Analysis

This is a narrow, low-risk parser-safety fix. It does not change the compatibility mode contract or the streamed payload content, but it does prevent a syntax-level failure that blocked the chat route from loading.