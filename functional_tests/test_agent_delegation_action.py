# test_agent_delegation_action.py
"""Executable regression tests for the Call agent action contract.

Version: 0.261.093
Implemented in: 0.261.093

Exercise real manifest normalization, save validation, and full-agent attachment
validation. External data services are bounded mocks; no provider is contacted.
"""

import ast
import builtins
import importlib
import importlib.util
import inspect
import json
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import Mock, patch

import pytest
from flask import Flask, session
from jsonschema import Draft7Validator

from test_support.agent_delegation import (
    APP_ROOT,
    delegation_environment,
    execute_functions,
    manifest,
    module_stub,
    reference,
)


@pytest.fixture
def environment():
    with delegation_environment() as value:
        yield value


@pytest.fixture
def validation_integrations(environment):
    helper, _ = environment
    derive_endpoint = Mock(side_effect=AssertionError("Unrelated connector must not be initialized"))
    dependencies = {
        "functions_agent_delegation": helper,
        "functions_blob_storage_operations": module_stub(
            "functions_blob_storage_operations", BLOB_STORAGE_PLUGIN_TYPE="blob_storage",
            derive_blob_endpoint_from_connection_string=derive_endpoint,
        ),
        "functions_chart_operations": module_stub(
            "functions_chart_operations", CHART_DEFAULT_ENDPOINT="internal://chart",
        ),
        "functions_databricks_operations": module_stub(
            "functions_databricks_operations",
            DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE="databricks_table",
            DATABRICKS_PLUGIN_TYPE="databricks",
        ),
        "functions_snowflake_operations": module_stub(
            "functions_snowflake_operations",
            SNOWFLAKE_DEFAULT_ENDPOINT="internal://snowflake", SNOWFLAKE_PLUGIN_TYPE="snowflake",
        ),
    }
    spec = importlib.util.spec_from_file_location(
        "_tested_delegation_json_schema_validation", APP_ROOT / "json_schema_validation.py",
    )
    validator = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, dependencies):
        spec.loader.exec_module(validator)
        tree = ast.parse(
            (APP_ROOT / "semantic_kernel_plugins" / "plugin_health_checker.py").read_text(encoding="utf-8"),
        )
        health_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PluginHealthChecker"
        )
        health_class.body = [
            node for node in health_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "validate_plugin_manifest"
        ]
        assert len(health_class.body) == 1
        namespace = {
            "Dict": Dict, "Any": Any, "Tuple": Tuple, "List": List,
            "AGENT_PLUGIN_TYPE": helper.AGENT_PLUGIN_TYPE,
            "AGENT_ACTION_VALIDATION_ERROR": helper.AGENT_ACTION_VALIDATION_ERROR,
            "validate_agent_action_manifest": helper.validate_agent_action_manifest,
        }
        exec(compile(ast.Module(body=[health_class], type_ignores=[]), "plugin_health_checker.py", "exec"), namespace)
        yield validator, namespace["PluginHealthChecker"]
    derive_endpoint.assert_not_called()


def test_module_import_and_manifest_validation_are_pure():
    original_import = builtins.__import__
    blocked = ("azure", "openai", "semantic_kernel", "config", "functions_settings",
               "functions_governance", "agent_delegation_runtime", "foundry_agent_runtime")

    def checked_import(name, *args, **kwargs):
        assert not any(name == prefix or name.startswith(f"{prefix}.") for prefix in blocked), name
        return original_import(name, *args, **kwargs)

    spec = importlib.util.spec_from_file_location(
        "_pure_agent_delegation", APP_ROOT / "functions_agent_delegation.py",
    )
    helper = importlib.util.module_from_spec(spec)
    with patch.object(builtins, "__import__", side_effect=checked_import):
        spec.loader.exec_module(helper)
        result = helper.validate_agent_action_manifest(manifest())
    assert result["endpoint"] == "internal://agent"
    assert result["auth"] == {"type": "user"}


