# test_workspace_authoring_persistence.py
"""Editor persistence across real SDK retries and classic personal-agent flows.

Version: 0.261.096
Implemented in: 0.261.096

The installed Cosmos ConnectionRetryPolicy executes against a fake HTTP
transport. Classic routes and personal persistence helpers execute unchanged
against the existing fake Cosmos/Key Vault services.
"""

import json
import sys
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import Mock, patch

from azure.core.exceptions import ResourceNotFoundError, ServiceResponseError
from azure.core.pipeline import Pipeline
from azure.core.pipeline.transport import HttpRequest, HttpResponse, HttpTransport
from azure.cosmos import exceptions as sdk_exceptions
from azure.cosmos._retry_utility import ConnectionRetryPolicy
import pytest

from test_support.agent_delegation import (
    CosmosHttpResponseError as HarnessCosmosHttpResponseError,
    CosmosResourceNotFoundError,
    execute_functions,
    module_stub,
)
from test_workspace_authoring_backend import (
    _load_module,
    action_payload,
    agent_payload,
    create,
    environment,
    patch_record,
)


class RetryResponse(HttpResponse):
    def __init__(self, request, status):
        super().__init__(request, None)
        self.status_code = status
        self.headers = {"content-type": "application/json"}
        self.reason = "Precondition Failed"
        self.content_type = "application/json"

    def body(self):
        return b'{"message":"The original ETag no longer matches."}'

    def text(self, encoding=None):
        return self.body().decode(encoding or "utf-8")


class CommitThenLoseResponseTransport(HttpTransport):
    def __init__(self, replace):
        self.replace = replace
        self.requests = []

    def open(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, request, **kwargs):
        self.requests.append((request.method, request.headers.get("If-Match")))
        try:
            self.replace(request)
        except HarnessCosmosHttpResponseError as exc:
            return RetryResponse(request, exc.status_code)
        raise ServiceResponseError("Connection dropped after the server committed the conditional PUT.")


@pytest.mark.parametrize("kind,field", [
    ("agents", "azure_openai_gpt_key"),
    ("plugins", "key"),
])
def test_real_cosmos_retry_keeps_credentials_after_committed_put_returns_412(environment, kind, field):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    draft = agent_payload() if kind == "agents" else action_payload()
    if kind == "agents":
        draft[field] = "initial-credential"
    resource = create(env, kind, draft)
    stored_kind = "agents" if kind == "agents" else "actions"
    records = env.services.records[stored_kind, "personal"]
    key = ("actor", resource["record"]["id"])
    container = env.services.containers[stored_kind, "personal"]
    original_replace = container.replace_item.side_effect
    retry_requests = []

    def retrying_replace(**kwargs):
        transport = CommitThenLoseResponseTransport(lambda request: original_replace(**{
            **kwargs,
            "etag": request.headers["If-Match"],
            "body": json.loads(request.body),
        }))
        policy = ConnectionRetryPolicy(retry_total=1, retry_read=1, retry_backoff_factor=0)
        pipeline = Pipeline(transport=transport, policies=[policy])
        request = HttpRequest(
            "PUT", "https://cosmos.example.test/dbs/test/colls/records/docs/owned-record",
            headers={"If-Match": kwargs["etag"], "Content-Type": "application/json"},
            data=json.dumps(kwargs["body"]),
        )
        response = pipeline.run(request)
        retry_requests.extend(transport.requests)
        assert response.http_response.status_code == 412
        raise sdk_exceptions.CosmosAccessConditionFailedError(
            message=response.http_response.text(), response=response.http_response,
        )

    container.replace_item.side_effect = retrying_replace
    updates = {field: "committed-replacement"} if kind == "agents" else {"auth": {field: "committed-replacement"}}
    env.services.secret_deletes.clear()
    with patch.dict(sys.modules, {"azure.cosmos.exceptions": sdk_exceptions}):
        result = patch_record(env, kind, resource, updates)
    assert result.status_code == 409, result.get_json()
    assert retry_requests == [("PUT", resource["revision"]), ("PUT", resource["revision"])]
    committed = records[key]
    reference = committed[field] if kind == "agents" else committed["auth"][field]
    assert env.services.vault[reference] == "committed-replacement"
    assert reference not in env.services.secret_deletes
    assert committed["_etag"] != resource["revision"]
    reloaded = env.client.get(f"/api/user/{kind}/{resource['record']['id']}?view=editor")
    assert reloaded.status_code == 200
    assert reloaded.get_json()["revision"] == committed["_etag"]
    assert "committed-replacement" not in json.dumps(reloaded.get_json())


