# test_workspace_authoring_sdk_boundaries.py
"""Owner-runtime evidence for editor storage after shared-response changes.

Version: 0.261.428
Implemented in: 0.261.428

Real personal/group/global storage owners consume installed-SDK CosmosDict point
and write responses, plain query rows, conditional conflicts and reminder patches.
"""

import sys
import uuid
from contextlib import contextmanager
from copy import deepcopy

import pytest
from azure.cosmos._cosmos_responses import CosmosDict

from test_support.agent_delegation import execute_functions
from test_support.shared_secret_responses import SharedContainer, environment, shared_routes


@pytest.fixture
def sdk_editors(shared_routes):
    env = shared_routes
    with pytest.MonkeyPatch.context() as scoped:
        for kind in ("actions", "agents"):
            container = SharedContainer("user_id")
            env.containers[kind, "personal"] = container
            env.services.containers[kind, "personal"] = container
            env.services.records[kind, "personal"] = container.items
            scoped.setattr(env.services.modules["config"], f"cosmos_personal_{kind}_container", container)
        scoped.setattr(env.identities, "WORKSPACE_IDENTITY_SCOPE_PERSONAL", "personal", raising=False)
        scoped.setattr(env.identities, "WORKSPACE_IDENTITY_SCOPE_GLOBAL", "global", raising=False)
        env.services.settings["merge_global_semantic_kernel_with_workspace"] = True
        yield env


def test_shared_fixture_restores_parent_sdk_modules_before_parent_teardown(environment):
    previous = sys.modules["azure.cosmos.exceptions"]
    with contextmanager(shared_routes.__wrapped__)(environment):
        assert sys.modules["azure.cosmos.exceptions"] is not previous
    assert sys.modules["azure.cosmos.exceptions"] is previous


def draft(kind, scope, **changes):
    result = {
        "id": str(uuid.uuid4()), "name": f"{scope}_{kind}", "description": "SDK contract",
    }
    if kind == "actions":
        result.update({
            "type": "openapi", "displayName": "SDK action", "endpoint": "https://service.invalid",
            "auth": {"type": "key", "key": "synthetic-sdk-credential"},
            "metadata": {}, "additionalFields": {},
        })
    else:
        result.update({
            "agent_type": "local", "display_name": "SDK agent", "instructions": "Be helpful.",
            "other_settings": {}, "actions_to_load": [], "azure_openai_gpt_key": "synthetic-sdk-credential",
        })
    if scope == "personal":
        result["user_id"] = "owner"
    elif scope == "group":
        result["group_id"] = "group-a"
    else:
        result.update(is_global=True, is_group=False, scope="global", is_enabled=True)
    result.update(changes)
    return result


def save(env, kind, scope, record, existing=None):
    if scope == "global":
        return env.helper.save_global_editor_record(kind, "owner", record, existing, env.services.settings)
    if scope == "group":
        return env.helper.save_group_editor_record(kind, "owner", "group-a", record, existing, env.services.settings)
    return env.helper.save_editor_record(kind, "owner", record, existing, env.services.settings)


@pytest.mark.parametrize("kind", ["agents", "actions"])
@pytest.mark.parametrize("scope", ["personal", "group", "global"])
def test_real_editor_read_list_and_name_owners_accept_sdk_shapes(sdk_editors, kind, scope):
    env = sdk_editors
    stored = env.containers[kind, scope].create_item(draft(kind, scope))
    assert isinstance(stored, CosmosDict)
    if scope == "global":
        read = env.helper.read_global_editor_record(kind, stored["id"])
        listed = env.helper.list_global_editor_records(kind)
        env.helper._assert_global_available_name(kind, {**stored, "name": "new_unused_name"}, stored)
        merged = env.helper.read_group_merged_global_record(
            kind, "owner", "group-a", stored["id"], env.services.settings,
        )
        assert isinstance(merged, CosmosDict)
    elif scope == "group":
        read = env.helper.read_group_editor_record(kind, "owner", "group-a", stored["id"], env.services.settings)
        listed = [record for record, _global in env.helper.list_group_editor_records(
            kind, "owner", "group-a", env.services.settings,
        )]
        env.helper._assert_group_available_name(kind, "owner", "group-a", {**stored, "name": "new_unused_name"}, stored)
    else:
        read = env.helper.read_editor_record(kind, "owner", stored["id"], env.services.settings)
        listed = env.helper.list_editor_records(kind, "owner", env.services.settings)
        env.helper._assert_available_name(kind, "owner", {**stored, "name": "new_unused_name"}, stored)
    assert isinstance(read, CosmosDict)
    assert read["_etag"] == stored["_etag"]
    assert len(listed) == 1
    assert type(listed[0]) is dict
    projection = env.helper.project_shared_record(
        read, kind, can_manage=scope != "global", global_scope=scope == "global", group_scope=scope == "group",
    )
    assert "synthetic-sdk-credential" not in str(projection)
    assert read == stored
    with pytest.raises((env.helper.WorkspaceAuthoringConflict, env.helper.WorkspaceAuthoringValidation)):
        if scope == "global":
            env.helper._assert_global_available_name(kind, stored, None)
        elif scope == "group":
            env.helper._assert_group_available_name(kind, "owner", "group-a", stored, None)
        else:
            env.helper._assert_available_name(kind, "owner", stored, None)