def test_real_plugin_discovery_and_metadata_are_side_effect_free(environment):
    helper, services = environment
    plugin_path = APP_ROOT / "semantic_kernel_plugins" / "agent_plugin.py"
    assert plugin_path.is_file(), "The Call agent plugin must be present for discovery."

    def kernel_function(*args, **kwargs):
        def decorate(function):
            function.is_kernel_function = True
            return function
        return decorate(args[0]) if args and callable(args[0]) else decorate

    functions = module_stub("semantic_kernel.functions", kernel_function=kernel_function)
    kernel = module_stub("semantic_kernel", functions=functions)
    logging_module = module_stub("functions_appinsights", log_event=Mock(), debug_print=Mock())
    stubs = {
        "semantic_kernel": kernel,
        "semantic_kernel.functions": functions,
        "functions_agent_delegation": helper,
        "functions_appinsights": logging_module,
    }
    original_import = builtins.__import__
    forbidden = ("azure", "openai", "agent_delegation_runtime", "foundry_agent_runtime",
                 "semantic_kernel_loader", "config")

    def checked_import(name, *args, **kwargs):
        assert not any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden), name
        return original_import(name, *args, **kwargs)

    with patch.dict(sys.modules, stubs), patch.object(sys, "path", [str(APP_ROOT), *sys.path]):
        loader = importlib.import_module("semantic_kernel_plugins.plugin_loader")
        with patch.object(loader.os, "listdir", return_value=["agent_plugin.py"]), patch.object(
            builtins, "__import__", side_effect=checked_import,
        ):
            discovered = loader.discover_plugins()
            assert len(discovered) == 1, logging_module.log_event.call_args_list
            plugin_class = next(iter(discovered.values()))
            for plugin in (plugin_class(), plugin_class(manifest())):
                assert plugin.metadata["type"] == "agent"
                assert plugin.display_name == "Call agent"
                assert set(plugin.get_functions()) == {"call_agent"}
                signature = inspect.signature(plugin.call_agent)
                assert list(signature.parameters) == ["task", "context"]
                assert signature.parameters["context"].default == ""
                assert inspect.iscoroutinefunction(plugin.call_agent)
            metadata = loader.get_all_plugin_metadata()
            assert len(metadata) == 1 and metadata[0]["type"] == "agent"
    services.settings_module.get_settings.assert_not_called()
    assert all(not container.mock_calls for container in services.containers.values())


@pytest.mark.parametrize("endpoint", [None, "", "internal://agent"])
def test_defaults_and_normalization_do_not_mutate_input(environment, endpoint):
    helper, services = environment
    source = manifest(reference(" target-id ", " USER ", " actor "), endpoint=endpoint)
    source.pop("auth")
    original = deepcopy(source)
    result = helper.validate_agent_action_manifest(source)
    assert result["additionalFields"]["target_agent"] == reference()
    assert result["auth"] == {"type": "user"}
    assert result["endpoint"] == "internal://agent"
    assert source == original
    assert result is not source
    services.settings_module.get_settings.assert_not_called()
    assert all(not container.mock_calls for container in services.containers.values())


@pytest.mark.parametrize("overrides", [
    {"type": "openapi"}, {"type": None},
    {"endpoint": "https://model.example.invalid"},
    {"endpoint": "internal://agent/target"}, {"endpoint": " internal://agent "},
    {"auth": None}, {"auth": {"type": "key", "key": "secret"}},
    {"auth": {"type": "user", "token": "secret"}},
    {"auth": {"type": "managed_identity"}}, {"auth": {"type": "workspace_identity"}},
    {"identity_id": "identity-id"},
    {"additionalFields": {}}, {"additionalFields": None},
    {"additionalFields": {"target_agent": reference(), "api_key": "secret"}},
    {"additionalFields": {"target_agent": reference(), "instructions": "override"}},
    {"additionalFields": {"target_agent": reference(), "endpoint": "https://override.invalid"}},
])
def test_manifest_rejects_auth_endpoint_and_extra_configuration(environment, overrides):
    helper, _ = environment
    with pytest.raises(ValueError):
        helper.validate_agent_action_manifest(manifest(**overrides))


