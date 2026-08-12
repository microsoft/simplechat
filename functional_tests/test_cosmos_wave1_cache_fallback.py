# test_cosmos_wave1_cache_fallback.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 1 cache fallback behavior.
Version: 0.250.005
Implemented in: 0.250.005

This test ensures Redis failures in the app cache layer fall back to
Cosmos-backed cache/source reads instead of failing callers.
"""

import copy
import importlib
import os
import sys
import types


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.insert(0, SINGLE_APP_DIR)


class FakeCosmosError(Exception):
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

    def read_item(self, item, partition_key):
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


class FailingRedis:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    def set(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

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
        raise RuntimeError("redis initialization failed")


def _install_fake_modules(container):
    fake_config = types.ModuleType("config")
    fake_config.cosmos_settings_container = container
    fake_config.exceptions = types.SimpleNamespace()
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights


def _load_cache_module(container):
    _install_fake_modules(container)
    sys.modules.pop("app_settings_cache", None)
    return importlib.import_module("app_settings_cache")


def test_redis_runtime_failure_falls_back_to_cosmos_settings():
    """A Redis read failure should return settings from Cosmos instead of raising."""
    container = FakeCosmosContainer()
    container.items["app_settings"] = {
        "id": "app_settings",
        "feature_flag": "from-cosmos",
    }
    container.items["app_settings_cache_version"] = {
        "id": "app_settings_cache_version",
        "type": "cache_version",
        "version": 7,
    }
    cache_module = _load_cache_module(container)
    cache_module.Redis = FailingRedis

    cache_module.configure_app_cache({
        "enable_redis_cache": True,
        "redis_url": "simplechat.redis.cache.windows.net",
        "redis_key": "test-key",
        "redis_auth_type": "key",
    })

    cached_settings = cache_module.get_settings_cache()

    assert cached_settings["feature_flag"] == "from-cosmos"
    assert cache_module.get_app_settings_cache_version() == 7


def test_redis_write_failure_persists_user_ui_cache_to_cosmos():
    """A Redis write failure should persist lightweight UI cache data in Cosmos."""
    container = FakeCosmosContainer()
    cache_module = _load_cache_module(container)
    cache_module.Redis = FailingRedis

    cache_module.configure_app_cache({
        "enable_redis_cache": True,
        "redis_url": "simplechat.redis.cache.windows.net",
        "redis_key": "test-key",
        "redis_auth_type": "key",
    })

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
    cache_module = _load_cache_module(container)
    cache_module.Redis = RaisingRedis

    cache_module.configure_app_cache({
        "enable_redis_cache": True,
        "redis_url": "simplechat.redis.cache.windows.net",
        "redis_key": "test-key",
        "redis_auth_type": "key",
    })

    assert cache_module.app_cache_is_using_redis is False
    assert cache_module.get_settings_cache()["feature_flag"] == "fallback-configured"


if __name__ == "__main__":
    tests = [
        test_redis_runtime_failure_falls_back_to_cosmos_settings,
        test_redis_write_failure_persists_user_ui_cache_to_cosmos,
        test_redis_initialization_failure_assigns_fallback_functions,
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
