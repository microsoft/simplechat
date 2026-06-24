# snowflake_plugin.py
"""Semantic Kernel plugin for read-only Snowflake query actions."""

import json
import logging
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from functions_debug import debug_print
from functions_snowflake_operations import (
    SNOWFLAKE_ALLOWED_READ_STATEMENTS,
    SNOWFLAKE_AUTH_METHOD_KEY_PAIR,
    SNOWFLAKE_AUTH_METHOD_OAUTH,
    SNOWFLAKE_AUTH_METHOD_PASSWORD,
    SNOWFLAKE_DEFAULT_ENDPOINT,
    SNOWFLAKE_PLUGIN_TYPE,
    normalize_snowflake_additional_fields,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class SnowflakePlugin(BasePlugin):
    """Snowflake connector plugin focused on read-only data retrieval."""

    MAX_IDENTIFIER_PARTS = 3
    _SQL_COMMENT_PATTERN = re.compile(r"(--[^\r\n]*|/\*.*?\*/)", re.DOTALL)
    _FIRST_WORD_PATTERN = re.compile(r"^\s*([A-Za-z]+)", re.IGNORECASE)
    _LIMIT_OR_FETCH_PATTERN = re.compile(r"\b(limit|fetch\s+(first|next))\b", re.IGNORECASE)
    _FORBIDDEN_READ_ONLY_PATTERN = re.compile(
        r"\b(ALTER|CALL|COPY|CREATE|DELETE|DROP|EXECUTE|GET|GRANT|INSERT|MERGE|PUT|REMOVE|REPLACE|REVOKE|TRUNCATE|UPDATE|USE)\b",
        re.IGNORECASE,
    )
    _SYSTEM_FUNCTION_PATTERN = re.compile(r"\bSYSTEM\$", re.IGNORECASE)
    _IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
    _SECRET_REDACTION_PATTERN = re.compile(
        r"(?i)(password|private\s*key|token|secret)\s*[=:]\s*[^\s,;]+"
    )

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._metadata = self.manifest.get("metadata", {}) or {}
        self._auth = self.manifest.get("auth", {}) if isinstance(self.manifest.get("auth"), dict) else {}
        self._additional_fields = normalize_snowflake_additional_fields(
            self.manifest.get("additionalFields", {}),
            auth_type=str(self._auth.get("type") or ""),
        )
        self.endpoint = str(self.manifest.get("endpoint") or SNOWFLAKE_DEFAULT_ENDPOINT).strip()
        self.account = self._additional_fields.get("account") or ""
        self.user = self._additional_fields.get("user") or self._auth.get("identity") or ""
        self.warehouse = self._additional_fields.get("warehouse") or ""
        self.database = self._additional_fields.get("database") or ""
        self.schema = self._additional_fields.get("schema") or ""
        self.role = self._additional_fields.get("role") or ""
        self.auth_type = str(self._auth.get("type") or "username_password").strip()
        self.auth_method = self._additional_fields.get("auth_method") or SNOWFLAKE_AUTH_METHOD_PASSWORD
        self.read_only = bool(self._additional_fields.get("read_only", True))
        self.max_rows = int(self._additional_fields.get("max_rows") or 1000)
        self.timeout = int(self._additional_fields.get("timeout") or 30)
        self.login_timeout = int(self._additional_fields.get("login_timeout") or 30)
        self.byte_limit = int(self._additional_fields.get("byte_limit") or 250000)
        self._validate_configuration()

    @property
    def display_name(self) -> str:
        return "Snowflake"

    @property
    def metadata(self) -> Dict[str, Any]:
        user_description = self._metadata.get(
            "description",
            "Snowflake query action using the Snowflake Python Connector.",
        )
        description = (
            f"{user_description}\n\n"
            "This action retrieves data from Snowflake for analysis, charts, documents, and other agent outputs. "
            "It is not a Snowflake management tool. Only SELECT, SHOW, DESCRIBE, EXPLAIN, and WITH statements "
            "are accepted by default, and query results are returned as structured columns and rows. "
            "Use get_databases, get_schemas, get_tables, and describe_table to discover schema before writing queries."
        )
        return {
            "name": self.manifest.get("name", "snowflake"),
            "type": SNOWFLAKE_PLUGIN_TYPE,
            "description": description,
            "methods": [
                {
                    "name": "execute_sql_query",
                    "description": "Execute a read-only SQL query against the configured Snowflake account.",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Read-only Snowflake SQL query to execute.", "required": True},
                    ],
                    "returns": {"type": "dict", "description": "Query ID, columns, rows, row counts, and truncation status."},
                },
                {
                    "name": "get_databases",
                    "description": "List databases visible to the configured Snowflake role.",
                    "parameters": [],
                    "returns": {"type": "dict", "description": "Database listing results."},
                },
                {
                    "name": "get_schemas",
                    "description": "List schemas in a database, or in the configured default database.",
                    "parameters": [
                        {"name": "database", "type": "str", "description": "Optional database name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Schema listing results."},
                },
                {
                    "name": "get_tables",
                    "description": "List tables in a schema using provided or configured database/schema defaults.",
                    "parameters": [
                        {"name": "database", "type": "str", "description": "Optional database name.", "required": False},
                        {"name": "schema", "type": "str", "description": "Optional schema name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Table listing results."},
                },
                {
                    "name": "describe_table",
                    "description": "Describe a Snowflake table using a one-, two-, or three-part table name.",
                    "parameters": [
                        {"name": "table_name", "type": "str", "description": "Table name to describe.", "required": True},
                    ],
                    "returns": {"type": "dict", "description": "Table column description results."},
                },
            ],
        }

    def get_functions(self) -> List[str]:
        return [
            "execute_sql_query",
            "get_databases",
            "get_schemas",
            "get_tables",
            "describe_table",
        ]

    def _validate_configuration(self) -> None:
        if self.endpoint != SNOWFLAKE_DEFAULT_ENDPOINT:
            raise ValueError(f"Snowflake action endpoint must be {SNOWFLAKE_DEFAULT_ENDPOINT}.")
        if not self.account:
            raise ValueError("Snowflake action requires additionalFields.account.")
        if not self.warehouse:
            raise ValueError("Snowflake action requires additionalFields.warehouse.")
        if self.auth_method not in {
            SNOWFLAKE_AUTH_METHOD_PASSWORD,
            SNOWFLAKE_AUTH_METHOD_KEY_PAIR,
            SNOWFLAKE_AUTH_METHOD_OAUTH,
        }:
            raise ValueError("Snowflake action supports auth methods password, key_pair, or oauth.")
        if not self.user and not (self.auth_type == "identity" and self.manifest.get("identity_id")):
            raise ValueError("Snowflake action requires a Snowflake user.")
        if self.auth_type == "identity" and self.manifest.get("identity_id"):
            return
        if self.auth_method == SNOWFLAKE_AUTH_METHOD_PASSWORD:
            if self.auth_type not in {"username_password", "key"}:
                raise ValueError("Snowflake password auth requires auth.type='username_password'.")
            if not self._auth.get("key"):
                raise ValueError("Snowflake password auth requires auth.key.")
        elif self.auth_method in {SNOWFLAKE_AUTH_METHOD_KEY_PAIR, SNOWFLAKE_AUTH_METHOD_OAUTH}:
            if self.auth_type != "key":
                raise ValueError("Snowflake key-pair and OAuth auth require auth.type='key'.")
            if not self._auth.get("key"):
                raise ValueError("Snowflake key-pair and OAuth auth require auth.key.")

    def _strip_sql_comments(self, query: str) -> str:
        return self._SQL_COMMENT_PATTERN.sub(" ", str(query or ""))

    def _first_word(self, query: str) -> str:
        first_word_match = self._FIRST_WORD_PATTERN.match(query or "")
        return first_word_match.group(1).upper() if first_word_match else ""

    def _validate_read_only_query(self, query: str) -> Optional[str]:
        normalized_query = self._strip_sql_comments(query).strip()
        if not normalized_query:
            return "Snowflake SQL query is required."

        statements = [statement.strip() for statement in normalized_query.split(";") if statement.strip()]
        if len(statements) != 1:
            return "Only one Snowflake SQL statement can be executed at a time."

        first_word = self._first_word(statements[0])
        if first_word not in SNOWFLAKE_ALLOWED_READ_STATEMENTS:
            return f"Only read-only Snowflake SQL statements are allowed. Found: {first_word or 'UNKNOWN'}."

        forbidden_match = self._FORBIDDEN_READ_ONLY_PATTERN.search(statements[0])
        if forbidden_match:
            return f"Read-only mode blocks SQL keyword: {forbidden_match.group(1).upper()}."
        if self._SYSTEM_FUNCTION_PATTERN.search(statements[0]):
            return "Read-only mode blocks Snowflake SYSTEM$ functions."
        return None

    def _apply_result_limit(self, query: str) -> str:
        stripped_query = str(query or "").strip().rstrip(";")
        first_word = self._first_word(stripped_query)
        if first_word in {"SELECT", "WITH"} and not self._LIMIT_OR_FETCH_PATTERN.search(stripped_query):
            return f"{stripped_query} LIMIT {self.max_rows}"
        return stripped_query

    def _is_valid_identifier_path(self, value: str, max_parts: int = MAX_IDENTIFIER_PARTS) -> bool:
        parts = [part.strip() for part in str(value or "").split(".") if part.strip()]
        if not parts or len(parts) > max_parts:
            return False
        return all(self._IDENTIFIER_PATTERN.match(part) for part in parts)

    def _qualified_identifier(self, *parts: str, max_parts: int = MAX_IDENTIFIER_PARTS) -> str:
        normalized_parts = [str(part or "").strip() for part in parts if str(part or "").strip()]
        path = ".".join(normalized_parts)
        if not self._is_valid_identifier_path(path, max_parts=max_parts):
            raise ValueError("Snowflake identifiers must use simple database.schema.table names.")
        return path

    def _default_schema_path(self, database: str = "", schema: str = "") -> str:
        requested_database = str(database or self.database or "").strip()
        requested_schema = str(schema or self.schema or "").strip()
        if requested_database and requested_schema:
            return self._qualified_identifier(requested_database, requested_schema, max_parts=2)
        if requested_schema:
            return self._qualified_identifier(requested_schema, max_parts=1)
        if requested_database:
            return self._qualified_identifier(requested_database, max_parts=1)
        return ""

    def _build_connection_kwargs(self) -> Dict[str, Any]:
        connection_kwargs: Dict[str, Any] = {
            "account": self.account,
            "user": self.user,
            "warehouse": self.warehouse,
            "login_timeout": self.login_timeout,
            "network_timeout": self.timeout,
            "application": "SimpleChat",
            "client_session_keep_alive": False,
        }
        if self.database:
            connection_kwargs["database"] = self.database
        if self.schema:
            connection_kwargs["schema"] = self.schema
        if self.role:
            connection_kwargs["role"] = self.role

        auth_key = str(self._auth.get("key") or "")
        if self.auth_method == SNOWFLAKE_AUTH_METHOD_PASSWORD:
            connection_kwargs["password"] = auth_key
        elif self.auth_method == SNOWFLAKE_AUTH_METHOD_KEY_PAIR:
            connection_kwargs["private_key"] = self._load_private_key_der(auth_key)
        elif self.auth_method == SNOWFLAKE_AUTH_METHOD_OAUTH:
            connection_kwargs["authenticator"] = "oauth"
            connection_kwargs["token"] = auth_key
        return connection_kwargs

    def _load_private_key_der(self, private_key_value: str) -> bytes:
        try:
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives import serialization
        except ImportError as exc:
            raise ImportError("Snowflake key-pair authentication requires cryptography.") from exc

        normalized_key = str(private_key_value or "").replace("\\n", "\n").encode("utf-8")
        passphrase_value = self._additional_fields.get("private_key_passphrase") or None
        password = str(passphrase_value).encode("utf-8") if passphrase_value else None
        private_key = serialization.load_pem_private_key(
            normalized_key,
            password=password,
            backend=default_backend(),
        )
        return private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def _connect(self):
        try:
            import snowflake.connector
        except ImportError as exc:
            raise ImportError("Snowflake Connector for Python is not installed.") from exc
        debug_print(
            f"[SnowflakePlugin] Opening Snowflake connection account={self.account} user_present={bool(self.user)} "
            f"warehouse={self.warehouse} database={self.database or '<default>'} schema={self.schema or '<default>'} "
            f"role={self.role or '<default>'} auth_method={self.auth_method} "
            f"login_timeout={self.login_timeout} network_timeout={self.timeout}"
        )
        return snowflake.connector.connect(**self._build_connection_kwargs())

    def _serialize_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, time):
            return value.isoformat()
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, (list, tuple)):
            return [self._serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._serialize_value(item) for key, item in value.items()}
        return str(value)

    def _column_name(self, column_metadata: Any) -> str:
        if hasattr(column_metadata, "name"):
            return str(column_metadata.name)
        if isinstance(column_metadata, (list, tuple)) and column_metadata:
            return str(column_metadata[0])
        return str(column_metadata or "")

    def _column_type(self, column_metadata: Any) -> str:
        if hasattr(column_metadata, "type_code"):
            return str(column_metadata.type_code)
        if isinstance(column_metadata, (list, tuple)) and len(column_metadata) > 1:
            return str(column_metadata[1])
        return ""

    def _normalize_cursor_results(self, cursor: Any, query: str) -> Dict[str, Any]:
        description = cursor.description or []
        columns = [self._column_name(column) for column in description]
        column_metadata = [
            {
                "name": self._column_name(column),
                "type_code": self._column_type(column),
            }
            for column in description
        ]

        fetched_rows = cursor.fetchmany(self.max_rows + 1) if columns else []
        truncated_by_rows = len(fetched_rows) > self.max_rows
        fetched_rows = fetched_rows[: self.max_rows]
        rows = [
            {
                column_name: self._serialize_value(row[index] if index < len(row) else None)
                for index, column_name in enumerate(columns)
            }
            for row in fetched_rows
        ]

        serialized_rows = json.dumps(rows, default=str)
        truncated_by_bytes = len(serialized_rows) > self.byte_limit
        if truncated_by_bytes:
            trimmed_rows = []
            current_size = 2
            for row in rows:
                row_size = len(json.dumps(row, default=str)) + 1
                if trimmed_rows and current_size + row_size > self.byte_limit:
                    break
                trimmed_rows.append(row)
                current_size += row_size
            rows = trimmed_rows or rows[:1]

        return {
            "success": True,
            "query_id": getattr(cursor, "sfqid", None),
            "query": query,
            "columns": columns,
            "column_metadata": column_metadata,
            "rows": rows,
            "row_count": len(rows),
            "total_row_count": getattr(cursor, "rowcount", None),
            "truncated": bool(truncated_by_rows or truncated_by_bytes),
        }

    def _safe_error_message(self, exc: Exception, fallback: str) -> str:
        raw_message = str(getattr(exc, "msg", None) or getattr(exc, "raw_msg", None) or exc or fallback)
        sanitized = self._SECRET_REDACTION_PATTERN.sub(r"\1=[REDACTED]", raw_message)
        return sanitized[:500] or fallback

    def _execute_read_only_statement(self, query: str) -> Dict[str, Any]:
        validation_error = self._validate_read_only_query(query) if self.read_only else None
        if validation_error:
            return self._error_response(validation_error, error_type="validation", query=query)

        statement = self._apply_result_limit(query)
        connection = None
        cursor = None
        try:
            debug_print(
                f"[SnowflakePlugin] Executing Snowflake statement first_word={self._first_word(statement)} "
                f"statement_length={len(statement)} max_rows={self.max_rows} timeout={self.timeout}"
            )
            connection = self._connect()
            debug_print("[SnowflakePlugin] Snowflake connection opened; creating cursor.")
            cursor = connection.cursor()
            cursor.execute(statement, timeout=self.timeout)
            result = self._normalize_cursor_results(cursor, statement)
            debug_print(
                f"[SnowflakePlugin] Snowflake statement succeeded query_id={result.get('query_id')} "
                f"row_count={result.get('row_count')} truncated={result.get('truncated')}"
            )
            return result
        except Exception as exc:
            debug_print(
                f"[SnowflakePlugin] Snowflake statement failed account={self.account} warehouse={self.warehouse} "
                f"query_id={getattr(cursor, 'sfqid', None) if cursor else None} "
                f"exception_type={type(exc).__name__} message={self._safe_error_message(exc, 'Snowflake query failed.')}"
            )
            log_event(
                f"[SnowflakePlugin] Snowflake query failed: {exc}",
                extra={
                    "account": self.account,
                    "warehouse": self.warehouse,
                    "plugin_name": self.manifest.get("name"),
                    "snowflake_query_id": getattr(cursor, "sfqid", None) if cursor else None,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_response(
                self._safe_error_message(exc, "Snowflake query failed."),
                error_type="snowflake",
                query=statement,
                query_id=getattr(cursor, "sfqid", None) if cursor else None,
            )
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                    debug_print("[SnowflakePlugin] Snowflake cursor closed.")
                except Exception:
                    pass
            if connection is not None:
                try:
                    connection.close()
                    debug_print("[SnowflakePlugin] Snowflake connection closed.")
                except Exception:
                    pass

    def _error_response(self, message: str, error_type: str = "validation", **extra: Any) -> Dict[str, Any]:
        payload = {
            "success": False,
            "error": message,
            "error_type": error_type,
        }
        payload.update(extra)
        return payload

    @plugin_function_logger("SnowflakePlugin")
    @kernel_function(description="Execute a read-only SQL query against the configured Snowflake account.", name="execute_sql_query")
    def execute_sql_query(self, query: str) -> Dict[str, Any]:
        return self._execute_read_only_statement(query)

    @plugin_function_logger("SnowflakePlugin")
    @kernel_function(description="List databases visible to the configured Snowflake credentials.", name="get_databases")
    def get_databases(self) -> Dict[str, Any]:
        return self._execute_read_only_statement("SHOW DATABASES")

    @plugin_function_logger("SnowflakePlugin")
    @kernel_function(description="List Snowflake schemas in a database, or in the configured default database.", name="get_schemas")
    def get_schemas(self, database: str = "") -> Dict[str, Any]:
        try:
            database_path = self._qualified_identifier(database or self.database, max_parts=1) if (database or self.database) else ""
        except ValueError as exc:
            return self._error_response(str(exc), error_type="validation")
        statement = f"SHOW SCHEMAS IN DATABASE {database_path}" if database_path else "SHOW SCHEMAS"
        return self._execute_read_only_statement(statement)

    @plugin_function_logger("SnowflakePlugin")
    @kernel_function(description="List Snowflake tables in a schema.", name="get_tables")
    def get_tables(self, database: str = "", schema: str = "") -> Dict[str, Any]:
        try:
            schema_path = self._default_schema_path(database=database, schema=schema)
        except ValueError as exc:
            return self._error_response(str(exc), error_type="validation")
        statement = f"SHOW TABLES IN SCHEMA {schema_path}" if schema_path else "SHOW TABLES"
        return self._execute_read_only_statement(statement)

    @plugin_function_logger("SnowflakePlugin")
    @kernel_function(description="Describe a Snowflake table using a simple one-, two-, or three-part table name.", name="describe_table")
    def describe_table(self, table_name: str) -> Dict[str, Any]:
        try:
            table_path = self._qualified_identifier(table_name, max_parts=3)
        except ValueError as exc:
            return self._error_response(str(exc), error_type="validation")
        return self._execute_read_only_statement(f"DESCRIBE TABLE {table_path}")