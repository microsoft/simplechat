# test_agent_credential_owner_runtime.py
"""Real owner CRUD with installed-SDK point responses and credential bindings.

Version: 0.261.428
Implemented in: 0.261.428

The existing isolated services supply policy/cache/Key Vault seams. Containers
retain partition routing, conditional ETags and real CosmosDict point responses.
"""

import ast
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import sys
from typing import Any, Dict, List
from unittest.mock import Mock, patch

import azure.core as sdk_core
import azure.cosmos as sdk_cosmos
from azure.cosmos._cosmos_responses import CosmosDict
import pytest

from agent_credential_contracts import AGENT_CREDENTIAL_BINDINGS, AgentCredentialReentryRequired
from test_support.m365 import CosmosContainer
from test_workspace_authoring_backend import (
    _load_module, agent_payload, environment, module_stub,
)


class AgentCredentialContainer(CosmosContainer):
    """SDK-default container supporting both classic and conditional editor CRUD."""

    def delete_item(self, item, partition_key, *, etag=None, match_condition=None):
        with self.lock:
            current = self.read_item(item, partition_key)
            if etag is not None and (
                current["_etag"] != etag or match_condition != sdk_core.MatchConditions.IfNotModified
            ):
                raise sdk_cosmos.exceptions.CosmosAccessConditionFailedError(status_code=412)
            super().delete_item(item, partition_key)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        rows = list(super().query_items(query, parameters, partition_key, **kwargs))
        values = {entry["name"]: entry["value"] for entry in parameters or []}
        for field in ("user_id", "group_id", "name"):
            if f"@{field}" in values:
                rows = [row for row in rows if row.get(field) == values[f"@{field}"]]
        if "c.is_enabled = true" in query:
            rows = [row for row in rows if row.get("is_enabled", True)]
        return rows

    def patch_item(self, item, partition_key, patch_operations, *, etag, match_condition):
        with self.lock:
            body = dict(self.read_item(item, partition_key))
            for operation in patch_operations:
                if operation["op"] != "set" or operation["path"] != "/metadata/key_vault_secret_reminder_sync":
                    raise AssertionError("Unexpected patch operation.")
                body["metadata"] = {**body.get("metadata", {}), "key_vault_secret_reminder_sync": operation["value"]}
            return self.replace_item(item, body, etag=etag, match_condition=match_condition)


@pytest.fixture
def owners(environment, monkeypatch):
    env = environment
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, {
            "azure.core": sdk_core, "azure.cosmos": sdk_cosmos,
            "azure.cosmos.exceptions": sdk_cosmos.exceptions,
            "functions_chat_bootstrap_cache": module_stub(
                "functions_chat_bootstrap_cache",
                bump_chat_bootstrap_user_cache_version=Mock(),
                bump_chat_bootstrap_global_cache_version=Mock(),
            ),
            "functions_debug": module_stub("functions_debug", debug_print=Mock()),
        }))
        config = env.services.modules["config"]
        containers = {}
        for scope, partition, attribute in (
            ("personal", "user_id", "cosmos_personal_agents_container"),
            ("group", "group_id", "cosmos_group_agents_container"),
            ("global", "id", "cosmos_global_agents_container"),
        ):
            containers[scope] = AgentCredentialContainer(partition)
            stack.enter_context(patch.object(config, attribute, containers[scope], create=True))
        settings_module = env.services.settings_module
        for name in ("update_user_settings", "save_settings"):
            stack.enter_context(patch.object(settings_module, name, Mock(), create=True))
        modules = {
            scope: _load_module(stack, f"functions_{scope}_agents")
            for scope in ("personal", "group", "global")
        }
        env.services.settings["merge_global_semantic_kernel_with_workspace"] = True
        with env.app.app_context():
            yield env, modules, containers


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
@pytest.mark.parametrize("vault_enabled", [False, True])
def test_classic_agent_owner_sdk_contracts(owners, scope, vault_enabled):
    env, modules, containers = owners
    module, container = modules[scope], containers[scope]
    record = agent_payload()
    record["azure_openai_gpt_key"] = "fresh-owner-credential"
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    if scope == "personal":
        saved = module.save_personal_agent("actor", record)
        current = module.get_personal_agent("actor", saved["id"])
        raw = module.get_personal_agent("actor", saved["id"], return_type=env.keyvault.SecretReturnType.NAME)
        listed = module.get_personal_agents("actor")
        remove = lambda: module.delete_personal_agent("actor", saved["id"])
    elif scope == "group":
        saved = module.save_group_agent("group-a", record, user_id="actor")
        current = module.get_group_agent("group-a", saved["id"])
        raw = module.get_group_agent("group-a", saved["id"], return_type=env.keyvault.SecretReturnType.NAME)
        listed = module.get_group_agents("group-a")
        remove = lambda: module.delete_group_agent("group-a", saved["id"])
    else:
        saved = module.save_global_agent(record, user_id="actor")
        assert saved is not None
        current = module.get_global_agent(saved["id"])
        raw = module.get_global_agent(saved["id"], return_type=env.keyvault.SecretReturnType.NAME)
        listed = module.get_global_agents()
        toggled = module.update_global_agent_enabled(saved["id"], False, user_id="actor")
        assert isinstance(toggled, CosmosDict)
        remove = lambda: module.delete_global_agent(saved["id"])
    assert current["azure_openai_gpt_key"] == "Stored_In_KeyVault"
    assert AGENT_CREDENTIAL_BINDINGS not in current
    assert AGENT_CREDENTIAL_BINDINGS in raw
    hydrated = env.keyvault.keyvault_agent_get_helper(
        raw, saved["id"], scope="user" if scope == "personal" else scope,
        owner_id={"personal": "actor", "group": "group-a", "global": "global"}[scope],
        return_type=env.keyvault.SecretReturnType.VALUE,
    )
    assert hydrated["azure_openai_gpt_key"] == "fresh-owner-credential"
    assert len(listed) == 1
    deleted = remove()
    assert deleted
    assert not container.items


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
@pytest.mark.parametrize("vault_enabled", [False, True])
def test_native_agent_owner_sdk_contracts(owners, scope, vault_enabled):
    env, _modules, containers = owners
    helper, settings = env.helper, env.services.settings
    record = agent_payload()
    record["azure_openai_gpt_key"] = "fresh-native-credential"
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    if scope == "personal":
        helper._assert_available_name("agents", "actor", record, None)
        saved = helper.save_editor_record("agents", "actor", record, None, settings)
        current = helper.read_editor_record("agents", "actor", saved["id"], settings)
        listed = helper.list_editor_records("agents", "actor", settings)
        helper.delete_editor_record("agents", "actor", current, settings)
    elif scope == "group":
        helper._assert_group_available_name("agents", "actor", "group-a", record, None)
        saved = helper.save_group_editor_record("agents", "actor", "group-a", record, None, settings)
        current = helper.read_group_editor_record("agents", "actor", "group-a", saved["id"], settings)
        listed = helper.list_group_editor_records("agents", "actor", "group-a", settings)
        helper.delete_group_editor_record("agents", "actor", "group-a", current, settings)
    else:
        helper._assert_global_available_name("agents", record, None)
        saved = helper.save_global_editor_record("agents", "actor", record, None, settings)
        current = helper.read_global_editor_record("agents", saved["id"])
        listed = helper.list_global_editor_records("agents")
        helper.read_group_merged_global_record("agents", "actor", "group-a", saved["id"], settings)
        helper.delete_global_editor_record("agents", "actor", current, settings)
    assert isinstance(saved, CosmosDict)
    assert isinstance(current, CosmosDict)
    assert listed
    assert not containers[scope].items