@pytest.mark.parametrize("field,value", [
    ("api_key", "private-key"), ("client_secret", "private-secret"),
    ("credentials", {"password": "private-password"}),
    ("base_url", "https://override.invalid"),
    ("azure_openai_endpoint", "https://override.invalid"),
    ("auth_token", "private-token"),
])
def test_manifest_rejects_top_level_credential_and_endpoint_overrides(environment, field, value):
    helper, _ = environment
    with pytest.raises(ValueError):
        helper.validate_agent_action_manifest(manifest(**{field: value}))


@pytest.mark.parametrize("value", [None, [], "target-id", {}, {
    "id": "target-id", "scope_type": "personal",
}, {**reference(), "user_id": "someone-else"}, {**reference(), "name": "fallback"}])
def test_target_requires_only_exact_scoped_reference(environment, value):
    helper, _ = environment
    with pytest.raises(ValueError):
        helper.normalize_agent_target(value)


@pytest.mark.parametrize("field,value", [
    ("id", ""), ("id", None), ("id", 123), ("id", "a" * 1024),
    ("id", "\u00e9" * 512),
    ("id", "x/y"), ("id", "x\\y"), ("id", "x?y"), ("id", "x#y"),
    ("id", "x\ny"), ("scope_id", " "), ("scope_id", {}),
    ("scope_type", "public"), ("scope_type", "all"), ("scope_type", ""),
])
def test_malformed_reference_is_rejected(environment, field, value):
    helper, _ = environment
    with pytest.raises(ValueError):
        helper.normalize_agent_target({**reference(), field: value})


def test_scope_normalization_preserves_case_sensitive_ids(environment):
    helper, _ = environment
    assert helper.normalize_agent_target(reference(" Target-ID ", " USER ", " Actor-ID ")) == reference(
        "Target-ID", "personal", "Actor-ID",
    )
    assert helper.normalize_agent_target(reference("global-id", "GLOBAL", "global")) == reference(
        "global-id", "global", "global",
    )
    with pytest.raises(ValueError):
        helper.normalize_agent_target(reference("global-id", "global", "creator-id"))
    with pytest.raises(ValueError):
        helper.agent_reference({"id": "target", "is_group": True, "is_global": True}, "actor")


def test_existing_uuid_prefixed_personal_agent_ids_are_supported(environment):
    helper, services = environment
    legacy_id = "11111111-1111-4111-8111-111111111111_" + "a" * 100
    schema = json.loads((APP_ROOT / "static" / "json" / "schemas" / "agent.schema.json").read_text(encoding="utf-8"))
    assert Draft7Validator(schema["definitions"]["Agent"]["properties"]["id"]).is_valid(legacy_id)
    target_ref = reference(legacy_id)
    assert helper.normalize_agent_target(target_ref) == target_ref
    services.add_agent(legacy_id)
    assert helper.resolve_delegation_agent(target_ref, user_id="actor")["id"] == legacy_id


@pytest.mark.parametrize("stored,expected", [
    ({"id": "target-id", "user_id": "actor"}, reference()),
    ({"id": "target-id", "is_group": True, "group_id": "group-a"}, reference(
        "target-id", "group", "group-a")),
    ({"id": "target-id", "is_global": True}, reference("target-id", "global", "global")),
])
def test_stored_agents_have_canonical_references(environment, stored, expected):
    helper, _ = environment
    assert helper.agent_reference(stored, "actor") == expected


def test_published_schema_validates_exact_target_and_user_authentication_only():
    schema_root = APP_ROOT / "static" / "json" / "schemas"
    definition = json.loads((schema_root / "agent.definition.json").read_text(encoding="utf-8"))
    schema = json.loads((schema_root / "agent_plugin.additional_settings.schema.json").read_text(encoding="utf-8"))
    assert definition["allowedAuthTypes"] == ["user"]
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    assert validator.is_valid({"target_agent": reference()})
    assert validator.is_valid({"target_agent": reference("global", "global", "global")})
    for invalid in (
        {}, {"target_agent": reference(), "api_key": "secret"},
        {"target_agent": {**reference(), "instructions": "override"}},
        {"target_agent": reference("global", "global", "creator")},
        {"target_agent": reference("public", "public", "workspace")},
    ):
        assert not validator.is_valid(invalid), invalid


