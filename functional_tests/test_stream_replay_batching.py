# test_stream_replay_batching.py
"""
Functional tests for batched chat stream replay persistence.
Version: 0.261.473
Implemented in: 0.261.473

This test ensures live content remains immediate while replay persistence is
batched, ordered, concurrency-safe, and available through the Cosmos fallback.
"""

import json
import threading
from textwrap import dedent
from pathlib import Path
from types import SimpleNamespace

from redis.exceptions import WatchError
from test_cosmos_wave1_cache_fallback import (
    FakeCosmosContainer,
    InMemoryRedis,
    _dependencies,
    _load_cache_module,
)

ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"


class WatchableRedisPipeline:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.operations = []
        self.watching = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def watch(self, key):
        self.watching = True
        self.watched_key = key
        return True

    def get(self, key):
        return self.redis_client.get(key)

    def multi(self):
        return self

    def delete(self, *keys):
        self.operations.append(("delete", keys))
        return self

    def set(self, key, value):
        self.operations.append(("set", (key, value)))
        return self

    def expire(self, key, seconds):
        self.operations.append(("expire", (key, seconds)))
        return self

    def rpush(self, key, value):
        self.operations.append(("rpush", (key, value)))
        return self

    def execute(self):
        self.redis_client.execute_count += 1
        if self.watching and self.redis_client.watch_conflicts:
            self.redis_client.watch_conflicts -= 1
            raise WatchError("synthetic stream metadata conflict")

        self.redis_client.executed_operations.append(
            [operation for operation, _ in self.operations]
        )
        for operation, arguments in self.operations:
            getattr(self.redis_client, operation)(*arguments)
        return []


class WatchableRedis(InMemoryRedis):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.execute_count = 0
        self.executed_operations = []
        self.exists_calls = 0
        self.watch_conflicts = 0

    def exists(self, key):
        self.exists_calls += 1
        return super().exists(key)

    def expire(self, key, seconds):
        return key in self.values

    def pipeline(self):
        return WatchableRedisPipeline(self)


def _extract_source(source, start_marker, end_marker):
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def _execute_route_source(source, namespace):
    compiled = compile(source, str(ROUTE_FILE), "exec")
    exec(compiled, namespace)  # noqa: S102 - Executes only source from ROUTE_FILE.


def _load_route_helpers():
    source = ROUTE_FILE.read_text(encoding="utf-8")
    helper_source = _extract_source(
        source,
        "def _extract_sse_event_payload",
        "def _refresh_m365_pending_action_event",
    )
    namespace = {"json": json}
    _execute_route_source(helper_source, namespace)
    return namespace


def _load_stream_session_class():
    source = ROUTE_FILE.read_text(encoding="utf-8")
    class_source = _extract_source(
        source,
        "class ActiveConversationStreamSession:",
        "class ActiveConversationStreamRegistry:",
    )
    namespace = {
        "json": json,
        "threading": threading,
        "time": __import__("time"),
        "TERMINAL_STREAM_STATUSES": {"completed", "error", "canceled"},
    }
    _execute_route_source(class_source, namespace)
    return namespace["ActiveConversationStreamSession"]


def test_plain_content_classifier_rejects_control_and_terminal_events():
    helpers = _load_route_helpers()
    classify = helpers["_get_batchable_stream_content"]

    assert classify('data: {"content": "alpha"}\n\n') == "alpha"
    assert classify('data: {"content": ""}\n\n') is None
    assert classify('data: {"content": "alpha", "type": "thought"}\n\n') is None
    assert classify('data: {"content": "alpha", "done": true}\n\n') is None
    assert classify('data: {"error": "failed"}\n\n') is None


def _load_background_publishers():
    source = ROUTE_FILE.read_text(encoding="utf-8")
    build_source = _extract_source(
        source,
        "    def build_background_stream_response(",
        "        def publish_pending_action(",
    )
    build_source = dedent(build_source) + (
        "\n    return publish_background_event, flush_replay_content\n"
    )
    clock = [100.0]
    live_events = []
    replay_events = []

    def push(event_text):
        live_events.append(event_text)
        return True

    def publish(event_text):
        replay_events.append(event_text)
        return True

    session = SimpleNamespace(
        conversation_id="conversation",
        is_accepting_events=lambda: True,
        publish=publish,
    )
    namespace = {
        **_load_route_helpers(),
        "time": SimpleNamespace(monotonic=lambda: clock[0]),
        "BackgroundStreamBridge": lambda **kwargs: SimpleNamespace(push=push),
        "get_current_user_id": lambda: "user",
        "get_settings": lambda: {},
        "g": SimpleNamespace(),
        "has_request_context": lambda: False,
        "should_withhold_chat_event": lambda *args: False,
        "public_chat_payload": lambda payload: payload,
        "enabled_chat_scanners": lambda *args: [],
        "_persist_retry_terminal_payload": lambda *args: False,
        "_attach_request_m365_pending_action_cards": lambda payload, user_id: payload,
    }
    _execute_route_source(build_source, namespace)
    publish_event, flush = namespace["build_background_stream_response"](
        lambda: (), stream_session=session,
    )
    return publish_event, flush, clock, live_events, replay_events


