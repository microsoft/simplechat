# test_workspace_authoring_backend.py
"""Executable contracts for native personal agent/action authoring.

Version: 0.261.096
Implemented in: 0.261.096

Real Flask route definitions, validators, payload normalizers, Key Vault helpers,
and conditional-write code run against scoped in-memory Cosmos/Key Vault seams.
No application startup, provider invocation, or live Azure resource is required.
"""

import importlib.util
import json
import logging
import re
import sys
import uuid
from contextlib import ExitStack
from copy import deepcopy
from functools import wraps
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from flask import Blueprint, Flask, jsonify, request, session

from test_support.agent_delegation import (
    APP_ROOT,
    CosmosHttpResponseError,
    MatchConditions,
    delegation_environment,
    execute_functions,
    module_stub,
    reference,
)


MASK = "***REDACTED***"
CURRENT_TYPES = sorted({
    path.stem.removesuffix("_plugin")
    for path in (APP_ROOT / "semantic_kernel_plugins").glob("*_plugin.py")
    if path.stem != "base_plugin"
})


def _load_module(stack, name, relative_path=None):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / (relative_path or f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    stack.enter_context(patch.dict(sys.modules, {name: module}))
    spec.loader.exec_module(module)
    return module


def _install_conditional_cosmos(services):
    services.writes = []
    services.sequence = 0
    services.before_replace = None

    def container_functions(kind, scope):
        records = services.records[kind, scope]

        def query_items(*, query, parameters=None, partition_key=None, **kwargs):
            values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
            result = []
            for (partition, _), record in records.items():
                if partition_key and partition != partition_key:
                    continue
                user_id = values.get("@user_id", values.get("@scope_id"))
                if user_id and record.get("user_id" if scope == "personal" else "group_id") != user_id:
                    continue
                if "@type" in values and record.get("type") != values["@type"]:
                    continue
                if "@name" in values:
                    name, expected = record.get("name", ""), values["@name"]
                    if (name.lower() != expected.lower()) if "STRINGEQUALS" in query else (name != expected):
                        continue
                result.append(deepcopy(record))
            return result

        def store(body):
            services.sequence += 1
            result = deepcopy(body)
            result["_etag"] = f'"revision-{services.sequence}"'
            partition = result["id"] if scope == "global" else result["user_id" if scope == "personal" else "group_id"]
            records[partition, result["id"]] = result
            return deepcopy(result)

        def create_item(*, body):
            assert scope == "personal"
            key = (body["user_id"], body["id"])
            if key in records:
                raise CosmosHttpResponseError(409)
            services.writes.append(("create", kind, deepcopy(body)))
            return store(body)

        def replace_item(*, item, body, etag, match_condition):
            assert match_condition is MatchConditions.IfNotModified
            assert scope == "personal"
            key = (body["user_id"], item)
            if services.before_replace:
                callback, services.before_replace = services.before_replace, None
                callback(records, key)
            current = records.get(key)
            if not current or current.get("_etag") != etag:
                raise CosmosHttpResponseError(412)
            assert body["id"] == item
            services.writes.append(("replace", kind, deepcopy(body)))
            return store(body)

        def delete_item(*, item, partition_key, etag, match_condition):
            assert match_condition is MatchConditions.IfNotModified
            key = (partition_key, item)
            if records[key].get("_etag") != etag:
                raise CosmosHttpResponseError(412)
            services.writes.append(("delete", kind, item))
            records.pop(key)

        def patch_item(*, item, partition_key, patch_operations, etag, match_condition):
            assert match_condition is MatchConditions.IfNotModified
            current = records[partition_key, item]
            if current.get("_etag") != etag:
                raise CosmosHttpResponseError(412)
            updated = deepcopy(current)
            for operation in patch_operations:
                assert operation["path"] == "/metadata/key_vault_secret_reminder_sync"
                updated["metadata"]["key_vault_secret_reminder_sync"] = operation["value"]
            services.writes.append(("patch", kind, deepcopy(updated)))
            return store(updated)

        return query_items, create_item, replace_item, delete_item, patch_item

    for (kind, scope), container in services.containers.items():
        query, create, replace, delete, patch_record = container_functions(kind, scope)
        container.query_items.side_effect = query
        container.create_item.side_effect = create
        container.replace_item.side_effect = replace
        container.delete_item.side_effect = delete
        container.patch_item.side_effect = patch_record
        container.upsert_item.side_effect = AssertionError("Editor writes must never upsert.")


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_ROOT))
    with delegation_environment() as (delegation, services), ExitStack() as stack:
        services.settings.update({
            "per_user_semantic_kernel": True, "enable_user_workspace": True,
            "allow_personal_ai_foundry_agents": True, "allow_personal_new_foundry_agents": True,
            "allow_user_custom_endpoints": True, "enable_key_vault_secret_storage": False,
            "key_vault_name": "test-only-vault", "enable_time_plugin": True,
        })
        services.denied_types = set()
        services.denied_endpoints = set()

        def check_type(feature, user_id, action_type, scope):
            services.check_action_type(feature, user_id, action_type, scope)
            if action_type in services.denied_types:
                raise PermissionError("private denied type diagnostic")

        services.governance.ensure_action_type_access.side_effect = check_type
        services.governance.is_action_scope_access_allowed = Mock(
            side_effect=lambda feature, user_id, scope: feature not in services.denied_features,
        )
        services.governance.is_action_type_access_allowed = Mock(
            side_effect=lambda feature, user_id, action_type, scope: feature not in services.denied_features and action_type not in services.denied_types,
        )
        services.governance.filter_governed_model_endpoints = Mock(
            side_effect=lambda user_id, endpoints, feature: [
                endpoint for endpoint in endpoints if endpoint["id"] not in services.denied_endpoints
            ],
        )
        _install_conditional_cosmos(services)
        services.vault = {}
        services.secret_writes = []
        services.secret_reads = []
        services.secret_deletes = []
        services.expiration_updates = []

        class SecretClient:
            def __init__(self, **kwargs):
                pass

            def set_secret(self, name, value):
                services.secret_writes.append((name, value))
                services.vault[name] = value
                return SimpleNamespace(value=value, id=f"https://test-only-vault.vault.azure.net/secrets/{name}/version")

            def get_secret(self, name, version=None):
                services.secret_reads.append(name)
                return SimpleNamespace(value=services.vault[name], id=f"https://test-only-vault.vault.azure.net/secrets/{name}/version")

            def begin_delete_secret(self, name):
                services.secret_deletes.append(name)
                services.vault.pop(name, None)

            def update_secret_properties(self, name, expires_on=None):
                services.expiration_updates.append((name, expires_on))

        services.modules["config"].KEY_VAULT_DOMAIN = ".vault.azure.net"
        services.modules["config"].SECRET_KEY = "test-only-not-a-production-credential"
        services.appinsights.sanitize_log_message = lambda message: message
        services.appinsights.debug_print = Mock()
        for prefix in ("agent", "action"):
            for operation in ("creation", "update", "deletion"):
                setattr(services.activity, f"log_{prefix}_{operation}", Mock())

        identities = module_stub(
            "functions_workspace_identities", validate_action_identity_reference=Mock(),
            hydrate_action_identity_reference=Mock(),
        )
        reminder = module_stub(
            "functions_keyvault_reminders",
            mark_key_vault_secret_reminder_disabled=Mock(),
            resolve_key_vault_secret_reminder_config=lambda record, path: (
                record.get("metadata", {}).get("key_vault_secret_reminders", {}).get(".".join(path))
                or record.get("metadata", {}).get("key_vault_secret_reminders", {}).get("__all__")
            ),
            upsert_key_vault_secret_reminder=Mock(),
        )
        stubs = {
            "functions_agent_delegation": delegation,
            "functions_authentication": module_stub("functions_authentication", get_current_user_id=lambda: "actor"),
            "functions_workspace_identities": identities,
            "functions_keyvault_reminders": reminder,
            "app_settings_cache": module_stub("app_settings_cache", get_settings_cache=lambda: deepcopy(services.settings)),
            "azure.identity": module_stub("azure.identity", DefaultAzureCredential=Mock()),
            "azure.keyvault": module_stub("azure.keyvault"),
            "azure.keyvault.secrets": module_stub("azure.keyvault.secrets", SecretClient=SecretClient),
            "semantic_kernel": module_stub("semantic_kernel"),
            "semantic_kernel.functions": module_stub("semantic_kernel.functions", kernel_function=lambda **kwargs: lambda function: function),
            "semantic_kernel_plugins.plugin_invocation_logger": module_stub(
                "semantic_kernel_plugins.plugin_invocation_logger", plugin_function_logger=lambda *args, **kwargs: lambda function: function,
            ),
            "functions_simplechat_operations": module_stub(
                "functions_simplechat_operations", SIMPLECHAT_PLUGIN_TYPE="simplechat",
                SIMPLECHAT_DEFAULT_ENDPOINT="simplechat://internal",
            ),
            "functions_azure_maps": module_stub(
                "functions_azure_maps", AZURE_MAPS_PLUGIN_TYPE="azure_maps_openlayers",
                AZURE_MAPS_DEFAULT_ENDPOINT="https://atlas.microsoft.com",
            ),
        }
        stack.enter_context(patch.dict(sys.modules, stubs))
        modules = [stubs["functions_simplechat_operations"], stubs["functions_azure_maps"]]
        for name in (
            "functions_mcp_operations", "functions_snowflake_operations", "functions_yamcs_operations",
            "functions_databricks_operations", "functions_tableau_operations", "functions_blob_storage_operations",
            "functions_chart_operations", "functions_msgraph_operations",
            "functions_azure_endpoint_validation", "functions_icon_utils",
        ):
            modules.append(_load_module(stack, name))
        rocks = _load_module(stack, "semantic_kernel_plugins.rocksdb_plugin", r"semantic_kernel_plugins\rocksdb_plugin.py")
        modules.append(rocks)
        modules.append(_load_module(stack, "semantic_kernel_plugins.sql_odbc_utils", r"semantic_kernel_plugins\sql_odbc_utils.py"))
        keyvault = _load_module(stack, "functions_keyvault")
        schema = _load_module(stack, "json_schema_validation")
        payload = _load_module(stack, "functions_agent_payload")
        health = _load_module(stack, "semantic_kernel_plugins.plugin_health_checker", r"semantic_kernel_plugins\plugin_health_checker.py")
        authoring = _load_module(stack, "functions_workspace_authoring")
        # Execute the actual settings sanitizer without application startup.
        settings_namespace = {
            "TABULAR_GENERATION_BACKEND_SETTING_KEYS": set(),
            "get_public_workspace_label_context": lambda values: {},
            "sanitize_model_endpoints_for_frontend": lambda values: [
                {**deepcopy(value), "auth": {key: item for key, item in value.get("auth", {}).items() if key not in {"api_key", "client_secret"}}}
                for value in values
            ],
        }
        execute_functions("functions_settings.py", {"sanitize_settings_for_user"}, settings_namespace)
        services.settings_module.sanitize_settings_for_user = Mock(
            side_effect=settings_namespace["sanitize_settings_for_user"],
        )

        app = Flask("workspace_editor_backend", root_path=str(APP_ROOT))
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-signing")
        namespace = {
            "__name__": __name__, "Blueprint": Blueprint, "jsonify": jsonify, "request": request,
            "session": session, "wraps": wraps, "logging": logging, "re": re, "uuid": uuid,
            "get_settings": services.settings_module.get_settings, "log_event": services.appinsights.log_event,
            "debug_print": Mock(), "check_user_access_status": Mock(return_value=(True, None)),
            "swagger_route": lambda **kwargs: lambda function: function, "get_auth_security": lambda: [],
            "personal_editor_response": authoring.personal_editor_response,
            "editor_error_response": authoring.editor_error_response,
            "ensure_editor_access": authoring.ensure_editor_access,
            "ensure_editor_options_access": authoring.ensure_editor_options_access,
            "build_agent_editor_options": authoring.build_agent_editor_options,
            "build_action_editor_types": authoring.build_action_editor_types,
            "clear_editor_test_secrets": authoring.clear_editor_test_secrets,
            "WorkspaceAuthoringValidation": authoring.WorkspaceAuthoringValidation,
            "validate_editor_action_manifest": authoring.validate_editor_action_manifest,
            "sanitize_agent_payload": payload.sanitize_agent_payload,
            "is_azure_ai_foundry_agent": payload.is_azure_ai_foundry_agent,
            "AgentPayloadError": payload.AgentPayloadError,
            "AssignedKnowledgeError": type("AssignedKnowledgeError", (ValueError,), {}),
            "apply_assigned_knowledge_to_agent_payload": Mock(side_effect=lambda value, **kwargs: value),
            "validate_agent": schema.validate_agent, "validate_plugin": schema.validate_plugin,
            "PLUGIN_STORAGE_MANAGED_FIELDS": schema.PLUGIN_STORAGE_MANAGED_FIELDS,
            "PluginHealthChecker": health.PluginHealthChecker,
            "validate_agent_delegation_bindings": delegation.validate_agent_delegation_bindings,
            "ensure_governance_access": services.governance.ensure_governance_access,
            "ensure_action_type_access": services.governance.ensure_action_type_access,
            "is_action_type_access_allowed": services.governance.is_action_type_access_allowed,
            "validate_action_identity_reference": identities.validate_action_identity_reference,
            "hydrate_action_identity_reference": identities.hydrate_action_identity_reference,
            "WORKSPACE_IDENTITY_SCOPE_PERSONAL": "personal",
            "McpDestinationPolicyError": type("McpDestinationPolicyError", (ValueError,), {}),
            "_enforce_mcp_destination_policy": Mock(),
            "_redact_plugin_for_logging": keyvault.redact_plugin_secret_values,
            "ensure_migration_complete": Mock(),
            "DOCUMENT_SEARCH_INTERNAL_ENDPOINT": "internal://document-search",
            "AGENT_PLUGIN_TYPE": delegation.AGENT_PLUGIN_TYPE,
            "AGENT_DEFAULT_ENDPOINT": delegation.AGENT_DEFAULT_ENDPOINT,
            "ui_trigger_word": keyvault.ui_trigger_word,
            "validate_secret_name_dynamic": keyvault.validate_secret_name_dynamic,
            "resolve_secret_reference_for_context": keyvault.resolve_secret_reference_for_context,
            "ACTION_CONNECTION_TEST_AUTH_SECRET_FIELDS": ("key", "identity", "tenantId"),
            "ACTION_CONNECTION_TEST_ADDITIONAL_SECRET_FIELDS": ("private_key_passphrase",),
            "ACTION_AUTH_SECRET_SOURCES": {"action"},
        }
        for module in modules:
            namespace.update({key: value for key, value in vars(module).items() if not key.startswith("_")})
        namespace.update({"log_event": services.appinsights.log_event, "logging": logging})
        namespace["build_combined_model_endpoints"] = Mock(return_value=[])
        namespace["get_global_agent_settings"] = Mock(return_value="classic settings")
        namespace["get_plugin_types"] = lambda allowed_type_filter: jsonify([
            {"type": name, "display": name.replace("_", " ").title(), "description": f"Configure {name}"}
            for name in CURRENT_TYPES if allowed_type_filter(name)
        ])
        namespace["get_personal_agents"] = lambda user_id: [
            {key: deepcopy(value) for key, value in record.items() if not key.startswith("_")}
            for (owner, _), record in services.records["agents", "personal"].items() if owner == user_id
        ]
        namespace["get_global_agents"] = lambda: [
            deepcopy(value) for value in services.records["agents", "global"].values()
        ]
        namespace["get_personal_action"] = lambda user_id, action_id, **kwargs: next((
            deepcopy(record) for (owner, _), record in services.records["actions", "personal"].items()
            if owner == user_id and action_id in {record["id"], record["name"]}
        ), None)
        namespace["SecretReturnType"] = keyvault.SecretReturnType
        namespace["ACTION_PERMISSION_ERROR_MESSAGE"] = "Not permitted."
        execute_functions("functions_authentication.py", {
            "apply_blueprint_auth", "login_required_blueprint", "login_required", "user_required", "get_current_user_id",
        }, namespace)
        execute_functions("functions_settings.py", {"enabled_required"}, namespace)
        execute_functions("route_backend_agents.py", {
            "_is_agent_allowed_for_user_selection", "_find_personal_agent",
            "_strip_disallowed_local_custom_connection_fields",
            "_prepare_personal_agent_for_editor", "_prepare_personal_agent_payload",
            "get_user_agents", "set_user_agents", "get_user_agent", "update_user_agent", "delete_user_agent",
            "get_global_agent_settings_for_users",
        }, namespace, blueprint="bpa")
        execute_functions("route_backend_plugins.py", {
            "_apply_plugin_runtime_defaults", "_validate_action_identity_for_scope", "_reject_non_admin_mcp_stdio",
            "_prepare_personal_action_for_editor", "_prepare_personal_action_payload",
            "get_user_plugins", "set_user_plugins", "get_user_plugin", "update_user_plugin", "delete_user_plugin",
            "get_user_plugin_types", "_rehydrate_action_test_secret", "_hydrate_mcp_custom_headers_for_test",
            "_resolve_secret_value_for_action_test", "_load_existing_plugin_for_test",
            "_resolve_action_identity_context", "_resolve_plugin_secret_context",
            "_prepare_action_test_manifest",
            "_flatten_editor_test_fields", "_prepare_editor_sql_test_data", "_prepare_editor_yamcs_test_data",
            "_is_personal_editor_test_request", "_assert_personal_editor_test_access",
            "_hydrate_sql_test_identity", "_load_existing_plugin_for_sql_test", "_resolve_secret_value_for_sql_test",
            "test_sql_connection", "test_yamcs_connection",
        }, namespace, blueprint="bpap")
        namespace["ACTION_ADDITIONAL_SECRET_SOURCES"] = {"action-addset"}
        app.register_blueprint(namespace["bpa"])
        app.register_blueprint(namespace["bpap"])
        client = app.test_client()
        with client.session_transaction() as state:
            state["user"] = {"oid": "actor", "roles": ["User"], "name": "Test actor"}
        yield SimpleNamespace(
            helper=authoring, services=services, client=client, app=app, namespace=namespace,
            keyvault=keyvault, schema=schema, identities=identities, reminders=reminder,
        )