def test_real_schema_and_health_checker_accept_internal_call_agent(validation_integrations, environment):
    validator, health_checker = validation_integrations
    _, services = environment
    source = manifest(description="Delegate to a specialist", metadata={})
    original = deepcopy(source)
    assert validator.validate_plugin(source) is None
    assert health_checker.validate_plugin_manifest(source, "agent") == (True, [])
    assert validator.get_allowed_auth_types_for_plugin_type("agent") == frozenset({"user"})
    assert source == original
    services.settings_module.get_settings.assert_not_called()
    assert all(not container.mock_calls for container in services.containers.values())


@pytest.mark.parametrize("overrides", [
    {"endpoint": "https://private-endpoint.invalid/secret-path"},
    {"identity_id": "private-identity"},
    {"auth": {"type": "key", "key": "private-credential"}},
    {"auth": {"type": "user", "key": "private-credential"}},
    {"additionalFields": {"target_agent": reference(), "password": "private-password"}},
    {"additionalFields": {"target_agent": {**reference(), "scope_type": "private-scope"}}},
    {"additionalFields": {"target_agent": reference("private/invalid-id")}},
])
def test_schema_and_health_checker_return_fixed_safe_validation_errors(
    validation_integrations, environment, overrides,
):
    validator, health_checker = validation_integrations
    helper, services = environment
    source = manifest(description="Call specialist", metadata={}, **overrides)
    with pytest.raises(ValueError) as direct_error:
        helper.validate_agent_action_manifest(source)
    assert str(direct_error.value) != helper.AGENT_ACTION_VALIDATION_ERROR
    schema_error = validator.validate_plugin(source)
    healthy, health_errors = health_checker.validate_plugin_manifest(source, "agent")
    assert schema_error == helper.AGENT_ACTION_VALIDATION_ERROR
    assert healthy is False
    assert health_errors == [helper.AGENT_ACTION_VALIDATION_ERROR]
    assert "private-" not in schema_error
    assert "private-" not in json.dumps(health_errors)
    services.settings_module.get_settings.assert_not_called()
    assert all(not container.mock_calls for container in services.containers.values())


@pytest.mark.parametrize("target_type", ["local", "aifoundry", "new_foundry", "foundry_workflow"])
def test_save_validates_without_constructing_provider(environment, target_type):
    helper, services = environment
    services.add_agent(agent_type=target_type, instructions="private instructions",
                       azure_openai_gpt_key="private-key")
    source = manifest(is_enabled=False)
    validated = helper.validate_agent_action_for_scope(
        source, user_id="actor", scope_type="personal", scope_id="actor",
    )
    assert validated == source
    services.governance.ensure_action_type_access.assert_called_once_with(
        "governance_user_actions", "actor", "agent", "personal",
    )
    services.containers["agents", "personal"].read_item.assert_called_once_with(
        item="target-id", partition_key="actor",
    )
    assert all(not container.upsert_item.called for container in services.containers.values())
    services.activity.log_agent_update.assert_not_called()


