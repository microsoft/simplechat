# test_sql_connection_diagnostics_runtime.py
"""
Functional tests for SQL connection diagnostics across routes, plugins, and logging.
Version: 0.261.373
Implemented in: 0.261.351

Run real plugin classes, connection builders, Flask handlers, and log_event against
isolated provider seams. No SQL, Cosmos, Azure Monitor, or network calls are allowed.
"""

import builtins
from copy import deepcopy
import importlib.util
import json
import logging
import re
from pathlib import Path, PureWindowsPath
import socket
import sys
from types import SimpleNamespace
import traceback
from unittest.mock import Mock

import pytest

from test_support.agent_delegation import module_stub
from test_workspace_authoring_backend import environment  # noqa: F401


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
SECRET = "private-provider-credential"


def load_module(monkeypatch, name, filename):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT.joinpath(*PureWindowsPath(filename).parts))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("SQL diagnostic tests must not contact live services.")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_ROOT))
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", module_stub(
        "azure.monitor.opentelemetry", configure_azure_monitor=Mock(
            side_effect=AssertionError("Exporter configuration is not allowed in these tests."),
        ),
    ))
    settings = {"enable_debug_logging": False}
    monkeypatch.setitem(sys.modules, "app_settings_cache", module_stub(
        "app_settings_cache", get_settings_cache=lambda: settings,
    ))
    diagnostics = load_module(
        monkeypatch, "semantic_kernel_plugins.sql_connection_diagnostics",
        r"semantic_kernel_plugins\sql_connection_diagnostics.py",
    )
    logger_module = load_module(monkeypatch, "functions_appinsights", "functions_appinsights.py")
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.Logger("sql-connection-test", level=logging.DEBUG)
    logger.addHandler(Capture())
    logger_module._appinsights_logger = logger
    monkeypatch.setitem(sys.modules, "functions_debug", module_stub(
        "functions_debug", debug_print=logger_module.debug_print,
    ))
    monkeypatch.setitem(sys.modules, "semantic_kernel.functions", module_stub(
        "semantic_kernel.functions", kernel_function=lambda **kwargs: lambda function: function,
    ))
    monkeypatch.setitem(sys.modules, "semantic_kernel_plugins.plugin_invocation_logger", module_stub(
        "semantic_kernel_plugins.plugin_invocation_logger",
        plugin_function_logger=lambda *args: lambda function: function,
    ))
    odbc = load_module(
        monkeypatch, "semantic_kernel_plugins.sql_odbc_utils",
        r"semantic_kernel_plugins\sql_odbc_utils.py",
    )
    query = load_module(
        monkeypatch, "semantic_kernel_plugins.sql_query_plugin",
        r"semantic_kernel_plugins\sql_query_plugin.py",
    )
    schema = load_module(
        monkeypatch, "semantic_kernel_plugins.sql_schema_plugin",
        r"semantic_kernel_plugins\sql_schema_plugin.py",
    )
    return SimpleNamespace(
        query=query.SQLQueryPlugin, schema=schema.SQLSchemaPlugin,
        diagnostics=diagnostics, logging=logger_module, records=records,
        settings=settings, odbc=odbc,
    )


def plugin_manifest(engine="sqlserver", auth_type="managed_identity", connection_string=None):
    return {
        "name": "sql_test", "auth": {"type": auth_type},
        "additionalFields": {
            "database_type": engine, "server": "db.example.test", "database": "test-db",
            "username": "sql-user" if auth_type == "username_password" else None,
            "password": SECRET if auth_type == "username_password" else None,
            "auth_type": auth_type, "connection_string": connection_string, "timeout": 7,
        },
    }


