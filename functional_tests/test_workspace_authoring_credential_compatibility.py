# test_workspace_authoring_credential_compatibility.py
"""Regression coverage for conditional editor writes and classic credential cleanup.

Version: 0.261.270
Implemented in: 0.261.096
Classic global agent delete of an editor-keyed credential: 0.261.270

The real editor and classic functions share isolated Cosmos/Key Vault services.
Lost write responses must not delete committed credentials, and classic operations
must use the actual stored references created by the V2 staging path.
"""

import logging
import sys
import traceback
import uuid
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from azure.core.exceptions import ServiceResponseError
from azure.core.pipeline import PipelineContext, PipelineRequest, PipelineResponse
from azure.core.pipeline.transport import HttpRequest
from azure.cosmos._retry_utility import ConnectionRetryPolicy

from test_support.agent_delegation import CosmosHttpResponseError, execute_functions
from test_workspace_authoring_backend import (
    action_payload,
    agent_payload,
    create,
    environment,
    patch_record,
    write_payload,
)


@pytest.mark.parametrize("kind,route_kind", [("agents", "agents"), ("actions", "plugins")])
@pytest.mark.parametrize("operation", ["create", "replace"])
def test_committed_write_followed_by_sdk_conflict_retains_its_credentials(environment, kind, route_kind, operation):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    draft = agent_payload() if kind == "agents" else action_payload()
    if kind == "agents":
        draft["azure_openai_gpt_key"] = "initial-test-credential"
    path = ("azure_openai_gpt_key",) if kind == "agents" else ("auth", "key")
    container = env.services.containers[kind, "personal"]

    if operation == "replace":
        original = create(env, route_kind, draft)
        replace = container.replace_item.side_effect

        def commit_then_conflict(**kwargs):
            replace(**kwargs)
            raise CosmosHttpResponseError(412)

        container.replace_item.side_effect = commit_then_conflict
        updates = {"azure_openai_gpt_key": "replacement-test-credential"} if kind == "agents" else {
            "auth": {"key": "replacement-test-credential"},
        }
        response = patch_record(env, route_kind, original, updates)
        expected_value = "replacement-test-credential"
    else:
        create_item = container.create_item.side_effect

        def commit_then_conflict(**kwargs):
            create_item(**kwargs)
            raise CosmosHttpResponseError(409)

        container.create_item.side_effect = commit_then_conflict
        response = env.client.post(f"/api/user/{route_kind}?view=editor", json=write_payload(draft))
        expected_value = "initial-test-credential" if kind == "agents" else "test-credential"

    assert response.status_code == 409
    committed = next(iter(env.services.records[kind, "personal"].values()))
    reference = committed
    for segment in path:
        reference = reference[segment]
    assert env.services.vault[reference] == expected_value
    assert reference not in env.services.secret_deletes
    assert expected_value not in response.get_data(as_text=True)


def test_real_sdk_retry_preserves_potentially_committed_credentials(environment):
    """Run the installed SDK retry policy, not just a directly injected 412."""
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    resource = create(env, "plugins", action_payload())
    container = env.services.containers["actions", "personal"]
    conditional_replace = container.replace_item.side_effect
    attempts = []

    def replace_with_sdk_retry(**kwargs):
        request = PipelineRequest(
            HttpRequest("PUT", "https://example.invalid/offline"),
            PipelineContext(Mock()),
        )
        request.http_request.headers["If-Match"] = kwargs["etag"]
        policy = ConnectionRetryPolicy(retry_backoff_factor=0)

        def send(pipeline_request):
            attempts.append(pipeline_request.http_request.headers["If-Match"])
            try:
                conditional_replace(**{
                    **kwargs, "etag": pipeline_request.http_request.headers["If-Match"],
                })
            except CosmosHttpResponseError as exc:
                return PipelineResponse(
                    pipeline_request.http_request,
                    SimpleNamespace(status_code=exc.status_code, headers={}),
                    pipeline_request.context,
                )
            raise ServiceResponseError("Offline: response lost after commit")

        policy.next = SimpleNamespace(send=send)
        response = policy.send(request)
        raise CosmosHttpResponseError(response.http_response.status_code)

    container.replace_item.side_effect = replace_with_sdk_retry
    response = patch_record(env, "plugins", resource, {
        "auth": {"key": "offline-committed-replacement"},
    })
    stored = env.services.records["actions", "personal"]["actor", resource["record"]["id"]]
    reference = stored["auth"]["key"]
    assert attempts == [resource["revision"], resource["revision"]]
    assert response.status_code == 409
    assert env.services.vault[reference] == "offline-committed-replacement"
    assert reference not in env.services.secret_deletes


def _wire_classic_agent_functions(env):
    container = env.services.containers["agents", "personal"]
    namespace = {
        "cosmos_personal_agents_container": container,
        "exceptions": sys.modules["azure.cosmos.exceptions"],
        "SecretReturnType": env.keyvault.SecretReturnType,
        "keyvault_agent_get_helper": env.keyvault.keyvault_agent_get_helper,
        "keyvault_agent_save_helper": env.keyvault.keyvault_agent_save_helper,
        "keyvault_agent_delete_helper": env.keyvault.keyvault_agent_delete_helper,
        "sanitize_agent_payload": env.namespace["sanitize_agent_payload"],
        "validate_agent_delegation_bindings": env.namespace["validate_agent_delegation_bindings"],
        "ensure_governance_access": env.services.governance.ensure_governance_access,
        "bump_chat_bootstrap_user_cache_version": Mock(),
        "debug_print": Mock(),
        "datetime": datetime,
    }
    names = {"get_personal_agent", "get_personal_agents", "save_personal_agent", "delete_personal_agent"}
    execute_functions("functions_personal_agents.py", names, namespace)
    env.namespace.update({name: namespace[name] for name in names})
    for operation in ("creation", "update", "deletion"):
        env.namespace[f"log_agent_{operation}"] = getattr(env.services.activity, f"log_agent_{operation}")

    def upsert_item(*, body):
        stored = {**deepcopy(body), "_etag": '"classic-edit"'}
        assert stored["user_id"] == "actor"
        env.services.records["agents", "personal"]["actor", stored["id"]] = stored
        return deepcopy(stored)

    def delete_item(*, item, partition_key):
        assert partition_key == "actor"
        del env.services.records["agents", "personal"][partition_key, item]

    container.upsert_item.side_effect = upsert_item
    container.delete_item.side_effect = delete_item
    return namespace


