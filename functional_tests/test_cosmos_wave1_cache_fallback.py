# test_cosmos_wave1_cache_fallback.py
#!/usr/bin/env python3
"""
Functional test for Cosmos cache fallback behavior.
Version: 0.261.485
Implemented in: 0.261.055
Per-event replay round-trip reduction implemented in: 0.261.467
Cosmos discovery pointer coverage implemented in: 0.261.468
Cosmos single-write content coverage implemented in: 0.261.469
Replay index format coverage implemented in: 0.261.472
Single-line fallback warning coverage implemented in: 0.261.485

This test ensures Redis failures in the app cache layer fall back to
Cosmos-backed cache/source reads instead of failing callers.
"""

import base64
import copy
import importlib
import json
import os
import sys
from unittest.mock import Mock, patch
from urllib.parse import unquote, urlsplit

import pytest
from azure.core.exceptions import AzureError, ServiceResponseError
from azure.cosmos import CosmosClient
from azure.cosmos._cosmos_responses import CosmosDict
from redis.exceptions import ConnectionError as RedisConnectionError, NoPermissionError
from test_chat_content_streaming import frame, stream_classes
from test_group_document_sdk_conditions import ConditionalWireTransport, WireResponse


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.insert(0, SINGLE_APP_DIR)


class FakeCosmosError(AzureError):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class FakeCosmosContainer:
    """Plain point responses require the explicit compatibility option."""

    def __init__(self, *, sdk_responses=True):
        self.sdk_responses = sdk_responses
        self.items = {}
        self._etag_counter = 0

    def _response(self, body):
        value = copy.deepcopy(dict(body))
        return CosmosDict(value, response_headers={}) if self.sdk_responses else value

    def _copy_with_new_etag(self, body):
        self._etag_counter += 1
        item = copy.deepcopy(dict(body))
        item["_etag"] = f"etag-{self._etag_counter}"
        return item

    def read_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        return self._response(self.items[item])

    def create_item(self, body):
        item_id = body["id"]
        if item_id in self.items:
            raise FakeCosmosError(409, f"Duplicate item {item_id}")
        self.items[item_id] = self._copy_with_new_etag(body)
        return self._response(self.items[item_id])

    def upsert_item(self, body):
        self.items[body["id"]] = self._copy_with_new_etag(body)
        return self._response(self.items[body["id"]])

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        if etag and self.items[item].get("_etag") != etag:
            raise FakeCosmosError(412, f"ETag mismatch for item {item}")
        self.items[item] = self._copy_with_new_etag(body)
        return self._response(self.items[item])

    def delete_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        del self.items[item]


class StreamPatchContainer(FakeCosmosContainer):
    def __init__(self, *, sdk_responses=True):
        super().__init__(sdk_responses=sdk_responses)
        self.calls = []
        self.lose_append_response = False
        self.append_error = None
        self.indexing_policy = {
            "indexingMode": "consistent", "automatic": True,
            "includedPaths": [{"path": "/*"}], "excludedPaths": [],
        }

    def read(self):
        return self._response({"id": "settings", "indexingPolicy": self.indexing_policy})

    def read_item(self, item, partition_key, **kwargs):
        self.calls.append("read")
        return super().read_item(item, partition_key, **kwargs)

    def upsert_item(self, body):
        self.calls.append("upsert")
        return super().upsert_item(body)

    def patch_item(self, item, partition_key, patch_operations, *, filter_predicate, no_response=False):
        self.calls.append("patch")
        assert item == partition_key
        if self.append_error is not None:
            raise self.append_error
        if item not in self.items:
            raise FakeCosmosError(404, "Missing stream replay item")
        body = copy.deepcopy(self.items[item])
        marker = patch_operations[-1]
        if no_response:
            metadata = body["payload"]
            expected = f'FROM c WHERE c.payload.submission_id = {json.dumps(metadata.get("submission_id"))}'
            allowed = filter_predicate == expected or (
                filter_predicate == expected + " AND c.payload.active = true" and metadata.get("active") is True
            )
        elif marker["path"] == "/replay_append_watermarks":
            allowed = "replay_append_watermarks" not in body and "NOT IS_DEFINED" in filter_predicate
        else:
            writer = marker["path"].rsplit("/", 1)[-1]
            watermarks = body.get("replay_append_watermarks")
            allowed = (
                isinstance(watermarks, dict)
                and watermarks.get(writer, 0) < marker["value"]
                and f'["{writer}"]' in filter_predicate
            )
        replay_field = patch_operations[0]["path"].split("/")[1]
        if not no_response:
            allowed = allowed and isinstance(body.get(replay_field), list) and f"IS_ARRAY(c.{replay_field})" in filter_predicate
        if not allowed:
            raise FakeCosmosError(412, "Replay append condition failed")
        for operation in patch_operations:
            _, field, *nested = operation["path"].split("/")
            if operation["op"] == "add":
                body[field].append(operation["value"])
            elif operation["op"] == "incr":
                body[field] = body.get(field, 0) + operation["value"]
            elif nested:
                body[field][nested[0]] = operation["value"]
            else:
                body[field] = operation["value"]
        if self.lose_append_response and not no_response:
            self.lose_append_response = False
            body[replay_field].append("data: concurrent-message\n\n")
            body["replay_append_watermarks"]["concurrent"] = 1
            self.items[item] = self._copy_with_new_etag(body)
            raise ServiceResponseError("Response lost after commit")
        self.items[item] = self._copy_with_new_etag(body)
        return self._response({} if no_response else self.items[item])


