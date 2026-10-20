# test_sql_connection_diagnostics.py
"""
Functional tests for credential-safe SQL connection diagnostics.
Version: 0.261.356
Implemented in: 0.261.351

Validate structured evidence, conservative classification, privacy, and cold import
behavior without SQL drivers, application bootstrap, Azure access, or network I/O.
"""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
SECRET = "private-credential-and-host.example.test"


@pytest.fixture
def diagnostics(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_ROOT))
    return importlib.import_module("semantic_kernel_plugins.sql_connection_diagnostics")


@pytest.mark.parametrize("engine,state,detail,expected,native", [
    ("sqlserver", "28000", f"[28000] {SECRET} (18456) (SQLDriverConnect)", "sql_authentication_failed", 18456),
    ("azure_sql", "HYT00", SECRET, "sql_connection_timeout", None),
    ("azuresql", "IM002", SECRET, "sql_driver_unavailable", None),
    ("sqlserver", "IM003", SECRET, "sql_driver_unavailable", None),
    ("sqlserver", "08001", f"[08001] {SECRET} (10060) (SQLDriverConnect)", "sql_connection_failed", 10060),
    ("sqlserver", "08001", f"[08001] {SECRET} (18456) (SQLDriverConnect)", "sql_authentication_failed", 18456),
    ("sqlserver", "HY000", SECRET, "sql_connection_failed", None),
])
def test_interface_error_uses_evidence_not_class_name(diagnostics, engine, state, detail, expected, native):
    error = type("InterfaceError", (Exception,), {})(state, detail)
    result = diagnostics.classify_sql_connection_error(error, engine)
    assert result.code == expected
    assert result.engine == "sqlserver"
    assert result.sqlstate == state
    assert result.native_error == native
    assert result.error_type == "InterfaceError"
    assert SECRET not in json.dumps(result.log_properties())
    assert SECRET not in str(diagnostics.SqlConnectionError(result))


@pytest.mark.parametrize("engine,attributes,args,expected,native,state", [
    ("postgresql", {"pgcode": "28P01"}, (SECRET,), "sql_authentication_failed", None, "28P01"),
    ("postgresql", {"sqlstate": "08006"}, (SECRET,), "sql_connection_failed", None, "08006"),
    ("mysql", {}, (1045, SECRET), "sql_authentication_failed", 1045, None),
    ("mysql", {}, (2003, SECRET), "sql_connection_failed", 2003, None),
    ("sqlite", {"sqlite_errorcode": 14}, (SECRET,), "sql_connection_failed", 14, None),
    ("sqlite", {"sqlite_errorcode": 2062}, (SECRET,), "sql_connection_failed", 2062, None),
])
def test_other_provider_structured_fields(diagnostics, engine, attributes, args, expected, native, state):
    error = type("OperationalError", (Exception,), attributes)(*args)
    result = diagnostics.classify_sql_connection_error(error, engine)
    assert (result.code, result.native_error, result.sqlstate) == (expected, native, state)
    assert SECRET not in repr(result)


@pytest.mark.parametrize("error,code", [
    (ImportError(SECRET), "sql_driver_unavailable"),
    (ModuleNotFoundError(SECRET), "sql_driver_unavailable"),
    (TimeoutError(SECRET), "sql_connection_timeout"),
    (ConnectionError(SECRET), "sql_connection_failed"),
    (type("InterfaceError", (Exception,), {})(SECRET), "sql_connection_failed"),
])
def test_python_errors_are_safely_classified(diagnostics, error, code):
    result = diagnostics.classify_sql_connection_error(error, "sqlserver")
    assert result.code == code
    assert result.sqlstate is None
    assert result.native_error is None
    assert SECRET not in result.message


@pytest.mark.parametrize("args,attributes", [
    ((), {}),
    ((["28000", SECRET],), {}),
    (({"sqlstate": "28000", "password": SECRET},), {}),
    ((SECRET * 10000,), {}),
    (("TOKEN",), {"pgcode": "TOKEN", "sqlstate": ["28000"]}),
    (("28000", f"[28000] {SECRET}:1433 id=18456"), {}),
    (("28000", f"{SECRET} (18456) (SQLDriverConnect)"), {}),
    (("28000", f"[28000] {SECRET} (99999999999) (SQLDriverConnect)"), {}),
    (("28000", f"[28000] {SECRET * 1000} (18456) (SQLDriverConnect)"), {}),
])
def test_unstructured_or_malformed_arguments_are_not_retained(diagnostics, args, attributes):
    error = type("UntrustedProviderError", (Exception,), attributes)(*args)
    result = diagnostics.classify_sql_connection_error(error, "sqlserver")
    assert result.native_error is None
    assert result.error_type == "Exception"
    assert SECRET not in repr(result)
    assert "TOKEN" not in repr(result)


@pytest.mark.parametrize("value", [True, False, 2**40, -(2**40), "1045", [1045], {"errno": 1045}, None])
def test_invalid_native_codes_are_rejected(diagnostics, value):
    error = Exception(value, SECRET)
    error.sqlite_errorcode = value
    mysql = diagnostics.classify_sql_connection_error(error, "mysql")
    sqlite = diagnostics.classify_sql_connection_error(error, "sqlite")
    assert mysql.native_error is None
    assert sqlite.native_error is None


