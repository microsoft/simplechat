# sql_connection_diagnostics.py
"""Credential-free SQL connection diagnostics, with no application bootstrap or I/O."""

import re
import uuid
from dataclasses import dataclass, field
from time import monotonic
from typing import Optional


SQL_ENGINES = frozenset({"sqlserver", "postgresql", "mysql", "sqlite", "unknown"})
SQLSTATE_PATTERN = re.compile(r"(?:[0-9]{2}|HY|IM|S[0-9]|HV|P0|XX|F0)[0-9A-Z]{3}", re.ASCII)
MAX_NATIVE_ERROR = 2**31 - 1
_ODBC_NATIVE_ERROR = re.compile(r"\((-?[0-9]{1,10})\) \((?:SQLDriverConnect|SQLConnect)\)$", re.ASCII)
_ERROR_TYPES = frozenset({
    "Error", "DatabaseError", "InterfaceError", "OperationalError", "InternalError",
    "ProgrammingError", "NotSupportedError", "IntegrityError", "DataError",
    "ImportError", "ModuleNotFoundError", "TimeoutError", "ConnectionError", "OSError",
})
_MESSAGES = {
    "sql_connection_failed": "SQL connection failed. Verify the connection and authentication settings.",
    "sql_driver_unavailable": "The required database driver is not available on the server. Contact your administrator.",
    "sql_connection_timeout": "SQL connection timed out. Check database availability and network access.",
    "sql_authentication_failed": "SQL authentication was rejected. Verify the selected authentication settings and database access.",
}
SQL_CONTEXT_ENUMS = {
    "sql_operation": frozenset({"sql_connection_test", "sql_query_connect", "sql_schema_connect"}),
    "sql_connection_source": frozenset({"parameters", "connection_string", "unknown"}),
    "sql_auth_mode": frozenset({"username_password", "managed_identity", "integrated", "none", "unknown"}),
    "sql_auth_source": frozenset({"reusable_identity", "inline", "unknown"}),
    "sql_stage": frozenset({"configuration", "identity_resolution", "driver_import", "connect", "probe"}),
    "sql_driver_family": frozenset({"odbc", "psycopg2", "pymysql", "sqlite3", "unknown"}),
    "sql_driver_major": frozenset({"17", "18", "unknown"}),
    "sql_driver_inventory": frozenset({"observed", "unavailable", "unknown"}),
}
SQL_CONTEXT_BOOLEANS = frozenset({
    "sql_mi_endpoint_present", "sql_mi_header_present", "sql_driver_17_available", "sql_driver_18_available",
})
SQL_CONTEXT_INTEGERS = {"sql_attempt_count": 2, "sql_fallback_count": 1, "sql_duration_ms": 86_400_000}
SQL_CONTEXT_KEYS = frozenset({
    *SQL_CONTEXT_ENUMS, *SQL_CONTEXT_BOOLEANS, *SQL_CONTEXT_INTEGERS, "sql_diagnostic_reference",
})


def valid_sql_context_property(key: str, value: object) -> bool:
    """Closed export contract, including when callers supply malformed log properties."""
    if key in SQL_CONTEXT_ENUMS:
        return type(value) is str and value in SQL_CONTEXT_ENUMS[key]
    if key in SQL_CONTEXT_BOOLEANS:
        return type(value) is bool
    if key in SQL_CONTEXT_INTEGERS:
        return type(value) is int and 0 <= value <= SQL_CONTEXT_INTEGERS[key]
    return key == "sql_diagnostic_reference" and type(value) is str and len(value) == 32 and re.fullmatch(
        r"[0-9a-f]{32}", value, re.ASCII,
    ) is not None