@pytest.mark.parametrize("scope,scope_id", [
    ("personal", "actor"), ("group", "group-a"), ("global", "global"),
])
@pytest.mark.parametrize("invalid", [False, True])
def test_storage_save_executes_shared_validation_before_persistence(environment, scope, scope_id, invalid):
    helper, services = environment
    services.add_agent("target-id", scope, scope_id)
    action = manifest(reference("target-id", scope, scope_id))
    if invalid:
        action["identity_id"] = "forged-identity"
    container = services.containers["actions", scope]
    container.upsert_item.side_effect = lambda *, body: deepcopy(body)
    keyvault = Mock(side_effect=lambda payload, **kwargs: payload)
    namespace = {
        "Dict": Dict, "Any": Any, "Optional": Optional, "datetime": datetime,
        "uuid": uuid, "traceback": Mock(), "print": Mock(), "debug_print": Mock(),
        "validate_agent_action_for_scope": helper.validate_agent_action_for_scope,
        "get_current_user_id": Mock(return_value="actor"),
        "get_personal_action": Mock(return_value=None),
        "SecretReturnType": SimpleNamespace(NAME="name", TRIGGER="trigger"),
        "exceptions": services.modules["azure.cosmos.exceptions"],
        "ensure_action_type_access": services.governance.ensure_action_type_access,
        "validate_action_identity_reference": Mock(),
        "keyvault_plugin_save_helper": keyvault,
        "_clean_action": lambda stored, *args: stored,
        "bump_chat_bootstrap_global_cache_version": services.cache.bump_chat_bootstrap_global_cache_version,
        "bump_chat_bootstrap_user_cache_version": services.cache.bump_chat_bootstrap_user_cache_version,
        f"cosmos_{scope}_actions_container": container,
        f"WORKSPACE_IDENTITY_SCOPE_{scope.upper()}": scope,
    }
    function_name = f"save_{scope}_action"
    execute_functions(f"functions_{scope}_actions.py", {function_name}, namespace)
    args = (action,) if scope == "global" else (scope_id, action)
    kwargs = {"user_id": "actor"} if scope in ("group", "global") else {"enforce_governance": False}
    app = Flask(__name__)
    app.secret_key = "test-only"
    with app.test_request_context():
        session["user"] = {"oid": "actor", "roles": ["Admin"]}
        if invalid:
            with pytest.raises(ValueError):
                namespace[function_name](*args, **kwargs)
            container.upsert_item.assert_not_called()
            keyvault.assert_not_called()
        else:
            stored = namespace[function_name](*args, **kwargs)
            assert stored["additionalFields"]["target_agent"] == reference("target-id", scope, scope_id)
            assert stored["auth"] == {"type": "user"}
            container.upsert_item.assert_called_once()
            services.containers["agents", scope].read_item.assert_called_once()


def test_ordinary_action_save_and_legacy_bindings_are_unchanged(environment):
    helper, services = environment
    ordinary = {"id": "ordinary", "type": "openapi", "auth": {"type": "key", "key": "preserve"}}
    assert helper.validate_agent_action_for_scope(
        ordinary, user_id=None, scope_type="personal", scope_id="actor",
    ) is ordinary
    services.add_action(type="openapi", id="ordinary", name="legacy_search")
    services.add_action(id="unrelated-delegation")
    agent = {"id": "caller", "actions_to_load": ["ordinary", "legacy_search"]}
    original = deepcopy(agent)
    helper.validate_agent_delegation_bindings(
        agent, user_id="actor", scope_type="personal", scope_id="actor",
    )
    assert agent == original
    assert all(not container.read_item.called for container in services.containers.values())
    services.governance.ensure_action_type_access.assert_not_called()


def test_full_agent_validator_accepts_exact_attachment_without_mutation(environment):
    helper, services = environment
    services.add_agent()
    services.add_action()
    caller = {"id": "caller-id", "agent_type": "local", "actions_to_load": ["action-id", "legacy_search"]}
    original = deepcopy(caller)
    helper.validate_agent_delegation_bindings(
        caller, user_id="actor", scope_type="personal", scope_id="actor",
    )
    assert caller == original
    services.governance.ensure_action_type_access.assert_called_once()


@pytest.mark.parametrize("caller_type", ["aifoundry", "new_foundry", "foundry_workflow"])
def test_foundry_callers_cannot_attach_simplechat_actions(environment, caller_type):
    helper, services = environment
    services.add_agent()
    services.add_action()
    with pytest.raises(ValueError, match="Foundry"):
        helper.validate_agent_delegation_bindings(
            {"id": "caller", "agent_type": caller_type, "actions_to_load": ["action-id"]},
            user_id="actor", scope_type="personal", scope_id="actor",
        )