@pytest.fixture
def classic_environment(environment):
    env = environment
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, {
            "functions_debug": module_stub("functions_debug", debug_print=Mock()),
        }))
        personal = _load_module(stack, "functions_personal_agents")
        container = env.services.containers["agents", "personal"]
        conditional_delete = container.delete_item.side_effect
        records = env.services.records["agents", "personal"]

        def upsert_item(*, body):
            env.services.sequence += 1
            result = deepcopy(body)
            result["_etag"] = f'"classic-{env.services.sequence}"'
            records[result["user_id"], result["id"]] = result
            env.services.writes.append(("classic-upsert", "agents", deepcopy(result)))
            return deepcopy(result)

        def delete_item(*, item, partition_key, **kwargs):
            if kwargs:
                return conditional_delete(item=item, partition_key=partition_key, **kwargs)
            key = (partition_key, item)
            if key not in records:
                raise CosmosResourceNotFoundError()
            env.services.writes.append(("classic-delete", "agents", item))
            records.pop(key)

        container.upsert_item.side_effect = upsert_item
        container.delete_item.side_effect = delete_item
        env.namespace.update({
            "get_personal_agents": personal.get_personal_agents,
            "save_personal_agent": personal.save_personal_agent,
            "delete_personal_agent": personal.delete_personal_agent,
            **{
                name: getattr(env.services.activity, name)
                for name in ("log_agent_creation", "log_agent_update", "log_agent_deletion")
            },
        })
        execute_functions("route_backend_agents.py", {"_create_personal_agent"}, env.namespace)
        # Key Vault really returns 404 for an invented/deleted name. The normal
        # fixture's permissive deletion would hide reconstruction of a legacy name.
        original_delete = env.keyvault.SecretClient.begin_delete_secret

        def delete_existing_secret(client, name):
            if name not in env.services.vault:
                raise ResourceNotFoundError("Key Vault secret not found.", status_code=404)
            return original_delete(client, name)

        stack.enter_context(patch.object(env.keyvault.SecretClient, "begin_delete_secret", delete_existing_secret))
        env.personal_agents = personal
        yield env


def _agent_with_secret(apim=False):
    draft = agent_payload()
    field = "azure_agent_apim_gpt_subscription_key" if apim else "azure_openai_gpt_key"
    draft["enable_agent_gpt_apim"] = apim
    draft[field] = "initial-agent-credential"
    return draft, field