def agent_payload(kind="local"):
    record = {
        "id": str(uuid.uuid4()), "name": f"test_{kind}", "display_name": "Same display name",
        "description": "", "instructions": "Be helpful.", "agent_type": kind,
        "actions_to_load": [], "other_settings": {}, "max_completion_tokens": -1,
    }
    if kind != "local":
        record.update({
            "azure_openai_gpt_endpoint": "https://project.services.ai.azure.com/api/projects/demo",
            "azure_openai_gpt_deployment": "test-agent", "azure_openai_gpt_api_version": "2025-11-15-preview",
        })
        section = {"aifoundry": "azure_ai_foundry", "new_foundry": "new_foundry", "foundry_workflow": "foundry_workflow"}[kind]
        record["other_settings"][section] = {
            "agent_id": "asst_test", "application_id": "app:1", "workflow_name": "workflow",
            "responses_api_version": "2025-11-15-preview", "client_secret": "foundry-test-credential",
            "authentication_type": "service_principal", "client_id": "client", "tenant_id": "tenant",
        }
    return record


def action_payload(kind="openapi"):
    record = {
        "name": f"test_{kind}", "displayName": "Same display name", "description": "Description",
        "type": kind, "endpoint": "https://api.example.test", "auth": {"type": "key", "key": "test-credential"},
        "metadata": {}, "additionalFields": {},
    }
    if kind == "agent":
        record.update({"endpoint": "internal://agent", "auth": {"type": "user"}, "additionalFields": {"target_agent": reference()}})
    return record


