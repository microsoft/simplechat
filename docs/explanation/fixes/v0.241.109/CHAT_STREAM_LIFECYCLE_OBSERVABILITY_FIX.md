# Chat Stream Lifecycle Observability Fix

## Overview

Fixed/Implemented in version: **0.241.109**
Related config update: `application/single_app/config.py` now reports `VERSION = "0.241.109"`.
Related functional test: `functional_tests/test_chat_stream_lifecycle_observability.py`

This change improves diagnostics for long-running chat streams, including document analysis runs that can stay active for 30 to 40 minutes.

## Issue Description

The streaming chat path already continued running on the backend after a browser-side disconnect, but the logging and status surfaces were too thin to prove what happened after a frontend failure.

Before this fix:
- Backend logs showed request start and some terminal conditions, but not a clear lifecycle for detach, reattach, keepalive, queue pressure, and terminal state.
- `/api/chat/stream/status/<conversation_id>` only reported whether a stream was currently pending.
- Frontend stream failures lived mostly in browser console output and were not reported back to the backend.
- Operators could not reliably answer whether a detached stream was still running, had completed, or had failed later.

## Root Cause Analysis

The stream session metadata only tracked a narrow `active` state and replay cache information. The stream bridge and reattach route handled disconnects and recovery, but they did not persist a richer lifecycle model or emit correlated structured logs for those transitions.

## Technical Details

### Files Modified
- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_stream_lifecycle_observability.py`

### Code Changes Summary
- Added backend stream lifecycle status helpers and persisted status snapshots for:
  - start
  - first content emitted
  - keepalive
  - detach
  - reattach
  - queue backpressure
  - completion
  - error
- Extended stream status responses to include lifecycle metadata instead of only a pending flag.
- Added a client-event endpoint so the frontend can report stream request errors, read errors, premature endings, aborts, and recovery attempts back to backend logs.
- Added frontend best-effort telemetry calls around the stream failure and recovery path.
- Bumped the app version to `0.241.109`.

### Operational Impact
- Backend logs can now show whether a long-running stream detached from the browser and continued to run.
- Reattach attempts are logged explicitly.
- Status queries can show detach, reattach, keepalive, queue backpressure, and terminal status details during the replay TTL window.
- Frontend stream failures are no longer limited to console-only diagnostics when the reporting path is available.

## Validation

### Test Coverage
- `functional_tests/test_chat_stream_lifecycle_observability.py`

### Verification Performed
- Python diagnostics on `route_backend_chats.py`
- `python -m py_compile application/single_app/route_backend_chats.py`
- JavaScript diagnostics on `application/single_app/static/js/chat/chat-streaming.js`
- `node --check application/single_app/static/js/chat/chat-streaming.js`

### Before and After
Before:
- Stream status exposed only pending/reattachable.
- Frontend failures were mostly visible only in browser console logs.
- No explicit lifecycle metadata for detach, reattach, keepalive, queue backpressure, and terminal status.

After:
- Stream status exposes lifecycle metadata and richer status fields.
- Backend logs capture detach, reattach, keepalive, queue backpressure, and terminal status transitions.
- The frontend reports failure and recovery events to the backend through the client-event endpoint.

## Limitations

This is best-effort observability, not a hard guarantee for every network partition. If the browser loses all connectivity, the frontend may be unable to send the client-event report. In that case, the backend lifecycle state and terminal logging still provide the primary source of truth.