class FailingRedis:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        raise RedisConnectionError("redis unavailable")

    def set(self, *args, **kwargs):
        raise RedisConnectionError("redis unavailable")

    def setex(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    def setnx(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    def incr(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    def delete(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    def pipeline(self):
        raise RuntimeError("redis unavailable")


class RaisingRedis(FailingRedis):
    def __init__(self, *args, **kwargs):
        raise RedisConnectionError("redis initialization failed")


class InMemoryRedisPipeline:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.operations = []

    def delete(self, *keys):
        self.operations.append(('delete', keys))
        return self

    def set(self, key, value):
        self.operations.append(('set', (key, value)))
        return self

    def expire(self, key, seconds):
        self.operations.append(('expire', (key, seconds)))
        return self

    def rpush(self, key, value):
        self.operations.append(('rpush', (key, value)))
        return self

    def execute(self):
        for operation, arguments in self.operations:
            getattr(self.redis_client, operation)(*arguments)
        return []


class InMemoryRedis:
    def __init__(self, *args, **kwargs):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value
        return True

    def setex(self, key, seconds, value):
        return self.set(key, value)

    def setnx(self, key, value):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def incr(self, key):
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = value
        return value

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)

    def exists(self, key):
        return key in self.values

    def expire(self, key, seconds):
        return self.exists(key)

    def rpush(self, key, value):
        self.values.setdefault(key, []).append(value)
        return len(self.values[key])

    def lrange(self, key, start, end):
        values = self.values.get(key, [])
        return values[start:] if end == -1 else values[start:end + 1]

    def pipeline(self):
        return InMemoryRedisPipeline(self)


def _load_cache_module():
    spec = importlib.util.spec_from_file_location(
        "cache_fallback_under_test",
        os.path.join(SINGLE_APP_DIR, "app_settings_cache.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dependencies(cache, container, redis_class):
    return cache.AppCacheDependencies(
        settings_container=container,
        governance_container=container,
        create_redis_client=redis_class,
        log_event=lambda *args, **kwargs: None,
    )


def test_redis_runtime_failure_falls_back_to_cosmos_settings():
    """A Redis read failure should return settings from Cosmos instead of raising."""
    container = FakeCosmosContainer()
    container.items["app_settings"] = {
        "id": "app_settings",
        "feature_flag": "from-cosmos",
        "_settings_revision": 7,
    }
    container.items["app_settings_cache_version"] = {
        "id": "app_settings_cache_version",
        "type": "cache_version",
        "version": 7,
    }
    cache_module = _load_cache_module()

    cache_module.configure_app_cache({
        "enable_redis_cache": True,
        "redis_url": "simplechat.redis.cache.windows.net",
        "redis_key": "test-key",
        "redis_auth_type": "key",
    }, dependencies=_dependencies(cache_module, container, FailingRedis))

    cached_settings = cache_module.get_settings_cache()

    assert cached_settings["feature_flag"] == "from-cosmos"
    assert cache_module.get_app_settings_cache_version() == 7


def test_redis_write_failure_persists_user_ui_cache_to_cosmos():
    """A Redis write failure should persist lightweight UI cache data in Cosmos."""
    container = FakeCosmosContainer()
    cache_module = _load_cache_module()

    cache_module.configure_app_cache({
        "enable_redis_cache": True,
        "redis_url": "simplechat.redis.cache.windows.net",
        "redis_key": "test-key",
        "redis_auth_type": "key",
    }, dependencies=_dependencies(cache_module, container, FailingRedis))

    cache_module.set_user_ui_settings_cache("user-1", {"theme": "dark"}, ttl_seconds=60)
    cached_settings = cache_module.get_user_ui_settings_cache("user-1")

    assert cached_settings == {"theme": "dark"}
    assert "app_cache_entry:USER_UI_SETTINGS:user-1" in container.items


def test_redis_initialization_failure_assigns_fallback_functions():
    """A Redis startup failure should not break app cache configuration."""
    cache_module = _load_cache_module()
    container = FakeCosmosContainer()
    container.items["app_settings"] = {
        "id": "app_settings",
        "feature_flag": "fallback-configured",
    }
    governance_id = cache_module.GOVERNANCE_CACHE_VERSION_DOC_ID
    container.items[governance_id] = {"id": governance_id, "version": 17}

    cache_module.configure_app_cache({
        "enable_redis_cache": True,
        "redis_url": "simplechat.redis.cache.windows.net",
        "redis_key": "test-key",
        "redis_auth_type": "key",
    }, dependencies=_dependencies(cache_module, container, RaisingRedis))

    cached_settings = cache_module.get_settings_cache()
    governance_version = cache_module.get_governance_cache_version()
    assert cache_module.app_cache_is_using_redis is False
    assert cached_settings["feature_flag"] == "fallback-configured"
    assert governance_version == 17


def test_stream_event_fallback_is_shared_between_workers():
    """Worker-local stream snapshots must not hide collaboration events."""
    container = StreamPatchContainer()
    worker_one = _load_cache_module()
    worker_two = _load_cache_module()
    settings = {"enable_redis_cache": False}

    worker_one.configure_app_cache(settings, dependencies=_dependencies(worker_one, container, RaisingRedis))
    worker_two.configure_app_cache(settings, dependencies=_dependencies(worker_two, container, RaisingRedis))

    cache_key = "collaboration:test-conversation"
    metadata = {"conversation_id": "test-conversation", "active": True}
    worker_one.initialize_stream_session_cache(cache_key, metadata, ttl_seconds=60)
    worker_one.append_stream_session_event(cache_key, "data: owner-message\n\n", ttl_seconds=60)
    assert worker_two.get_stream_session_meta(cache_key) == metadata
    worker_two.set_stream_session_meta(cache_key, metadata, ttl_seconds=60)
    worker_two.append_stream_session_event(cache_key, "data: invitee-message\n\n", ttl_seconds=60)

    expected_events = ["data: owner-message\n\n", "data: invitee-message\n\n"]
    assert worker_one.get_stream_session_events(cache_key) == expected_events
    assert worker_two.get_stream_session_events(cache_key) == expected_events

    with patch.object(container, "read_item", side_effect=ServiceResponseError("Read unavailable")):
        replay = worker_two.get_stream_session_events(cache_key)
    assert replay == expected_events


def test_stream_event_fallback_patches_in_one_request_and_upgrades_legacy_items():
    container = StreamPatchContainer()
    cache_module = _load_cache_module()
    cache_module.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(
        cache_module, container, RaisingRedis,
    ))

    cache_key = "chat:replay-test"
    cache_module.initialize_stream_session_cache(cache_key, {"active": True}, ttl_seconds=60)
    container.calls.clear()
    cache_module.append_stream_session_event(cache_key, "data: first\n\n", ttl_seconds=60)
    assert container.calls == ["patch"]

    events_id = cache_module._build_cosmos_cache_doc_id(cache_module._get_stream_session_events_key(cache_key))
    del container.items[events_id]["replay_append_watermarks"]
    cache_module.append_stream_session_event(cache_key, "data: second\n\n", ttl_seconds=60)
    assert cache_module.get_stream_session_events(cache_key) == ["data: first\n\n", "data: second\n\n"]


def test_stream_event_fallback_does_not_duplicate_a_committed_append_after_a_lost_reply():
    container = StreamPatchContainer()
    cache_module = _load_cache_module()
    cache_module.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(
        cache_module, container, RaisingRedis,
    ))

    cache_key = "chat:retry-test"
    cache_module.initialize_stream_session_cache(cache_key, {"active": True}, ttl_seconds=60)
    container.lose_append_response = True
    cache_module.append_stream_session_event(
        cache_key, "data: first\n\n", ttl_seconds=60, require_shared=True, progress_chars=5,
    )

    replay = cache_module.get_stream_session_events(cache_key)
    assert replay == ["data: first\n\n", "data: concurrent-message\n\n"]
    other_worker = _load_cache_module()
    other_worker.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(
        other_worker, container, RaisingRedis,
    ))
    progress = other_worker.get_cosmos_stream_progress(cache_key, shared=True)
    assert (progress.event_count, progress.content_chars) == (1, 5)


def test_cosmos_replay_keeps_one_retry_watermark_per_writer_not_per_chunk():
    container = StreamPatchContainer()
    cache = _load_cache_module()
    cache.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(cache, container, RaisingRedis))
    cache_key = "chat:replay-watermarks"
    cache.initialize_stream_session_cache(cache_key, {"active": True}, ttl_seconds=60)
    container.calls.clear()
    for index in range(64):
        cache.append_stream_session_event(cache_key, f"data: {index}\n\n", ttl_seconds=60)
    assert container.calls == ["patch"] * 64
    replay_id = cache._build_cosmos_cache_doc_id(cache._get_stream_session_events_key(cache_key))
    (sequence,) = container.items[replay_id]["replay_append_watermarks"].values()
    assert sequence == 64
    assert len(container.items[replay_id]["payload"]) == 64


def test_cosmos_scoped_direct_deltas_make_exactly_one_storage_call_each():
    container = StreamPatchContainer()
    writer, reader = (_load_cache_module() for _ in range(2))
    for cache in (writer, reader):
        cache.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(cache, container, RaisingRedis))
    publishing = stream_classes(writer, Mock()).ActiveConversationStreamSession(
        "owner", "conversation", submission_id="turn",
    )
    reading = stream_classes(reader, Mock()).ActiveConversationStreamSession(
        "owner", "conversation", submission_id="turn",
    )
    publishing.initialize()
    publishing.publish(frame({"content": "first"}), require_shared=True)
    content = [frame({"content": text}) for text in ("second", "third", "fourth")]
    for event in content:
        container.calls.clear()
        published = publishing.publish(event, require_shared=True)
        assert published and container.calls == ["patch"]
    replay = reader.get_stream_session_events(publishing.cache_key)
    snapshot = reading.get_status_snapshot(shared_progress=True)
    assert replay == [frame({"content": "first"}), *content]
    assert (snapshot["event_count"], snapshot["content_event_count"], snapshot["content_chars"]) == (4, 4, 22)


