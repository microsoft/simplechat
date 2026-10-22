# test_sql_managed_identity_authentication.py
"""
Functional tests for consistent SQL managed identity authentication.
Version: 0.261.373
Implemented in: 0.261.372

Exercise real identity storage/hydration, SQL handlers, query/schema plugins and
connection builders with SDK-shaped Cosmos responses and blocked network access.
"""

import ast
from contextlib import ExitStack
from copy import deepcopy
import importlib.util
import json
import logging
from pathlib import PurePosixPath
import socket
import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Dict
from unittest.mock import Mock

from azure.core import MatchConditions
from azure.cosmos import exceptions
from jsonschema import Draft7Validator
import pytest

from test_sql_connection_diagnostics_runtime import (
    APP_ROOT,
    block_network as sql_block_network,
    load_module,
    plugin_manifest,
    runtime as sql_runtime,
)
from test_support.agent_delegation import execute_functions, module_stub
from test_support.m365 import CosmosContainer
from test_workspace_authoring_backend import _load_module as load_authoring_module, environment


CLIENT_ID = "11111111-2222-4333-8444-555555555555"
STALE_CLIENT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
STALE_PASSWORD = "synthetic-inactive-sql-password"


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    sql_block_network.__wrapped__(monkeypatch)


def test_network_guard_blocks_dns_before_external_io():
    with pytest.raises(AssertionError, match="must not contact live services"):
        socket.getaddrinfo("sql-regression.invalid", 1433)


@pytest.mark.parametrize("loader", [load_module, load_authoring_module])
@pytest.mark.parametrize("relative_path", [
    r"semantic_kernel_plugins\rocksdb_plugin.py",
    str(PurePosixPath("semantic_kernel_plugins", "rocksdb_plugin.py")),
])
def test_shared_module_loaders_resolve_host_path_components(monkeypatch, loader, relative_path):
    monkeypatch.setitem(loader.__globals__, "APP_ROOT", PurePosixPath("virtual-app"))
    spec = SimpleNamespace(loader=SimpleNamespace(exec_module=Mock()))
    spec_factory = Mock(return_value=spec)
    module = ModuleType("sql_portable_loader_test")
    monkeypatch.setattr(importlib.util, "spec_from_file_location", spec_factory)
    monkeypatch.setattr(importlib.util, "module_from_spec", Mock(return_value=module))
    with ExitStack() as stack:
        owner = monkeypatch if loader is load_module else stack
        loaded = loader(owner, "sql_portable_loader_test", relative_path)
    assert loaded is module
    assert spec_factory.call_args.args[1] == PurePosixPath(
        "virtual-app", "semantic_kernel_plugins", "rocksdb_plugin.py",
    )
    spec.loader.exec_module.assert_called_once_with(module)


@pytest.fixture
def sql_environment(environment, monkeypatch):
    env = environment
    with monkeypatch.context() as scoped:
        config = sys.modules["config"]
        containers = {}
        for scope, field in (
            ("personal", "user_id"), ("group", "group_id"),
            ("public", "public_workspace_id"), ("global", "global_id"),
        ):
            containers[scope] = CosmosContainer(field)
            scoped.setattr(
                config, f"cosmos_{scope}_workspace_identities_container", containers[scope], raising=False,
            )
        scoped.setitem(sys.modules, "azure.core", module_stub("azure.core", MatchConditions=MatchConditions))
        scoped.setitem(sys.modules, "azure.cosmos.exceptions", exceptions)
        identities = load_module(scoped, "functions_workspace_identities", "functions_workspace_identities.py")
        scoped.setitem(env.namespace, "hydrate_action_identity_reference", identities.hydrate_action_identity_reference)
        yield SimpleNamespace(env=env, identities=identities, containers=containers)


@pytest.fixture
def runtime(monkeypatch):
    with monkeypatch.context() as scoped:
        yield sql_runtime.__wrapped__(scoped)


def create_identity(sql_environment, client_id, *, scope="personal", owner="actor"):
    identities = sql_environment.identities
    credentials = {"auth_type": "managed_identity"}
    if client_id is not None:
        credentials["managed_identity_client_id"] = client_id
    created = identities.create_workspace_identity(
        scope, owner,
        {"name": "SQL workload identity", "usage_contexts": ["action"], "credentials": credentials},
        "actor",
    )
    return created["identity_id"]


def install_driver(monkeypatch, *, error=None):
    connection = Mock()
    connect = Mock(side_effect=error) if error else Mock(return_value=connection)
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    return connect, connection