@pytest.mark.parametrize("kind", ["query", "schema"])
@pytest.mark.parametrize("engine,module,error,expected", [
    ("sqlserver", "pyodbc", Exception("28000", f"[28000] {SECRET} (18456) (SQLDriverConnect)"), "sql_authentication_failed"),
    ("azure_sql", "pyodbc", Exception("HYT00", SECRET), "sql_connection_timeout"),
    ("postgresql", "psycopg2", type("OperationalError", (Exception,), {"pgcode": "28P01"})(SECRET), "sql_authentication_failed"),
    ("mysql", "pymysql", Exception(1045, SECRET), "sql_authentication_failed"),
    ("sqlite", "sqlite3", Exception(SECRET), "sql_connection_failed"),
])
@pytest.mark.parametrize("debug", [False, True])
def test_plugins_log_safe_structured_connection_failures(runtime, monkeypatch, capsys, kind, engine, module, error, expected, debug):
    runtime.settings["enable_debug_logging"] = debug
    connect = Mock(side_effect=error)
    monkeypatch.setitem(sys.modules, module, module_stub(module, connect=connect))
    plugin = getattr(runtime, kind)(plugin_manifest(engine))
    runtime.records.clear()
    capsys.readouterr()
    with pytest.raises(runtime.diagnostics.SqlConnectionError) as caught:
        plugin._get_connection()
    formatted_trace = "".join(traceback.format_exception(caught.value))
    assert SECRET not in formatted_trace
    assert caught.value.diagnostic.code == expected
    assert plugin._connection is None
    connect.assert_called_once()
    events = [record for record in runtime.records if getattr(record, "sc_message", "").startswith("[SQL_CONNECTION]")]
    assert len(events) == 1
    event = events[0]
    assert event.levelno == logging.WARNING
    assert event.sc_failure_code == expected
    assert event.sc_sql_engine == ("sqlserver" if engine == "azure_sql" else engine)
    assert event.sc_operation == f"sql_{kind}_connect"
    assert SECRET not in json.dumps([record.__dict__ for record in runtime.records], default=str)
    assert SECRET not in capsys.readouterr().out


@pytest.mark.parametrize("method,args", [
    ("execute_query", ("SELECT 1",)),
    ("execute_scalar", ("SELECT 1",)),
    ("query_database", ("Read a value", "SELECT 1")),
])
def test_query_failure_results_have_safe_code_without_provider_text(runtime, monkeypatch, method, args):
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub(
        "pyodbc", connect=Mock(side_effect=Exception("28000", SECRET)),
    ))
    plugin = runtime.query(plugin_manifest())
    result = getattr(plugin, method)(*args)
    assert result.data["error_code"] == "sql_authentication_failed"
    assert "error" in result.data
    assert SECRET not in json.dumps(result.data)
    assert SECRET not in json.dumps(result.metadata)
    assert "sqlstate" not in result.data


def test_schema_failure_results_and_raised_errors_are_safe(runtime, monkeypatch):
    connect = Mock(side_effect=Exception("IM002", SECRET))
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    plugin = runtime.schema(plugin_manifest())
    result = plugin.get_database_schema()
    assert result.data["error_code"] == "sql_driver_unavailable"
    assert result.metadata == {"source": "sql_schema_plugin", "success": False}
    assert SECRET not in json.dumps(result.data)
    for method, args in [
        ("get_table_list", ()), ("get_table_schema", ("Example",)), ("get_relationships", ()),
    ]:
        with pytest.raises(runtime.diagnostics.SqlConnectionError) as caught:
            getattr(plugin, method)(*args)
        assert SECRET not in str(caught.value)