def test_cosmos_replay_index_only_changes_new_verified_documents_and_cold_workers_reconcile():
    container = StreamPatchContainer()
    writer, reader = (_load_cache_module() for _ in range(2))
    for cache in (writer, reader):
        cache.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(cache, container, RaisingRedis))
    opted_in = {writer.COSMOS_REPLAY_PREFERENCE: True}
    legacy_key = "owner:chat:legacy"
    indexed_key = "owner:chat:off"
    excluded_key = "owner:chat:excluded"
    writer.initialize_stream_session_cache(legacy_key, opted_in, ttl_seconds=60)
    container.indexing_policy["excludedPaths"] = [{"path": writer.COSMOS_REPLAY_INDEX_PATH}]
    writer.initialize_stream_session_cache(legacy_key, opted_in, ttl_seconds=60)
    session = stream_classes(writer, Mock()).ActiveConversationStreamSession(
        "owner", "chat", submission_id="excluded", exclude_cosmos_replay_text=True,
    )
    session.initialize()
    writer.initialize_stream_session_cache(indexed_key, {}, ttl_seconds=60)
    get_doc = lambda key: container.items[writer._build_cosmos_cache_doc_id(writer._get_stream_session_events_key(key))]
    assert "payload" in get_doc(legacy_key)
    assert "payload" in get_doc(indexed_key)
    assert "payload" not in get_doc(excluded_key)

    container.calls.clear()
    writer.append_stream_session_event(excluded_key, "data: first\n\n", ttl_seconds=60, require_shared=True, progress_chars=5)
    assert container.calls == ["patch"]
    container.calls.clear()
    reader.append_stream_session_event(excluded_key, "data: second\n\n", ttl_seconds=60)
    assert container.calls == ["patch", "read", "patch"]
    replay = reader.get_stream_session_events(excluded_key)
    assert replay == ["data: first\n\n", "data: second\n\n"]
    progress = reader.get_cosmos_stream_progress(excluded_key, shared=True)
    assert (progress.event_count, progress.content_chars) == (1, 5)
    assert get_doc(excluded_key)[writer.COSMOS_REPLAY_EVENTS_FIELD] == replay
    assert "payload" not in get_doc(excluded_key)