def check_managed_identity(connection_string, client_id):
    assert ";Authentication=ActiveDirectoryMsi" in connection_string
    assert "PWD=" not in connection_string
    assert "Trusted_Connection=" not in connection_string
    assert STALE_PASSWORD not in connection_string
    if client_id:
        assert f";UID={client_id}" in connection_string
    else:
        assert "UID=" not in connection_string


@pytest.mark.parametrize("kind", ["query", "schema"])
@pytest.mark.parametrize("engine", ["sqlserver", "azure_sql", "azuresql"])
@pytest.mark.parametrize("canonical", [False, True])
@pytest.mark.parametrize("client_id", [None, CLIENT_ID])
def test_plugins_honor_managed_identity_over_inactive_password_fields(
    runtime, monkeypatch, kind, engine, canonical, client_id,
):
    manifest = plugin_manifest(engine)
    manifest["additionalFields"].update({"username": "old-sql-user", "password": STALE_PASSWORD})
    if canonical:
        manifest["auth"] = {"type": "identity", "identity": "managed_identity"}
        manifest["additionalFields"]["auth_type"] = "username_password"
    if client_id is not None:
        manifest["additionalFields"]["managed_identity_client_id"] = client_id
    original = deepcopy(manifest)
    connect, connection = install_driver(monkeypatch)
    plugin = getattr(runtime, kind)(manifest)
    result = plugin._get_connection()
    repeated = plugin._get_connection()
    assert result is connection and repeated is connection
    connect.assert_called_once()
    check_managed_identity(connect.call_args.args[0], client_id)
    assert manifest == original


@pytest.mark.parametrize("kind", ["query", "schema"])
def test_direct_manifest_client_id_is_supported(runtime, monkeypatch, kind):
    manifest = plugin_manifest()
    manifest["managed_identity_client_id"] = CLIENT_ID
    connect, _ = install_driver(monkeypatch)
    plugin = getattr(runtime, kind)(manifest)
    plugin._get_connection()
    check_managed_identity(connect.call_args.args[0], CLIENT_ID)


@pytest.mark.parametrize("scope,owner", [("personal", "actor"), ("group", "group-a"), ("global", "global")])
@pytest.mark.parametrize("client_id", [None, CLIENT_ID])
@pytest.mark.parametrize("kind", ["query", "schema"])
def test_real_identity_hydration_overrides_stale_selectors_without_persisting(
    sql_environment, runtime, monkeypatch, scope, owner, client_id, kind,
):
    identities = sql_environment.identities
    identity_id = create_identity(sql_environment, client_id, scope=scope, owner=owner)
    action = plugin_manifest()
    action.update({"type": f"sql_{kind}", "identity_id": identity_id})
    action["auth"] = {"type": "identity", "identity": identity_id}
    action["managed_identity_client_id"] = STALE_CLIENT_ID
    action["additionalFields"]["managed_identity_client_id"] = STALE_CLIENT_ID
    original = deepcopy(action)
    stored = deepcopy(sql_environment.containers[scope].items)
    hydrated = identities.hydrate_action_identity_reference(
        action, scope, owner, return_type=sql_environment.env.keyvault.SecretReturnType.VALUE,
    )
    connect, _ = install_driver(monkeypatch)
    plugin = getattr(runtime, kind)(hydrated)
    plugin._get_connection()
    check_managed_identity(connect.call_args.args[0], client_id)
    assert action == original
    assert sql_environment.containers[scope].items == stored


@pytest.mark.parametrize("editor", [False, True])
@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("client_id", [None, CLIENT_ID])
@pytest.mark.parametrize("kind", ["query", "schema"])
def test_connection_checks_use_real_reusable_identity_hydration(
    sql_environment, monkeypatch, editor, saved, client_id, kind,
):
    env = sql_environment.env
    identity_id = create_identity(sql_environment, client_id)
    fields = {
        "database_type": "azure_sql", "server": "db.example.test", "database": "test-db",
        "connection_method": "parameters", "managed_identity_client_id": STALE_CLIENT_ID,
        "username": "old-sql-user", "password": STALE_PASSWORD,
    }
    payload = {**fields, "identity_id": identity_id, "action_scope": "personal"}
    if editor:
        payload.update({
            "type": f"sql_{kind}", "auth": {"type": "identity", "identity": identity_id},
            "additionalFields": fields,
        })
    if saved:
        env.services.add("actions", "personal", "actor", {
            "id": "saved-sql", "name": "saved_sql", "user_id": "actor",
            "type": f"sql_{kind}", "identity_id": identity_id,
            "auth": {"type": "identity", "identity": identity_id}, "additionalFields": fields,
        })
        payload["existing_plugin"] = {"scope": "personal", "id": "saved-sql", "name": "saved_sql"}
    original = deepcopy(env.services.records)
    connect, connection = install_driver(monkeypatch)
    response = env.client.post("/api/plugins/test-sql-connection", json=payload)
    assert response.status_code == 200, response.get_json()
    connect.assert_called_once()
    check_managed_identity(connect.call_args.args[0], client_id)
    connection.cursor.return_value.execute.assert_called_once_with("SELECT 1")
    connection.close.assert_called_once()
    assert env.services.records == original
    assert env.services.writes == []