def configured_action_payload(environment, kind):
    record = action_payload(kind)
    if kind == "agent":
        return record
    allowed = environment.schema.get_allowed_auth_types_for_plugin_type(kind)
    auth_type = next(value for value in ("NoAuth", "user", "key", "identity", "username_password", "servicePrincipal", "basic", "connection_string") if value in allowed)
    record["auth"] = {"type": auth_type}
    if auth_type not in {"NoAuth", "user"}:
        record["auth"].update({"identity": "test-identity", "key": "test-credential", "tenantId": "test-tenant"})
    fields = record["additionalFields"]
    if kind in {"sql_query", "sql_schema"}:
        fields.update({"database_type": "sqlserver", "server": "server.example.test", "database": "test-db"})
    elif kind == "blob_storage":
        record["endpoint"] = "https://testaccount.blob.core.windows.net"
        fields["container_name"] = "documents"
    elif kind == "queue_storage":
        record["endpoint"] = "https://testaccount.queue.core.windows.net"
        fields["queue_name"] = "work"
    elif kind in {"databricks", "databricks_table"}:
        record["endpoint"] = "https://adb-1234567890123456.7.azuredatabricks.net"
        fields.update({"warehouse_id": "test-warehouse", "cloud": "azure_commercial"})
    elif kind == "snowflake":
        record["endpoint"] = "snowflake://query"
        record["auth"] = {"type": "username_password", "identity": "analyst", "key": "test-credential"}
        fields.update({"account": "org-account", "warehouse": "compute", "user": "analyst", "auth_method": "password"})
    elif kind == "tableau":
        record["auth"] = {"type": "key", "identity": "test-pat", "key": "test-credential"}
        fields.update({"site_content_url": "test-site", "pat_name": "test-pat"})
    elif kind == "yamcs":
        fields.update({"instance": "test-instance", "processor": "realtime"})
    elif kind == "cosmos_query":
        record["endpoint"] = "https://testaccount.documents.azure.com"
        fields.update({"database_name": "db", "container_name": "items", "partition_key_path": "/id"})
    elif kind == "log_analytics":
        fields["workspaceId"] = "test-workspace"
    elif kind == "mcp":
        fields.update({"transport": "streamable_http", "auth_method": "none"})
    elif kind == "embedding_model":
        record.update({"api_version": "2024-06-01", "deployment": "test-embedding"})
    elif kind in {"chart", "simplechat", "msgraph"}:
        record["endpoint"] = ""
    return record


def write_payload(updates, revision=None, **fields):
    return {
        "updates": updates, "clear_secret_paths": [], "removed_paths": [],
        **({"expected_revision": revision} if revision else {}), **fields,
    }


def create(environment, kind, record):
    response = environment.client.post(f"/api/user/{kind}?view=editor", json=write_payload(record))
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def patch_record(environment, kind, resource, updates, **fields):
    return environment.client.patch(
        f"/api/user/{kind}/{resource['record']['id']}?view=editor",
        json=write_payload(updates, resource["revision"], **fields),
    )


