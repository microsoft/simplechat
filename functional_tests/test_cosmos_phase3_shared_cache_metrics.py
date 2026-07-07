# test_cosmos_phase3_shared_cache_metrics.py
#!/usr/bin/env python3
"""
Functional test for Phase 3 shared cache metrics.
Version: 0.250.037
Implemented in: 0.250.032
Cosmos fallback bypass implemented in: 0.250.037

This test ensures shared cache consumers record safe hit, miss, write,
delete, and version-bump metrics without exposing raw cache keys.
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
        self.read_count = 0
        self.delete_count = 0
        self._etag_counter = 0

    def _copy_with_new_etag(self, body):
        self._etag_counter += 1
        item = copy.deepcopy(body)
        item["_etag"] = f"etag-{self._etag_counter}"
        return item

    def read_item(self, item, partition_key):
        self.read_count += 1
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
        self.delete_count += 1
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        del self.items[item]


class FakeRedisClient:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value
        return True

    def setex(self, key, ttl_seconds, value):
        self.values[key] = value
        return True

    def delete(self, key):
        self.values.pop(key, None)
        return True


def _load_shared_cache_module(settings_container):
    fake_config = types.ModuleType("config")
    fake_config.cosmos_settings_container = settings_container
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    sys.modules.pop("functions_shared_cache", None)
    return importlib.import_module("functions_shared_cache")


def test_shared_cache_records_safe_metrics_for_common_operations():
    """Shared cache operations should emit counters with hashed cache-key context only."""
    settings_container = FakeCosmosContainer()
    shared_cache = _load_shared_cache_module(settings_container)
    shared_cache.reset_shared_cache_metrics()

    assert shared_cache.get_shared_cache_entry("phase3", "sensitive-user-key") is None
    assert shared_cache.set_shared_cache_entry("phase3", "sensitive-user-key", {"value": 1}) is True
    assert shared_cache.get_shared_cache_entry("phase3", "sensitive-user-key") == {"value": 1}
    assert shared_cache.delete_shared_cache_entry("phase3", "sensitive-user-key") is True

    metrics = shared_cache.get_shared_cache_metrics()
    counts = metrics["counts"]

    assert counts["phase3:get:cosmos:miss"] == 1
    assert counts["phase3:set:cosmos:success"] == 1
    assert counts["phase3:get:cosmos:hit"] == 1
    assert counts["phase3:delete:cosmos:success"] == 1
    assert "cache_key_hash" in metrics["last_event"]
    assert "sensitive-user-key" not in str(metrics)


def test_shared_cache_records_version_bump_metrics():
    """Version reads and bumps should be visible in shared cache diagnostics."""
    settings_container = FakeCosmosContainer()
    shared_cache = _load_shared_cache_module(settings_container)
    shared_cache.reset_shared_cache_metrics()

    version = shared_cache.bump_shared_cache_version(
        "phase3_cache_version",
        description="Phase 3 test cache version.",
    )

    metrics = shared_cache.get_shared_cache_metrics()

    assert version == 1
    assert metrics["counts"]["shared_cache_version:version_bump:cosmos:success"] == 1
    assert metrics["last_event"]["operation"] == "version_bump"
    assert metrics["last_event"]["version"] == 1
    assert "phase3_cache_version" not in str(metrics)


def test_shared_cache_can_skip_cosmos_fallback_for_volatile_entries():
    """High-churn caches should be able to bypass Cosmos when Redis is unavailable."""
    settings_container = FakeCosmosContainer()
    shared_cache = _load_shared_cache_module(settings_container)
    shared_cache.reset_shared_cache_metrics()

    assert shared_cache.get_shared_cache_entry(
        "volatile",
        "conversation-list",
        allow_cosmos_fallback=False,
    ) is None
    assert shared_cache.set_shared_cache_entry(
        "volatile",
        "conversation-list",
        {"value": 1},
        allow_cosmos_fallback=False,
    ) is False
    assert shared_cache.delete_shared_cache_entry(
        "volatile",
        "conversation-list",
        allow_cosmos_fallback=False,
    ) is True

    metrics = shared_cache.get_shared_cache_metrics()
    counts = metrics["counts"]

    assert counts["volatile:get:cosmos:skipped"] == 1
    assert counts["volatile:set:cosmos:skipped"] == 1
    assert counts["volatile:delete:cosmos:skipped"] == 1
    assert settings_container.items == {}


def test_shared_cache_skips_cosmos_after_redis_miss_when_fallback_disabled():
    """Redis-backed volatile cache misses should not point-read/delete Cosmos fallback entries."""
    settings_container = FakeCosmosContainer()
    shared_cache = _load_shared_cache_module(settings_container)
    shared_cache.reset_shared_cache_metrics()
    redis_client = FakeRedisClient()

    assert shared_cache.get_shared_cache_entry(
        "volatile",
        "conversation-list",
        redis_client=redis_client,
        allow_cosmos_fallback=False,
    ) is None
    assert shared_cache.delete_shared_cache_entry(
        "volatile",
        "conversation-list",
        redis_client=redis_client,
        allow_cosmos_fallback=False,
    ) is True

    metrics = shared_cache.get_shared_cache_metrics()
    counts = metrics["counts"]

    assert counts["volatile:get:redis:miss"] == 1
    assert counts["volatile:get:cosmos:skipped"] == 1
    assert counts["volatile:delete:redis:success"] == 1
    assert counts["volatile:delete:cosmos:skipped"] == 1
    assert settings_container.read_count == 0
    assert settings_container.delete_count == 0
    assert settings_container.items == {}


if __name__ == "__main__":
    tests = [
        test_shared_cache_records_safe_metrics_for_common_operations,
        test_shared_cache_records_version_bump_metrics,
        test_shared_cache_can_skip_cosmos_fallback_for_volatile_entries,
        test_shared_cache_skips_cosmos_after_redis_miss_when_fallback_disabled,
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