def test_cosmos_replay_index_status_distinguishes_quoted_paths_and_conflicts():
    cache = _load_cache_module()
    policy = {
        "indexingMode": "consistent", "automatic": True, "includedPaths": [{"path": "/*"}],
        "excludedPaths": [{"path": '/"stream_replay_events/[]"/?'}],
    }
    assert cache.cosmos_replay_index_policy_state(policy) == "missing"
    policy["excludedPaths"] = [{"path": '/"stream_replay_events"/[]/?'}]
    assert cache.cosmos_replay_index_policy_state(policy) == "ready"
    policy["includedPaths"].append({"path": "/stream_replay_events/[]/?"})
    assert cache.cosmos_replay_index_policy_state(policy) == "conflict"


@pytest.mark.parametrize("terminal", ("close", "retract", "unconfirmed"))
def test_cosmos_progress_survives_replay_expiry_for_cold_readers_and_terminal_status(terminal):
    container = StreamPatchContainer()
    writer, reader = (_load_cache_module() for _ in range(2))
    for cache in (writer, reader):
        cache.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(cache, container, RaisingRedis))
    publishing = stream_classes(writer, Mock()).ActiveConversationStreamSession(
        "owner", "conversation", submission_id="turn",
    )
    cold = stream_classes(reader, Mock()).ActiveConversationStreamSession(
        "owner", "conversation", submission_id="turn",
    )
    publishing.initialize()
    for text in ("first", "second", "third"):
        publishing.publish(frame({"content": text}), require_shared=True)
    replay_id = writer._build_cosmos_cache_doc_id(writer._get_stream_session_events_key(publishing.cache_key))
    container.items[replay_id]["expires_at"] = "2000-01-01T00:00:00"

    replay = reader.get_stream_session_events(cold.cache_key)
    live = cold.get_status_snapshot(shared_progress=True)
    assert replay == [] and live["active"]
    assert (live["event_count"], live["content_event_count"], live["content_chars"]) == (3, 3, 16)

    if terminal == "close":
        cold.close()
    elif terminal == "retract":
        cold.retract({"done": True, "blocked": True, "role": "safety", "content": "Removed"})
    else:
        cold.publish(frame({
            "done": True, "error": "Replay could not be confirmed", "error_code": "stream_replay_unconfirmed",
        }))
    finished = reader.get_stream_session_meta(cold.cache_key)
    assert not finished["active"] and finished["replay_progress_finalized"]
    assert (finished["event_count"], finished["content_event_count"], finished["content_chars"]) == (3, 3, 16)