@pytest.mark.parametrize("kind", ["query", "schema"])
def test_driver_import_failures_do_not_escape_as_raw_import_errors(runtime, monkeypatch, kind):
    original_import = builtins.__import__

    def missing_driver(name, *args, **kwargs):
        if name == "pyodbc":
            raise ImportError(SECRET)
        return original_import(name, *args, **kwargs)

    plugin = getattr(runtime, kind)(plugin_manifest())
    with monkeypatch.context() as scope:
        scope.setattr(builtins, "__import__", missing_driver)
        with pytest.raises(runtime.diagnostics.SqlConnectionError) as caught:
            plugin._get_connection()
    assert caught.value.diagnostic.code == "sql_driver_unavailable"
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("kind", ["query", "schema"])
@pytest.mark.parametrize("auth,connection_string,expected_suffix", [
    ("managed_identity", None, ";Authentication=ActiveDirectoryMsi"),
    ("integrated", None, ";Trusted_Connection=yes"),
    ("username_password", None, f";UID=sql-user;PWD={SECRET}"),
    ("connection_string", f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER=other;PWD={SECRET}", None),
])
def test_auth_inputs_and_timeout_are_unchanged(runtime, monkeypatch, kind, auth, connection_string, expected_suffix):
    connection = Mock()
    connect = Mock(return_value=connection)
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    plugin = getattr(runtime, kind)(plugin_manifest(auth_type=auth, connection_string=connection_string))
    result = plugin._get_connection()
    again = plugin._get_connection()
    assert result is connection and again is connection
    connect.assert_called_once()
    actual = connect.call_args.args[0]
    if connection_string:
        assert actual == connection_string
    else:
        assert actual == "DRIVER={ODBC Driver 18 for SQL Server};SERVER=db.example.test;DATABASE=test-db" + expected_suffix
    assert connect.call_args.kwargs == ({"timeout": 7} if kind == "query" else {})


@pytest.mark.parametrize("kind", ["query", "schema"])
def test_driver_fallback_remains_bounded_and_non_driver_errors_do_not_retry(runtime, monkeypatch, kind):
    saved = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=db.example.test;DATABASE=test-db"
    connect = Mock(side_effect=[
        Exception("01000", "[unixODBC][Driver Manager]Can't open lib 'ODBC Driver 17 for SQL Server' : file not found"),
        Exception("28000", SECRET),
    ])
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    plugin = getattr(runtime, kind)(plugin_manifest(connection_string=saved))
    with pytest.raises(runtime.diagnostics.SqlConnectionError) as caught:
        plugin._get_connection()
    assert caught.value.diagnostic.code == "sql_authentication_failed"
    assert connect.call_count == 2
    assert "ODBC Driver 17" in connect.call_args_list[0].args[0]
    assert "ODBC Driver 18" in connect.call_args_list[1].args[0]
    assert connect.call_args_list[0].kwargs == connect.call_args_list[1].kwargs
    connect.reset_mock(side_effect=True)
    connect.side_effect = Exception("28000", SECRET)
    with pytest.raises(runtime.diagnostics.SqlConnectionError):
        plugin._get_connection()
    connect.assert_called_once()


def test_successful_query_scalar_and_schema_shapes_are_unchanged(runtime, monkeypatch):
    cursor = Mock()
    cursor.description = [("number",)]
    cursor.fetchmany.return_value = [(1,)]
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = []
    connection = Mock()
    connection.cursor.return_value = cursor
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=Mock(return_value=connection)))
    query = runtime.query(plugin_manifest())
    rows = query.execute_query("SELECT 1")
    scalar = query.execute_scalar("SELECT 1")
    answer = query.query_database("Read a value", "SELECT 1")
    schema = runtime.schema(plugin_manifest()).get_database_schema()
    assert rows.data == {
        "columns": ["number"], "data": [{"number": 1}], "row_count": 1,
        "is_truncated": False, "query": "SELECT 1;",
    }
    assert scalar.data == {"value": 1, "query": "SELECT 1;"}
    assert answer.data == {**rows.data, "question": "Read a value"}
    assert schema.data == {
        "database_type": "sqlserver", "database_name": "test-db", "tables": {}, "relationships": [],
    }


@pytest.mark.parametrize("debug", [False, True])
def test_real_logger_preserves_valid_evidence_and_rejects_invalid_values(runtime, capsys, debug):
    runtime.settings["enable_debug_logging"] = debug
    diagnostic = runtime.diagnostics.classify_sql_connection_error(
        Exception("28000", f"[28000] {SECRET} (18456) (SQLDriverConnect)"), "azure_sql",
    )
    runtime.logging.log_event(
        "[SQL_CONNECTION] SQL connection failed.", level=logging.WARNING,
        extra={**diagnostic.log_properties(), "operation": "sql_connection_test"},
    )
    event = runtime.records[-1]
    assert event.sc_sqlstate == "28000"
    assert event.sc_sql_native_error == 18456
    assert event.sc_sql_engine == "sqlserver"
    assert event.sc_failure_code == "sql_authentication_failed"
    assert SECRET not in json.dumps(event.__dict__, default=str)
    assert SECRET not in capsys.readouterr().out
    for state, engine, native in [
        (SECRET, SECRET, SECRET), ("TOKEN", {}, True), ("28000\n", ["sqlserver"], 2**40),
    ]:
        properties = runtime.logging._build_logger_extra("[SQL_CONNECTION]", {
            "sqlstate": state, "sql_engine": engine, "sql_native_error": native,
        })
        assert properties == {"sc_message": "[SQL_CONNECTION]", "sc_message_length": 16}


