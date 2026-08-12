# Settings Container RU Write Suppression Fix

## Issue Description

The Cosmos DB `settings` container was consuming excessive RU with only a single active user. Investigation found several high-churn runtime paths writing or reading operational cache/state documents in `settings` when they should have used Redis, short-lived in-process state, or read-only behavior.

Fixed in version: **0.250.037**

## Root Cause

- Generic app settings writes invalidated unrelated chat-bootstrap and custom-pages cache-version documents.
- The admin Cosmos throughput status refresh persisted live status back into app settings on every GET.
- Background Cosmos autoscale evaluations returned runtime settings updates even when no scale action occurred.
- Conversation cache versions and volatile payloads could fall back to the global `settings` container instead of bypassing cache when Redis was unavailable.
- DAI admin status reads could repeatedly point-read state documents, including shadow-validation state while shadow validation was disabled.

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_settings.py`
- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/functions_shared_cache.py`
- `application/single_app/functions_chat_bootstrap_cache.py`
- `application/single_app/functions_conversation_cache.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/functions_document_access_index.py`
- `application/single_app/config.py`

### Code Changes Summary

- Scoped app settings cache refresh to the app-settings cache only.
- Made Cosmos throughput status GET read-only.
- Limited autoscale runtime settings updates to actual scale actions or errors.
- Added `allow_cosmos_fallback=False` support to shared cache helpers.
- Disabled Cosmos fallback for chat bootstrap and conversation volatile cache payloads.
- Moved conversation cache versioning to Redis-only behavior; Redis-unavailable paths bypass cache and continue source Cosmos queries.
- Added short-TTL in-process caching for DAI backfill, repair backlog, and shadow-validation state reads.
- Skipped shadow-validation state reads in DAI status when shadow validation is disabled.

## Validation

- `python functional_tests\test_cosmos_wave2a_chat_bootstrap_cache.py`
- `python functional_tests\test_cosmos_wave2b_conversation_cache.py`
- `python functional_tests\test_cosmos_phase3_shared_cache_metrics.py`
- `python functional_tests\test_cosmos_wave4a_document_access_backfill.py`
- `python functional_tests\test_cosmos_throughput_refresh_logging.py`
- `.\venv\Scripts\python.exe functional_tests\test_cosmos_wave2a_custom_pages_cache.py`
- `python -m compileall -f` on touched application and functional test files

## Before and After

- **Before:** routine settings writes, status refreshes, and volatile cache activity could inflate `settings` writes and reads.
- **After:** only intentional app settings changes, actual autoscale actions, and required DAI state operations touch `settings`; Redis-unavailable conversation caching falls back to normal source-query behavior without creating cache/version documents.
