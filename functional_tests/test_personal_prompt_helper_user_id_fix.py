#!/usr/bin/env python3
# test_personal_prompt_helper_user_id_fix.py
"""
Functional test for personal prompt helper user ID handling.
Version: 0.239.206
Implemented in: 0.239.206

This test ensures that personal prompt get, update, and delete flows keep
using the caller user_id after the shared prompt helper refactor.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import types
import uuid


ROOT_DIR = Path(__file__).resolve().parents[1]
PROMPTS_FILE = ROOT_DIR / "application" / "single_app" / "functions_prompts.py"
CONFIG_FILE = ROOT_DIR / "application" / "single_app" / "config.py"


class FakeCosmosResourceNotFoundError(Exception):
    """Raised when a fake container item cannot be found."""


class FakeContainer:
    def __init__(self):
        self.items = {}

    def create_item(self, body):
        stored = dict(body)
        self.items[stored["id"]] = stored
        return dict(stored)

    def read_item(self, item, partition_key):
        del partition_key
        if item not in self.items:
            raise FakeCosmosResourceNotFoundError(item)
        return dict(self.items[item])

    def query_items(self, query, parameters, enable_cross_partition_query=True):
        del enable_cross_partition_query
        lookup = {param["name"]: param["value"] for param in parameters}
        results = []

        for item in self.items.values():
            if "@pid" in lookup and item.get("id") != lookup["@pid"]:
                continue
            if "@type" in lookup and item.get("type") != lookup["@type"]:
                continue
            if "@prompt_type" in lookup and item.get("type") != lookup["@prompt_type"]:
                continue
            if "@id" in lookup:
                if not any(item.get(field) == lookup["@id"] for field in ("user_id", "group_id", "public_id")):
                    continue
            if "@id_value" in lookup:
                if not any(item.get(field) == lookup["@id_value"] for field in ("user_id", "group_id", "public_id")):
                    continue
            if "@search" in lookup and lookup["@search"].lower() not in (item.get("name") or "").lower():
                continue
            results.append(dict(item))

        if "COUNT(1)" in query:
            return [len(results)]

        return results

    def replace_item(self, item, body):
        if item not in self.items:
            raise FakeCosmosResourceNotFoundError(item)
        stored = dict(body)
        self.items[item] = stored
        return dict(stored)

    def delete_item(self, item, partition_key):
        del partition_key
        if item not in self.items:
            raise FakeCosmosResourceNotFoundError(item)
        del self.items[item]


def load_functions_prompts_module():
    fake_config = types.ModuleType("config")
    fake_config.datetime = datetime
    fake_config.timezone = timezone
    fake_config.uuid = uuid
    fake_config.CosmosResourceNotFoundError = FakeCosmosResourceNotFoundError
    fake_config.cosmos_user_prompts_container = FakeContainer()
    fake_config.cosmos_group_prompts_container = FakeContainer()
    fake_config.cosmos_public_prompts_container = FakeContainer()

    previous_config = sys.modules.get("config")
    sys.modules["config"] = fake_config

    module_globals = {"__name__": "functions_prompts_test_module"}
    try:
        exec(PROMPTS_FILE.read_text(encoding="utf-8"), module_globals)
    finally:
        if previous_config is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = previous_config

    return module_globals


def test_personal_prompt_crud_round_trip_uses_user_id_scope():
    """Verify personal prompt CRUD keeps the caller user_id in scope."""
    print("Testing personal prompt CRUD helper behavior...")

    prompts_module = load_functions_prompts_module()
    create_prompt_doc = prompts_module["create_prompt_doc"]
    get_prompt_doc = prompts_module["get_prompt_doc"]
    update_prompt_doc = prompts_module["update_prompt_doc"]
    delete_prompt_doc = prompts_module["delete_prompt_doc"]

    created = create_prompt_doc(
        name="Original Prompt",
        content="Original content",
        prompt_type="user_prompt",
        user_id="user-123",
    )

    fetched = get_prompt_doc("user-123", created["id"], "user_prompt")
    assert fetched is not None, "Expected owner to retrieve the created prompt"
    assert fetched.get("user_id") == "user-123", "Expected personal prompt to remain bound to the owner"

    unauthorized_fetch = get_prompt_doc("user-999", created["id"], "user_prompt")
    assert unauthorized_fetch is None, "Expected non-owner prompt lookup to be denied"

    updated = update_prompt_doc(
        user_id="user-123",
        prompt_id=created["id"],
        prompt_type="user_prompt",
        updates={"name": "Updated Prompt", "content": "Updated content"},
    )
    assert updated is not None, "Expected owner update to succeed"
    assert updated["name"] == "Updated Prompt", "Expected prompt update to persist"

    unauthorized_update = update_prompt_doc(
        user_id="user-999",
        prompt_id=created["id"],
        prompt_type="user_prompt",
        updates={"name": "Wrong User"},
    )
    assert unauthorized_update is None, "Expected non-owner update to return None"

    unauthorized_delete = delete_prompt_doc(user_id="user-999", prompt_id=created["id"])
    assert unauthorized_delete is False, "Expected non-owner delete to return False"

    owner_delete = delete_prompt_doc(user_id="user-123", prompt_id=created["id"])
    assert owner_delete is True, "Expected owner delete to succeed"

    missing_after_delete = get_prompt_doc("user-123", created["id"], "user_prompt")
    assert missing_after_delete is None, "Expected prompt lookup to return None after deletion"

    print("PASS: Personal prompt CRUD helper behavior is correct")


def test_config_version_is_bumped_for_personal_prompt_fix():
    """Verify config version was updated for this regression fix."""
    print("Testing config version bump...")

    config_text = CONFIG_FILE.read_text(encoding="utf-8")
    assert 'VERSION = "0.239.206"' in config_text, "Expected config.py version 0.239.206"

    print("PASS: Config version updated to 0.239.206")


if __name__ == "__main__":
    tests = [
        test_personal_prompt_crud_round_trip_uses_user_id_scope,
        test_config_version_is_bumped_for_personal_prompt_fix,
    ]

    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    passed = sum(results)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)