@pytest.mark.parametrize("editor", [False, True])
@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("engine,module,error,expected", [
    ("azure_sql", "pyodbc", Exception("28000", SECRET), "sql_authentication_failed"),
    ("postgresql", "psycopg2", TimeoutError(SECRET), "sql_connection_timeout"),
    ("mysql", "pymysql", Exception(1045, SECRET), "sql_authentication_failed"),
    ("sqlite", "sqlite3", ImportError(SECRET), "sql_driver_unavailable"),
])
def test_sql_endpoint_has_shared_safe_errors_for_classic_and_editor(environment, monkeypatch, editor, saved, engine, module, error, expected):
    env = environment
    fields = {
        "database_type": engine, "server": "db.example.test", "database": "test-db",
        "auth_type": "managed_identity",
    }
    payload = {**fields, "auth_type": "managed_identity", "action_scope": "personal"}
    if editor:
        payload.update({"type": "sql_query", "auth": {"type": "identity", "identity": "managed_identity"}, "additionalFields": fields})
    if saved:
        env.services.add("actions", "personal", "actor", {
            "id": "saved-sql", "name": "saved_sql", "user_id": "actor", "type": "sql_query",
            "auth": {"type": "identity", "identity": "managed_identity"}, "additionalFields": fields,
        })
        payload["existing_plugin"] = {"scope": "personal", "id": "saved-sql", "name": "saved_sql"}
    original = deepcopy(env.services.records)
    connect = Mock(side_effect=error)
    monkeypatch.setitem(sys.modules, module, module_stub(module, connect=connect))
    response = env.client.post("/api/plugins/test-sql-connection", json=payload)
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error_code"] == expected
    assert SECRET not in json.dumps(body)
    assert "sqlstate" not in body and "sql_native_error" not in body
    connect.assert_called_once()
    events = [call for call in env.services.appinsights.log_event.call_args_list if call.args[0].startswith("[SQL_CONNECTION]")]
    assert len(events) == 1
    assert events[0].kwargs["level"] == logging.WARNING
    assert events[0].kwargs["extra"]["failure_code"] == expected
    assert env.services.records == original
    assert env.services.writes == []


@pytest.mark.parametrize("editor", [False, True])
@pytest.mark.parametrize("engine,module,message", [
    ("sqlserver", "pyodbc", "Successfully connected to test-db on db.example.test."),
    ("postgresql", "psycopg2", "Successfully connected to PostgreSQL database test-db."),
    ("mysql", "pymysql", "Successfully connected to MySQL database test-db."),
    ("sqlite", "sqlite3", "Successfully connected to SQLite database."),
])
def test_sql_endpoint_success_shape_and_provider_inputs_are_unchanged(environment, monkeypatch, editor, engine, module, message):
    env = environment
    fields = {
        "database_type": engine, "server": "db.example.test", "database": "test-db",
        "auth_type": "username_password", "username": "sql-user", "password": SECRET,
        "timeout": 99,
    }
    payload = {**fields, "action_scope": "personal"}
    if editor:
        payload.update({"type": "sql_query", "auth": {"type": "user"}, "additionalFields": fields})
    connection = Mock()
    connect = Mock(return_value=connection)
    monkeypatch.setitem(sys.modules, module, module_stub(module, connect=connect))
    response = env.client.post("/api/plugins/test-sql-connection", json=payload)
    assert response.status_code == 200
    assert response.get_json() == {"success": True, "message": message}
    connect.assert_called_once()
    if engine == "sqlserver":
        assert connect.call_args.args == (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER=db.example.test;DATABASE=test-db;UID=sql-user;PWD={SECRET}",
        )
        assert connect.call_args.kwargs == {"timeout": 15}
    elif engine == "sqlite":
        assert connect.call_args.args == ("test-db",)
        assert connect.call_args.kwargs == {"timeout": 15}
    else:
        assert connect.call_args.args == ()
        assert connect.call_args.kwargs == {
            "host": "db.example.test", "database": "test-db", "connect_timeout": 15,
            "user": "sql-user", "password": SECRET,
        }
    connection.cursor.return_value.execute.assert_called_once_with("SELECT 1")
    connection.cursor.return_value.close.assert_called_once()
    connection.close.assert_called_once()
    assert env.services.writes == []