@pytest.mark.parametrize("apim", [False, True])
@pytest.mark.parametrize("save_method", ["patch", "collection"])
@pytest.mark.parametrize("delete_method", ["item", "name", "collection"])
def test_editor_agent_secrets_survive_classic_reads_saves_and_removal(classic_environment, apim, save_method, delete_method):
    env = classic_environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    draft, field = _agent_with_secret(apim)
    resource = create(env, "agents", draft)
    replaced = patch_record(env, "agents", resource, {field: "rotated-agent-credential"})
    assert replaced.status_code == 200, replaced.get_json()
    agent_id = resource["record"]["id"]
    stored = env.services.records["agents", "personal"]["actor", agent_id]
    actual_reference = stored[field]
    assert "--editor-" in actual_reference
    classic = env.client.get(f"/api/user/agents/{agent_id}")
    assert classic.status_code == 200
    assert classic.get_json()[field] == env.keyvault.ui_trigger_word
    env.services.secret_writes.clear()
    if save_method == "patch":
        saved = env.client.patch(f"/api/user/agents/{agent_id}", json=classic.get_json())
    else:
        collection = env.client.get("/api/user/agents").get_json()
        saved = env.client.post("/api/user/agents", json=collection)
    assert saved.status_code == 200, saved.get_json()
    assert env.services.records["agents", "personal"]["actor", agent_id][field] == actual_reference
    assert env.services.vault[actual_reference] == "rotated-agent-credential"
    assert env.services.secret_writes == []
    if delete_method == "collection":
        deleted = env.client.post("/api/user/agents", json=[])
    else:
        identifier = agent_id if delete_method == "item" else draft["name"]
        deleted = env.client.delete(f"/api/user/agents/{identifier}")
    assert deleted.status_code == 200, deleted.get_json()
    assert ("actor", agent_id) not in env.services.records["agents", "personal"]
    assert actual_reference in env.services.secret_deletes
    assert actual_reference not in env.services.vault


def test_classic_create_then_editor_replace_then_classic_rename_preserves_actual_reference(classic_environment):
    env = classic_environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    draft, field = _agent_with_secret()
    classic_created = env.client.post("/api/user/agents", json=draft)
    assert classic_created.status_code == 201, classic_created.get_json()
    detail = env.client.get(f"/api/user/agents/{draft['id']}?view=editor").get_json()
    changed = patch_record(env, "agents", detail, {field: "editor-rotated-credential"})
    assert changed.status_code == 200, changed.get_json()
    reference = env.services.records["agents", "personal"]["actor", draft["id"]][field]
    classic = env.client.get(f"/api/user/agents/{draft['id']}").get_json()
    classic["name"] = "renamed_classically"
    env.services.secret_writes.clear()
    renamed = env.client.post("/api/user/agents", json=[classic])
    assert renamed.status_code == 200, renamed.get_json()
    assert env.services.records["agents", "personal"]["actor", draft["id"]][field] == reference
    assert env.services.secret_writes == []
    deleted = env.client.delete("/api/user/agents/renamed_classically")
    assert deleted.status_code == 200, deleted.get_json()
    assert reference not in env.services.vault


def test_classic_agent_cleanup_uses_only_the_current_users_stored_references(classic_environment):
    env = classic_environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    draft, field = _agent_with_secret()
    resource = create(env, "agents", draft)
    owner_reference = env.services.records["agents", "personal"]["actor", draft["id"]][field]
    other_reference = env.keyvault.build_full_secret_name("editor-other-user", draft["id"], "agent", "user")
    env.services.vault[other_reference] = "another-users-credential"
    other = env.services.add("agents", "personal", "other-user", {
        **draft, field: other_reference,
    })
    response = env.client.delete(f"/api/user/agents/{resource['record']['id']}")
    assert response.status_code == 200, response.get_json()
    assert owner_reference not in env.services.vault
    assert env.services.vault[other_reference] == "another-users-credential"
    assert env.services.records["agents", "personal"]["other-user", draft["id"]] == other


def test_staging_failure_before_any_cosmos_write_can_clean_up_its_fresh_secret(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    resource = create(env, "plugins", action_payload())
    original = deepcopy(env.services.records)
    staged_reference = env.keyvault.build_full_secret_name("editor-uncommitted", "actor", "action", "user")

    def fail_staging(record, kind, user_id, settings, staged):
        env.services.vault[staged_reference] = "uncommitted-credential"
        staged.append(staged_reference)
        raise RuntimeError("Key Vault rejected a subsequent secret.")

    container = env.services.containers["actions", "personal"]
    container.replace_item.reset_mock()
    with patch.object(env.helper, "_stage_editor_secrets", side_effect=fail_staging):
        response = patch_record(env, "plugins", resource, {"auth": {"key": "replacement"}})
    assert response.status_code == 503
    container.replace_item.assert_not_called()
    assert staged_reference not in env.services.vault
    assert env.services.records == original


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