@dataclass
class SqlConnectionContext:
    """One connection attempt chain; never retains inputs, environment values, or provider text."""

    operation: str
    reference: str = field(default_factory=lambda: uuid.uuid4().hex, init=False)
    stage: str = "configuration"
    properties: dict = field(default_factory=lambda: {
        key: "unknown" for key in (
            "sql_connection_source", "sql_auth_mode", "sql_auth_source",
            "sql_driver_family", "sql_driver_major", "sql_driver_inventory",
        )
    }, init=False)
    started_at: float = field(default_factory=monotonic, init=False, repr=False)
    attempts: int = 0
    fallbacks: int = 0

    def configure(
        self, engine, *, connection_string_used=False, auth_type=None,
        username_password=False, identity_selected=False, environ=None,
    ):
        mode = "unknown"
        if not connection_string_used:
            if engine == "sqlserver":
                if username_password:
                    mode = "username_password"
                elif auth_type == "managed_identity":
                    mode = "managed_identity"
                elif auth_type == "integrated" or not auth_type:
                    mode = "integrated"
            elif engine in {"postgresql", "mysql"} and username_password:
                mode = "username_password"
            elif engine == "sqlite":
                mode = "none"
        self.properties = {
            "sql_connection_source": "connection_string" if connection_string_used else "parameters",
            "sql_auth_mode": mode,
            "sql_auth_source": "reusable_identity" if identity_selected else "inline",
            "sql_driver_family": {
                "sqlserver": "odbc", "postgresql": "psycopg2", "mysql": "pymysql", "sqlite": "sqlite3",
            }.get(engine, "unknown"),
            "sql_driver_major": "unknown",
            "sql_driver_inventory": "unknown",
        }
        if mode == "managed_identity" and environ is not None:
            self.properties.update({
                "sql_mi_endpoint_present": bool(environ.get("IDENTITY_ENDPOINT")),
                "sql_mi_header_present": bool(environ.get("IDENTITY_HEADER")),
            })

    def observe_odbc(self, connection_string, installed_drivers=None):
        # Only recognize the leading, exact standard driver attribute. Do not parse credentials.
        major = "unknown"
        if type(connection_string) is str:
            for candidate in ("17", "18"):
                if connection_string.startswith(f"DRIVER={{ODBC Driver {candidate} for SQL Server}};"):
                    major = candidate
                    break
        self.properties["sql_driver_major"] = major
        if type(installed_drivers) in (list, tuple) and len(installed_drivers) <= 128:
            self.properties["sql_driver_inventory"] = "observed"
            for candidate in ("17", "18"):
                self.properties[f"sql_driver_{candidate}_available"] = any(
                    type(driver) is str and driver == f"ODBC Driver {candidate} for SQL Server"
                    for driver in installed_drivers
                )

    def log_properties(self):
        values = {
            **self.properties, "sql_operation": self.operation, "sql_stage": self.stage,
            "sql_diagnostic_reference": self.reference, "sql_attempt_count": self.attempts,
            "sql_fallback_count": self.fallbacks,
            "sql_duration_ms": min(max(int((monotonic() - self.started_at) * 1000), 0), 86_400_000),
        }
        return {key: value for key, value in values.items() if valid_sql_context_property(key, value)}


def valid_sqlstate(value: object) -> bool:
    """Accept only bounded SQLSTATE values, not provider messages or arbitrary strings."""
    return type(value) is str and len(value) == 5 and SQLSTATE_PATTERN.fullmatch(value) is not None


def valid_native_error(value: object) -> bool:
    return type(value) is int and -MAX_NATIVE_ERROR <= value <= MAX_NATIVE_ERROR


@dataclass(frozen=True)
class SqlConnectionDiagnostic:
    code: str
    engine: str
    error_type: str
    sqlstate: Optional[str] = None
    native_error: Optional[int] = None

    @property
    def message(self) -> str:
        return _MESSAGES[self.code]

    def log_properties(self) -> dict:
        properties = {
            "failure_code": self.code,
            "sql_engine": self.engine,
            "error_type": self.error_type,
        }
        if self.sqlstate is not None:
            properties["sqlstate"] = self.sqlstate
        if self.native_error is not None:
            properties["sql_native_error"] = self.native_error
        return properties


class SqlConnectionError(RuntimeError):
    """A connection failure safe for existing plugin result and logging handlers."""

    def __init__(self, diagnostic: SqlConnectionDiagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.message)


def classify_sql_connection_error(error: Exception, database_type: str) -> SqlConnectionDiagnostic:
    """Classify structured driver evidence without retaining raw exception messages."""
    engine = database_type if type(database_type) is str else "unknown"
    if engine in {"azure_sql", "azuresql"}:
        engine = "sqlserver"
    if engine not in SQL_ENGINES:
        engine = "unknown"

    sqlstate = None
    native_error = None
    args = error.args
    if engine in {"sqlserver", "postgresql"}:
        for candidate in (getattr(error, "sqlstate", None), getattr(error, "pgcode", None), args[0] if args else None):
            if valid_sqlstate(candidate):
                sqlstate = candidate
                break
    if engine == "sqlserver" and sqlstate and len(args) > 1:
        detail = args[1]
        # pyodbc puts the native code at the end of its SQLDriverConnect diagnostic.
        # Never collect arbitrary numbers (ports, IDs, or credentials) from provider text.
        if type(detail) is str and len(detail) <= 8192 and detail.startswith(f"[{sqlstate}]"):
            match = _ODBC_NATIVE_ERROR.search(detail)
            if match:
                candidate = int(match.group(1))
                if valid_native_error(candidate):
                    native_error = candidate
    elif engine == "mysql" and args and valid_native_error(args[0]):
        native_error = args[0]
    elif engine == "sqlite":
        candidate = getattr(error, "sqlite_errorcode", None)
        if valid_native_error(candidate):
            native_error = candidate

    code = "sql_connection_failed"
    if isinstance(error, ImportError) or sqlstate in {"IM002", "IM003"}:
        code = "sql_driver_unavailable"
    elif isinstance(error, TimeoutError) or sqlstate in {"HYT00", "HYT01"}:
        code = "sql_connection_timeout"
    elif (
        (sqlstate is not None and sqlstate.startswith("28"))
        or (engine == "sqlserver" and native_error in {18452, 18456})
        or (engine == "mysql" and native_error in {1045, 1698})
    ):
        code = "sql_authentication_failed"

    error_type = type(error).__name__
    return SqlConnectionDiagnostic(
        code, engine, error_type if error_type in _ERROR_TYPES else "Exception",
        sqlstate, native_error,
    )