def test_sql_endpoint_reusable_identity_and_real_logger_share_contract(environment, runtime, monkeypatch):
    env = environment

    def hydrate(manifest, scope_type, scope_id, *, return_type):
        assert (scope_type, scope_id) == ("personal", "actor")
        result = deepcopy(manifest)
        result["auth"] = {"type": "identity", "identity": "managed_identity"}
        result["additionalFields"]["auth_type"] = "managed_identity"
        return result

    env.identities.hydrate_action_identity_reference.side_effect = hydrate
    monkeypatch.setitem(env.namespace, "log_event", runtime.logging.log_event)
    connect = Mock(side_effect=Exception("28000", f"[28000] {SECRET} (18456) (SQLDriverConnect)"))
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    response = env.client.post("/api/plugins/test-sql-connection", json={
        "type": "sql_query", "identity_id": "owned-identity",
        "auth": {"type": "identity", "identity": "owned-identity"}, "action_scope": "personal",
        "additionalFields": {
            "database_type": "azure_sql", "server": "db.example.test", "database": "test-db",
        },
    })
    assert response.status_code == 400
    assert response.get_json()["error_code"] == "sql_authentication_failed"
    env.identities.hydrate_action_identity_reference.assert_called_once()
    assert "Authentication=ActiveDirectoryMsi" in connect.call_args.args[0]
    event = runtime.records[-1]
    assert (event.sc_sqlstate, event.sc_sql_native_error, event.sc_sql_engine) == ("28000", 18456, "sqlserver")
    assert SECRET not in json.dumps(event.__dict__, default=str)
    assert "owned-identity" not in json.dumps(event.__dict__, default=str)


@pytest.mark.parametrize("scope,admin,expected", [
    ("group", False, 400), ("global", True, 400), ("global", False, 403),
])
def test_scoped_identity_authorization_is_unchanged(environment, monkeypatch, scope, admin, expected):
    env = environment
    monkeypatch.setitem(env.namespace, "WORKSPACE_IDENTITY_SCOPE_GROUP", "group")
    monkeypatch.setitem(env.namespace, "WORKSPACE_IDENTITY_SCOPE_GLOBAL", "global")
    monkeypatch.setitem(env.namespace, "require_active_group", env.services.groups.require_active_group)
    monkeypatch.setitem(env.namespace, "assert_group_role", env.services.groups.assert_group_role)
    with env.client.session_transaction() as state:
        state["user"] = {**state["user"], "roles": ["User", "Admin"] if admin else ["User"]}
    env.identities.hydrate_action_identity_reference.return_value = {
        "auth": {"type": "identity", "identity": "managed_identity"},
        "additionalFields": {"auth_type": "managed_identity"},
    }
    connect = Mock(side_effect=Exception("HYT00", SECRET))
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    response = env.client.post("/api/plugins/test-sql-connection", json={
        "action_scope": scope, "identity_id": "scoped-identity", "database_type": "sqlserver",
        "server": "db.example.test", "database": "test-db",
    })
    assert response.status_code == expected
    if expected == 403:
        connect.assert_not_called()
        env.identities.hydrate_action_identity_reference.assert_not_called()
    else:
        assert response.get_json()["error_code"] == "sql_connection_timeout"
        connect.assert_called_once()
        call = env.identities.hydrate_action_identity_reference.call_args
        assert call.args[1:3] == (scope, "group-a" if scope == "group" else "global")


