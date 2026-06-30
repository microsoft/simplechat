# test_cosmos_wave2a_chat_bootstrap_cache.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 2A chat bootstrap cache.
Version: 0.250.006
Implemented in: 0.250.006

This test ensures chat bootstrap cache keys are versioned and invalidated by
global and per-user cache version bumps.
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


def _load_chat_bootstrap_module(settings_container):
    fake_config = types.ModuleType("config")
    fake_config.cosmos_settings_container = settings_container
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    for module_name in [
        "functions_shared_cache",
        "app_settings_cache",
        "functions_chat_bootstrap_cache",
    ]:
        sys.modules.pop(module_name, None)
    return importlib.import_module("functions_chat_bootstrap_cache")


def _cache_inputs():
    return {
        "settings": {
            "allow_user_agents": True,
            "enable_semantic_kernel": True,
            "enable_group_workspaces": True,
            "allow_group_agents": True,
            "enable_multi_model_endpoints": True,
            "allow_user_custom_endpoints": True,
            "allow_group_custom_endpoints": True,
            "enable_public_workspaces": True,
            "enable_user_workspace": True,
            "allow_user_plugins": True,
            "allow_group_plugins": True,
        },
        "user_settings_dict": {
            "personal_model_endpoints": [{"id": "personal-endpoint"}],
        },
        "user_groups_raw": [{"id": "group-1", "name": "Group One"}],
        "user_visible_public_workspaces": [{"id": "public-1", "name": "Public One"}],
    }


def test_chat_bootstrap_cache_key_changes_after_global_bump():
    """A global version bump should change the chat bootstrap cache key."""
    settings_container = FakeCosmosContainer()
    bootstrap_cache = _load_chat_bootstrap_module(settings_container)
    inputs = _cache_inputs()

    first_key = bootstrap_cache.build_chat_bootstrap_cache_key("user-1", **inputs)
    bootstrap_cache.set_cached_chat_bootstrap_payload(
        first_key,
        {
            "chat_agent_options": [{"id": "agent-1"}],
            "chat_model_options": [],
            "chat_prompt_options": [],
        },
        ttl_seconds=300,
    )
    bootstrap_cache.bump_chat_bootstrap_global_cache_version(reason="test")
    second_key = bootstrap_cache.build_chat_bootstrap_cache_key("user-1", **inputs)

    assert first_key != second_key
    assert bootstrap_cache.get_cached_chat_bootstrap_payload(first_key)["chat_agent_options"][0]["id"] == "agent-1"
    assert bootstrap_cache.get_cached_chat_bootstrap_payload(second_key) is None


def test_chat_bootstrap_cache_key_changes_after_user_bump():
    """A user version bump should only change that user's cache key."""
    settings_container = FakeCosmosContainer()
    bootstrap_cache = _load_chat_bootstrap_module(settings_container)
    inputs = _cache_inputs()

    user_one_before = bootstrap_cache.build_chat_bootstrap_cache_key("user-1", **inputs)
    user_two_before = bootstrap_cache.build_chat_bootstrap_cache_key("user-2", **inputs)
    bootstrap_cache.bump_chat_bootstrap_user_cache_version("user-1", reason="test")
    user_one_after = bootstrap_cache.build_chat_bootstrap_cache_key("user-1", **inputs)
    user_two_after = bootstrap_cache.build_chat_bootstrap_cache_key("user-2", **inputs)

    assert user_one_before != user_one_after
    assert user_two_before == user_two_after


def test_chat_bootstrap_route_and_write_hooks_are_wired():
    """Contract test for route cache usage and write-path invalidation hooks."""
    route_source = open(
        os.path.join(SINGLE_APP_DIR, "route_frontend_chats.py"),
        "r",
        encoding="utf-8",
    ).read()
    assert "build_chat_bootstrap_cache_key" in route_source
    assert "get_cached_chat_bootstrap_payload" in route_source
    assert "set_cached_chat_bootstrap_payload" in route_source

    for file_name, marker in {
        "functions_global_agents.py": "bump_chat_bootstrap_global_cache_version(reason=\"global_agent_saved\")",
        "functions_personal_agents.py": "bump_chat_bootstrap_user_cache_version(user_id, reason=\"personal_agent_saved\")",
        "functions_group_agents.py": "bump_chat_bootstrap_global_cache_version(reason=\"group_agent_saved\")",
        "functions_global_actions.py": "bump_chat_bootstrap_global_cache_version(reason=\"global_action_saved\")",
        "functions_personal_actions.py": "bump_chat_bootstrap_user_cache_version(user_id, reason=\"personal_action_saved\")",
        "functions_group_actions.py": "bump_chat_bootstrap_global_cache_version(reason=\"group_action_saved\")",
        "functions_prompts.py": "_invalidate_prompt_chat_bootstrap_cache(",
        "functions_settings.py": "bump_chat_bootstrap_global_cache_version(reason=f\"settings_write:{context}\")",
    }.items():
        source = open(os.path.join(SINGLE_APP_DIR, file_name), "r", encoding="utf-8").read()
        assert marker in source, f"Missing invalidation hook marker in {file_name}: {marker}"
        if file_name == "functions_settings.py":
            assert source.count("def _refresh_app_settings_cache_after_write(") == 1


if __name__ == "__main__":
    tests = [
        test_chat_bootstrap_cache_key_changes_after_global_bump,
        test_chat_bootstrap_cache_key_changes_after_user_bump,
        test_chat_bootstrap_route_and_write_hooks_are_wired,
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
