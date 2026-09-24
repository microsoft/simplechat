# test_cosmos_wave1_cache_fallback.py
#!/usr/bin/env python3
"""
Functional test for Cosmos cache fallback behavior.
Version: 0.261.052
Implemented in: 0.261.052

This test ensures Redis failures in the app cache layer fall back to
Cosmos-backed cache/source reads instead of failing callers.
"""

import copy
import importlib
import os
import sys
from azure.core.exceptions import AzureError
from redis.exceptions import ConnectionError as RedisConnectionError


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.insert(0, SINGLE_APP_DIR)


class FakeCosmosError(AzureError):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class FakeCosmosContainer:
    def __init__(self):
        self.items = {}
        self._etag_counter = 0

    def _copy_with_new_etag(self, body):
        self._etag_counter += 1
        item = copy.deepcopy(body)
        item["_etag"] = f"etag-{self._etag_counter}"
        return item

    def read_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        return copy.deepcopy(self.items[item])

    def create_item(self, body):
        item_id = body["id"]
        if item_id in self.items:
            raise FakeCosmosError(409, f"Duplicate item {item_id}")
        self.items[item_id] = self._copy_with_new_etag(body)
        return copy.deepcopy(self.items[item_id])

    def upsert_item(self, body):
        self.items[body["id"]] = self._copy_with_new_etag(body)
        return copy.deepcopy(self.items[body["id"]])

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        if etag and self.items[item].get("_etag") != etag:
            raise FakeCosmosError(412, f"ETag mismatch for item {item}")
        self.items[item] = self._copy_with_new_etag(body)
        return copy.deepcopy(self.items[item])

    def delete_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        del self.items[item]


class StreamAppendConflictContainer(FakeCosmosContainer):
    def __init__(self):
        super().__init__()
        self.conflicts_remaining = 1

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if self.conflicts_remaining:
            self.conflicts_remaining -= 1
            concurrent_body = copy.deepcopy(self.items[item])
            concurrent_body['payload'].append('data: concurrent-message\n\n')
            self.items[item] = self._copy_with_new_etag(concurrent_body)
            raise FakeCosmosError(412, "Concurrent stream append")
        return super().replace_item(item, body, etag=etag, match_condition=match_condition, **kwargs)


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
    container = FakeCosmosContainer()
    container.items["app_settings"] = {
        "id": "app_settings",
        "feature_flag": "fallback-configured",
    }
    cache_module = _load_cache_module()

    cache_module.configure_app_cache({
        "enable_redis_cache": True,
        "redis_url": "simplechat.redis.cache.windows.net",
        "redis_key": "test-key",
        "redis_auth_type": "key",
    }, dependencies=_dependencies(cache_module, container, RaisingRedis))

    assert cache_module.app_cache_is_using_redis is False
    assert cache_module.get_settings_cache()["feature_flag"] == "fallback-configured"


def test_stream_event_fallback_is_shared_between_workers():
    """Worker-local stream snapshots must not hide collaboration events."""
    container = FakeCosmosContainer()
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


def test_stream_event_fallback_retries_concurrent_append():
    """Concurrent stream publishes must retain both events after an ETag conflict."""
    container = StreamAppendConflictContainer()
    cache_module = _load_cache_module()
    cache_module.configure_app_cache({"enable_redis_cache": False}, dependencies=_dependencies(
        cache_module, container, RaisingRedis,
    ))

    cache_key = "collaboration:conflict-test"
    cache_module.initialize_stream_session_cache(cache_key, {"active": True}, ttl_seconds=60)
    cache_module.append_stream_session_event(cache_key, "data: owner-message\n\n", ttl_seconds=60)

    assert cache_module.get_stream_session_events(cache_key) == [
        "data: concurrent-message\n\n",
        "data: owner-message\n\n",
    ]


if __name__ == "__main__":
    tests = [
        test_redis_runtime_failure_falls_back_to_cosmos_settings,
        test_redis_write_failure_persists_user_ui_cache_to_cosmos,
        test_redis_initialization_failure_assigns_fallback_functions,
        test_stream_event_fallback_is_shared_between_workers,
        test_stream_event_fallback_retries_concurrent_append,
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