def test_cosmos_content_does_not_recreate_a_missing_replay_log():
    container = StreamPatchContainer()
    cache = _load_cache_module()
    cache.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(cache, container, RaisingRedis))
    with pytest.raises(cache.StreamReplayUnconfirmed):
        cache.append_stream_session_event(
            "owner:conversation:turn", "data: unconfirmed\n\n", ttl_seconds=60,
            require_shared=True, progress_chars=5,
        )
    assert container.calls == ["patch"]
    assert not container.items

def test_cosmos_direct_content_does_not_claim_replay_when_the_item_is_full():
    container = StreamPatchContainer()
    cache = _load_cache_module()
    cache.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(cache, container, RaisingRedis))
    cache_key = "chat:replay-full"
    cache.initialize_stream_session_cache(cache_key, {"active": True}, ttl_seconds=60)
    cache.append_stream_session_event(cache_key, "data: confirmed\n\n", ttl_seconds=60, require_shared=True)
    container.append_error = FakeCosmosError(413, "Replay item too large")
    with pytest.raises(cache.StreamReplayUnconfirmed):
        cache.append_stream_session_event(cache_key, "data: unconfirmed\n\n", ttl_seconds=60, require_shared=True)
    with patch.object(container, "read_item", side_effect=ServiceResponseError("Read unavailable")):
        replay = cache.get_stream_session_events(cache_key)
    assert replay == ["data: confirmed\n\n"]