def test_saved_action_loading_preserves_selected_identity(sql_environment, runtime, monkeypatch):
    env = sql_environment.env
    identity_id = create_identity(sql_environment, CLIENT_ID)
    namespace = {
        **env.namespace,
        "bind_action_origin": sys.modules["functions_action_manifest"].bind_action_origin,
        "retired_action_management_view": sys.modules["functions_legacy_action_management"].retired_action_management_view,
        "keyvault_plugin_get_helper": env.keyvault.keyvault_plugin_get_helper,
    }
    execute_functions("functions_personal_actions.py", {"_clean_action"}, namespace)
    action = plugin_manifest()
    action.update({"id": "saved-sql", "type": "sql_query", "identity_id": identity_id, "user_id": "actor"})
    original = deepcopy(action)
    loaded = namespace["_clean_action"](action, "actor", env.keyvault.SecretReturnType.VALUE)
    connect, _ = install_driver(monkeypatch)
    plugin = runtime.query(loaded)
    plugin._get_connection()
    check_managed_identity(connect.call_args.args[0], CLIENT_ID)
    assert action == original


@pytest.mark.parametrize("kind", ["query", "schema"])
def test_switching_to_a_password_identity_overrides_stale_managed_identity(
    sql_environment, runtime, monkeypatch, kind,
):
    env = sql_environment.env
    identities = sql_environment.identities
    created = identities.create_workspace_identity(
        "personal", "actor",
        {"name": "SQL password identity", "usage_contexts": ["action"], "credentials": {
            "auth_type": "username_password", "username": "identity-user", "password": "synthetic-identity-password",
        }},
        "actor",
    )
    action = plugin_manifest()
    action.update({"type": f"sql_{kind}", "identity_id": created["identity_id"]})
    action["auth"] = {"type": "identity", "identity": "managed_identity"}
    action["additionalFields"]["managed_identity_client_id"] = STALE_CLIENT_ID
    hydrated = identities.hydrate_action_identity_reference(
        action, "personal", "actor", return_type=env.keyvault.SecretReturnType.VALUE,
    )
    connect, _ = install_driver(monkeypatch)
    plugin = getattr(runtime, kind)(hydrated)
    plugin._get_connection()
    connection_string = connect.call_args.args[0]
    assert ";UID=identity-user;PWD=synthetic-identity-password" in connection_string
    assert "Authentication=ActiveDirectoryMsi" not in connection_string
    assert STALE_CLIENT_ID not in connection_string
    response = env.client.post("/api/plugins/test-sql-connection", json={
        **action, "action_scope": "personal",
    })
    assert response.status_code == 200, response.get_json()
    assert connect.call_args.args[0] == connection_string