@pytest.mark.parametrize("delete_mode", ["id", "name", "collection"])
@pytest.mark.parametrize("replace_secret", [False, True])
def test_classic_edit_and_delete_preserve_then_clean_actual_editor_reference(environment, delete_mode, replace_secret):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    draft = {**agent_payload(), "azure_openai_gpt_key": "original-test-credential"}
    resource = create(env, "agents", draft)
    if replace_secret:
        response = patch_record(env, "agents", resource, {"azure_openai_gpt_key": "replaced-test-credential"})
        assert response.status_code == 200
        resource = response.get_json()
    agent_id = resource["record"]["id"]
    records = env.services.records["agents", "personal"]
    stored_reference = records["actor", agent_id]["azure_openai_gpt_key"]
    assert "editor-" in stored_reference
    expected_secret = env.services.vault[stored_reference]
    _wire_classic_agent_functions(env)

    read = env.client.get(f"/api/user/agents/{agent_id}")
    assert read.status_code == 200
    assert read.get_json()["azure_openai_gpt_key"] == "Stored_In_KeyVault"
    saved = env.client.patch(f"/api/user/agents/{agent_id}", json={"description": "Edited in classic"})
    assert saved.status_code == 200, saved.get_json()
    assert records["actor", agent_id]["azure_openai_gpt_key"] == stored_reference
    assert env.services.vault[stored_reference] == expected_secret

    def strict_delete(_client, name):
        if name not in env.services.vault:
            error = LookupError("The requested test secret does not exist.")
            error.status_code = 404
            raise error
        env.services.secret_deletes.append(name)
        del env.services.vault[name]

    with patch.object(env.keyvault.SecretClient, "begin_delete_secret", strict_delete):
        if delete_mode == "collection":
            deleted = env.client.post("/api/user/agents", json=[])
        else:
            identifier = agent_id if delete_mode == "id" else draft["name"]
            deleted = env.client.delete(f"/api/user/agents/{identifier}")
        assert deleted.status_code == 200, deleted.get_json()
    assert ("actor", agent_id) not in records
    assert stored_reference in env.services.secret_deletes
    assert stored_reference not in env.services.vault


def test_classic_global_delete_removes_the_editor_reference_it_holds(environment):
    """The classic admin route deletes a global agent whose key the V2 editor stored.

    The V2 global editor names a credential afresh (``{id}--agent--global--editor-...``).
    The classic delete used to read the agent masked and rebuild the classic name from
    the placeholder, so on a vault without that name it failed: the agent could not be
    deleted, and its real credential would have been left behind.
    """
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    agent_id = str(uuid.uuid4())
    record = {
        **agent_payload(), "id": agent_id, "is_global": True, "is_group": False,
        "azure_openai_gpt_key": "global-test-credential",
    }
    staged = []
    env.helper._stage_editor_secrets(record, "agents", "admin", env.services.settings, staged, global_scope=True)
    reference = record["azure_openai_gpt_key"]
    assert staged == [reference]
    assert reference.startswith(f"{agent_id}--agent--global--editor-")
    assert env.services.vault[reference] == "global-test-credential"

    records = env.services.records["agents", "global"]
    records[agent_id, agent_id] = {**deepcopy(record), "_etag": '"stored"'}
    container = env.services.containers["agents", "global"]
    deleted = []

    def delete_item(*, item, partition_key):
        assert partition_key == item, "Global agents are partitioned by their own id."
        deleted.append(item)
        del records[partition_key, item]

    container.delete_item.side_effect = delete_item
    namespace = {
        "cosmos_global_agents_container": container,
        "keyvault_agent_get_helper": env.keyvault.keyvault_agent_get_helper,
        "keyvault_agent_delete_helper": env.keyvault.keyvault_agent_delete_helper,
        "get_current_user_id": lambda: "admin",
        "bump_chat_bootstrap_global_cache_version": Mock(),
        "log_event": Mock(),
        "logging": logging,
        "traceback": traceback,
    }
    execute_functions("functions_global_agents.py", {"get_global_agent", "delete_global_agent"}, namespace)
    # The classic list and editor still see only the placeholder.
    assert namespace["get_global_agent"](agent_id)["azure_openai_gpt_key"] == "Stored_In_KeyVault"

    def strict_delete(_client, name):
        if name not in env.services.vault:
            error = LookupError("The requested test secret does not exist.")
            error.status_code = 404
            raise error
        env.services.secret_deletes.append(name)
        del env.services.vault[name]

    with patch.object(env.keyvault.SecretClient, "begin_delete_secret", strict_delete):
        assert namespace["delete_global_agent"](agent_id) is True
    assert deleted == [agent_id]
    assert env.services.secret_deletes == [reference]
    assert reference not in env.services.vault