@pytest.mark.parametrize("progress_chars", (None, 5))
def test_cosmos_replay_uses_one_conditional_patch_through_the_installed_sdk(progress_chars):
    cache_module = _load_cache_module()
    cache_key = "chat:wire"
    doc_id = cache_module._build_cosmos_cache_doc_id(cache_module._get_stream_session_events_key(cache_key))

    class WireTransport(ConditionalWireTransport):
        def send(self, request, **kwargs):
            url = urlsplit(request.url)
            if url.hostname == "fixture.documents.azure.com" and (
                unquote(url.path.rstrip("/")) == f"/dbs/fixture/colls/groups/docs/{doc_id}"
            ):
                assert request.method == "PATCH"
                self.requests.append(request)
                return WireResponse(request, {"id": doc_id, "payload": ["data: earlier\n\n", "data: event\n\n"]})
            return super().send(request, **kwargs)

    wire = WireTransport()
    fixture_key = base64.b64encode(b"fixture-only").decode("ascii")
    with CosmosClient(
        "https://fixture.documents.azure.com", credential=fixture_key,
        transport=wire, enable_endpoint_discovery=False,
    ) as client:
        container = client.get_database_client("fixture").get_container_client("groups")
        cache_module.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(
            cache_module, container, RaisingRedis,
        ))
        cache_module.append_stream_session_event(
            cache_key, "data: event\n\n", ttl_seconds=60, progress_chars=progress_chars,
        )

    (request,) = [request for request in wire.requests if "/docs/" in urlsplit(request.url).path]
    body = json.loads(request.body)
    assert body["operations"][0] == {"op": "add", "path": "/payload/-", "value": "data: event\n\n"}
    marker = body["operations"][-1]
    assert marker["path"].startswith("/replay_append_watermarks/") and marker["op"] == "set"
    assert f'["{marker["path"].rsplit("/", 1)[1]}"] < {marker["value"]}' in body["condition"]
    assert json.loads(request.headers["x-ms-documentdb-partitionkey"]) == [doc_id]
    increments = [op for op in body["operations"] if op["op"] == "incr"]
    assert increments == ([] if progress_chars is None else [
        {"op": "incr", "path": "/streamed_content_events", "value": 1},
        {"op": "incr", "path": "/streamed_content_chars", "value": 5},
    ])


@pytest.mark.parametrize(("status", "expected", "control"), [
    (204, "renewed", False), (412, "superseded", False), (404, "missing", False),
    (204, "renewed", True), (412, "superseded", True),
])
def test_cosmos_discovery_renewal_is_one_conditional_patch(status, expected, control):
    cache = _load_cache_module()
    key = "owner:conversation"
    doc_id = cache._build_cosmos_cache_doc_id(cache._get_stream_session_metadata_key(key))

    class DiscoveryWireTransport(ConditionalWireTransport):
        def send(self, request, **kwargs):
            url = urlsplit(request.url)
            if unquote(url.path.rstrip("/")) == f"/dbs/fixture/colls/groups/docs/{doc_id}":
                assert request.method == "PATCH"
                self.requests.append(request)
                error = {412: "PreconditionFailed", 404: "NotFound"}.get(status)
                return WireResponse(request, {"code": error, "message": error} if error else None, status)
            return super().send(request, **kwargs)

    wire = DiscoveryWireTransport()
    with CosmosClient(
        "https://fixture.documents.azure.com", credential=base64.b64encode(b"fixture-only").decode("ascii"),
        transport=wire, enable_endpoint_discovery=False,
    ) as client:
        container = client.get_database_client("fixture").get_container_client("groups")
        cache.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(cache, container, RaisingRedis))
        renew = cache.renew_cosmos_stream_metadata if control else cache.renew_cosmos_stream_discovery
        result = renew(key, "current-attempt", 600)

    assert result == expected
    (request,) = [item for item in wire.requests if "/docs/" in urlsplit(item.url).path]
    body = json.loads(request.body)
    predicate = 'FROM c WHERE c.payload.submission_id = "current-attempt"'
    assert body["condition"] == (predicate + " AND c.payload.active = true" if control else predicate)
    assert {op["path"] for op in body["operations"]} == {"/updated_at", "/expires_at"}
    assert json.loads(request.headers["x-ms-documentdb-partitionkey"]) == [doc_id]
    assert request.headers["Prefer"] == "return=minimal"


