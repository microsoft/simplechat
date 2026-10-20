# sql_connection_diagnostics.py
"""Credential-free SQL connection diagnostics, with no application bootstrap or I/O."""

import re
from dataclasses import dataclass
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