def test_route_pushes_live_content_before_batched_replay_and_flushes_controls():
    publish, flush, clock, live, replay = _load_background_publishers()
    helpers = _load_route_helpers()
    first = 'data: {"content": "alpha"}\n\n'
    second = 'data: {"content": "beta"}\n\n'

    assert publish(first) is True
    clock[0] += 0.249
    assert publish(second) is True
    assert live == [first, second]
    assert replay == []

    clock[0] = 100.25
    assert flush() is True
    assert [helpers["_extract_sse_event_payload"](event) for event in replay] == [
        {"content": "alphabeta"},
    ]

    for payload in (
        {"type": "thought", "content": "working"},
        {"done": True},
        {"error": "failed"},
        {"cancelled": True},
    ):
        publish, _, _, live, replay = _load_background_publishers()
        control = f"data: {json.dumps(payload)}\n\n"
        assert publish(first) is True
        assert publish(control) is True
        assert live == [first, control]
        assert [helpers["_extract_sse_event_payload"](event) for event in replay] == [
            {"content": "alpha"}, payload,
        ]


def test_cancellation_polling_reuses_recent_metadata_and_supports_forced_reads():
    session_class = _load_stream_session_class()
    session = session_class.__new__(session_class)
    session._cancel_poll_lock = threading.Lock()
    session._last_cancel_poll_at = 0.0
    session._last_cancel_requested = False
    session._last_cancel_reason = ""
    metadata_reads = []
    session._get_metadata = lambda: (
        metadata_reads.append(True)
        or {"status": "streaming", "cancel_requested": False}
    )
    session._has_disconnect_grace_expired = lambda metadata: False

    first_result = session.is_cancel_requested()
    cached_result = session.is_cancel_requested()
    forced_result = session.is_cancel_requested(force=True)

    assert first_result is False
    assert cached_result is False
    assert forced_result is False
    assert len(metadata_reads) == 2


def test_cancellation_polling_preserves_disconnect_grace_cancellation():
    session_class = _load_stream_session_class()
    session = session_class.__new__(session_class)
    session._cancel_poll_lock = threading.Lock()
    session._last_cancel_poll_at = 0.0
    session._last_cancel_requested = False
    session._last_cancel_reason = ""
    metadata = iter([
        {"status": "detached_running", "cancel_requested": False},
        {
            "status": "cancel_requested",
            "cancel_requested": True,
            "cancel_reason": "client_disconnect_timeout",
        },
    ])
    cancel_reasons = []
    session._get_metadata = lambda: next(metadata)
    session._has_disconnect_grace_expired = lambda value: True
    session.request_cancel = lambda reason: cancel_reasons.append(reason)

    cancel_requested = session.is_cancel_requested(force=True)

    assert cancel_requested is True
    assert cancel_reasons == ["client_disconnect_timeout"]
    assert session.get_cancel_reason() == "client_disconnect_timeout"


def test_cancellation_polling_refreshes_at_the_batch_interval():
    session_class = _load_stream_session_class()
    clock = [100.0]
    session_class.is_cancel_requested.__globals__["time"] = SimpleNamespace(
        monotonic=lambda: clock[0],
    )
    session = session_class.__new__(session_class)
    session._cancel_poll_lock = threading.Lock()
    session._last_cancel_poll_at = 0.0
    session._last_cancel_requested = False
    session._last_cancel_reason = ""
    metadata = {"status": "streaming", "cancel_requested": False}
    reads = []
    session._get_metadata = lambda: reads.append(True) or dict(metadata)
    session._has_disconnect_grace_expired = lambda value: False

    assert session.is_cancel_requested() is False
    metadata.update(cancel_requested=True, cancel_reason="other_worker")
    clock[0] = 100.249
    assert session.is_cancel_requested() is False
    assert len(reads) == 1
    clock[0] = 100.25
    assert session.is_cancel_requested() is True
    assert session.get_cancel_reason() == "other_worker"
    assert len(reads) == 2


def test_combined_cosmos_fallback_persists_event_and_metadata():
    container = FakeCosmosContainer()
    cache = _load_cache_module()
    container.items[cache.GOVERNANCE_CACHE_VERSION_DOC_ID] = {
        "id": cache.GOVERNANCE_CACHE_VERSION_DOC_ID,
        "version": 7,
    }
    cache.configure_app_cache(
        {"enable_redis_cache": False},
        dependencies=_dependencies(cache, container, WatchableRedis),
    )

    saved = cache.append_stream_session_event_and_meta(
        "session-1",
        'data: {"content": "fallback"}\n\n',
        {"active": True, "status": "streaming", "event_count": 1},
        ttl_seconds=60,
    )
    events = cache.get_stream_session_events("session-1")
    metadata = cache.get_stream_session_meta("session-1")

    assert saved is True
    assert events == ['data: {"content": "fallback"}\n\n']
    assert metadata["event_count"] == 1
    assert metadata["status"] == "streaming"
    assert cache.get_governance_cache_version() == 7