def test_foreign_personal_identity_is_denied_before_connect(environment, monkeypatch):
    env = environment
    env.identities.hydrate_action_identity_reference.side_effect = PermissionError(SECRET)
    connect = Mock()
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    response = env.client.post("/api/plugins/test-sql-connection", json={
        "identity_id": "foreign", "auth": {"type": "identity", "identity": "foreign"},
        "additionalFields": {"database_type": "azure_sql", "server": "db.example.test", "database": "test-db"},
    })
    assert response.status_code == 403
    assert SECRET not in json.dumps(response.get_json())
    connect.assert_not_called()
    assert env.services.writes == []


@pytest.mark.parametrize("kind", ["query", "schema"])
@pytest.mark.parametrize("uses_string", [False, True])
@pytest.mark.parametrize("inventory", ["observed", "unavailable", "unknown"])
def test_runtime_connection_context_captures_only_observable_facts(runtime, monkeypatch, kind, uses_string, inventory):
    monkeypatch.setenv("IDENTITY_ENDPOINT", SECRET)
    monkeypatch.setenv("IDENTITY_HEADER", SECRET)
    connect = Mock(side_effect=Exception("28000", SECRET))
    provider = module_stub("pyodbc", connect=connect)
    if inventory != "unknown":
        provider.drivers = Mock(
            return_value=["ODBC Driver 18 for SQL Server", SECRET],
            side_effect=OSError(SECRET) if inventory == "unavailable" else None,
        )
    monkeypatch.setitem(sys.modules, "pyodbc", provider)
    saved_string = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER=private;PWD={SECRET}" if uses_string else None
    manifest = {**plugin_manifest(connection_string=saved_string), "identity_id": SECRET}
    plugin = getattr(runtime, kind)(manifest)
    runtime.records.clear()
    with pytest.raises(runtime.diagnostics.SqlConnectionError):
        plugin._get_connection()
    event = runtime.records[-1]
    assert event.sc_sql_auth_source == "reusable_identity"
    assert event.sc_sql_auth_mode == ("unknown" if uses_string else "managed_identity")
    assert event.sc_sql_stage == "connect"
    assert event.sc_sql_attempt_count == 1
    assert event.sc_sql_fallback_count == 0
    assert event.sc_sql_driver_family == "odbc" and event.sc_sql_driver_major == "18"
    assert event.sc_sql_driver_inventory == inventory
    if inventory == "observed":
        assert event.sc_sql_driver_17_available is False
        assert event.sc_sql_driver_18_available is True
    if not uses_string:
        assert event.sc_sql_mi_endpoint_present is True
        assert event.sc_sql_mi_header_present is True
    else:
        assert not hasattr(event, "sc_sql_mi_endpoint_present")
    assert re.fullmatch(r"[0-9a-f]{32}", event.sc_sql_diagnostic_reference)
    assert SECRET not in json.dumps(event.__dict__, default=str)
    connect.assert_called_once()


@pytest.mark.parametrize("kind", ["query", "schema"])
@pytest.mark.parametrize("succeeds", [False, True])
def test_fallback_and_terminal_failure_share_one_reference(runtime, monkeypatch, kind, succeeds):
    connection = Mock()
    connect = Mock(side_effect=[
        Exception("01000", "ODBC Driver 17 for SQL Server can't open lib"),
        connection if succeeds else Exception("28000", SECRET),
    ])
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    plugin = getattr(runtime, kind)(plugin_manifest(
        connection_string="DRIVER={ODBC Driver 17 for SQL Server};SERVER=private",
    ))
    runtime.records.clear()
    if succeeds:
        actual = plugin._get_connection()
        assert actual is connection
    else:
        with pytest.raises(runtime.diagnostics.SqlConnectionError):
            plugin._get_connection()
    events = [item for item in runtime.records if item.sc_message.startswith("[SQL_CONNECTION]")]
    assert len(events) == (1 if succeeds else 2)
    assert len({item.sc_sql_diagnostic_reference for item in events}) == 1
    assert events[-1].sc_sql_attempt_count == 2
    assert events[-1].sc_sql_fallback_count == 1
    assert events[-1].sc_sql_driver_major == "18"
    assert connect.call_count == 2