@pytest.mark.parametrize("kind", ["agents", "actions"])
@pytest.mark.parametrize("scope", ["personal", "group", "global"])
def test_real_editor_write_owners_preserve_sdk_revisions_and_cleanup(sdk_editors, kind, scope):
    env = sdk_editors
    env.services.settings["enable_key_vault_secret_storage"] = True
    created = save(env, kind, scope, draft(kind, scope))
    assert isinstance(created, CosmosDict)
    path = ("auth", "key") if kind == "actions" else ("azure_openai_gpt_key",)
    reference = created["auth"]["key"] if kind == "actions" else created[path[0]]
    assert env.services.vault[reference] == "synthetic-sdk-credential"
    update = deepcopy(created)
    if kind == "actions":
        update["auth"]["key"] = "synthetic-sdk-replacement"
    else:
        update[path[0]] = "synthetic-sdk-replacement"
    replaced = save(env, kind, scope, update, created)
    assert isinstance(replaced, CosmosDict)
    assert replaced["_etag"] != created["_etag"]
    assert reference in env.services.secret_deletes
    before = deepcopy(env.containers[kind, scope].items)
    with pytest.raises(env.helper.WorkspaceAuthoringConflict):
        save(env, kind, scope, update, created)
    assert env.containers[kind, scope].items == before


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
def test_real_reminder_owner_consumes_sdk_patch_response(sdk_editors, scope):
    env = sdk_editors
    env.services.settings["enable_key_vault_secret_storage"] = True
    record = draft("actions", scope, metadata={"key_vault_secret_reminders": {"__all__": {
        "enabled": True, "expires_on": "2030-01-01", "contact_email": "fixture@example.test",
        "lead_days": 30, "label": "SDK test", "notes": "",
    }}})
    saved = save(env, "actions", scope, record)
    assert isinstance(saved, CosmosDict)
    assert saved["metadata"]["key_vault_secret_reminder_sync"]
    assert env.services.expiration_updates
    container = env.containers["actions", scope]
    partition = saved["id"] if scope == "global" else "group-a" if scope == "group" else "owner"
    current = container.read_item(saved["id"], partition)
    assert current["_etag"] == saved["_etag"]
    assert current["metadata"] == saved["metadata"]


@pytest.mark.parametrize("kind", ["agents", "actions"])
@pytest.mark.parametrize("scope", ["personal", "group", "global"])
def test_real_editor_delete_owners_keep_conditional_sdk_semantics(sdk_editors, kind, scope):
    env = sdk_editors
    stored = save(env, kind, scope, draft(kind, scope))
    container = env.containers[kind, scope]

    def delete(record):
        if scope == "global":
            return env.helper.delete_global_editor_record(kind, "owner", record, env.services.settings)
        if scope == "group":
            return env.helper.delete_group_editor_record(kind, "owner", "group-a", record, env.services.settings)
        return env.helper.delete_editor_record(kind, "owner", record, env.services.settings)

    changed = container.upsert_item({**stored, "description": "Changed elsewhere"})
    assert isinstance(changed, CosmosDict)
    with pytest.raises(env.helper.WorkspaceAuthoringConflict):
        delete(stored)
    assert len(container.items) == 1
    delete(changed)
    assert container.items == {}


def test_agent_migration_owner_retains_plain_scoped_query_records(sdk_editors):
    env = sdk_editors
    namespace = {
        f"cosmos_{scope}_agents_container": env.containers["agents", scope]
        for scope in ("personal", "group", "global")
    }
    for scope in ("personal", "group", "global"):
        env.containers["agents", scope].create_item(draft("agents", scope))
    execute_functions("route_backend_agents.py", {
        "_strip_cosmos_metadata", "_load_all_agent_records_for_default_migration",
    }, namespace)
    records = namespace["_load_all_agent_records_for_default_migration"]()
    assert [record["scope"] for record in records] == ["global", "group", "personal"]
    assert all(type(record["agent"]) is dict for record in records)
    assert all("_etag" not in record["agent"] for record in records)
    assert records[1]["scope_id"] == "group-a"
    assert records[2]["scope_id"] == "owner"
