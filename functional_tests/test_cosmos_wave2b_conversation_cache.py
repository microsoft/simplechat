# test_cosmos_wave2b_conversation_cache.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 2B conversation list/search cache.
Version: 0.250.037
Implemented in: 0.250.007
Conversation cache metrics updated in: 0.250.034
Redis-only volatile cache fallback implemented in: 0.250.037

This test ensures conversation list/search/feed caches are versioned per user,
invalidate for personal and collaboration mutations, and fail open when cache
writes or Redis are unavailable.
"""

import copy
import importlib
import os
import sys
import types
from contextlib import contextmanager


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
        return copy.deepcopy(body)

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


class ConflictOnceFakeCosmosContainer(FakeCosmosContainer):
    def __init__(self):
        super().__init__()
        self.conflict_triggered = False

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if not self.conflict_triggered:
            self.conflict_triggered = True
            conflicting_body = copy.deepcopy(self.items[item])
            conflicting_body["version"] = int(conflicting_body.get("version", 0)) + 1
            self.items[item] = self._copy_with_new_etag(conflicting_body)
            raise FakeCosmosError(412, f"ETag mismatch for item {item}")
        return super().replace_item(
            item,
            body,
            etag=etag,
            match_condition=match_condition,
            **kwargs,
        )


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

    def incr(self, key):
        value = int(self.values.get(key) or 0) + 1
        self.values[key] = str(value)
        return value

    def delete(self, key):
        self.values.pop(key, None)
        return True


@contextmanager
def _load_conversation_cache_module(settings_container, group_doc=None, redis_client=None):
    module_names = [
        "config",
        "functions_appinsights",
        "app_settings_cache",
        "functions_group",
        "functions_shared_cache",
        "functions_conversation_cache",
    ]
    saved_modules = {
        module_name: sys.modules.get(module_name)
        for module_name in module_names
    }

    fake_config = types.ModuleType("config")
    fake_config.cosmos_settings_container = settings_container
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    fake_app_settings_cache = types.ModuleType("app_settings_cache")
    fake_app_settings_cache.get_app_cache_redis_client = lambda: redis_client
    sys.modules["app_settings_cache"] = fake_app_settings_cache

    fake_group = types.ModuleType("functions_group")
    fake_group.find_group_by_id = lambda group_id: copy.deepcopy(group_doc) if group_doc else None
    sys.modules["functions_group"] = fake_group

    for module_name in [
        "functions_shared_cache",
        "functions_conversation_cache",
    ]:
        sys.modules.pop(module_name, None)
    try:
        yield importlib.import_module("functions_conversation_cache")
    finally:
        for module_name, module_value in saved_modules.items():
            if module_value is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = module_value


def test_conversation_cache_key_changes_after_user_bump():
    """A user version bump should change that user's list cache key."""
    settings_container = FakeCosmosContainer()
    with _load_conversation_cache_module(settings_container, redis_client=FakeRedisClient()) as conversation_cache:
        first_key = conversation_cache.build_conversation_cache_key(
            "user-1",
            "list",
            parameters={"include_hidden": True},
        )
        conversation_cache.set_cached_conversation_payload(
            first_key,
            {"conversations": [{"id": "conversation-1"}]},
            ttl_seconds=120,
        )
        conversation_cache.bump_conversation_cache_version("user-1", reason="test")
        second_key = conversation_cache.build_conversation_cache_key(
            "user-1",
            "list",
            parameters={"include_hidden": True},
        )

        assert first_key != second_key
        assert conversation_cache.get_cached_conversation_payload(first_key)["conversations"][0]["id"] == "conversation-1"
        assert conversation_cache.get_cached_conversation_payload(second_key) is None
        assert not settings_container.items


def test_conversation_cache_bump_uses_redis_version_counter():
    """Conversation version bumps should use Redis instead of settings-container version docs."""
    settings_container = ConflictOnceFakeCosmosContainer()
    with _load_conversation_cache_module(settings_container, redis_client=FakeRedisClient()) as conversation_cache:
        first_version = conversation_cache.bump_conversation_cache_version("user-1", reason="first")
        second_version = conversation_cache.bump_conversation_cache_version("user-1", reason="second")

    assert first_version == 1
    assert second_version == 2
    assert "conversation_cache_version:user-1" not in settings_container.items


def test_conversation_cache_key_reads_redis_version_without_settings_container():
    """Conversation keys should observe external Redis version bumps without settings-container reads."""
    settings_container = FakeCosmosContainer()
    redis_client = FakeRedisClient()
    with _load_conversation_cache_module(settings_container, redis_client=redis_client) as conversation_cache:
        conversation_cache.bump_conversation_cache_version("user-1", reason="initial")
        first_key = conversation_cache.build_conversation_cache_key("user-1", "feed", parameters={})

        redis_client.incr("conversation_cache_version:user-1")

        second_key = conversation_cache.build_conversation_cache_key("user-1", "feed", parameters={})

    assert first_key != second_key
    assert not settings_container.items


