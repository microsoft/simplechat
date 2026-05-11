# Embedding Rate Limit Wait Time Fix

## Fix Title
Embedding retries now honor server-provided wait times from Azure OpenAI rate-limit responses.

## Issue Description
The embedding helpers retried `429 Too Many Requests` failures using only local exponential backoff with jitter. When Azure OpenAI returned a `Retry-After` style header, the application ignored that server guidance and retried on its own schedule.

## Root Cause Analysis
- `generate_embedding()` and `generate_embeddings_batch()` only used a client-side backoff calculation after `RateLimitError`.
- The underlying OpenAI/Azure OpenAI `429` response headers were available on the exception response, but the helper never parsed them.
- As a result, retries could happen earlier than the service requested, increasing the chance of repeated throttling.

## Version Implemented
Fixed in version: **0.239.116**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/functions_content.py` | Added retry header parsing and applied it to both embedding retry loops |
| `functional_tests/test_embedding_rate_limit_wait_time.py` | Added regression coverage for `Retry-After` parsing and embedding retry timing |
| `application/single_app/config.py` | Version bump to 0.239.116 |

## Code Changes Summary
- Added a shared helper to parse `retry-after-ms`, `x-ms-retry-after-ms`, and `retry-after` values from rate-limit responses.
- Updated both single-item and batched embedding generation to prefer the server-provided wait time when it is available and reasonable.
- Kept the existing jittered exponential backoff as a fallback when the response does not provide a usable retry delay.

## Testing Approach
- Added `functional_tests/test_embedding_rate_limit_wait_time.py`.
- The functional test stubs the embedding client and rate-limit exception so it can verify:
  - Header parsing for millisecond and date-based retry values.
  - Single embedding retries sleep for the server-provided duration.
  - Batched embedding retries sleep for the server-provided duration.

## Impact Analysis
- Embedding retries now align more closely with Azure OpenAI throttling guidance.
- This reduces avoidable repeat `429` responses during document ingestion and batched embedding creation.
- Existing fallback behavior remains in place for responses that do not include a usable retry hint.

## Validation
- Regression test: `functional_tests/test_embedding_rate_limit_wait_time.py`
- Before: embedding retries always used local backoff, even when the `429` response included a wait time.
- After: embedding retries use the server-provided wait time when available, then fall back to local backoff only when necessary.