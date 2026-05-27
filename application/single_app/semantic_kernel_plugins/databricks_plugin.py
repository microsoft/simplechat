# databricks_plugin.py
"""Semantic Kernel plugin for Azure Commercial Databricks SQL actions."""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from azure.identity import ClientSecretCredential, DefaultAzureCredential
from requests import RequestException
from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from functions_databricks_operations import (
    DATABRICKS_ALLOWED_READ_STATEMENTS,
    DATABRICKS_AZURE_COMMERCIAL_TOKEN_SCOPE,
    DATABRICKS_CLOUD_AZURE_COMMERCIAL,
    DATABRICKS_PLUGIN_TYPE,
    DATABRICKS_SQL_STATEMENTS_PATH,
    normalize_databricks_additional_fields,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class DatabricksPlugin(BasePlugin):
    """Databricks SQL Statement Execution plugin for Azure Commercial."""

    MAX_IDENTIFIER_PARTS = 3
    _SQL_COMMENT_PATTERN = re.compile(r"(--[^\r\n]*|/\*.*?\*/)", re.DOTALL)
    _FIRST_WORD_PATTERN = re.compile(r"^\s*([A-Za-z]+)", re.IGNORECASE)
    _LIMIT_PATTERN = re.compile(r"\blimit\b", re.IGNORECASE)
    _FORBIDDEN_READ_ONLY_PATTERN = re.compile(
        r"\b(ALTER|COPY|CREATE|DELETE|DROP|GRANT|INSERT|MERGE|OPTIMIZE|REFRESH|REPLACE|RESTORE|REVOKE|TRUNCATE|UPDATE|VACUUM)\b",
        re.IGNORECASE,
    )
    _IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._metadata = self.manifest.get("metadata", {}) or {}
        self._auth = self.manifest.get("auth", {}) if isinstance(self.manifest.get("auth"), dict) else {}
        self._additional_fields = normalize_databricks_additional_fields(
            self.manifest.get("additionalFields", {}),
            auth_type=str(self._auth.get("type") or ""),
        )
        self.endpoint = self._normalize_workspace_url(
            self.manifest.get("endpoint")
            or self._additional_fields.get("workspace_url")
            or self._additional_fields.get("workspaceUrl")
            or ""
        )
        self.cloud = self._additional_fields.get("cloud") or DATABRICKS_CLOUD_AZURE_COMMERCIAL
        self.auth_type = str(self._auth.get("type") or "key").strip()
        self.auth_method = self._additional_fields.get("auth_method") or "pat"
        self.warehouse_id = self._additional_fields.get("warehouse_id") or ""
        self.catalog = self._additional_fields.get("catalog") or ""
        self.schema = self._additional_fields.get("schema") or ""
        self.read_only = bool(self._additional_fields.get("read_only", True))
        self.max_rows = int(self._additional_fields.get("max_rows") or 1000)
        self.timeout = int(self._additional_fields.get("timeout") or 30)
        self.wait_timeout = int(self._additional_fields.get("wait_timeout") or 30)
        self.byte_limit = int(self._additional_fields.get("byte_limit") or 250000)
        self._validate_configuration()

    @property
    def display_name(self) -> str:
        return "Databricks"

    @property
    def metadata(self) -> Dict[str, Any]:
        user_description = self._metadata.get(
            "description",
            "Azure Commercial Databricks SQL action using the Statement Execution API.",
        )
        description = (
            f"{user_description}\n\n"
            "This action executes read-only SQL against an Azure Commercial Databricks SQL Warehouse. "
            "It uses the Databricks Statement Execution API, not an ODBC driver. "
            "Only SELECT, SHOW, DESCRIBE, EXPLAIN, and WITH queries are accepted by default."
        )
        return {
            "name": self.manifest.get("name", "databricks"),
            "type": DATABRICKS_PLUGIN_TYPE,
            "description": description,
            "methods": [
                {
                    "name": "execute_sql_query",
                    "description": "Execute a read-only SQL query against the configured Databricks SQL Warehouse.",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Read-only SQL query to execute.", "required": True},
                    ],
                    "returns": {"type": "dict", "description": "Query status, columns, rows, and row count."},
                },
                {
                    "name": "get_catalogs",
                    "description": "List catalogs available to the configured Databricks credentials.",
                    "parameters": [],
                    "returns": {"type": "dict", "description": "Catalog listing results."},
                },
                {
                    "name": "get_schemas",
                    "description": "List schemas in a catalog, or in the configured default catalog.",
                    "parameters": [
                        {"name": "catalog", "type": "str", "description": "Optional catalog name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Schema listing results."},
                },
                {
                    "name": "get_tables",
                    "description": "List tables in a schema, using provided or configured catalog/schema defaults.",
                    "parameters": [
                        {"name": "catalog", "type": "str", "description": "Optional catalog name.", "required": False},
                        {"name": "schema", "type": "str", "description": "Optional schema name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Table listing results."},
                },
                {
                    "name": "describe_table",
                    "description": "Describe a table using a one-, two-, or three-part table name.",
                    "parameters": [
                        {"name": "table_name", "type": "str", "description": "Table name to describe.", "required": True},
                    ],
                    "returns": {"type": "dict", "description": "Table description results."},
                },
            ],
        }

    def get_functions(self) -> List[str]:
        return [
            "execute_sql_query",
            "get_catalogs",
            "get_schemas",
            "get_tables",
            "describe_table",
        ]

    @classmethod
    def _normalize_workspace_url(cls, endpoint: Any) -> str:
        value = str(endpoint or "").strip().rstrip("/")
        if value.endswith(DATABRICKS_SQL_STATEMENTS_PATH):
            value = value[: -len(DATABRICKS_SQL_STATEMENTS_PATH)].rstrip("/")
        return value

    def _validate_configuration(self) -> None:
        if self.cloud != DATABRICKS_CLOUD_AZURE_COMMERCIAL:
            raise ValueError("Only Azure Commercial Databricks is supported by this action version.")

        parsed_endpoint = urlparse(self.endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            raise ValueError("Databricks action requires an HTTPS workspace URL endpoint.")
        if not self.warehouse_id:
            raise ValueError("Databricks action requires additionalFields.warehouse_id.")
        if self.auth_type not in {"key", "identity", "servicePrincipal"}:
            raise ValueError("Databricks action supports auth.type values 'key', 'identity', and 'servicePrincipal'.")
        if self.auth_type == "key" and not self._auth.get("key"):
            raise ValueError("Databricks action requires auth.key for PAT or bearer-token authentication.")
        if self.auth_type == "servicePrincipal":
            if not self._auth.get("identity") or not self._auth.get("key") or not self._auth.get("tenantId"):
                raise ValueError("Databricks service principal auth requires auth.identity, auth.key, and auth.tenantId.")

    def _get_access_token(self) -> str:
        if self.auth_type == "key":
            return str(self._auth.get("key") or "")
        if self.auth_type == "servicePrincipal":
            credential = ClientSecretCredential(
                tenant_id=str(self._auth.get("tenantId") or ""),
                client_id=str(self._auth.get("identity") or ""),
                client_secret=str(self._auth.get("key") or ""),
            )
            return credential.get_token(DATABRICKS_AZURE_COMMERCIAL_TOKEN_SCOPE).token
        credential = DefaultAzureCredential()
        return credential.get_token(DATABRICKS_AZURE_COMMERCIAL_TOKEN_SCOPE).token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
        }

    def _statement_url(self, statement_id: str = "") -> str:
        base_url = f"{self.endpoint}{DATABRICKS_SQL_STATEMENTS_PATH}"
        if statement_id:
            return f"{base_url}/{statement_id}"
        return base_url

    def _strip_sql_comments(self, query: str) -> str:
        return self._SQL_COMMENT_PATTERN.sub(" ", str(query or ""))

    def _validate_read_only_query(self, query: str) -> Optional[str]:
        normalized_query = self._strip_sql_comments(query).strip()
        if not normalized_query:
            return "SQL query is required."

        statements = [statement.strip() for statement in normalized_query.split(";") if statement.strip()]
        if len(statements) != 1:
            return "Only one SQL statement can be executed at a time."

        first_word_match = self._FIRST_WORD_PATTERN.match(statements[0])
        first_word = first_word_match.group(1).upper() if first_word_match else ""
        if first_word not in DATABRICKS_ALLOWED_READ_STATEMENTS:
            return f"Only read-only Databricks SQL statements are allowed. Found: {first_word or 'UNKNOWN'}."

        forbidden_match = self._FORBIDDEN_READ_ONLY_PATTERN.search(statements[0])
        if forbidden_match:
            return f"Read-only mode blocks SQL keyword: {forbidden_match.group(1).upper()}."
        return None

    def _apply_result_limit(self, query: str) -> str:
        stripped_query = str(query or "").strip().rstrip(";")
        first_word_match = self._FIRST_WORD_PATTERN.match(stripped_query)
        first_word = first_word_match.group(1).upper() if first_word_match else ""
        if first_word in {"SELECT", "WITH"} and not self._LIMIT_PATTERN.search(stripped_query):
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
            raise ValueError("Databricks identifiers must use simple catalog.schema.table names.")
        return path

    def _default_schema_path(self, catalog: str = "", schema: str = "") -> str:
        requested_catalog = str(catalog or self.catalog or "").strip()
        requested_schema = str(schema or self.schema or "").strip()
        if requested_catalog and requested_schema:
            return self._qualified_identifier(requested_catalog, requested_schema, max_parts=2)
        if requested_schema:
            return self._qualified_identifier(requested_schema, max_parts=1)
        if requested_catalog:
            return self._qualified_identifier(requested_catalog, max_parts=1)
        return ""

    def _submit_statement(self, statement: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "statement": statement,
            "warehouse_id": self.warehouse_id,
            "wait_timeout": f"{self.wait_timeout}s",
            "on_wait_timeout": "CONTINUE",
        }
        if self.catalog:
            payload["catalog"] = self.catalog
        if self.schema:
            payload["schema"] = self.schema

        response = requests.post(
            self._statement_url(),
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._wait_for_statement(response.json())

    def _wait_for_statement(self, statement_response: Dict[str, Any]) -> Dict[str, Any]:
        status = statement_response.get("status", {}) if isinstance(statement_response, dict) else {}
        state = str(status.get("state") or "").upper()
        statement_id = str(statement_response.get("statement_id") or "").strip()
        if state not in {"PENDING", "RUNNING"} or not statement_id:
            return statement_response

        deadline = time.time() + min(self.timeout, 60)
        current_response = statement_response
        while time.time() < deadline:
            time.sleep(1)
            response = requests.get(
                self._statement_url(statement_id),
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            current_response = response.json()
            status = current_response.get("status", {}) if isinstance(current_response, dict) else {}
            state = str(status.get("state") or "").upper()
            if state not in {"PENDING", "RUNNING"}:
                return current_response
        return current_response

    def _normalize_statement_response(self, statement_response: Dict[str, Any], query: str) -> Dict[str, Any]:
        if not isinstance(statement_response, dict):
            return self._error_response("Databricks returned an unexpected response shape.", error_type="response")

        status = statement_response.get("status", {}) if isinstance(statement_response.get("status"), dict) else {}
        state = str(status.get("state") or "UNKNOWN")
        error = status.get("error") if isinstance(status.get("error"), dict) else {}
        if state.upper() in {"FAILED", "CANCELED", "CLOSED"}:
            return self._error_response(
                str(error.get("message") or f"Databricks statement ended with state {state}."),
                error_type="databricks",
                status=state,
                query=query,
            )

        manifest = statement_response.get("manifest", {}) if isinstance(statement_response.get("manifest"), dict) else {}
        schema = manifest.get("schema", {}) if isinstance(manifest.get("schema"), dict) else {}
        columns = [column.get("name") for column in schema.get("columns", []) if isinstance(column, dict)]
        result = statement_response.get("result", {}) if isinstance(statement_response.get("result"), dict) else {}
        rows = result.get("data_array") if isinstance(result.get("data_array"), list) else []
        if columns and rows and isinstance(rows[0], list):
            rows = [dict(zip(columns, row)) for row in rows]

        serialized_rows = json.dumps(rows, default=str)
        truncated_by_bytes = len(serialized_rows) > self.byte_limit
        if truncated_by_bytes:
            rows = rows[: max(1, min(len(rows), self.max_rows))]

        return {
            "success": True,
            "statement_id": statement_response.get("statement_id"),
            "status": state,
            "query": query,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "total_row_count": manifest.get("total_row_count"),
            "truncated": bool(truncated_by_bytes),
        }

    def _execute_read_only_statement(self, query: str) -> Dict[str, Any]:
        validation_error = self._validate_read_only_query(query) if self.read_only else None
        if validation_error:
            return self._error_response(validation_error, error_type="validation", query=query)

        statement = self._apply_result_limit(query)
        try:
            statement_response = self._submit_statement(statement)
            return self._normalize_statement_response(statement_response, statement)
        except RequestException as exc:
            log_event(
                f"[DatabricksPlugin] Databricks request failed: {exc}",
                extra={"endpoint": self.endpoint, "plugin_name": self.manifest.get("name")},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_response("Databricks request failed.", error_type="request", query=statement)
        except Exception as exc:
            log_event(
                f"[DatabricksPlugin] Databricks statement execution failed: {exc}",
                extra={"endpoint": self.endpoint, "plugin_name": self.manifest.get("name")},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_response("Databricks statement execution failed.", error_type="unexpected", query=statement)

    def _error_response(self, message: str, error_type: str = "validation", **extra: Any) -> Dict[str, Any]:
        payload = {
            "success": False,
            "error": message,
            "error_type": error_type,
        }
        payload.update(extra)
        return payload

    @plugin_function_logger("DatabricksPlugin")
    @kernel_function(description="Execute a read-only SQL query against the configured Databricks SQL Warehouse.", name="execute_sql_query")
    def execute_sql_query(self, query: str) -> Dict[str, Any]:
        return self._execute_read_only_statement(query)

    @plugin_function_logger("DatabricksPlugin")
    @kernel_function(description="List catalogs available to the configured Databricks credentials.", name="get_catalogs")
    def get_catalogs(self) -> Dict[str, Any]:
        return self._execute_read_only_statement("SHOW CATALOGS")

    @plugin_function_logger("DatabricksPlugin")
    @kernel_function(description="List Databricks schemas in a catalog, or in the configured default catalog.", name="get_schemas")
    def get_schemas(self, catalog: str = "") -> Dict[str, Any]:
        try:
            catalog_path = self._qualified_identifier(catalog or self.catalog, max_parts=1) if (catalog or self.catalog) else ""
        except ValueError as exc:
            return self._error_response(str(exc), error_type="validation")
        statement = f"SHOW SCHEMAS IN {catalog_path}" if catalog_path else "SHOW SCHEMAS"
        return self._execute_read_only_statement(statement)

    @plugin_function_logger("DatabricksPlugin")
    @kernel_function(description="List Databricks tables in a schema.", name="get_tables")
    def get_tables(self, catalog: str = "", schema: str = "") -> Dict[str, Any]:
        try:
            schema_path = self._default_schema_path(catalog=catalog, schema=schema)
        except ValueError as exc:
            return self._error_response(str(exc), error_type="validation")
        statement = f"SHOW TABLES IN {schema_path}" if schema_path else "SHOW TABLES"
        return self._execute_read_only_statement(statement)

    @plugin_function_logger("DatabricksPlugin")
    @kernel_function(description="Describe a Databricks table using a simple one-, two-, or three-part table name.", name="describe_table")
    def describe_table(self, table_name: str) -> Dict[str, Any]:
        try:
            table_path = self._qualified_identifier(table_name, max_parts=3)
        except ValueError as exc:
            return self._error_response(str(exc), error_type="validation")
        return self._execute_read_only_statement(f"DESCRIBE TABLE {table_path}")