def test_unknown_engine_cannot_supply_provider_evidence(diagnostics):
    result = diagnostics.classify_sql_connection_error(Exception("28000", SECRET), SECRET)
    assert result.code == "sql_connection_failed"
    assert result.engine == "unknown"
    assert result.sqlstate is None


@pytest.mark.parametrize("mode,uses_string,credentials,engine,expected", [
    ("managed_identity", False, False, "sqlserver", "managed_identity"),
    ("integrated", False, False, "sqlserver", "integrated"),
    ("managed_identity", False, True, "sqlserver", "username_password"),
    ("username_password", False, True, "postgresql", "username_password"),
    ("managed_identity", True, False, "sqlserver", "unknown"),
    ("username_password", True, True, "sqlserver", "unknown"),
    (SECRET, False, False, "sqlserver", "unknown"),
    (None, False, False, "sqlite", "none"),
])
def test_context_describes_effective_inputs_without_retaining_them(
    diagnostics, mode, uses_string, credentials, engine, expected,
):
    context = diagnostics.SqlConnectionContext("sql_connection_test")
    context.configure(
        engine, connection_string_used=uses_string, auth_type=mode,
        username_password=credentials, identity_selected=True,
        environ={"IDENTITY_ENDPOINT": SECRET, "IDENTITY_HEADER": SECRET},
    )
    properties = context.log_properties()
    assert properties["sql_auth_mode"] == expected
    assert properties["sql_auth_source"] == "reusable_identity"
    assert properties["sql_connection_source"] == ("connection_string" if uses_string else "parameters")
    assert ("sql_mi_endpoint_present" in properties) == (expected == "managed_identity")
    assert SECRET not in repr(context)
    assert diagnostics.valid_sql_context_property("sql_diagnostic_reference", context.reference)
    assert 0 <= properties["sql_duration_ms"] <= 86_400_000


@pytest.mark.parametrize("value", [SECRET, SECRET * 1000, {}, [], None, True, 2**50, -1],
                         ids=["secret", "oversized", "object", "array", "null", "bool", "huge", "negative"])
def test_every_context_field_rejects_untrusted_values(diagnostics, value):
    for key in diagnostics.SQL_CONTEXT_KEYS:
        if type(value) is bool and key in diagnostics.SQL_CONTEXT_BOOLEANS:
            continue
        valid = diagnostics.valid_sql_context_property(key, value)
        assert valid is False, key


def test_driver_observation_is_conservative_and_references_are_per_connection(diagnostics):
    context = diagnostics.SqlConnectionContext("sql_query_connect")
    other = diagnostics.SqlConnectionContext("sql_query_connect")
    assert context.reference != other.reference
    context.observe_odbc("DRIVER={ODBC Driver 17 for SQL Server};SERVER=" + SECRET, [
        "ODBC Driver 18 for SQL Server", SECRET,
    ])
    properties = context.log_properties()
    assert properties["sql_driver_major"] == "17"
    assert properties["sql_driver_inventory"] == "observed"
    assert properties["sql_driver_17_available"] is False
    assert properties["sql_driver_18_available"] is True
    context.observe_odbc(SECRET + ";DRIVER={ODBC Driver 18 for SQL Server};")
    properties = context.log_properties()
    assert properties["sql_driver_major"] == "unknown"
    assert SECRET not in repr(context)


def test_diagnostic_helper_is_not_a_user_facing_action(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_ROOT.parents[1] / "scripts"))
    inventory = importlib.import_module("build_docs_inventory")
    actions = inventory.extract_actions()
    assert all(action["module"] != "sql_connection_diagnostics.py" for action in actions)


def test_cold_import_and_required_operations_survive_optimized_python():
    probe = r'''
import importlib.abc
import socket
import sys

class BlockExternalImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {
            "config", "functions_settings", "functions_appinsights", "azure",
            "pyodbc", "psycopg2", "pymysql",
        }:
            raise RuntimeError("Diagnostic module crossed bootstrap boundary: " + fullname)

sys.meta_path.insert(0, BlockExternalImports())
def no_network(*args, **kwargs):
    raise RuntimeError("Network access forbidden")
socket.socket = no_network
socket.getaddrinfo = no_network
from semantic_kernel_plugins.sql_connection_diagnostics import classify_sql_connection_error, SqlConnectionContext
context = SqlConnectionContext("sql_connection_test")
context.configure("sqlserver", auth_type="managed_identity", environ={})
if context.log_properties()["sql_mi_endpoint_present"] is not False:
    raise AssertionError("Managed identity observation failed")
result = classify_sql_connection_error(Exception("HYT00", "private data"), "azure_sql")
if result.code != "sql_connection_timeout" or result.engine != "sqlserver":
    raise AssertionError("Required diagnostic operation failed")
if result.log_properties()["sqlstate"] != "HYT00":
    raise AssertionError("Required diagnostic evidence was lost")
'''
    env = {**os.environ, "PYTHONPATH": str(APP_ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    for flags in ([], ["-O"]):
        completed = subprocess.run(
            [sys.executable, *flags, "-c", probe], env=env, capture_output=True,
            text=True, timeout=30, check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stdout + completed.stderr)
