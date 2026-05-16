# sql_odbc_utils.py
"""
Shared SQL Server ODBC driver utilities.
"""

from typing import Any, Callable, Dict, Optional

from functions_appinsights import log_event


DEFAULT_SQL_SERVER_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"
LEGACY_SQL_SERVER_ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

_MISSING_DRIVER_ERROR_MARKERS = (
    "can't open lib",
    "data source name not found",
    "specified driver could not be loaded",
    "file not found",
    "im002",
)


def build_sql_server_odbc_connection_string(
    server: str,
    database: str,
    driver: Optional[str] = None,
    port: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    auth_type: Optional[str] = None,
) -> str:
    """Build a SQL Server ODBC connection string with the current default driver."""
    selected_driver = (driver or DEFAULT_SQL_SERVER_ODBC_DRIVER).strip()
    conn_str = f"DRIVER={{{selected_driver}}};SERVER={server}"
    if port:
        conn_str += f",{port}"
    conn_str += f";DATABASE={database}"

    if username and password:
        conn_str += f";UID={username};PWD={password}"
    elif auth_type == 'managed_identity':
        conn_str += ";Authentication=ActiveDirectoryMsi"
    elif auth_type == 'integrated' or not auth_type:
        conn_str += ";Trusted_Connection=yes"

    return conn_str


def replace_legacy_sql_server_odbc_driver(connection_string: str) -> str:
    """Return a Driver 18 connection string when the saved value uses Driver 17."""
    if not isinstance(connection_string, str):
        return connection_string
    return connection_string.replace(
        LEGACY_SQL_SERVER_ODBC_DRIVER,
        DEFAULT_SQL_SERVER_ODBC_DRIVER,
    )


def should_retry_sql_server_odbc_driver_18(connection_string: str, error: Exception) -> bool:
    """Determine whether a failed Driver 17 connection should be retried with Driver 18."""
    if not isinstance(connection_string, str) or LEGACY_SQL_SERVER_ODBC_DRIVER not in connection_string:
        return False

    error_text = str(error).lower()
    return any(marker in error_text for marker in _MISSING_DRIVER_ERROR_MARKERS)


def connect_with_sql_server_odbc_fallback(
    connect_callable: Callable[..., Any],
    connection_string: str,
    connect_kwargs: Optional[Dict[str, Any]] = None,
    log_source: str = "SQLODBC",
) -> Any:
    """Connect to SQL Server and retry legacy Driver 17 strings with Driver 18 if needed."""
    kwargs = connect_kwargs or {}
    try:
        return connect_callable(connection_string, **kwargs)
    except Exception as ex:
        if not should_retry_sql_server_odbc_driver_18(connection_string, ex):
            raise

        fallback_connection_string = replace_legacy_sql_server_odbc_driver(connection_string)
        log_event(
            f"[{log_source}] Retrying SQL Server ODBC connection with Driver 18 after Driver 17 was unavailable.",
            extra={
                "legacy_driver": LEGACY_SQL_SERVER_ODBC_DRIVER,
                "fallback_driver": DEFAULT_SQL_SERVER_ODBC_DRIVER,
                "error_type": type(ex).__name__,
            },
            debug_only=True,
        )
        return connect_callable(fallback_connection_string, **kwargs)