@pytest.mark.parametrize("kind", ["local", "aifoundry", "new_foundry", "foundry_workflow"])
@pytest.mark.parametrize("vault_enabled", [False, True])
def test_agent_types_create_edit_and_redact(environment, kind, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    draft = agent_payload(kind)
    if kind == "local":
        draft["azure_openai_gpt_key"] = "local-test-credential"
        draft["other_settings"] = {"unknown": {"false": False, "zero": 0, "empty": []}}
    resource = create(env, "agents", draft)
    assert resource["read_only"] is False and resource["revision"]
    assert "test-credential" not in json.dumps(resource)
    assert "_etag" not in resource["record"]
    updated = patch_record(env, "agents", resource, {"description": "Edited"})
    assert updated.status_code == 200, updated.get_json()
    latest = updated.get_json()
    stored = env.services.records["agents", "personal"]["actor", draft["id"]]
    assert stored["description"] == "Edited"
    assert stored["user_id"] == stored["modified_by"] == stored["created_by"] == "actor"
    assert latest["revision"] != resource["revision"]
    assert stored["max_completion_tokens"] == -1
    if kind == "local":
        assert stored["other_settings"] == draft["other_settings"]
    fetched = env.client.get(f"/api/user/agents/{draft['id']}?view=editor")
    assert fetched.get_json() == latest
    assert fetched.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("kind", CURRENT_TYPES)
def test_every_action_type_create_edit_reload_delete(environment, kind):
    env = environment
    env.services.add_agent()
    draft = configured_action_payload(env, kind)
    resource = create(env, "plugins", draft)
    saved_type = "databricks" if kind == "databricks_table" else kind
    assert resource["record"]["type"] == saved_type
    assert "test-credential" not in json.dumps(resource)
    update = patch_record(env, "plugins", resource, {
        "description": "Updated without executing the connector",
        "metadata": {"custom_configuration": {"enabled": False, "maximum": 0, "items": []}},
    })
    assert update.status_code == 200, update.get_json()
    latest = update.get_json()
    assert latest["record"]["metadata"]["custom_configuration"] == {"enabled": False, "maximum": 0, "items": []}
    assert env.client.get(f"/api/user/plugins/{resource['record']['id']}?view=editor").get_json() == latest
    assert env.client.delete(f"/api/user/plugins/{resource['record']['id']}?view=editor").status_code == 200


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_action_secret_intent_and_nested_round_trip(environment, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    draft = action_payload()
    draft["additionalFields"] = {
        "custom__Secret": "custom-secret-value", "unknown": {"scope": "keep", "enabled": False, "limit": 0, "values": []},
    }
    resource = create(env, "plugins", draft)
    assert set(resource["secret_paths"]) == {"/auth/key", "/additionalFields/custom__Secret"}
    stored_key = env.services.records["actions", "personal"]["actor", resource["record"]["id"]]["auth"]["key"]
    response = patch_record(env, "plugins", resource, {
        "auth": {"key": MASK}, "additionalFields": {"unknown": {"limit": 12}},
    })
    assert response.status_code == 200, response.get_json()
    current = response.get_json()
    stored = env.services.records["actions", "personal"]["actor", resource["record"]["id"]]
    assert stored["auth"]["key"] == stored_key
    assert stored["additionalFields"]["unknown"] == {"scope": "keep", "enabled": False, "limit": 12, "values": []}
    assert "custom-secret-value" not in json.dumps(current)
    replacement = patch_record(env, "plugins", current, {"auth": {"key": "replacement-credential"}})
    assert replacement.status_code == 200
    assert "replacement-credential" not in json.dumps(replacement.get_json())
    cleared = patch_record(
        env, "plugins", replacement.get_json(), {},
        clear_secret_paths=["/additionalFields/custom__Secret"], removed_paths=["/additionalFields/unknown/limit"],
    )
    assert cleared.status_code == 200, cleared.get_json()
    final = env.services.records["actions", "personal"]["actor", resource["record"]["id"]]
    assert "custom__Secret" not in final["additionalFields"]
    assert "limit" not in final["additionalFields"]["unknown"]
    assert "/additionalFields/custom__Secret" not in cleared.get_json()["secret_paths"]


@pytest.mark.parametrize("kind,secret_fields", [
    ("sql_query", {"connection_string": "Server=x;Password=secret", "password": "sql-secret"}),
    ("snowflake", {"private_key": "private-key-material", "private_key_passphrase": "snowflake-phrase-test-value", "token": "snowflake-token"}),
    ("yamcs", {"password": "yamcs-secret", "token": "yamcs-token"}),
    ("mcp", {"custom_headers": {"X-Access/Token~1": "header-secret", "X-Other": "another-secret"}}),
])
@pytest.mark.parametrize("vault_enabled", [False, True])
def test_canonical_connector_secrets_never_reach_editor(environment, kind, secret_fields, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    stored = env.services.add("actions", "personal", "actor", {
        **action_payload(kind), "id": f"{kind}-stored", "additionalFields": secret_fields,
    })
    detail = env.client.get(f"/api/user/plugins/{stored['id']}?view=editor")
    assert detail.status_code == 200
    encoded = json.dumps(detail.get_json())
    for value in secret_fields.values():
        for secret in value.values() if isinstance(value, dict) else [value]:
            assert secret not in encoded
    if kind == "mcp":
        assert "/additionalFields/custom_headers/X-Access~1Token~01" in detail.get_json()["secret_paths"]


def test_stale_and_racing_saves_do_not_change_stored_credentials(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    resource = create(env, "plugins", action_payload())
    original = deepcopy(env.services.records["actions", "personal"]["actor", resource["record"]["id"]])
    original_key = original["auth"]["key"]
    env.services.secret_writes.clear()
    stale = {**resource, "revision": '"stale"'}
    response = patch_record(env, "plugins", stale, {"auth": {"key": "stale-secret"}})
    assert response.status_code == 409
    assert env.services.secret_writes == []
    env.services.before_replace = lambda records, key: records[key].update({"description": "Other tab", "_etag": '"other-tab"'})
    response = patch_record(env, "plugins", resource, {"auth": {"key": "racing-secret"}})
    assert response.status_code == 409
    stored = env.services.records["actions", "personal"]["actor", resource["record"]["id"]]
    assert stored["auth"]["key"] == original_key
    assert env.services.vault[original_key] == "test-credential"
    assert stored["description"] == "Other tab"
    # A surfaced conflict may be an SDK retry after a commit; unused fresh values
    # are retained conservatively instead of risking deletion of live credentials.
    assert any(value == "racing-secret" for value in env.services.vault.values())
    assert all(
        name not in env.services.secret_deletes
        for name, value in env.services.secret_writes if value == "racing-secret"
    )
    assert all(name != original_key for name in env.services.secret_deletes)


def test_legacy_shared_name_secret_is_not_overwritten_or_deleted(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    reference_name = env.keyvault.build_full_secret_name("legacy", "actor", "action", "user")
    env.services.vault[reference_name] = "legacy-credential"
    first = env.services.add("actions", "personal", "actor", {
        **action_payload(), "id": "first", "auth": {"type": "key", "key": reference_name},
    })
    env.services.add("actions", "personal", "actor", {
        **action_payload(), "id": "second", "name": "second", "auth": {"type": "key", "key": reference_name},
    })
    resource = env.helper.editor_resource(first, "actions")
    response = patch_record(env, "plugins", resource, {"auth": {"key": "replacement"}})
    assert response.status_code == 200, response.get_json()
    assert env.services.vault[reference_name] == "legacy-credential"
    assert reference_name not in env.services.secret_deletes
    assert response.get_json()["record"]["auth"]["key"] == MASK


@pytest.mark.parametrize("updates,fields", [
    ({"auth": {"key": ""}}, {}),
    ({"auth": {"key": None}}, {}),
    ({"auth": None}, {}),
    ({"auth": {"key": "other--action--user--credential"}}, {}),
    ({"auth": {"key": "actor--action--user--foreign-action"}}, {}),
    ({}, {"removed_paths": ["/auth"]}),
    ({}, {"removed_paths": ["/auth/key"]}),
    ({}, {"clear_secret_paths": ["/description"]}),
    ({}, {"removed_paths": ["/additionalFields/bad~2pointer"]}),
    ({"id": "other"}, {}),
    ({"user_id": "other"}, {}),
    ({"scope": "global"}, {}),
    ({"created_by": "other"}, {}),
    ({"_etag": "fake"}, {}),
])
def test_invalid_patch_intent_cannot_change_owned_state(environment, updates, fields):
    env = environment
    resource = create(env, "plugins", action_payload())
    before = deepcopy(env.services.records)
    response = patch_record(env, "plugins", resource, updates, **fields)
    assert response.status_code == 400, response.get_json()
    assert env.services.records == before


def test_missing_revision_and_new_record_masks_are_rejected(environment):
    env = environment
    resource = create(env, "plugins", action_payload())
    response = env.client.patch(
        f"/api/user/plugins/{resource['record']['id']}?view=editor", json=write_payload({"description": "No revision"}),
    )
    assert response.status_code == 400
    draft = {**action_payload(), "name": "masked-new", "auth": {"type": "key", "key": MASK}}
    response = env.client.post("/api/user/plugins?view=editor", json=write_payload(draft))
    assert response.status_code == 400


def test_scope_governance_and_global_read_only(environment):
    env = environment
    personal = env.services.add("agents", "personal", "actor", agent_payload())
    provided = env.services.add("agents", "global", "global", {**agent_payload(), "id": personal["id"], "azure_openai_gpt_key": "global-credential"})
    env.services.add("agents", "personal", "other", {**agent_payload(), "id": "foreign"})
    listed = env.client.get("/api/user/agents?view=editor").get_json()
    assert len(listed) == 2 and {record["is_global"] for record in listed} == {False, True}
    detail = env.client.get(f"/api/user/agents/{provided['id']}?view=editor&scope=global")
    assert detail.status_code == 200 and detail.get_json()["read_only"] is True
    assert "global-credential" not in json.dumps(detail.get_json())
    for method in ("patch", "delete"):
        response = getattr(env.client, method)(
            f"/api/user/agents/{provided['id']}?view=editor&scope=global",
            json=write_payload({"description": "No"}, detail.get_json()["revision"]),
        )
        assert response.status_code == 403
    assert env.client.get("/api/user/agents/foreign?view=editor").status_code == 404
    env.services.denied_agents.add(provided["id"])
    assert env.client.get(f"/api/user/agents/{provided['id']}?view=editor&scope=global").status_code == 403
    assert len(env.client.get("/api/user/agents?view=editor").get_json()) == 1
    env.services.settings["merge_global_semantic_kernel_with_workspace"] = False
    assert env.client.get(f"/api/user/agents/{provided['id']}?view=editor&scope=global").status_code == 404


@pytest.mark.parametrize("kind,flag,feature", [
    ("agents", "allow_user_agents", "governance_user_agents"),
    ("plugins", "allow_user_plugins", "governance_user_actions"),
])
def test_feature_and_governance_denials_cover_reads_and_writes(environment, kind, flag, feature):
    env = environment
    for disabled in ("flag", "governance", "kernel", "workspace"):
        env.services.settings[flag] = disabled != "flag"
        env.services.settings["enable_semantic_kernel"] = disabled != "kernel"
        env.services.settings["enable_user_workspace"] = disabled != "workspace"
        env.services.denied_features = {feature} if disabled == "governance" else set()
        for method, suffix in (("get", ""), ("get", "/missing"), ("post", ""), ("patch", "/missing"), ("delete", "/missing")):
            response = getattr(env.client, method)(f"/api/user/{kind}{suffix}?view=editor", json=write_payload({}))
            if kind == "plugins" and method in {"get", "delete"}:
                expected_statuses = {200} if not suffix else {404}
            else:
                expected_statuses = {400, 403} if disabled == "flag" else {403}
            assert response.status_code in expected_statuses, (
                disabled, method, suffix, response.get_json(),
            )
    assert not env.services.writes


def test_action_type_governance_checks_existing_type_before_change(environment):
    env = environment
    resource = create(env, "plugins", action_payload())
    env.services.denied_types.add("openapi")
    assert env.client.get("/api/user/plugins?view=editor").get_json() == []
    assert env.client.get(f"/api/user/plugins/{resource['record']['id']}?view=editor").status_code == 403
    assert patch_record(env, "plugins", resource, {"type": "http"}).status_code == 403
    assert env.client.delete(f"/api/user/plugins/{resource['record']['id']}?view=editor").status_code == 403


def test_preserves_unavailable_agent_references_and_capabilities(environment):
    env = environment
    draft = agent_payload()
    draft["actions_to_load"] = ["legacy-action-name", "missing-action"]
    draft["other_settings"] = {
        "action_capabilities": {"missing-action": {"read": True, "write": False}},
        "assigned_knowledge": {"enabled": True, "document_ids": ["missing-document"], "scopes": {"personal": True}},
        "advanced": {"scope": "custom", "id": "retained", "zero": 0},
    }
    stored = env.services.add("agents", "personal", "actor", draft)
    env.namespace["apply_assigned_knowledge_to_agent_payload"].side_effect = AssertionError("Unchanged knowledge must not be reselected.")
    response = patch_record(env, "agents", env.helper.editor_resource(stored, "agents"), {"instructions": "Edited instructions"})
    assert response.status_code == 200, response.get_json()
    record = env.services.records["agents", "personal"]["actor", draft["id"]]
    assert record["actions_to_load"] == draft["actions_to_load"]
    assert record["other_settings"] == draft["other_settings"]


def test_call_agent_is_an_ordinary_action_with_existing_target_validation(environment):
    env = environment
    env.services.add_agent()
    action = create(env, "plugins", action_payload("agent"))
    local = agent_payload()
    local["actions_to_load"] = [action["record"]["id"], "legacy-unavailable"]
    local_agent = create(env, "agents", local)
    assert local_agent["record"]["actions_to_load"] == local["actions_to_load"]
    response = patch_record(env, "agents", local_agent, {"agent_type": "new_foundry"})
    assert response.status_code == 400
    denied = action_payload("agent")
    denied["name"] = "foreign-target"
    denied["additionalFields"]["target_agent"] = reference(scope_id="other")
    response = env.client.post("/api/user/plugins?view=editor", json=write_payload(denied))
    assert response.status_code in {400, 403, 404}
    assert len(env.services.records["actions", "personal"]) == 1


def test_scoped_identity_validation_and_personal_stdio_policy(environment):
    env = environment
    env.identities.validate_action_identity_reference.side_effect = LookupError("foreign identity credential")
    identity = {**action_payload(), "identity_id": "other-identity"}
    response = env.client.post("/api/user/plugins?view=editor", json=write_payload(identity))
    assert response.status_code == 400
    assert "foreign identity credential" not in json.dumps(response.get_json())
    env.identities.validate_action_identity_reference.side_effect = None
    stdio = action_payload("mcp")
    stdio["endpoint"] = "stdio://local"
    stdio["additionalFields"] = {"transport": "stdio", "command": "executable"}
    response = env.client.post("/api/user/plugins?view=editor", json=write_payload(stdio))
    assert response.status_code == 400
    assert not env.services.writes


def test_editor_settings_are_allowlisted_and_global_endpoint_governance_applies(environment):
    env = environment
    env.services.settings.update({
        "azure_openai_gpt_key": "global-secret", "semantic_kernel_agents": [{"key": "global-agent-secret"}],
        "global_selected_agent": {"instructions": "private-global-instructions"},
        "unrelated_internal_endpoint": "https://internal.example.test",
        "gpt_model": {"selected": [{"deploymentName": "gpt-test", "api_key": "catalogue-secret"}]},
        "enable_agent_template_gallery": True, "agent_templates_allow_user_submission": False,
        "key_vault_secret_expiration_default_lead_days": 45,
        "key_vault_secret_expiration_default_contact_email": "owner@example.test",
    })
    env.services.denied_endpoints.add("blocked")
    env.namespace["build_combined_model_endpoints"].return_value = [
        {"id": "allowed", "scope": "global", "models": [{"id": "model"}]},
        {"id": "blocked", "scope": "global", "models": [{"id": "private"}]},
        {"id": "personal", "scope": "user", "models": []},
    ]
    response = env.client.get("/api/user/agent/settings?view=editor")
    assert response.status_code == 200
    options = response.get_json()
    encoded = json.dumps(options)
    for value in ("global-secret", "global-agent-secret", "private-global-instructions", "internal.example.test", "catalogue-secret"):
        assert value not in encoded
    assert {item["id"] for item in options["model_endpoints"]} == {"allowed", "personal"}
    assert {item["value"] for item in options["agent_types"]} == {"local", "aifoundry", "new_foundry", "foundry_workflow"}
    assert options["settings"]["key_vault_secret_expiration_default_lead_days"] == 45
    assert options["settings"]["agent_templates_allow_user_submission"] is False
    assert options["builtin_actions"] == [{"id": "time", "label": "Time"}]
    env.services.governance.filter_governed_model_endpoints.assert_called_once()
    assert env.services.governance.filter_governed_model_endpoints.call_args.args[2] == "governance_global_endpoints"
    assert env.services.settings_module.sanitize_settings_for_user.call_count == 3
    env.namespace["get_global_agent_settings"].assert_not_called()


def test_all_discovered_types_get_canonical_schemas_and_allowed_auth(environment):
    env = environment
    response = env.client.get("/api/user/plugins/types?view=editor")
    assert response.status_code == 200
    definitions = {item["type"]: item for item in response.get_json()}
    assert set(definitions) == set(CURRENT_TYPES)
    for kind, definition in definitions.items():
        assert set(definition["allowed_auth_types"]) == env.schema.get_allowed_auth_types_for_plugin_type(kind)
        assert "additional_fields_schema" in definition and "metadata_schema" in definition
        schema_path = APP_ROOT / "static" / "json" / "schemas" / f"{kind}_plugin.additional_settings.schema.json"
        if schema_path.is_file():
            assert definition["additional_fields_schema"] == json.loads(schema_path.read_text(encoding="utf-8"))
    env.services.denied_types.add("agent")
    assert "agent" not in {item["type"] for item in env.client.get("/api/user/plugins/types?view=editor").get_json()}


def test_editor_openapi_type_description_does_not_inherit_retired_url_download_claim(environment):
    env = environment
    legacy = [
        {"type": "openapi", "display": "OpenAPI", "description": "Supports file upload, URL download, and various authentication methods."},
        {"type": "math", "display": "Math", "description": "Keep this existing description."},
    ]
    env.namespace["get_plugin_types"] = lambda allowed_type_filter: jsonify([
        deepcopy(definition) for definition in legacy if allowed_type_filter(definition["type"])
    ])
    response = env.client.get("/api/user/plugins/types?view=editor")
    assert response.status_code == 200
    definitions = {definition["type"]: definition for definition in response.get_json()}
    assert "URL download" not in definitions["openapi"]["description"]
    assert "Download hosted specifications before uploading" in definitions["openapi"]["description"]
    assert definitions["math"]["description"] == legacy[1]["description"]
    assert "URL download" in legacy[0]["description"]


def test_delete_is_owned_conditional_and_cleans_only_unreferenced_secrets(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    resource = create(env, "plugins", action_payload())
    foreign = env.services.add("actions", "personal", "other", {**action_payload(), "id": "foreign"})
    assert env.client.delete(f"/api/user/plugins/{foreign['id']}?view=editor").status_code == 404
    response = env.client.delete(f"/api/user/plugins/{resource['record']['id']}?view=editor")
    assert response.status_code == 200 and response.get_json() == {"success": True}
    assert ("actor", resource["record"]["id"]) not in env.services.records["actions", "personal"]
    assert not env.services.vault
    assert ("other", "foreign") in env.services.records["actions", "personal"]


def test_reminders_only_sync_after_successful_main_conditional_write(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    draft = action_payload()
    draft["metadata"] = {"key_vault_secret_reminders": {"auth.key": {"enabled": True, "expires_on": "2030-01-01"}}}
    resource = create(env, "plugins", draft)
    assert env.services.expiration_updates
    env.services.expiration_updates.clear()
    env.reminders.upsert_key_vault_secret_reminder.reset_mock()
    env.services.before_replace = lambda records, key: records[key].update({"_etag": '"changed"'})
    response = patch_record(env, "plugins", resource, {
        "auth": {"key": "losing-secret"}, "metadata": {"key_vault_secret_reminders": {"auth.key": {"expires_on": "2031-01-01"}}},
    })
    assert response.status_code == 409
    assert env.services.expiration_updates == []
    env.reminders.upsert_key_vault_secret_reminder.assert_not_called()


def test_classic_reads_and_stored_secret_test_hydration_remain_compatible(environment):
    env = environment
    stored = env.services.add("actions", "personal", "actor", {**action_payload(), "id": "classic"})
    classic = env.client.get("/api/user/plugins/classic")
    assert classic.status_code == 200 and classic.get_json()["auth"]["key"] == stored["auth"]["key"]
    assert "record" not in classic.get_json()
    for mask in (MASK, "Stored_In_KeyVault"):
        assert env.namespace["_rehydrate_action_test_secret"](mask, "owned-credential", "OpenAPI", "auth.key") == "owned-credential"
    with pytest.raises(ValueError):
        env.namespace["_rehydrate_action_test_secret"](MASK, None, "OpenAPI", "auth.key")


def test_unknown_storage_errors_do_not_leak_provider_diagnostics(environment):
    env = environment
    env.services.containers["agents", "personal"].query_items.side_effect = RuntimeError("provider credential=never-expose")
    response = env.client.get("/api/user/agents?view=editor")
    assert response.status_code == 503
    assert "never-expose" not in json.dumps(response.get_json())


def test_ambiguous_storage_result_never_deletes_potentially_committed_credentials(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    resource = create(env, "plugins", action_payload())
    container = env.services.containers["actions", "personal"]
    replace = container.replace_item.side_effect

    def commit_then_disconnect(**kwargs):
        replace(**kwargs)
        raise RuntimeError("provider response lost")

    container.replace_item.side_effect = commit_then_disconnect
    response = patch_record(env, "plugins", resource, {"auth": {"key": "committed-credential"}})
    assert response.status_code == 503
    stored = env.services.records["actions", "personal"]["actor", resource["record"]["id"]]
    assert env.services.vault[stored["auth"]["key"]] == "committed-credential"


def test_array_replacement_and_secret_removal_allow_normal_call_agent_type_change(environment):
    env = environment
    env.services.add_agent()
    draft = action_payload()
    draft["metadata"] = {"values": ["before", "another"]}
    resource = create(env, "plugins", draft)
    response = patch_record(
        env, "plugins", resource,
        {
            "type": "agent", "endpoint": "internal://agent", "auth": {"type": "user"},
            "additionalFields": {"target_agent": reference()}, "metadata": {"values": []},
        },
        clear_secret_paths=["/auth/key"],
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["record"]["auth"] == {"type": "user"}
    assert response.get_json()["record"]["metadata"]["values"] == []


def test_authorization_is_checked_before_legacy_migration(environment):
    env = environment
    assert env.client.get("/api/user/plugins?view=editor").status_code == 200
    env.namespace["ensure_migration_complete"].assert_called_once_with("actor")
    env.namespace["ensure_migration_complete"].reset_mock()
    env.services.denied_features.add("governance_user_actions")
    assert env.client.get("/api/user/plugins?view=editor").get_json() == []
    env.namespace["ensure_migration_complete"].assert_not_called()


def test_model_choice_is_not_a_custom_connection_and_legacy_connections_survive(environment):
    env = environment
    env.services.settings["allow_user_custom_endpoints"] = False
    draft = agent_payload()
    draft.update({
        "model_endpoint_id": "provided-endpoint", "model_id": "provided-model", "model_provider": "aoai",
        "azure_openai_gpt_deployment": "provided-deployment", "enable_agent_gpt_apim": False,
    })
    resource = create(env, "agents", draft)
    assert resource["record"]["azure_openai_gpt_deployment"] == "provided-deployment"
    assert patch_record(env, "agents", resource, {"azure_openai_gpt_endpoint": "https://custom.example.test"}).status_code == 403
    stored = env.services.records["agents", "personal"]["actor", resource["record"]["id"]]
    stored["azure_openai_gpt_endpoint"] = "https://legacy.example.test"
    stored["azure_openai_gpt_key"] = "legacy-test-credential"
    current = env.helper.editor_resource(stored, "agents")
    update = patch_record(env, "agents", current, {"instructions": "Only change instructions"})
    assert update.status_code == 200, update.get_json()
    assert update.get_json()["record"]["azure_openai_gpt_endpoint"] == "https://legacy.example.test"
    assert update.get_json()["record"]["azure_openai_gpt_key"] == MASK


def test_legacy_sql_auth_fields_survive_but_new_unsupported_properties_are_rejected(environment):
    env = environment
    record = configured_action_payload(env, "sql_query")
    record["auth"]["client_secret"] = "legacy-client-credential"
    record["legacy_extension"] = {"id": "old-extension-id", "limit": 0}
    stored = env.services.add("actions", "personal", "actor", {**record, "id": "legacy-sql"})
    resource = env.helper.editor_resource(stored, "actions")
    update = patch_record(env, "plugins", resource, {"description": "Edited"})
    assert update.status_code == 200, update.get_json()
    assert update.get_json()["record"]["auth"]["client_secret"] == MASK
    assert update.get_json()["record"]["legacy_extension"] == record["legacy_extension"]
    invalid = patch_record(env, "plugins", update.get_json(), {"auth": {"new_unsupported_field": "not allowed"}})
    assert invalid.status_code == 400


def test_changed_assigned_knowledge_uses_real_personal_scope_policy(environment):
    env = environment
    with ExitStack() as stack:
        config = env.services.modules["config"]
        for name in ("cosmos_user_documents_container", "cosmos_group_documents_container", "cosmos_public_documents_container"):
            stack.enter_context(patch.object(config, name, Mock(), create=True))
        documents = module_stub(
            "functions_documents",
            get_document_record=Mock(side_effect=lambda user_id, document_id, **scope: (
                {"id": document_id, "user_id": user_id} if document_id == "owned-document" and not scope else None
            )),
            sanitize_tags_for_filter=lambda tags: list(dict.fromkeys(str(tag).lower() for tag in tags or [])),
            select_current_documents=lambda values: values,
            sort_documents=lambda values, *args, **kwargs: values,
        )
        sources = {
            "functions_documents": documents,
            "functions_group": module_stub(
                "functions_group", find_group_by_id=Mock(return_value={"id": "group"}),
                get_user_role_in_group=Mock(return_value=None),
            ),
            "functions_public_workspaces": module_stub(
                "functions_public_workspaces", find_public_workspace_by_id=Mock(return_value=None),
                get_all_public_workspaces=Mock(return_value=[]),
            ),
            "functions_source_review": module_stub("functions_source_review", normalize_review_url=lambda value: value),
        }
        stack.enter_context(patch.dict(sys.modules, sources))
        policy = _load_module(stack, "functions_assigned_knowledge")
        env.namespace["apply_assigned_knowledge_to_agent_payload"] = policy.apply_assigned_knowledge_to_agent_payload
        env.namespace["AssignedKnowledgeError"] = policy.AssignedKnowledgeError
        draft = agent_payload()
        draft["other_settings"]["assigned_knowledge"] = {
            "enabled": True, "scopes": {"personal": True}, "document_ids": ["owned-document"],
            "tags": ["Finance"], "allow_user_workspace_context": False, "allowed_user_workspace_actions": [],
        }
        resource = create(env, "agents", draft)
        knowledge = resource["record"]["other_settings"]["assigned_knowledge"]
        assert knowledge["tags"] == ["finance"]
        assert knowledge["allowed_user_workspace_actions"] == []
        invalid = patch_record(env, "agents", resource, {
            "other_settings": {"assigned_knowledge": {"document_ids": ["foreign-document"]}},
        })
        assert invalid.status_code == 400
        stored = env.services.records["agents", "personal"]["actor", resource["record"]["id"]]
        assert stored["other_settings"]["assigned_knowledge"]["document_ids"] == ["owned-document"]
        documents.get_document_record.assert_any_call("actor", "foreign-document")


@pytest.mark.parametrize("kind,path", [
    ("agents", ("azure_openai_gpt_key",)),
    ("actions", ("auth", "key")),
    ("actions", ("additionalFields", "custom__Secret")),
])
def test_legacy_stored_placeholders_resolve_only_the_owned_existing_secret(environment, kind, path):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    record = agent_payload() if kind == "agents" else {**action_payload(), "id": "legacy-action"}
    if len(path) == 1:
        record[path[0]] = "Stored_In_KeyVault"
    else:
        record[path[0]][path[1]] = "Stored_In_KeyVault"
    stored = env.services.add(kind, "personal", "actor", record)
    scope_value = stored["id"] if kind == "agents" else "actor"
    source = "agent" if kind == "agents" else "action" if path[0] == "auth" else "action-addset"
    secret_name = stored["name"] if path[-1] != "custom__Secret" else f"{stored['name']}-custom"
    expected_reference = env.keyvault.build_full_secret_name(secret_name, scope_value, source, "user")
    env.services.vault[expected_reference] = "owned-legacy-credential"
    resource = env.helper.editor_resource(stored, kind)
    route_kind = "agents" if kind == "agents" else "plugins"
    stale = {**resource, "revision": '"stale"'}
    assert patch_record(env, route_kind, stale, {"description": "Stale"}).status_code == 409
    assert env.services.secret_reads == []
    updated = patch_record(env, route_kind, resource, {"description": "Edited"})
    assert updated.status_code == 200, updated.get_json()
    current = env.services.records[kind, "personal"]["actor", stored["id"]]
    value = current[path[0]] if len(path) == 1 else current[path[0]][path[1]]
    assert value == expected_reference
    assert env.services.secret_reads == [expected_reference]
    assert env.services.vault[expected_reference] == "owned-legacy-credential"


def test_missing_legacy_credential_needs_reentry_not_a_guessed_reference(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    stored = env.services.add("actions", "personal", "actor", {
        **action_payload(), "id": "missing-legacy", "auth": {"type": "key", "key": "Stored_In_KeyVault"},
    })
    resource = env.helper.editor_resource(stored, "actions")
    failed = patch_record(env, "plugins", resource, {"description": "No credential"})
    assert failed.status_code == 400
    assert env.services.records["actions", "personal"]["actor", stored["id"]] == stored
    env.services.settings["enable_key_vault_secret_storage"] = False
    repaired = patch_record(env, "plugins", resource, {"auth": {"key": "replacement-test-credential"}})
    assert repaired.status_code == 200, repaired.get_json()
    assert "replacement-test-credential" not in json.dumps(repaired.get_json())
    assert env.services.records["actions", "personal"]["actor", stored["id"]]["auth"]["key"] == "replacement-test-credential"


def test_action_only_authors_can_read_reminder_defaults_without_agent_access(environment):
    env = environment
    stored_agent = env.services.add("agents", "personal", "actor", {
        **agent_payload(), "instructions": "private-agent-instructions",
    })
    env.services.settings["allow_user_agents"] = False
    env.services.settings["allow_user_plugins"] = True
    env.services.settings["key_vault_secret_expiration_default_lead_days"] = 45
    env.services.settings["semantic_kernel_agents"] = [{"instructions": "private-global-agent"}]
    env.services.settings["gpt_model"] = {"selected": [{"deploymentName": "private-agent-model"}]}
    env.namespace["build_combined_model_endpoints"].side_effect = AssertionError("Do not load an unavailable agent catalogue.")
    response = env.client.get("/api/user/agent/settings?view=editor")
    assert response.status_code == 200, response.get_json()
    options = response.get_json()
    assert options["settings"]["key_vault_secret_expiration_default_lead_days"] == 45
    assert options["settings"]["allow_user_agents"] is False
    assert not any(agent_type["enabled"] for agent_type in options["agent_types"])
    assert options["model_endpoints"] == options["builtin_actions"] == []
    assert "private-agent" not in json.dumps(options)
    assert "private-global-agent" not in json.dumps(options)
    env.namespace["build_combined_model_endpoints"].assert_not_called()
    for method, path in (
        ("get", "/api/user/agents"),
        ("get", f"/api/user/agents/{stored_agent['id']}"),
        ("post", "/api/user/agents"),
        ("patch", f"/api/user/agents/{stored_agent['id']}"),
        ("delete", f"/api/user/agents/{stored_agent['id']}"),
    ):
        denied = getattr(env.client, method)(f"{path}?view=editor", json=write_payload({}))
        assert denied.status_code in {400, 403}
    assert env.services.records["agents", "personal"]["actor", stored_agent["id"]] == stored_agent
    env.services.denied_features.add("governance_user_actions")
    assert env.client.get("/api/user/agent/settings?view=editor").status_code == 403
    env.services.denied_features.clear()
    env.services.settings["allow_user_plugins"] = False
    assert env.client.get("/api/user/agent/settings?view=editor").status_code == 403


@pytest.mark.parametrize("kind,root", [("agents", "other_settings"), ("plugins", "additionalFields")])
@pytest.mark.parametrize("vault_enabled", [False, True])
def test_replaced_arrays_preserve_owned_masks_but_not_omitted_object_fields(environment, kind, root, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    draft = agent_payload() if kind == "agents" else action_payload()
    draft[root]["foo"] = [
        {"id": "first", "token": "array-first-credential", "remove_me": "old", "nested": {"keep": 1, "discard": 3}},
        {"id": "second", "token": "array-second-credential", "keep": 2},
    ]
    resource = create(env, kind, draft)
    assert f"/{root}/foo/0/token" in resource["secret_paths"]
    replacement = deepcopy(resource["record"][root]["foo"])
    replacement[0].pop("remove_me")
    replacement[0]["nested"] = {"keep": 4}
    response = patch_record(env, kind, resource, {root: {"foo": replacement}})
    assert response.status_code == 200, response.get_json()
    stored_kind = "agents" if kind == "agents" else "actions"
    stored = env.services.records[stored_kind, "personal"]["actor", resource["record"]["id"]][root]["foo"]
    assert stored[0]["token"] == "array-first-credential"
    assert stored[1]["token"] == "array-second-credential"
    assert "remove_me" not in stored[0]
    assert stored[0]["nested"] == {"keep": 4}
    assert "array-first-credential" not in json.dumps(response.get_json())
    assert "array-second-credential" not in json.dumps(response.get_json())


def test_array_credential_omissions_require_explicit_clearing(environment):
    env = environment
    draft = agent_payload()
    draft["other_settings"]["foo"] = [{"token": "array-credential", "keep": 1}]
    resource = create(env, "agents", draft)
    original = deepcopy(env.services.records)
    replacement = {"other_settings": {"foo": [{"keep": 2}]}}
    rejected = patch_record(env, "agents", resource, replacement)
    assert rejected.status_code == 400
    assert env.services.records == original
    cleared = patch_record(
        env, "agents", resource, replacement, clear_secret_paths=["/other_settings/foo/0/token"],
    )
    assert cleared.status_code == 200, cleared.get_json()
    assert cleared.get_json()["record"]["other_settings"]["foo"] == [{"keep": 2}]
    assert "/other_settings/foo/0/token" not in cleared.get_json()["secret_paths"]


@pytest.mark.parametrize("empty_value", ["", None])
def test_explicit_array_secret_clears_accept_empty_values_in_array_replacements(environment, empty_value):
    env = environment
    draft = agent_payload()
    draft["other_settings"]["foo"] = [{"token": "array-credential", "keep": 1}]
    resource = create(env, "agents", draft)
    replacement = {"other_settings": {"foo": [{"token": empty_value, "keep": 2}]}}
    assert patch_record(env, "agents", resource, replacement).status_code == 400
    cleared = patch_record(
        env, "agents", resource, replacement, clear_secret_paths=["/other_settings/foo/0/token"],
    )
    assert cleared.status_code == 200, cleared.get_json()
    assert cleared.get_json()["record"]["other_settings"]["foo"] == [{"keep": 2}]


def test_a_mask_at_a_new_array_path_cannot_borrow_another_entries_credential(environment):
    env = environment
    draft = agent_payload()
    draft["other_settings"]["foo"] = [{"token": "array-credential"}]
    resource = create(env, "agents", draft)
    original = deepcopy(env.services.records)
    response = patch_record(env, "agents", resource, {
        "other_settings": {"foo": [{"token": MASK}, {"token": MASK}]},
    })
    assert response.status_code == 400
    assert env.services.records == original


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_connection_test_clear_intent_never_rehydrates_the_cleared_credential(environment, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    draft = action_payload()
    draft["additionalFields"]["openapi_spec_content"] = {
        "openapi": "3.0.0", "info": {"title": "Test", "version": "1"}, "paths": {},
    }
    resource = create(env, "plugins", draft)
    original = deepcopy(env.services.records)
    data = {
        "endpoint": draft["endpoint"], "auth": {"type": "key", "key": MASK},
        "plugin_context": {"scope": "user", "id": resource["record"]["id"], "name": draft["name"]},
        "action_scope": "personal",
    }
    with env.app.test_request_context("/"):
        session["user"] = {"oid": "actor", "roles": ["User"]}
        kept, scope_type, scope_id = env.namespace["_prepare_action_test_manifest"](data, "openapi", "OpenAPI")
        assert kept["auth"]["key"] == "test-credential"
        assert (scope_type, scope_id) == ("personal", "actor")
        data["auth"]["key"] = ""
        classic, _, _ = env.namespace["_prepare_action_test_manifest"](data, "openapi", "OpenAPI")
        assert classic["auth"]["key"] == "test-credential"
        data["clear_secret_paths"] = ["/auth/key"]
        env.services.secret_reads.clear()
        cleared, _, _ = env.namespace["_prepare_action_test_manifest"](data, "openapi", "OpenAPI")
    assert not cleared["auth"].get("key")
    assert env.services.secret_reads == []
    assert env.services.records == original


def test_mcp_test_clears_one_header_while_preserving_other_owned_headers(environment):
    env = environment
    stored = env.services.add("actions", "personal", "actor", {
        **action_payload("mcp"), "id": "mcp-header-clear", "auth": {"type": "NoAuth"},
        "additionalFields": {
            "transport": "streamable_http", "auth_method": "none",
            "custom_headers": {"X-Removed": "removed-credential", "X-Kept": "kept-credential"},
        },
    })
    data = {
        "endpoint": stored["endpoint"], "auth": {"type": "NoAuth"},
        "plugin_context": {"scope": "personal", "id": stored["id"], "name": stored["name"]},
        "action_scope": "personal",
        "additionalFields": {
            "transport": "streamable_http", "auth_method": "none",
            "custom_headers": {"X-Removed": "", "X-Kept": MASK},
        },
        "clear_secret_paths": ["/additionalFields/custom_headers/X-Removed"],
    }
    with env.app.test_request_context("/"):
        session["user"] = {"oid": "actor", "roles": ["User"]}
        manifest, _, _ = env.namespace["_prepare_action_test_manifest"](data, "mcp", "MCP")
    assert manifest["additionalFields"]["custom_headers"] == {"X-Kept": "kept-credential"}
    assert env.services.records["actions", "personal"]["actor", stored["id"]] == stored


def test_transient_clear_paths_cannot_remove_owner_fields(environment):
    env = environment
    stored = env.services.add("actions", "personal", "actor", {**action_payload(), "id": "owned"})
    with pytest.raises(env.helper.WorkspaceAuthoringValidation):
        env.helper.clear_editor_test_secrets(stored, ["/user_id"])
    assert env.services.records["actions", "personal"]["actor", stored["id"]] == stored


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_sql_editor_full_auth_uses_owned_secret_and_canonical_flat_parameters(environment, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    draft = configured_action_payload(env, "sql_query")
    draft["auth"] = {"type": "user", "identity": "db-user", "key": "sql-test-credential"}
    draft["additionalFields"].update({"username": "db-user", "password": "sql-test-credential"})
    resource = create(env, "plugins", draft)
    original = deepcopy(env.services.records)
    connection = Mock()
    connect = Mock(return_value=connection)
    data = {
        "auth": resource["record"]["auth"], "additionalFields": resource["record"]["additionalFields"],
        "existing_plugin": {"scope": "user", "id": resource["record"]["id"], "name": draft["name"]},
        "action_scope": "personal", "server": "stale-flat-value", "database": "stale-flat-value",
    }
    with patch.dict(sys.modules, {"pyodbc": module_stub("pyodbc", connect=connect)}):
        response = env.client.post("/api/plugins/test-sql-connection", json=data)
    assert response.status_code == 200, response.get_json()
    connection_string = connect.call_args.args[0]
    assert "SERVER=server.example.test" in connection_string
    assert "DATABASE=test-db" in connection_string
    assert "UID=db-user" in connection_string
    assert "sql-test-credential" in connection_string
    assert "stale-flat-value" not in connection_string
    assert "sql-test-credential" not in json.dumps(response.get_json())
    assert env.services.records == original


def test_sql_editor_service_principal_does_not_silently_test_another_authentication_mode(environment):
    env = environment
    connect = Mock()
    data = {
        "auth": {"type": "servicePrincipal", "identity": "client-id", "tenantId": "tenant-id", "key": "sp-test-credential"},
        "additionalFields": {"database_type": "azure_sql", "server": "server.example.test", "database": "test-db"},
        "auth_type": "service_principal", "action_scope": "personal",
    }
    with patch.dict(sys.modules, {"pyodbc": module_stub("pyodbc", connect=connect)}):
        response = env.client.post("/api/plugins/test-sql-connection", json=data)
    assert response.status_code == 400
    assert "not supported by the SQL action runtime" in response.get_json()["error"]
    assert "sp-test-credential" not in json.dumps(response.get_json())
    connect.assert_not_called()


def test_sql_editor_identity_credentials_override_stale_flat_auth_hints(environment):
    env = environment

    def hydrate(manifest, scope_type, scope_id, *, return_type):
        assert (scope_type, scope_id, return_type) == ("personal", "actor", env.keyvault.SecretReturnType.VALUE)
        result = deepcopy(manifest)
        result["auth"] = {"type": "user"}
        result["additionalFields"].update({
            "identity_auth_type": "username_password", "username": "identity-user", "password": "identity-sql-credential",
        })
        return result

    env.identities.hydrate_action_identity_reference.side_effect = hydrate
    connect = Mock(return_value=Mock())
    data = {
        "identity_id": "owned-identity", "auth": {"type": "identity", "identity": "owned-identity"},
        "additionalFields": {"database_type": "sqlserver", "server": "server.example.test", "database": "db"},
        "auth_type": "identity", "action_scope": "personal",
    }
    with patch.dict(sys.modules, {"pyodbc": module_stub("pyodbc", connect=connect)}):
        response = env.client.post("/api/plugins/test-sql-connection", json=data)
    assert response.status_code == 200, response.get_json()
    assert "UID=identity-user" in connect.call_args.args[0]
    assert "identity-sql-credential" in connect.call_args.args[0]
    env.identities.hydrate_action_identity_reference.assert_called_once()


def test_unsaved_yamcs_editor_can_test_a_scoped_identity(environment):
    env = environment

    def hydrate(manifest, scope_type, scope_id, *, return_type):
        assert (scope_type, scope_id, return_type) == ("personal", "actor", env.keyvault.SecretReturnType.VALUE)
        assert manifest["type"] == "yamcs" and manifest["identity_id"] == "owned-identity"
        result = deepcopy(manifest)
        result["auth"] = {"type": "key", "key": "identity-yamcs-credential"}
        result["additionalFields"]["auth_method"] = "api_key"
        return result

    env.identities.hydrate_action_identity_reference.side_effect = hydrate
    client = Mock()
    client.ctx = None
    client.get_server_info.return_value = SimpleNamespace(version="test")
    client.list_instances.return_value = [SimpleNamespace(name="demo")]
    credential = Mock(side_effect=lambda value: SimpleNamespace(key=value))
    client_factory = Mock(return_value=client)
    yamcs_client = module_stub(
        "yamcs.client", APIKeyCredentials=credential, Credentials=Mock(), YamcsClient=client_factory,
    )
    data = {
        "identity_id": "owned-identity", "auth": {"type": "identity", "identity": "owned-identity"},
        "endpoint": "https://yamcs.example.test",
        "additionalFields": {"instance": "demo", "auth_method": "identity", "tls_verify": False},
        "action_scope": "personal",
    }
    with patch.dict(sys.modules, {"yamcs": module_stub("yamcs"), "yamcs.client": yamcs_client}):
        response = env.client.post("/api/plugins/test-yamcs-connection", json=data)
    assert response.status_code == 200, response.get_json()
    credential.assert_called_once_with("identity-yamcs-credential")
    assert client_factory.call_args.kwargs["tls_verify"] is False
    assert "identity-yamcs-credential" not in json.dumps(response.get_json())
    client.close.assert_called_once()
    env.identities.hydrate_action_identity_reference.assert_called_once()
    assert env.services.writes == []


@pytest.mark.parametrize("endpoint", ["/api/plugins/test-sql-connection", "/api/plugins/test-yamcs-connection"])
def test_editor_connection_identities_fail_closed_without_provider_diagnostics(environment, endpoint):
    env = environment
    env.identities.hydrate_action_identity_reference.side_effect = PermissionError("private identity provider credential")
    response = env.client.post(endpoint, json={
        "identity_id": "foreign-identity", "auth": {"type": "identity", "identity": "foreign-identity"},
        "additionalFields": {
            "database_type": "sqlserver", "server": "server.example.test", "database": "db", "instance": "demo",
        },
        "endpoint": "https://yamcs.example.test", "action_scope": "personal",
    })
    assert response.status_code == 403
    assert "private identity provider credential" not in json.dumps(response.get_json())
    assert env.services.writes == []


def test_sql_cleared_password_does_not_fall_back_to_duplicate_auth_secret(environment):
    env = environment
    draft = configured_action_payload(env, "sql_query")
    draft["auth"] = {"type": "user", "identity": "db-user", "key": "duplicate-sql-credential"}
    draft["additionalFields"].update({"username": "db-user", "password": "duplicate-sql-credential"})
    resource = create(env, "plugins", draft)
    fields = {**resource["record"]["additionalFields"], "password": ""}
    original = deepcopy(env.services.records)
    connect = Mock()
    with patch.dict(sys.modules, {"pyodbc": module_stub("pyodbc", connect=connect)}):
        response = env.client.post("/api/plugins/test-sql-connection", json={
            "auth": resource["record"]["auth"], "additionalFields": fields,
            "existing_plugin": {"scope": "personal", "id": resource["record"]["id"]},
            "action_scope": "personal", "clear_secret_paths": ["/additionalFields/password"],
        })
    assert response.status_code == 400
    assert "username and password are required" in response.get_json()["error"]
    connect.assert_not_called()
    assert env.services.records == original


def test_sql_editor_driver_failures_do_not_echo_resolved_credentials(environment):
    env = environment
    connect = Mock(side_effect=RuntimeError("Driver rejected private-sql-credential"))
    with patch.dict(sys.modules, {"pyodbc": module_stub("pyodbc", connect=connect)}):
        response = env.client.post("/api/plugins/test-sql-connection", json={
            "auth": {"type": "user"},
            "additionalFields": {
                "database_type": "sqlserver", "server": "server.example.test", "database": "db",
                "username": "db-user", "password": "private-sql-credential",
            },
            "action_scope": "personal",
        })
    assert response.status_code == 400
    assert "private-sql-credential" not in json.dumps(response.get_json())


def test_new_yamcs_identity_testing_does_not_expand_group_or_admin_behavior(environment):
    env = environment
    for scope in ("group", "global"):
        response = env.client.post("/api/plugins/test-yamcs-connection", json={
            "identity_id": "another-scope-identity",
            "auth": {"type": "identity", "identity": "another-scope-identity"},
            "additionalFields": {"instance": "demo"},
            "server_url": "https://yamcs.example.test", "instance": "demo", "action_scope": scope,
        })
        assert response.status_code == 400
    env.identities.hydrate_action_identity_reference.assert_not_called()


@pytest.mark.parametrize("endpoint,action_type", [
    ("/api/plugins/test-sql-connection", "sql_query"),
    ("/api/plugins/test-yamcs-connection", "yamcs"),
])
def test_editor_identity_tests_enforce_personal_action_type_governance(environment, endpoint, action_type):
    env = environment
    env.services.denied_types.update({"sql_query", "sql_schema", "yamcs"})
    response = env.client.post(endpoint, json={
        "type": action_type, "identity_id": "owned-identity",
        "auth": {"type": "identity", "identity": "owned-identity"},
        "additionalFields": {
            "server": "server.example.test", "database": "db", "instance": "demo",
        },
        "endpoint": "https://yamcs.example.test", "action_scope": "personal",
    })
    assert response.status_code == 403
    env.identities.hydrate_action_identity_reference.assert_not_called()


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_embedding_editor_root_fields_survive_and_drive_the_existing_runtime(environment, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    draft = configured_action_payload(env, "embedding_model")
    resource = create(env, "plugins", draft)
    assert resource["record"]["api_version"] == "2024-06-01"
    assert resource["record"]["deployment"] == "test-embedding"
    updated = patch_record(env, "plugins", resource, {
        "deployment": "custom-vectors", "api_version": "2024-10-21",
    })
    assert updated.status_code == 200, updated.get_json()
    latest = updated.get_json()
    assert latest["record"]["api_version"] == "2024-10-21"
    assert latest["record"]["deployment"] == "custom-vectors"
    assert "api_version" not in latest["record"]["additionalFields"]
    assert "deployment" not in latest["record"]["additionalFields"]
    assert env.client.get(f"/api/user/plugins/{resource['record']['id']}?view=editor").get_json() == latest
    stored = env.services.records["actions", "personal"]["actor", resource["record"]["id"]]
    runtime_manifest = env.keyvault.keyvault_plugin_get_helper(
        stored, scope_value="actor", scope="user", return_type=env.keyvault.SecretReturnType.VALUE,
    )
    with ExitStack() as stack:
        module = _load_module(stack, "semantic_kernel_plugins.embedding_model_plugin", r"semantic_kernel_plugins\embedding_model_plugin.py")
        response = Mock()
        response.json.return_value = {"data": [{"embedding": [0.25, 0.75]}]}
        post = stack.enter_context(patch.object(module.requests, "post", return_value=response))
        plugin = module.EmbeddingModelPlugin(runtime_manifest)
        assert plugin.embed("test input") == [0.25, 0.75]
        assert post.call_args.args[0] == f"{draft['endpoint']}/openai/deployments/custom-vectors/embeddings?api-version=2024-10-21"
        assert post.call_args.kwargs["headers"]["api-key"] == "test-credential"
    assert env.schema.validate_plugin(draft), "Classic/shared schema behavior must stay unchanged."


@pytest.mark.parametrize("field,value", [
    ("api_version", 7), ("api_version", None), ("api_version", ""),
    ("deployment", []), ("deployment", {"name": "wrong type"}), ("deployment", "   "),
])
def test_embedding_editor_rejects_invalid_root_field_types(environment, field, value):
    env = environment
    draft = configured_action_payload(env, "embedding_model")
    draft[field] = value
    response = env.client.post("/api/user/plugins?view=editor", json=write_payload(draft))
    assert response.status_code == 400
    assert not env.services.writes


def test_embedding_editor_root_field_exception_does_not_apply_to_other_action_types(environment):
    env = environment
    draft = {**action_payload(), "api_version": "2024-06-01", "deployment": "must-not-be-accepted"}
    response = env.client.post("/api/user/plugins?view=editor", json=write_payload(draft))
    assert response.status_code == 400
    assert not env.services.writes


@pytest.mark.parametrize("disabled_flag", ["allow_user_plugins", "enable_semantic_kernel", "enable_user_workspace"])
def test_action_read_and_cleanup_do_not_require_authoring_flags(environment, disabled_flag):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    resource = create(env, "plugins", action_payload())
    provided = env.services.add("actions", "global", "global", {
        **action_payload(), "id": "provided-action", "name": "provided-action",
        "auth": {"type": "key", "key": "provided-credential"},
    })
    env.services.settings[disabled_flag] = False
    listed = env.client.get("/api/user/plugins?view=editor")
    assert listed.status_code == 200
    assert {item["id"] for item in listed.get_json()} == {resource["record"]["id"], provided["id"]}
    assert "test-credential" not in json.dumps(listed.get_json())
    assert "provided-credential" not in json.dumps(listed.get_json())
    assert env.client.get(f"/api/user/plugins/{resource['record']['id']}?view=editor").status_code == 200
    global_detail = env.client.get("/api/user/plugins/provided-action?view=editor&scope=global")
    assert global_detail.status_code == 200 and global_detail.get_json()["read_only"] is True
    assert env.client.get("/api/user/plugins/types?view=editor").status_code == 200
    assert patch_record(env, "plugins", resource, {"description": "Denied edit"}).status_code in {400, 403}
    assert env.client.post("/api/user/plugins?view=editor", json=write_payload(action_payload())).status_code in {400, 403}
    deleted = env.client.delete(f"/api/user/plugins/{resource['record']['id']}?view=editor")
    assert deleted.status_code == 200 and deleted.get_json() == {"success": True}
    assert not env.services.vault
    assert env.services.records["actions", "global"][provided["id"], provided["id"]] == provided
    assert env.client.delete("/api/user/plugins/provided-action?view=editor&scope=global").status_code == 403


def test_provided_actions_remain_readable_when_personal_action_governance_denies_authoring(environment):
    env = environment
    resource = create(env, "plugins", action_payload())
    provided = env.services.add("actions", "global", "global", {
        **action_payload(), "id": "provided", "name": "provided",
    })
    env.services.denied_features.add("governance_user_actions")
    env.services.containers["actions", "personal"].query_items.reset_mock()
    listed = env.client.get("/api/user/plugins?view=editor")
    assert listed.status_code == 200
    assert [record["id"] for record in listed.get_json()] == [provided["id"]]
    env.services.containers["actions", "personal"].query_items.assert_not_called()
    assert env.client.get(f"/api/user/plugins/{resource['record']['id']}?view=editor").status_code == 403
    assert env.client.delete(f"/api/user/plugins/{resource['record']['id']}?view=editor").status_code == 403
    assert env.client.get("/api/user/plugins/provided?view=editor&scope=global").status_code == 200
    options = env.client.get("/api/user/agent/settings?view=editor")
    assert options.status_code == 200 and options.get_json()["settings"]["allow_user_plugins"] is False
    env.services.denied_actions.add(provided["id"])
    assert env.client.get("/api/user/plugins?view=editor").get_json() == []
    assert env.client.get("/api/user/plugins/provided?view=editor&scope=global").status_code == 403


def test_existing_ordinary_and_provided_call_agent_actions_can_be_attached_without_creation_permission(environment):
    env = environment
    env.services.add_agent("global-target", scope="global", scope_id="global")
    ordinary = create(env, "plugins", action_payload())
    call_agent = env.services.add("actions", "global", "global", {
        **action_payload("agent"), "id": "provided-call",
        "additionalFields": {"target_agent": reference("global-target", "global", "global")},
    })
    env.services.settings["allow_user_plugins"] = False
    available = env.client.get("/api/user/plugins?view=editor")
    assert available.status_code == 200
    assert {record["id"] for record in available.get_json()} == {
        ordinary["record"]["id"], call_agent["id"],
    }
    draft = agent_payload()
    draft["actions_to_load"] = [ordinary["record"]["id"], call_agent["id"]]
    saved = create(env, "agents", draft)
    assert saved["record"]["actions_to_load"] == draft["actions_to_load"]
    options = env.client.get("/api/user/agent/settings?view=editor").get_json()
    assert options["settings"]["allow_user_agents"] is True
    assert options["settings"]["allow_user_plugins"] is False


def test_personal_call_agent_existing_bindings_survive_without_bypassing_runtime_flag(environment):
    env = environment
    env.services.add_agent()
    call_agent = create(env, "plugins", action_payload("agent"))
    draft = agent_payload()
    draft["actions_to_load"] = [call_agent["record"]["id"]]
    resource = create(env, "agents", draft)
    env.services.settings["allow_user_plugins"] = False
    assert env.client.get(f"/api/user/plugins/{call_agent['record']['id']}?view=editor").status_code == 200
    edited = patch_record(env, "agents", resource, {"instructions": "Unrelated edit"})
    assert edited.status_code == 200, edited.get_json()
    assert edited.get_json()["record"]["actions_to_load"] == draft["actions_to_load"]
    new_agent = {**agent_payload(), "name": "another-caller", "actions_to_load": draft["actions_to_load"]}
    rejected = env.client.post("/api/user/agents?view=editor", json=write_payload(new_agent))
    assert rejected.status_code == 403
    assert ("actor", new_agent["id"]) not in env.services.records["agents", "personal"]


def test_agent_name_uniqueness_uses_the_normalized_saved_name(environment):
    env = environment
    create(env, "agents", {**agent_payload(), "name": "existing_name"})
    other = create(env, "agents", {**agent_payload(), "name": "other_name"})
    original = deepcopy(env.services.records)
    renamed = patch_record(env, "agents", other, {"name": " existing_name "})
    assert renamed.status_code == 409, renamed.get_json()
    duplicate = env.client.post("/api/user/agents?view=editor", json=write_payload({
        **agent_payload(), "name": " existing_name ",
    }))
    assert duplicate.status_code == 409, duplicate.get_json()
    assert env.services.records == original


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_sql_connection_string_tests_do_not_require_separate_credentials(environment, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER=server.example.test;"
        "DATABASE=db;UID=db-user;PWD=connection-string-credential;"
    )
    draft = configured_action_payload(env, "sql_query")
    draft["auth"] = {"type": "user"}
    draft["additionalFields"].update({
        "connection_method": "connection_string", "connection_string": connection_string,
    })
    resource = create(env, "plugins", draft)
    connect = Mock(return_value=Mock())
    context = {"scope": "personal", "id": resource["record"]["id"], "name": draft["name"]}
    with patch.dict(sys.modules, {"pyodbc": module_stub("pyodbc", connect=connect)}):
        classic = env.client.post("/api/plugins/test-sql-connection", json={
            "database_type": "sqlserver", "connection_method": "connection_string",
            "connection_string": connection_string, "existing_plugin": context,
        })
        assert classic.status_code == 200, classic.get_json()
        connect.reset_mock()
        response = env.client.post("/api/plugins/test-sql-connection", json={
            "auth": resource["record"]["auth"], "additionalFields": resource["record"]["additionalFields"],
            "action_scope": "personal", "existing_plugin": context,
        })
    assert response.status_code == 200, response.get_json()
    assert connect.call_args.args[0] == connection_string
    assert "connection-string-credential" not in json.dumps(response.get_json())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