def test_cosmos_discovery_does_not_choose_stale_local_submission():
    container = FakeCosmosContainer()
    worker_one = _load_cache_module()
    worker_two = _load_cache_module()
    for worker in (worker_one, worker_two):
        worker.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(worker, container, RaisingRedis))
    key = "owner:conversation"
    worker_one.set_stream_session_meta(key, {"submission_id": "old"}, ttl_seconds=60)
    worker_two.set_stream_session_meta(key, {"submission_id": "new"}, ttl_seconds=60)
    found = worker_one.get_cosmos_stream_discovery(key)
    worker_two.delete_stream_session_cache(key)
    missing = worker_one.get_cosmos_stream_discovery(key)
    assert found == {"submission_id": "new"}
    assert missing is None


def test_cosmos_discovery_does_not_report_a_read_outage_as_no_stream(caplog):
    container = FakeCosmosContainer()
    cache = _load_cache_module()
    cache.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(cache, container, RaisingRedis))
    caplog.set_level("WARNING")
    with patch.object(container, "read_item", side_effect=ServiceResponseError("Read unavailable")):
        with pytest.raises(cache.StreamDiscoveryUnavailable):
            cache.get_cosmos_stream_discovery("owner:conversation")
        with pytest.raises(cache.StreamDiscoveryUnavailable):
            cache.get_cosmos_stream_discovery("owner:conversation\r\n[ASC] forged record")
    forged = [record.getMessage() for record in caplog.records if "forged record" in record.getMessage()]
    assert forged and not any("\r" in message or "\n" in message for message in forged)


def test_cosmos_discovery_initialization_retries_and_reports_unconfirmed_writes():
    container = FakeCosmosContainer()
    cache = _load_cache_module()
    cache.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(cache, container, RaisingRedis))
    write = container.upsert_item

    def recover(body):
        if container.upsert_item.call_count == 1:
            raise ServiceResponseError("Write unavailable")
        return write(body)

    with patch.object(container, "upsert_item", side_effect=recover) as upsert:
        cache.initialize_cosmos_stream_discovery("owner:conversation", "turn", 600)
    assert upsert.call_count == 2
    found = cache.get_cosmos_stream_discovery("owner:conversation")
    assert found == {"submission_id": "turn"}

    with patch.object(container, "upsert_item", side_effect=ServiceResponseError("Write unavailable")) as upsert:
        with pytest.raises(cache.StreamDiscoveryUnavailable):
            cache.initialize_cosmos_stream_discovery("owner:other", "turn", 600)
    assert upsert.call_count == 2

def test_redis_content_uses_one_script_and_only_falls_back_on_a_rejected_invocation():
    cache_module = _load_cache_module()
    redis_client = InMemoryRedis()
    redis_client.eval = Mock(side_effect=[
        1, NoPermissionError("this user has no permissions to run the 'eval' command"),
    ])
    cache_module.configure_app_cache(
        {"enable_redis_cache": True, "redis_url": "redis.example.test"},
        dependencies=_dependencies(cache_module, FakeCosmosContainer(), lambda **kwargs: redis_client),
    )
    args = ("owner:chat:turn", "owner:chat", "turn", "data: event\n\n", "2026-11-21T00:00:00", 5, 60)
    result = cache_module.publish_stream_content(*args)
    assert result == 1
    redis_client.eval.assert_called_once()
    assert redis_client.eval.call_args.args[1:5] == (
        3, "STREAM_SESSION_META:owner:chat:turn", "STREAM_SESSION_EVENTS:owner:chat:turn",
        "STREAM_SESSION_META:owner:chat",
    )

    fallback = cache_module.publish_stream_content(*args)
    assert fallback == 0 and not cache_module.can_publish_stream_content()
    fallback = cache_module.publish_stream_content(*args)
    assert fallback == 0 and redis_client.eval.call_count == 2


