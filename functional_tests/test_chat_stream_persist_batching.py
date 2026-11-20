#!/usr/bin/env python3
# test_chat_stream_persist_batching.py
"""
Functional test for chat stream session persistence batching.
Version: 0.261.066
Implemented in: 0.261.066

This test ensures ActiveConversationStreamSession batches its Cosmos/Redis
event-append and metadata-persist calls instead of making one of each per
streamed SSE chunk, which previously blocked each token on a synchronous
Cosmos read-modify-write round trip (visible as ~0.5-1.5 second per-word
streaming delays whenever enable_redis_cache is false). It also confirms the
temporary diagnostic route/instrumentation added while root-causing this
issue was fully removed.

route_backend_chats.py has a very large runtime dependency tree (semantic
kernel, Azure SDK clients, etc.), so — matching this project's existing
pattern for that file (see test_chat_stream_heartbeat_reattach.py) — this
test asserts against the file's source text rather than importing and
executing the module. The actual batching *behavior* (fewer round trips,
correct ordering, batch merging) is covered by runtime tests against
app_settings_cache.append_stream_session_events_batch in
test_cosmos_wave1_cache_fallback.py.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
APP_CACHE_FILE = ROOT / "application" / "single_app" / "app_settings_cache.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def assert_not_contains(file_path: Path, forbidden: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if forbidden in content:
        raise AssertionError(f"Did not expect to find {forbidden!r} in {file_path}")


def test_stream_session_publish_batches_persistence_instead_of_per_chunk():
    print("Testing chat stream session persistence batching...")

    # The buffering mechanism exists and is wired into publish()/close().
    assert_contains(ROUTE_FILE, "STREAM_SESSION_PERSIST_FLUSH_INTERVAL_SECONDS = 0.75")
    assert_contains(ROUTE_FILE, "self._pending_persist_events = []")
    assert_contains(ROUTE_FILE, "self._pending_persist_metadata = None")
    assert_contains(ROUTE_FILE, "def _flush_pending_persist(self):")
    assert_contains(ROUTE_FILE, "app_settings_cache.append_stream_session_events_batch(")

    # publish() buffers rather than persisting unconditionally on every call.
    assert_contains(ROUTE_FILE, "self._pending_persist_events.append(event_text)")
    assert_contains(ROUTE_FILE, "self._pending_persist_metadata = metadata")
    assert_contains(
        ROUTE_FILE,
        "time.time() - self._last_persist_flush_at >= STREAM_SESSION_PERSIST_FLUSH_INTERVAL_SECONDS",
    )

    # close() flushes any trailing buffered state before computing final metadata,
    # preserving the events-before-metadata ordering reconnecting consumers rely on.
    assert_contains(ROUTE_FILE, "self._flush_pending_persist()")

    # Regression guard: publish() must not go back to calling these on every chunk
    # unconditionally (only _flush_pending_persist should call them now).
    assert_not_contains(
        ROUTE_FILE,
        "app_settings_cache.append_stream_session_event(\n            self.cache_key,\n            event_text,",
    )

    # The new batch-append cache function exists for both the Cosmos fallback and
    # Redis-backed paths, and is dispatched the same way as the existing single-
    # event function (not a replacement for it — collaboration still uses that one).
    assert_contains(APP_CACHE_FILE, "def _append_stream_session_events_batch_fallback(cache_key, event_texts")
    assert_contains(APP_CACHE_FILE, "def append_stream_session_events_batch_redis(cache_key, event_texts")
    assert_contains(APP_CACHE_FILE, "append_stream_session_events_batch = None")
    assert_contains(APP_CACHE_FILE, "def _append_stream_session_event_fallback(cache_key, event_text")

    # Temporary diagnostic scaffolding added while root-causing this issue must be
    # fully removed.
    assert_not_contains(ROUTE_FILE, "STREAM_DIAG")
    assert_not_contains(ROUTE_FILE, "diag-stream-test")
    assert_not_contains(ROUTE_FILE, "diag_stream_test")
    assert_not_contains(APP_CACHE_FILE, "STREAM_DIAG")

    assert_contains(CONFIG_FILE, 'VERSION = "0.261.066"')

    print("Chat stream session persistence batching checks passed!")


if __name__ == "__main__":
    try:
        test_stream_session_publish_batches_persistence_instead_of_per_chunk()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)