def test_companion_schema_uses_the_same_identity(sql_environment, runtime, monkeypatch):
    identity_id = create_identity(sql_environment, CLIENT_ID)
    manifest = plugin_manifest()
    manifest.update({"type": "sql_query", "identity_id": identity_id})
    hydrated = sql_environment.identities.hydrate_action_identity_reference(
        manifest, "personal", "actor", return_type=sql_environment.env.keyvault.SecretReturnType.VALUE,
    )
    tree = ast.parse((APP_ROOT / "semantic_kernel_plugins" / "logged_plugin_loader.py").read_text(encoding="utf-8"))
    loader_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LoggedPluginLoader")
    method = next(node for node in loader_class.body if isinstance(node, ast.FunctionDef) and node.name == "_auto_create_companion_schema_plugin")
    namespace = {
        "Dict": Dict, "Any": Any, "SQLSchemaPlugin": runtime.schema,
        "BasePlugin": sys.modules["semantic_kernel_plugins.base_plugin"].BasePlugin,
        "copy_action_manifest": sys.modules["functions_action_manifest"].copy_action_manifest,
        "register_action_plugin": Mock(), "logging": logging, "log_event": Mock(),
        "ActionCredentialsRequired": type("ActionCredentialsRequired", (Exception,), {}),
        "M365PolicyError": type("M365PolicyError", (Exception,), {}),
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<sql-schema-companion>", "exec"), namespace)
    loader = SimpleNamespace(kernel=SimpleNamespace(plugins={}), plugin_instances=[], _wrap_plugin_functions=Mock())
    namespace["_auto_create_companion_schema_plugin"](loader, hydrated, "database_query")
    assert len(loader.plugin_instances) == 1
    connect, _ = install_driver(monkeypatch)
    query = runtime.query(hydrated)
    query._get_connection()
    loader.plugin_instances[0]._get_connection()
    assert connect.call_count == 2
    assert connect.call_args_list[0].args == connect.call_args_list[1].args
    check_managed_identity(connect.call_args.args[0], CLIENT_ID)
    namespace["register_action_plugin"].assert_called_once()


@pytest.mark.parametrize("kind", ["query", "schema"])
@pytest.mark.parametrize("selector", [None, "", CLIENT_ID, "not-a-guid;PWD=untrusted"])
def test_complete_connection_strings_remain_authoritative(runtime, monkeypatch, kind, selector):
    connection_string = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=explicit;DATABASE=db;Authentication=ActiveDirectoryMsi"
    manifest = plugin_manifest(connection_string=connection_string)
    manifest["additionalFields"]["managed_identity_client_id"] = selector
    connect, _ = install_driver(monkeypatch)
    plugin = getattr(runtime, kind)(manifest)
    plugin._get_connection()
    assert connect.call_args.args == (connection_string,)


@pytest.mark.parametrize("kind", ["query", "schema"])
@pytest.mark.parametrize("selector", ["not-a-guid;PWD=untrusted", "0" * 36, "00000000-0000-0000-0000-000000000000", True, 7, {}, []])
def test_invalid_selectors_fail_safely_before_driver_connect(runtime, monkeypatch, kind, selector):
    manifest = plugin_manifest()
    manifest["additionalFields"]["managed_identity_client_id"] = selector
    connect, _ = install_driver(monkeypatch)
    plugin = getattr(runtime, kind)(manifest)
    runtime.records.clear()
    with pytest.raises(runtime.diagnostics.SqlConnectionError) as caught:
        plugin._get_connection()
    assert caught.value.diagnostic.code == "sql_configuration_rejected"
    connect.assert_not_called()
    assert "untrusted" not in str(caught.value)
    assert "untrusted" not in json.dumps([record.__dict__ for record in runtime.records], default=str)


@pytest.mark.parametrize("editor", [False, True])
def test_invalid_inline_selector_has_safe_configuration_feedback(sql_environment, monkeypatch, editor):
    fields = {
        "database_type": "sqlserver", "server": "db.example.test", "database": "test-db",
        "auth_type": "managed_identity", "managed_identity_client_id": "invalid;PWD=untrusted",
    }
    payload = dict(fields)
    if editor:
        payload.update({"type": "sql_query", "auth": {"type": "identity", "identity": "managed_identity"}, "additionalFields": fields})
    connect, _ = install_driver(monkeypatch)
    response = sql_environment.env.client.post("/api/plugins/test-sql-connection", json=payload)
    body = response.get_json()
    assert response.status_code == 400
    assert body["error_code"] == "sql_configuration_rejected"
    assert "managed identity client ID" in body["error"]
    assert "untrusted" not in json.dumps(body)
    connect.assert_not_called()


@pytest.mark.parametrize("editor", [False, True])
@pytest.mark.parametrize("client_id", [None, CLIENT_ID])
def test_inactive_masked_password_is_not_resolved(sql_environment, monkeypatch, editor, client_id):
    env = sql_environment.env
    fields = {
        "database_type": "sqlserver", "server": "db.example.test", "database": "test-db",
        "auth_type": "managed_identity", "username": "old-sql-user",
        "password": env.keyvault.ui_trigger_word, "managed_identity_client_id": client_id,
    }
    payload = dict(fields)
    if editor:
        payload.update({"type": "sql_query", "auth": {"type": "identity", "identity": "managed_identity"}, "additionalFields": fields})
    connect, _ = install_driver(monkeypatch)
    response = env.client.post("/api/plugins/test-sql-connection", json=payload)
    assert response.status_code == 200, response.get_json()
    check_managed_identity(connect.call_args.args[0], client_id)
    assert env.services.secret_reads == []


@pytest.mark.parametrize("editor", [False, True])
def test_connection_check_preserves_a_complete_connection_string(sql_environment, monkeypatch, editor):
    connection_string = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=explicit;DATABASE=db;Authentication=ActiveDirectoryMsi"
    fields = {
        "database_type": "sqlserver", "connection_method": "connection_string",
        "connection_string": connection_string, "auth_type": "managed_identity",
        "managed_identity_client_id": "invalid-inactive-selector",
    }
    payload = dict(fields)
    if editor:
        payload.update({"type": "sql_query", "auth": {"type": "identity", "identity": "managed_identity"}, "additionalFields": fields})
    connect, _ = install_driver(monkeypatch)
    response = sql_environment.env.client.post("/api/plugins/test-sql-connection", json=payload)
    assert response.status_code == 200, response.get_json()
    assert connect.call_args.args == (connection_string,)


@pytest.mark.parametrize("auth", [[], "managed_identity", True])
def test_malformed_authentication_is_rejected_before_connect(sql_environment, monkeypatch, auth):
    connect, _ = install_driver(monkeypatch)
    response = sql_environment.env.client.post("/api/plugins/test-sql-connection", json={
        "auth": auth, "database_type": "sqlserver", "server": "db.example.test", "database": "test-db",
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "Authentication must be an object."
    connect.assert_not_called()


@pytest.mark.parametrize("kind", ["query", "schema"])
def test_selector_is_declared_in_the_sql_configuration_schema(kind):
    path = APP_ROOT / "static" / "json" / "schemas" / f"sql_{kind}_plugin.additional_settings.schema.json"
    definition = json.loads(path.read_text(encoding="utf-8"))
    errors = list(Draft7Validator(definition).iter_errors({
        "database_type": "azure_sql", "managed_identity_client_id": CLIENT_ID,
    }))
    assert "managed_identity_client_id" in definition["properties"]
    assert errors == []


@pytest.mark.parametrize("kind", ["query", "schema"])
def test_managed_identity_manifest_passes_real_plugin_validation(sql_environment, kind):
    manifest = {
        "name": "sql_identity", "type": f"sql_{kind}", "endpoint": f"sql://sql_{kind}",
        "description": "Synthetic SQL identity validation", "metadata": {},
        "auth": {"type": "identity", "identity": "managed_identity"},
        "additionalFields": {
            "database_type": "sqlserver", "server": "db.example.test", "database": "test-db",
            "managed_identity_client_id": CLIENT_ID,
        },
    }
    error = sql_environment.env.schema.validate_plugin(manifest)
    assert error is None, error


@pytest.mark.parametrize("kind", ["query", "schema"])
def test_managed_identity_login_rejection_does_not_retry_or_fall_back(runtime, monkeypatch, kind):
    connect, _ = install_driver(monkeypatch, error=Exception("28000", "synthetic provider rejection"))
    manifest = plugin_manifest()
    manifest["additionalFields"]["managed_identity_client_id"] = CLIENT_ID
    plugin = getattr(runtime, kind)(manifest)
    with pytest.raises(runtime.diagnostics.SqlConnectionError) as caught:
        plugin._get_connection()
    assert caught.value.diagnostic.code == "sql_authentication_failed"
    connect.assert_called_once()
    check_managed_identity(connect.call_args.args[0], CLIENT_ID)
    events = [record for record in runtime.records if getattr(record, "sc_message", "").startswith("[SQL_CONNECTION]")]
    assert events[-1].sc_sql_auth_mode == "managed_identity"
    assert CLIENT_ID not in json.dumps(events[-1].__dict__, default=str)


@pytest.mark.parametrize("client_id", [None, CLIENT_ID])
def test_azure_sql_factory_uses_the_shared_identity_selector(runtime, monkeypatch, client_id):
    factory = load_module(
        monkeypatch, "semantic_kernel_plugins.sql_plugin_factory", r"semantic_kernel_plugins\sql_plugin_factory.py",
    )
    kwargs = {} if client_id is None else {"managed_identity_client_id": client_id}
    schema, query = factory.SQLPluginFactory.create_azure_sql_plugins("db.example.test", "test-db", **kwargs)
    connect, _ = install_driver(monkeypatch)
    schema._get_connection()
    query._get_connection()
    assert connect.call_count == 2
    for call in connect.call_args_list:
        check_managed_identity(call.args[0], client_id)
