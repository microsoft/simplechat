# test_cosmos_wave2a_chat_bootstrap_cache.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 2A chat bootstrap cache.
Version: 0.250.037
Implemented in: 0.250.006
Settings write invalidation scoped in: 0.250.037

This test ensures chat bootstrap cache keys are versioned and invalidated by
global and per-user cache version bumps without relying on generic settings
write invalidation.
"""

import copy
import importlib
import os
import sys
import types
from datetime import datetime


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


def _load_chat_bootstrap_module(settings_container, redis_client=None):
    fake_config = types.ModuleType("config")
    fake_config.cosmos_settings_container = settings_container
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    fake_app_settings_cache = types.ModuleType("app_settings_cache")
    fake_app_settings_cache.get_app_cache_redis_client = lambda: redis_client
    fake_app_settings_cache.get_app_settings_cache_version = lambda: 0
    fake_app_settings_cache.get_governance_cache_version = lambda: 0
    sys.modules["app_settings_cache"] = fake_app_settings_cache

    for module_name in [
        "functions_shared_cache",
        "functions_chat_bootstrap_cache",
    ]:
        sys.modules.pop(module_name, None)
    return importlib.import_module("functions_chat_bootstrap_cache")


def _load_public_workspaces_module(public_workspaces_container, invalidation_reasons):
    fake_config = types.ModuleType("config")
    fake_config.cosmos_public_workspaces_container = public_workspaces_container
    fake_config.datetime = datetime
    fake_config.exceptions = types.SimpleNamespace(CosmosResourceNotFoundError=FakeCosmosError)
    sys.modules["config"] = fake_config

    fake_group = types.ModuleType("functions_group")
    sys.modules["functions_group"] = fake_group

    fake_authentication = types.ModuleType("functions_authentication")
    fake_authentication.get_current_user_info = lambda: None
    sys.modules["functions_authentication"] = fake_authentication

    fake_settings = types.ModuleType("functions_settings")
    sys.modules["functions_settings"] = fake_settings

    fake_branding = types.ModuleType("functions_workspace_branding")
    fake_branding.DEFAULT_WORKSPACE_HERO_COLOR = "#000000"
    fake_branding.get_workspace_logo_metadata = lambda *args, **kwargs: {}
    fake_branding.normalize_workspace_hero_color = lambda value: value or "#000000"
    sys.modules["functions_workspace_branding"] = fake_branding

    fake_bootstrap_cache = types.ModuleType("functions_chat_bootstrap_cache")
    fake_bootstrap_cache.bump_chat_bootstrap_global_cache_version = (
        lambda reason=None: invalidation_reasons.append(reason)
    )
    sys.modules["functions_chat_bootstrap_cache"] = fake_bootstrap_cache

    sys.modules.pop("functions_public_workspaces", None)
    return importlib.import_module("functions_public_workspaces")


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
    bootstrap_cache = _load_chat_bootstrap_module(settings_container, redis_client=FakeRedisClient())
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
    bootstrap_cache = _load_chat_bootstrap_module(settings_container, redis_client=FakeRedisClient())
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
    }.items():
        source = open(os.path.join(SINGLE_APP_DIR, file_name), "r", encoding="utf-8").read()
        assert marker in source, f"Missing invalidation hook marker in {file_name}: {marker}"
        if file_name == "functions_settings.py":
            assert source.count("def _refresh_app_settings_cache_after_write(") == 1

    settings_source = open(os.path.join(SINGLE_APP_DIR, "functions_settings.py"), "r", encoding="utf-8").read()
    assert "bump_chat_bootstrap_global_cache_version(reason=f\"settings_write:{context}\")" not in settings_source


def test_phase3_low_churn_invalidation_hooks_are_wired():
    """Contract test for Phase 3 group/public/custom-pages invalidation coverage."""
    expected_markers = {
        "functions_group.py": [
            "bump_chat_bootstrap_global_cache_version(reason=\"group_created\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"group_deleted\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"group_model_endpoints_updated\")",
        ],
        "functions_public_workspaces.py": [
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_created\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_deleted\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_document_manager_added\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_document_manager_removed\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_document_manager_request_approved\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_document_manager_request_rejected\")",
        ],
        "functions_simplechat_operations.py": [
            "bump_chat_bootstrap_global_cache_version(reason=\"group_marked_inactive\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"group_member_added\")",
        ],
        "route_backend_groups.py": [
            "bump_chat_bootstrap_global_cache_version(reason=\"group_updated\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"group_member_request_approved\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"group_member_removed\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"group_member_role_updated\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"group_ownership_transferred\")",
        ],
        "route_backend_public_workspaces.py": [
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_updated\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_member_request_approved\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_member_added\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_member_removed\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_member_role_updated\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_ownership_transferred\")",
        ],
        "route_backend_control_center.py": [
            "bump_chat_bootstrap_global_cache_version(reason=\"group_status_updated\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"group_member_added\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_status_updated\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_bulk_status_updated\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_member_added\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"group_ownership_transferred\")",
            "bump_chat_bootstrap_global_cache_version(reason=\"public_workspace_ownership_transferred\")",
        ],
    }

    for file_name, markers in expected_markers.items():
        source = open(os.path.join(SINGLE_APP_DIR, file_name), "r", encoding="utf-8").read()
        for marker in markers:
            assert marker in source, f"Missing Phase 3 invalidation hook in {file_name}: {marker}"

    groups_source = open(os.path.join(SINGLE_APP_DIR, "route_backend_groups.py"), "r", encoding="utf-8").read()
    group_update_route = groups_source[
        groups_source.index("def api_update_group(group_id):"):
        groups_source.index("def api_get_group_logo(group_id):")
    ]
    assert "cosmos_groups_container.upsert_item(group_doc)" in group_update_route
    assert "bump_chat_bootstrap_global_cache_version(reason=\"group_updated\")" in group_update_route


def test_chat_bootstrap_payload_cache_does_not_fallback_to_settings_container_without_redis():
    """Volatile chat bootstrap payloads should not write shared cache entries to settings without Redis."""
    settings_container = FakeCosmosContainer()
    bootstrap_cache = _load_chat_bootstrap_module(settings_container, redis_client=None)
    inputs = _cache_inputs()

    cache_key = bootstrap_cache.build_chat_bootstrap_cache_key("user-1", **inputs)

    assert bootstrap_cache.set_cached_chat_bootstrap_payload(cache_key, {"chat_agent_options": []}) is False
    assert bootstrap_cache.get_cached_chat_bootstrap_payload(cache_key) is None
    assert not any(item_id.startswith("shared_cache_entry:chat_bootstrap:") for item_id in settings_container.items)


def test_public_workspace_request_approval_persists_manager_and_invalidates_cache():
    """Approving a document-manager request should persist both membership and pending cleanup."""
    public_workspaces_container = FakeCosmosContainer()
    invalidation_reasons = []
    public_workspaces_container.create_item({
        "id": "workspace-1",
        "pendingDocumentManagers": [
            {
                "userId": "user-1",
                "email": "user1@example.com",
                "displayName": "User One",
            },
        ],
        "documentManagers": [],
    })
    public_workspaces = _load_public_workspaces_module(public_workspaces_container, invalidation_reasons)

    public_workspaces.approve_document_manager_request("workspace-1", "user-1")

    saved_workspace = public_workspaces_container.items["workspace-1"]
    assert saved_workspace["pendingDocumentManagers"] == []
    assert saved_workspace["documentManagers"] == [{
        "userId": "user-1",
        "email": "user1@example.com",
        "displayName": "User One",
    }]
    assert invalidation_reasons == ["public_workspace_document_manager_request_approved"]


if __name__ == "__main__":
    tests = [
        test_chat_bootstrap_cache_key_changes_after_global_bump,
        test_chat_bootstrap_cache_key_changes_after_user_bump,
        test_chat_bootstrap_route_and_write_hooks_are_wired,
        test_phase3_low_churn_invalidation_hooks_are_wired,
        test_chat_bootstrap_payload_cache_does_not_fallback_to_settings_container_without_redis,
        test_public_workspace_request_approval_persists_manager_and_invalidates_cache,
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
