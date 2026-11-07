# Chat OpenAI Timeout, Stream Disconnect Resilience, and Worker Isolation Fix

- **Fixed in version**: **0.261.387** (`application/single_app/config.py`)

## Issue Description

Production SimpleChat instances experienced long-running hangs on chat and document-action endpoints (averaging ~5 minutes, p95 ~18.7 minutes, and max ~72 minutes across 711 logged requests), eventually locking up instances until manual restart.

## Root Cause Analysis

1. **Unbounded OpenAI SDK client timeouts and retries**: `AzureOpenAI`, `OpenAI`, and `AsyncOpenAI` clients in `route_backend_chats.py`, `functions_model_endpoint_runtime.py`, `functions_workflow_runner.py`, and related helpers were constructed without an explicit `timeout` or `max_retries`. The OpenAI Python SDK defaults (`timeout=600s`, `max_retries=2`) allowed a single stalled call to block for up to 30 minutes.
2. **Multi-call amplification in `execute_document_action_chat_request()` and pre-stream helpers**: Multi-window document actions (Analyze and Compare) executed sequential model calls inside the background stream worker without an overall wall-clock deadline, and single-window calls (`concurrency=1`) blocked synchronously inside `chat.completions.create()` without polling `cancel_requested`. Auxiliary pre-stream calls (history answerability and older-message summarization) also shared the unbounded client.
3. **Disconnected `/api/chat/stream` sessions never self-cancelled**: On client disconnect (`GeneratorExit`), `BackgroundStreamBridge` marked the session `detached_running` to allow `/api/chat/stream/reattach/<conversation_id>`, leaving abandoned streams running until completion. In addition, sync OpenAI streams did not call `stream.close()` in a `finally:` block on exit or cancellation.
4. **Shared worker-pool and Gunicorn thread exhaustion**: `build_background_stream_response()` submitted `stream_worker` to the shared `app.extensions['executor']` (30 threads shared with document uploads, file sync, and data-management jobs), while each active SSE connection occupied one of Gunicorn's 16 HTTP threads (`2 workers × 8 threads`).

## Technical Details

### Files Modified

- `application/single_app/model_endpoint_clients.py`
- `application/single_app/functions_model_endpoint_runtime.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/functions_search_service.py`
- `application/single_app/config.py`
- `application/single_app/app.py`
- `application/single_app/gunicorn.conf.py`
- `application/single_app/admin_settings_nav.py`
- `application/single_app/admin_settings_fields.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin/_panes/redis-caching.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `docs/admin/scale.md`

### Code Changes Summary

1. **Granular Model Client Timeouts & Retries**: Added `build_openai_client_timeout_options()` and `bind_callable_with_timeout()` in `model_endpoint_clients.py` (`connect=10s`, `read=120s` default, `write=30s`, `pool=10s`, `max_retries=1` default) and applied them across `AzureOpenAI`, `OpenAI`, `AsyncOpenAI`, and Anthropic clients. Bounded auxiliary history calls to 30s with 0 retries.
2. **Document Action Total Deadline & Cancellable Invocations**: Enforced `document_action_timeout_seconds` (default 300s / 5 minutes) across `_execute_document_action_workflow()` and `execute_document_action_chat_request()`, routing model invocations through `_invoke_document_action_model_completion()` with remaining-deadline timeouts and 50ms cancellation polling while preserving completed durable checkpoints.
3. **Disconnected Stream Grace-Period Auto-Cancellation & Stream Close**: Added `stream.close()` in a `finally:` block in `chat_stream_api()` and enhanced `ActiveConversationStreamSession` to auto-cancel `detached_running` sessions once `stream_disconnect_grace_seconds` (default 60s) expires without reattachment.
4. **Dedicated Chat Stream Worker Pool & Gunicorn Threads**: Added `chat_stream_executor` (`CHAT_STREAM_EXECUTOR_MAX_WORKERS = 32`) in `config.py` and `app.py` for `build_background_stream_response()`, and increased default `GUNICORN_THREADS` from `8` to `16` in `gunicorn.conf.py`.
5. **Admin Settings Scale Controls**: Added the **Request & Stream Timeouts** section (`request-stream-timeouts-section`) under **Scale > Redis & Caching** in both V1 and V2 Admin Settings with range sliders for `model_stream_read_timeout_seconds`, `document_action_timeout_seconds`, `stream_disconnect_grace_seconds`, and `model_call_max_retries`.

## Validation

- `python functional_tests/test_chat_openai_timeout_and_stream_resilience.py`
- `python functional_tests/test_v2_admin_scale_parity.py`
- `python functional_tests/test_v2_admin_scale_normalization.py`
- `python functional_tests/test_admin_settings_fields_registry_integrity.py`
- `python functional_tests/test_admin_settings_nav_map.py`
- `python functional_tests/test_docs_app_surface_coverage.py`
