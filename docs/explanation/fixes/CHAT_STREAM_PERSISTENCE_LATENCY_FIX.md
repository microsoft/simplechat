# Chat Stream Persistence Latency Fix (v0.261.066)

Fixed/Implemented in version: **0.261.066**

Related configuration update: `application\single_app\config.py` increments
`VERSION` from `0.261.065` to `0.261.066`.

## Issue

Chat responses streamed at roughly **0.5-1.5 seconds per word** in deployments
with `enable_redis_cache` disabled — the project's documented, supported
no-Redis configuration, not a degraded fallback mode. The delay was flat
(constant per chunk, not growing with response length), reproduced identically
locally and when deployed, and was independent of the model, reasoning effort,
and whether agents/actions were enabled.

## Root cause

`ActiveConversationStreamSession.publish()` runs once per streamed SSE chunk
(i.e. once per token) and unconditionally called two cache-persistence
functions on every single call:

1. `app_settings_cache.append_stream_session_event(...)` — with Redis disabled,
   this falls to `_append_stream_session_event_fallback()`, which performs a
   synchronous Cosmos DB `read_item` + `replace_item` (with etag-based
   optimistic-concurrency retry) **per chunk**, reading and rewriting the
   entire growing replay-history array every time.
2. `self._persist_metadata(metadata)` — unconditionally calls
   `_set_cosmos_cache_entry(...)`, a second synchronous Cosmos write, also per
   chunk.

This blocked the generator before the next token could be yielded to the
browser, even though the actual Azure OpenAI stream itself was fast (confirmed
via direct `curl` and a bare-SDK script, both near-instant for the same
request) and the *read* side of this cache (`get_stream_session_meta`) was
already serving from an in-memory hit, not Cosmos.

The Redis-backed path does not have this problem — `RPUSH`/`SET` are O(1), no
read-modify-write — so this was specific to the Cosmos fallback.

Investigation also confirmed the persisted state (reconnect/replay history,
status, cancel flag) is only ever read on an explicit reconnect, status check,
or cancel request — nothing reads it per chunk — so the per-chunk write was
pure overhead relative to what any reader actually needs. A reattaching client
tails events at roughly 1 Hz, so being briefly behind is already expected and
tolerated.

## Technical details

`ActiveConversationStreamSession.publish()` now buffers the event text and the
latest computed metadata in memory, and only invokes the slow persistence
calls when either ~0.75 seconds have elapsed since the last flush, or this is
the stream's terminal event. `close()` flushes any trailing buffered state
before computing its own final metadata, preserving the existing ordering
(events persisted before the terminal metadata write) that reattaching clients
on other workers depend on.

This intentionally introduces **no new threads, locks, or queues**: `publish()`
remains fully synchronous and single-threaded, in the same order as before —
only how often it calls the slow functions changed, not who calls them or when
relative to the live SSE delivery path (`BackgroundStreamBridge`, which is
untouched and was never the bottleneck).

A new `append_stream_session_events_batch()` cache function (Cosmos-fallback
and Redis implementations) replaces the per-chunk single-event append during
these periodic flushes with one call covering everything buffered since the
last flush — one Cosmos round trip per flush interval instead of one per
streamed token. The existing single-event `append_stream_session_event()`
function is unchanged and still used by `route_backend_collaboration.py`'s
`CollaborationEventSession`, which has different multi-writer concurrency
needs and its own test coverage.

### Files modified

- `application\single_app\route_backend_chats.py`: `ActiveConversationStreamSession`
  buffers events/metadata and flushes periodically instead of per chunk.
- `application\single_app\app_settings_cache.py`: new
  `append_stream_session_events_batch()` (Cosmos-fallback and Redis
  implementations), dispatched the same way as the existing single-event
  function.
- `functional_tests\test_cosmos_wave1_cache_fallback.py`: new coverage for the
  batch-append function (ordering, merging with prior single appends, empty
  batch, Redis path); test fixtures updated to support Redis `RPUSH` with
  multiple values (matching real `redis-py` behavior).
- `functional_tests\test_chat_stream_persist_batching.py`: new source-level
  regression test confirming the buffering/flush wiring and the removal of
  temporary diagnostic instrumentation added while root-causing this issue.

### Behavior and impact

| Scenario | Before | After |
| --- | --- | --- |
| `enable_redis_cache: false`, normal streaming | Cosmos read+write on every chunk; ~0.5-1.5s/word | One batched Cosmos write roughly every 0.75s; no per-word stall |
| `enable_redis_cache: true` | Already fast (O(1) `RPUSH`/`SET`) | Unchanged behavior, now also batched |
| Client reconnects mid-stream | Full replay history from Cosmos | Same; replay may lag by up to ~0.75s of the most recent words, which reattach already tolerates |
| Stream ends (`done`/`error`/cancel) | Final state persisted immediately | Same — terminal events always flush immediately, synchronously |
| Collaboration (`CollaborationEventSession`) | Per-event Cosmos append | Unchanged — still uses the single-event function |

No change to the live SSE delivery path, authentication, authorization, or any
model/agent behavior.

## Validation

- `python functional_tests/test_cosmos_wave1_cache_fallback.py`: **10 tests
  passed** (6 pre-existing + 4 new for the batch-append function).
- `python functional_tests/test_chat_stream_persist_batching.py`: **1 test
  passed**.
- `python -m py_compile application/single_app/route_backend_chats.py
  application/single_app/app_settings_cache.py`: compiles cleanly.
- Manual reproduction: with `enable_redis_cache: false`, chat responses stream
  at a normal pace locally with no per-word stall.
- Manual verification: a mid-stream disconnect/reconnect still replays the
  full event history via `GET /api/chat/stream/reattach/<id>` and reaches a
  terminal `done` state.

### Known pre-existing, unrelated test failure

`functional_tests/test_chat_stream_heartbeat_reattach.py` currently fails on
`main` (confirmed via `git stash` before applying this fix) because it asserts
the literal string `stream_with_context(stream_session.iter_events())`, which
no longer appears verbatim since the reattach route was refactored to use
`BackgroundStreamBridge`/`consume_stream()` at some point after that test was
written. This is unrelated to this fix and out of scope here.