def test_conversation_cache_invalidation_fans_out_to_viewers():
    """Invalidating a conversation should include owners, participants, and group viewers."""
    settings_container = FakeCosmosContainer()
    with _load_conversation_cache_module(
        settings_container,
        redis_client=FakeRedisClient(),
        group_doc={
            "id": "group-1",
            "owner": {"id": "group-owner"},
            "admins": [{"userId": "group-admin"}],
            "documentManagers": [{"userId": "group-doc-manager"}],
            "users": [{"userId": "group-user"}],
        },
    ) as conversation_cache:
        bumped_user_ids = []
        conversation_cache.bump_conversation_cache_version = (
            lambda user_id, reason="test": bumped_user_ids.append(user_id) or 1
        )

        conversation_cache.invalidate_conversation_cache_for_item(
            {
                "id": "conversation-1",
                "user_id": "owner-user",
                "created_by_user_id": "creator-user",
                "accepted_participant_ids": ["accepted-user"],
                "pending_participant_ids": ["pending-user"],
                "owner_user_ids": ["collab-owner"],
                "admin_user_ids": ["collab-admin"],
                "participants": [
                    {"user_id": "active-participant", "status": "accepted"},
                    {"user_id": "removed-participant", "status": "removed"},
                ],
                "tags": [
                    {"category": "participant", "user_id": "tagged-participant"},
                ],
                "scope": {"group_id": "group-1"},
            },
            reason="test",
        )

    assert set(bumped_user_ids) == {
        "owner-user",
        "creator-user",
        "accepted-user",
        "pending-user",
        "collab-owner",
        "collab-admin",
        "active-participant",
        "tagged-participant",
        "group-owner",
        "group-admin",
        "group-doc-manager",
        "group-user",
    }


def test_conversation_cache_write_failures_do_not_escape():
    """Cache write failures should not fail the caller."""
    settings_container = FakeCosmosContainer()
    with _load_conversation_cache_module(settings_container, redis_client=FakeRedisClient()) as conversation_cache:
        def raise_cache_write(*args, **kwargs):
            raise RuntimeError("cache unavailable")

        conversation_cache.set_shared_cache_entry = raise_cache_write
        assert conversation_cache.set_cached_conversation_payload(
            "cache-key",
            {"success": True},
            ttl_seconds="invalid",
        ) is False


def test_conversation_cache_disabled_bypasses_reads_and_writes():
    """Disabled conversation cache should bypass cache entries and leave source reads authoritative."""
    settings_container = FakeCosmosContainer()
    with _load_conversation_cache_module(settings_container, redis_client=FakeRedisClient()) as conversation_cache:
        cache_key = conversation_cache.build_conversation_cache_key(
            "user-1",
            "list",
            parameters={"include_hidden": True},
        )
        assert conversation_cache.set_cached_conversation_payload(
            cache_key,
            {"conversations": [{"id": "conversation-1"}]},
            ttl_seconds=120,
        ) is True

        disabled_settings = {"enable_conversation_cache": False}
        assert conversation_cache.get_cached_conversation_payload(
            cache_key,
            settings=disabled_settings,
        ) is None
        assert conversation_cache.set_cached_conversation_payload(
            "disabled-key",
            {"conversations": [{"id": "conversation-2"}]},
            settings=disabled_settings,
        ) is False
        assert "shared_cache_entry:conversation_cache:disabled-key" not in settings_container.items


def test_conversation_cache_redis_unavailable_bypasses_without_settings_writes():
    """Redis-unavailable conversation cache should fall back to source Cosmos query behavior."""
    settings_container = FakeCosmosContainer()
    with _load_conversation_cache_module(settings_container, redis_client=None) as conversation_cache:
        cache_key = conversation_cache.build_conversation_cache_key(
            "user-1",
            "list",
            parameters={"include_hidden": True},
        )

        assert cache_key is None
        assert conversation_cache.bump_conversation_cache_version("user-1", reason="redis-missing") is None
        assert conversation_cache.get_cached_conversation_payload("list:user-1:test") is None
        assert conversation_cache.set_cached_conversation_payload(
            "list:user-1:test",
            {"conversations": [{"id": "conversation-1"}]},
            ttl_seconds=120,
        ) is False
        assert not settings_container.items