def test_combined_redis_transaction_retries_and_preserves_coordination_state():
    container = FakeCosmosContainer()
    cache = _load_cache_module()
    cache.configure_app_cache(
        {
            "enable_redis_cache": True,
            "redis_url": "simplechat.redis.cache.windows.net",
            "redis_key": "test-key",
            "redis_auth_type": "key",
        },
        dependencies=_dependencies(cache, container, WatchableRedis),
    )
    redis_client = cache.APP_REDIS_CLIENT
    cache.initialize_stream_session_cache(
        "session-2",
        {
            "active": True,
            "status": "cancel_requested",
            "cancel_requested": True,
            "cancel_reason": "user_requested",
            "consumer_detached": True,
            "detach_count": 1,
        },
        ttl_seconds=60,
    )
    redis_client.watch_conflicts = 1

    saved = cache.append_stream_session_event_and_meta(
        "session-2",
        'data: {"content": "batched"}\n\n',
        {
            "active": True,
            "status": "streaming",
            "cancel_requested": False,
            "consumer_detached": False,
            "event_count": 8,
        },
        ttl_seconds=60,
    )
    metadata = cache.get_stream_session_meta("session-2")
    events = cache.get_stream_session_events("session-2")

    assert saved is True
    assert redis_client.execute_count == 3
    assert redis_client.executed_operations[-1] == [
        "rpush",
        "set",
        "expire",
        "expire",
    ]
    assert redis_client.exists_calls == 0
    assert metadata["status"] == "cancel_requested"
    assert metadata["cancel_requested"] is True
    assert metadata["consumer_detached"] is True
    assert metadata["event_count"] == 8
    assert events == ['data: {"content": "batched"}\n\n']


def test_combined_redis_transaction_does_not_reopen_terminal_session():
    container = FakeCosmosContainer()
    cache = _load_cache_module()
    cache.configure_app_cache(
        {
            "enable_redis_cache": True,
            "redis_url": "simplechat.redis.cache.windows.net",
            "redis_key": "test-key",
            "redis_auth_type": "key",
        },
        dependencies=_dependencies(cache, container, WatchableRedis),
    )
    cache.initialize_stream_session_cache(
        "session-3",
        {"active": False, "status": "completed", "event_count": 9},
        ttl_seconds=60,
    )

    saved = cache.append_stream_session_event_and_meta(
        "session-3",
        'data: {"content": "late"}\n\n',
        {"active": True, "status": "streaming", "event_count": 10},
        ttl_seconds=60,
    )

    assert saved is False
    assert cache.get_stream_session_events("session-3") == []
    assert cache.get_stream_session_meta("session-3")["status"] == "completed"


def test_combined_redis_transaction_preserves_terminal_cancellation():
    for cancel_requested in (False, True):
        cache = _load_cache_module()
        cache.configure_app_cache(
            {
                "enable_redis_cache": True,
                "redis_url": "simplechat.redis.cache.windows.net",
                "redis_key": "test-key",
                "redis_auth_type": "key",
            },
            dependencies=_dependencies(cache, FakeCosmosContainer(), WatchableRedis),
        )
        cache.initialize_stream_session_cache(
            "cancel-session",
            {
                "active": True,
                "status": "cancel_requested" if cancel_requested else "streaming",
                "cancel_requested": cancel_requested,
                "canceled_at": None,
            },
        )
        saved = cache.append_stream_session_event_and_meta(
            "cancel-session",
            'data: {"cancelled": true, "done": true}\n\n',
            {
                "active": False,
                "status": "canceled",
                "cancel_requested": True,
                "canceled_at": "2026-11-20T16:00:00",
            },
        )
        metadata = cache.get_stream_session_meta("cancel-session")

        assert saved is True
        assert metadata["active"] is False
        assert metadata["status"] == "canceled"
        assert metadata["cancel_requested"] is True
        assert metadata["canceled_at"] == "2026-11-20T16:00:00"


if __name__ == "__main__":
    tests = [
        test_plain_content_classifier_rejects_control_and_terminal_events,
        test_route_pushes_live_content_before_batched_replay_and_flushes_controls,
        test_cancellation_polling_reuses_recent_metadata_and_supports_forced_reads,
        test_cancellation_polling_preserves_disconnect_grace_cancellation,
        test_cancellation_polling_refreshes_at_the_batch_interval,
        test_combined_cosmos_fallback_persists_event_and_metadata,
        test_combined_redis_transaction_retries_and_preserves_coordination_state,
        test_combined_redis_transaction_does_not_reopen_terminal_session,
        test_combined_redis_transaction_preserves_terminal_cancellation,
    ]
    for test in tests:
        print(f"Running {test.__name__}...")
        test()
    print(f"Stream replay batching checks passed: {len(tests)}/{len(tests)}")