def test_native_reminder_patch_preserves_sdk_response_and_etag(owners, monkeypatch):
    env, _modules, _containers = owners
    container = AgentCredentialContainer("user_id")
    monkeypatch.setattr(env.services.modules["config"], "cosmos_personal_actions_container", container)
    env.services.settings["enable_key_vault_secret_storage"] = True
    saved = container.create_item({
        "id": "action", "user_id": "actor", "name": "action",
        "auth": {"key": "actor--action--user--action"},
        "metadata": {"key_vault_secret_reminders": {"auth.key": {"enabled": True}}},
    })

    def sync(updated, *args):
        updated["metadata"]["key_vault_secret_reminder_sync"] = {"auth.key": {"status": "synced"}}

    monkeypatch.setattr(env.keyvault, "_sync_plugin_secret_reminder", sync)
    updated = env.helper._sync_editor_reminders(saved, "actions", "actor", env.services.settings)
    assert isinstance(updated, CosmosDict)
    assert updated["_etag"] != saved["_etag"]
    assert updated["metadata"]["key_vault_secret_reminder_sync"]["auth.key"]["status"] == "synced"


def test_foundry_chat_upload_query_owner_contract(environment, monkeypatch):
    """The unchanged Foundry query owner consumes ordinary mapping query rows."""
    app = Path(__file__).resolve().parents[1] / "application" / "single_app"
    tree = ast.parse((app / "foundry_agent_runtime.py").read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_collect_recent_chat_upload_file_inputs")
    container = Mock()
    container.query_items.return_value = [{
        "id": "upload", "filename": "sample.txt", "blob_container": "files",
        "blob_path": "sample", "metadata": {"is_user_upload": True},
    }]
    monkeypatch.setattr(environment.services.modules["config"], "cosmos_messages_container", container, raising=False)
    append = Mock()
    namespace = {"List": List, "Dict": Dict, "Any": Any, "log_event": Mock(), "_append_foundry_file_input": append}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "foundry_agent_runtime.py", "exec"), namespace)
    namespace["_collect_recent_chat_upload_file_inputs"](
        conversation_id="chat", file_inputs=[], file_metadata=[], seen_sources=set(), max_files=3, max_file_bytes=1024,
    )
    append.assert_called_once()
    assert append.call_args.kwargs["file_name"] == "sample.txt"
    assert container.query_items.call_args.kwargs["partition_key"] == "chat"


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
@pytest.mark.parametrize("collection", [False, True])
def test_classic_owner_value_reads_surface_reentry_instead_of_missing_records(owners, scope, collection):
    env, modules, containers = owners
    record = agent_payload()
    record["azure_openai_gpt_key"] = "unversioned-legacy-value"
    if scope == "personal":
        record["user_id"] = "actor"
    elif scope == "group":
        record["group_id"] = "group-a"
    containers[scope].create_item(record)
    module = modules[scope]
    with pytest.raises(AgentCredentialReentryRequired):
        if scope == "personal":
            if collection:
                module.get_personal_agents("actor", return_type=env.keyvault.SecretReturnType.VALUE)
            else:
                module.get_personal_agent("actor", record["id"], return_type=env.keyvault.SecretReturnType.VALUE)
        elif scope == "group":
            if collection:
                module.get_group_agents("group-a", return_type=env.keyvault.SecretReturnType.VALUE)
            else:
                module.get_group_agent("group-a", record["id"], return_type=env.keyvault.SecretReturnType.VALUE)
        elif collection:
            module.get_global_agents(return_type=env.keyvault.SecretReturnType.VALUE)
        else:
            module.get_global_agent(record["id"], return_type=env.keyvault.SecretReturnType.VALUE)
    assert env.services.secret_reads == []