def test_redis_content_does_not_retry_an_unconfirmed_write_on_a_different_backend():
    cache_module = _load_cache_module()
    redis_client = InMemoryRedis()
    redis_client.eval = Mock(side_effect=RedisConnectionError("response lost"))
    container = FakeCosmosContainer()
    cache_module.configure_app_cache(
        {"enable_redis_cache": True, "redis_url": "redis.example.test"},
        dependencies=_dependencies(cache_module, container, lambda **kwargs: redis_client),
    )
    with pytest.raises(cache_module.StreamReplayUnconfirmed, match="publication could not be confirmed"):
        cache_module.publish_stream_content(
            "owner:chat:turn", "owner:chat", "turn", "data: event\n\n", "2026-11-21T00:00:00", 5, 60,
        )
    redis_client.eval.assert_called_once()
    assert not container.items


def test_redis_reads_back_a_committed_publication_after_losing_the_reply():
    cache = _load_cache_module()
    redis_client = InMemoryRedis()
    container = FakeCosmosContainer()
    cache.configure_app_cache(
        {"enable_redis_cache": True, "redis_url": "redis.example.test"},
        dependencies=_dependencies(cache, container, lambda **kwargs: redis_client),
    )
    attempt, discovery, submission = "owner:chat:turn", "owner:chat", "turn"
    event = "data: event\n\n"

    def commit_then_lose_reply(script, key_count, metadata_key, events_key, discovery_key, *args):
        metadata = json.dumps({"submission_id": submission, "last_content_publish_id": args[4]})
        redis_client.set(metadata_key, metadata)
        redis_client.set(discovery_key, metadata)
        redis_client.rpush(events_key, args[0])
        raise RedisConnectionError("response lost")

    redis_client.eval = Mock(side_effect=commit_then_lose_reply)
    accepted = cache.publish_stream_content(attempt, discovery, submission, event, "now", 5, 60)
    replay = cache.get_stream_session_events(attempt)
    assert accepted == 1 and replay == [event]
    redis_client.eval.assert_called_once()
    assert not container.items

def test_redis_stream_session_initialization_preserves_existing_events():
    """A second app service must not erase events published before it attaches."""
    cache_module = _load_cache_module()
    cache_module.configure_app_cache({
        "enable_redis_cache": True,
        "redis_url": "simplechat.redis.cache.windows.net",
        "redis_key": "test-key",
        "redis_auth_type": "key",
    }, dependencies=_dependencies(cache_module, FakeCosmosContainer(), InMemoryRedis))

    cache_key = "collaboration:redis-test"
    metadata = {"conversation_id": "redis-test", "active": True}
    cache_module.initialize_stream_session_cache(cache_key, metadata, ttl_seconds=60)
    cache_module.append_stream_session_event(cache_key, "data: owner-message\n\n", ttl_seconds=60)

    cache_module.initialize_stream_session_cache(cache_key, metadata, ttl_seconds=60)
    cache_module.append_stream_session_event(cache_key, "data: invitee-message\n\n", ttl_seconds=60)

    assert cache_module.get_stream_session_events(cache_key) == [
        "data: owner-message\n\n",
        "data: invitee-message\n\n",
    ]


if __name__ == "__main__":
    tests = [
        test_redis_runtime_failure_falls_back_to_cosmos_settings,
        test_redis_write_failure_persists_user_ui_cache_to_cosmos,
        test_redis_initialization_failure_assigns_fallback_functions,
        test_stream_event_fallback_is_shared_between_workers,
        test_stream_event_fallback_patches_in_one_request_and_upgrades_legacy_items,
        test_stream_event_fallback_does_not_duplicate_a_committed_append_after_a_lost_reply,
        test_redis_stream_session_initialization_preserves_existing_events,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("Test passed.")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    sys.exit(0 if all(results) else 1)