@pytest.mark.parametrize("debug", [False, True])
def test_sql_context_export_contract_applies_to_console_and_monitor(runtime, capsys, debug):
    runtime.settings["enable_debug_logging"] = debug
    for bad in [SECRET, SECRET * 1000, {}, [], None, 2**50, -1]:
        properties = {key: bad for key in runtime.diagnostics.SQL_CONTEXT_KEYS}
        runtime.logging.log_event("[SQL_CONNECTION] Fixture.", extra=properties, level=logging.WARNING)
    assert SECRET not in json.dumps([item.__dict__ for item in runtime.records], default=str)
    assert SECRET not in capsys.readouterr().out
    context = runtime.diagnostics.SqlConnectionContext("sql_connection_test")
    context.configure("sqlserver", auth_type="managed_identity", environ={})
    runtime.logging.log_event("[SQL_CONNECTION] Fixture.", extra=context.log_properties(), level=logging.WARNING)
    event = runtime.records[-1]
    assert event.sc_sql_auth_mode == "managed_identity"
    assert event.sc_sql_mi_endpoint_present is False
    assert event.sc_sql_mi_header_present is False
    assert event.sc_sql_diagnostic_reference == context.reference


@pytest.mark.parametrize("stage", ["driver_import", "connect", "probe"])
def test_sql_endpoint_reference_links_safe_ui_error_to_actual_failure_stage(environment, runtime, monkeypatch, stage):
    env = environment
    monkeypatch.setitem(env.namespace, "log_event", runtime.logging.log_event)
    connection = Mock()
    connect = Mock(return_value=connection, side_effect=Exception("28000", SECRET) if stage == "connect" else None)
    if stage == "probe":
        connection.cursor.return_value.execute.side_effect = Exception("42000", SECRET)
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    original_import = builtins.__import__

    def import_driver(name, *args, **kwargs):
        if name == "pyodbc" and stage == "driver_import":
            raise ImportError(SECRET)
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as scope:
        scope.setattr(builtins, "__import__", import_driver)
        response = env.client.post("/api/plugins/test-sql-connection", json={
            "database_type": "sqlserver", "server": "private-host", "database": "private-db",
            "auth_type": "managed_identity",
        })
    assert response.status_code == 400
    body = response.get_json()
    reference = body["details"]["diagnostic_reference"]
    assert re.fullmatch(r"[0-9a-f]{32}", reference)
    assert set(body) == {"success", "error", "error_code", "details"}
    assert set(body["details"]) == {"diagnostic_reference"}
    event = runtime.records[-1]
    assert event.sc_sql_diagnostic_reference == reference
    assert event.sc_sql_stage == stage
    assert event.sc_sql_attempt_count == (0 if stage == "driver_import" else 1)
    for sensitive in [SECRET, "private-host", "private-db", "managed_identity"]:
        assert sensitive not in json.dumps(body)
    assert SECRET not in json.dumps(event.__dict__, default=str)


@pytest.mark.parametrize("editor", [False, True])
@pytest.mark.parametrize("error,status", [(PermissionError(SECRET), 403), (LookupError(SECRET), 404), (ValueError(SECRET), 400)])
def test_identity_resolution_failure_is_correlated_without_provider_or_identity_text(
    environment, runtime, monkeypatch, editor, error, status,
):
    env = environment
    monkeypatch.setitem(env.namespace, "log_event", runtime.logging.log_event)
    env.identities.hydrate_action_identity_reference.side_effect = error
    connect = Mock()
    monkeypatch.setitem(sys.modules, "pyodbc", module_stub("pyodbc", connect=connect))
    payload = {"identity_id": SECRET, "database_type": "azure_sql", "server": "private", "database": "private"}
    if editor:
        payload.update({"auth": {"type": "identity", "identity": SECRET}, "additionalFields": {}})
    response = env.client.post("/api/plugins/test-sql-connection", json=payload)
    assert response.status_code == status
    body = response.get_json()
    assert set(body["details"]) == {"diagnostic_reference"}
    assert SECRET not in json.dumps(body)
    assert runtime.records[-1].sc_sql_stage == "identity_resolution"
    assert runtime.records[-1].sc_sql_diagnostic_reference == body["details"]["diagnostic_reference"]
    assert SECRET not in json.dumps(runtime.records[-1].__dict__, default=str)
    connect.assert_not_called()
