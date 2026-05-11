# Chat Stream Debug Logging Fix

Fixed/Implemented in version: **0.239.142**

## Issue Description

Normal chat usage goes through `/api/chat/stream`, but the streaming path did not emit enough unconditional `debug_print()` output to make local troubleshooting practical. Startup logging still worked, while key runtime steps in the streaming request and Semantic Kernel orchestration path were too quiet.

## Root Cause Analysis

The codebase still contained many `debug_print()` statements in `route_backend_chats.py`, but many of them were in the non-streaming `/api/chat` handler or inside narrower conditional branches. The frontend chat UI uses the streaming route by default, so important request entry and plugin orchestration events were not consistently visible in the local console.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_stream_debug_logging.py`
- `functional_tests/test_chat_stream_compatibility_sse_syntax.py`
- `functional_tests/test_chat_stream_background_execution.py`

### Code Changes Summary

- Added unconditional streaming-route `debug_print()` output for request entry, compatibility-mode routing, normalized request state, model initialization, conversation load/create, and final stream completion.
- Added explicit streaming Semantic Kernel orchestration logging for plugin invocation clearing, tabular-analysis entry/exit, response-path selection, plugin callback registration, plugin callback execution, and callback deregistration.
- Bumped the application version to `0.239.142`.
- Added a regression test that checks the required streaming debug markers remain present.
- Updated existing streaming regression tests to use the current application version.

### Testing Approach

- Added `functional_tests/test_chat_stream_debug_logging.py` to verify the new streaming debug markers exist.
- Re-ran existing streaming regression tests covering SSE syntax and background execution.

## Validation

### Before

- Startup debug output proved `debug_print()` still worked.
- Regular UI chat requests still appeared quiet in the console.
- Plugin execution visibility depended on hitting narrower branches instead of the main streaming path.

### After

- The streaming route now logs a request summary as soon as `/api/chat/stream` is entered.
- The console shows which response path was selected, when plugin callbacks were registered and fired, and when the stream finalized.
- Stream-focused regression tests pass with the updated instrumentation and version bump.

### Impact Analysis

This change is deliberately narrow: it restores operational visibility for the route the frontend already uses, without changing the streaming contract or response payload shape.