def test_conversation_cache_metrics_track_rolling_events():
    """Conversation cache metrics should track DAI-style rolling cache events."""
    settings_container = FakeCosmosContainer()
    with _load_conversation_cache_module(settings_container, redis_client=FakeRedisClient()) as conversation_cache:
        conversation_cache.reset_conversation_cache_metrics()
        list_key = conversation_cache.build_conversation_cache_key(
            "user-1",
            "list",
            parameters={"include_hidden": True},
        )
        feed_key = conversation_cache.build_conversation_cache_key(
            "user-1",
            "feed",
            parameters={"limit": 25},
        )

        assert conversation_cache.set_cached_conversation_payload(
            list_key,
            {"conversations": [{"id": "conversation-1"}]},
            ttl_seconds=120,
        ) is True
        assert conversation_cache.get_cached_conversation_payload(list_key)["conversations"][0]["id"] == "conversation-1"
        assert conversation_cache.get_cached_conversation_payload(feed_key) is None
        assert conversation_cache.get_cached_conversation_payload(
            list_key,
            settings={"enable_conversation_cache": False},
        ) is None
        assert conversation_cache.set_cached_conversation_payload(
            list_key,
            {"conversations": [{"id": "conversation-2"}]},
            settings={"conversation_cache_ttl_seconds": 0},
        ) is False
        assert conversation_cache.bump_conversation_cache_version("user-1", reason="metrics-test") == 1

        metrics = conversation_cache.get_conversation_cache_metrics()
        window_15m = metrics["windows"]["15m"]

    assert window_15m["hit_count"] == 1
    assert window_15m["miss_count"] == 1
    assert window_15m["bypass_count"] == 2
    assert window_15m["write_count"] == 1
    assert window_15m["invalidation_count"] == 1
    assert window_15m["error_count"] == 0
    assert window_15m["hit_rate_percent"] == 50.0
    assert window_15m["operation_counts"]["list"] == 4
    assert window_15m["operation_counts"]["feed"] == 1
    assert window_15m["operation_counts"]["version"] == 1
    assert metrics["last_invalidation"]["reason"] == "metrics-test"


def test_conversation_cache_route_and_mutation_hooks_are_wired():
    """Contract test for list/search/feed cache usage and invalidation hooks."""
    route_source = open(
        os.path.join(SINGLE_APP_DIR, "route_backend_conversations.py"),
        "r",
        encoding="utf-8",
    ).read()
    assert "build_conversation_cache_key(user_id, \"list\"" in route_source
    assert "_build_conversation_cache_access_parameters(user_id)" in route_source
    assert "get_conversation_cache_settings(settings)" in route_source
    assert "cache_settings.get('enabled')" in route_source
    assert "\"access\": access_parameters" in route_source or "'access': access_parameters" in route_source
    assert "feed_cache_parameters" in route_source and "\"feed\"" in route_source
    assert "search_cache_parameters" in route_source and "\"search\"" in route_source
    assert "get_cached_conversation_payload" in route_source
    assert "set_cached_conversation_payload" in route_source
    assert "invalidate_conversation_cache_for_item(conversation_item, reason=\"conversation_chat_type_normalized\")" in route_source

    settings_source = open(os.path.join(SINGLE_APP_DIR, "functions_settings.py"), "r", encoding="utf-8").read()
    assert "'enable_conversation_cache': True" in settings_source

    cache_source = open(os.path.join(SINGLE_APP_DIR, "functions_conversation_cache.py"), "r", encoding="utf-8").read()
    maintenance_source = open(os.path.join(SINGLE_APP_DIR, "functions_app_maintenance.py"), "r", encoding="utf-8").read()
    assert "def get_conversation_cache_metrics()" in cache_source
    assert "bump_shared_cache_version" not in cache_source
    assert "get_shared_cache_version" not in cache_source
    assert "allow_cosmos_fallback=False" in cache_source
    assert "redis_unavailable" in cache_source
    assert "_record_conversation_cache_metric(\"hit\", operation=operation)" in cache_source
    assert "_record_conversation_cache_metric(\"miss\", operation=operation)" in cache_source
    assert "_record_conversation_cache_metric(\"bypass\", operation=operation, reason=\"disabled\")" in cache_source
    assert "_record_conversation_cache_metric(\"invalidate\", operation=\"version\", reason=reason)" in cache_source
    assert "'conversation_cache': {" in maintenance_source
    assert "'metrics': get_conversation_cache_metrics()" in maintenance_source

    for file_name, marker in {
        "route_backend_conversations.py": "bump_conversation_cache_version(user_id, reason=\"conversation_pin_toggled\")",
        "route_backend_chats.py": "invalidate_conversation_cache_for_item(conversation_item, reason=\"chat_stream_completed\")",
        "functions_collaboration.py": "invalidate_conversation_cache_for_item(conversation_doc, reason=\"collaboration_message_saved\")",
        "route_backend_notifications.py": "bump_conversation_cache_version(user_id, reason=\"notification_marked_read\")",
    }.items():
        source = open(os.path.join(SINGLE_APP_DIR, file_name), "r", encoding="utf-8").read()
        assert marker in source, f"Missing conversation cache hook marker in {file_name}: {marker}"
        if file_name == "route_backend_chats.py":
            assert source.count("reason=\"chat_image_generated\"") == 1
        if file_name == "functions_collaboration.py":
            assert "collaboration_notification_created" not in source


if __name__ == "__main__":
    tests = [
        test_conversation_cache_key_changes_after_user_bump,
        test_conversation_cache_bump_uses_redis_version_counter,
        test_conversation_cache_key_reads_redis_version_without_settings_container,
        test_conversation_cache_invalidation_fans_out_to_viewers,
        test_conversation_cache_write_failures_do_not_escape,
        test_conversation_cache_disabled_bypasses_reads_and_writes,
        test_conversation_cache_redis_unavailable_bypasses_without_settings_writes,
        test_conversation_cache_metrics_track_rolling_events,
        test_conversation_cache_route_and_mutation_hooks_are_wired,
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