def test_full_agent_validator_rejects_action_name_and_self_reference(environment):
    helper, services = environment
    services.add_agent()
    services.add_action()
    with pytest.raises(ValueError, match="ID"):
        helper.validate_agent_delegation_bindings(
            {"id": "caller", "actions_to_load": ["delegate_task"]},
            user_id="actor", scope_type="personal", scope_id="actor",
        )
    with pytest.raises(ValueError, match="itself"):
        helper.validate_agent_delegation_bindings(
            {"id": "target-id", "actions_to_load": ["action-id"]},
            user_id="actor", scope_type="personal", scope_id="actor",
        )


def test_unchanged_bindings_allow_unrelated_edits_but_execution_rechecks(environment):
    helper, services = environment
    existing = services.add_agent("caller", actions_to_load=["action-id"])
    services.add_action()
    services.denied_features.add("governance_user_actions")
    edited = {**existing, "instructions": "updated unrelated instructions"}
    helper.validate_agent_delegation_bindings(
        edited, existing_agent=existing, user_id="actor",
        scope_type="personal", scope_id="actor",
    )
    services.governance.ensure_action_type_access.assert_not_called()
    services.settings_module.get_settings.assert_not_called()
    assert all(not container.mock_calls for container in services.containers.values())
    with pytest.raises(PermissionError):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller"), user_id="actor",
        )


@pytest.mark.parametrize("target_state", ["missing", "disabled"])
def test_unrelated_model_edits_do_not_resolve_stale_targets(environment, target_state):
    helper, services = environment
    existing = services.add_agent("caller", actions_to_load=["action-id"])
    services.add_action()
    if target_state == "disabled":
        services.add_agent(is_enabled=False)
    edited = {**existing, "model_endpoint_id": "replacement-model"}
    helper.validate_agent_delegation_bindings(
        edited, existing_agent=existing, user_id="actor",
        scope_type="personal", scope_id="actor",
    )
    services.settings_module.get_settings.assert_not_called()
    assert all(not container.mock_calls for container in services.containers.values())
    with pytest.raises(LookupError):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller"), user_id="actor",
        )
    assert services.containers["agents", "personal"].read_item.call_args.kwargs == {
        "item": "target-id", "partition_key": "actor",
    }


def test_changed_agent_type_does_not_skip_attachment_revalidation(environment):
    helper, services = environment
    existing = services.add_agent("caller", actions_to_load=["action-id"])
    services.add_action()
    with pytest.raises(ValueError, match="Foundry"):
        helper.validate_agent_delegation_bindings(
            {**existing, "agent_type": "new_foundry"}, existing_agent=existing,
            user_id="actor", scope_type="personal", scope_id="actor",
        )


@pytest.mark.parametrize("roles,denied_target,allowed", [
    (["Admin"], False, True), (["User"], False, False), (["Admin"], True, False),
])
def test_new_global_action_needs_admin_and_target_policy_not_unsaved_action_acl(
    environment, roles, denied_target, allowed,
):
    helper, services = environment
    services.add_agent("target-id", "global", "global")
    source = manifest(reference("target-id", "global", "global"))
    source.pop("id")
    services.governance.ensure_global_action_access.side_effect = PermissionError("No saved action policy")
    if denied_target:
        services.denied_agents.add("target-id")
    app = Flask(__name__)
    app.secret_key = "test-only"
    with app.test_request_context():
        session["user"] = {"oid": "actor", "roles": roles}
        if allowed:
            validated = helper.validate_agent_action_for_scope(
                source, user_id="actor", scope_type="global", scope_id="global",
            )
            assert "id" not in validated
            services.governance.ensure_governance_access.assert_called_once_with(
                "governance_global_agents_usage", "actor",
                item_entity_type="global_agent", item_id="target-id",
            )
        else:
            with pytest.raises(PermissionError):
                helper.validate_agent_action_for_scope(
                    source, user_id="actor", scope_type="global", scope_id="global",
                )
    services.governance.ensure_global_action_access.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
