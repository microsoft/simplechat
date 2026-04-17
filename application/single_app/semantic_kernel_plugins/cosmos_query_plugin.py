# cosmos_query_plugin.py
"""
Read-only Azure Cosmos DB query plugin for Semantic Kernel.
"""

import hashlib
import itertools
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Union

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.identity import DefaultAzureCredential
from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class ResultWithMetadata:
    def __init__(self, data: Any, metadata: Dict[str, Any]):
        self.data = data
        self.metadata = metadata

    def __str__(self) -> str:
        return str(self.data)

    def __repr__(self) -> str:
        return f"ResultWithMetadata(data={self.data!r}, metadata={self.metadata!r})"


class CosmosQueryPlugin(BasePlugin):
    """Read-only Azure Cosmos DB for NoSQL query plugin."""

    _client_cache: Dict[str, CosmosClient] = {}

    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)
        self.manifest = manifest or {}
        additional_fields = self.manifest.get("additionalFields", {}) or {}

        self.endpoint = (self.manifest.get("endpoint") or "").strip()
        self.database_name = (
            self.manifest.get("database_name")
            or additional_fields.get("database_name")
            or ""
        ).strip()
        self.container_name = (
            self.manifest.get("container_name")
            or additional_fields.get("container_name")
            or ""
        ).strip()
        self.partition_key_path = (
            self.manifest.get("partition_key_path")
            or additional_fields.get("partition_key_path")
            or ""
        ).strip()
        self.field_hints = self._normalize_field_hints(additional_fields.get("field_hints"))
        self.max_items = int(additional_fields.get("max_items", 100) or 100)
        self.timeout = int(additional_fields.get("timeout", 30) or 30)
        self.auth_type = (((self.manifest.get("auth") or {}).get("type") or "identity").strip().lower())
        self.auth_identity = ((self.manifest.get("auth") or {}).get("identity") or "managed_identity").strip()
        self.auth_key = ((self.manifest.get("auth") or {}).get("key") or "").strip()
        self._metadata = self.manifest.get("metadata", {}) or {}
        self._container_client = None

        self._validate_configuration()

        log_event(
            "[CosmosQueryPlugin] Initialized plugin",
            extra={
                "endpoint": self.endpoint,
                "database_name": self.database_name,
                "container_name": self.container_name,
                "partition_key_path": self.partition_key_path,
                "field_hint_count": len(self.field_hints),
                "max_items": self.max_items,
                "timeout": self.timeout,
                "auth_type": self.auth_type,
                "auth_identity": self.auth_identity,
                "has_auth_key": bool(self.auth_key),
            },
            level=logging.INFO,
        )

    @property
    def display_name(self) -> str:
        return "Cosmos Query"

    @property
    def metadata(self) -> Dict[str, Any]:
        user_desc = self._metadata.get(
            "description",
            "Read-only Azure Cosmos DB query plugin for a single configured container.",
        )
        api_desc = (
            "This plugin runs read-only Azure Cosmos DB for NoSQL queries against one configured "
            "database and container. Use the configured partition key path and field hints when "
            "constructing queries. Prefer parameterized queries, and provide the partition_key "
            "argument when you know the partition value so the request can stay scoped to a single "
            "partition. Mutation statements are blocked."
        )
        return {
            "name": self._metadata.get("name", "cosmos_query_plugin"),
            "type": "cosmos_query",
            "description": f"{user_desc}\n\n{api_desc}",
            "methods": [
                {
                    "name": "execute_query",
                    "description": "Execute a read-only Azure Cosmos DB SQL query against the configured container.",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Cosmos DB SQL query text.", "required": True},
                        {"name": "parameters", "type": "List[Dict[str, Any]] | Dict[str, Any]", "description": "Optional query parameters using @name placeholders.", "required": False},
                        {"name": "max_items", "type": "int", "description": "Optional per-call item cap.", "required": False},
                        {"name": "partition_key", "type": "str", "description": "Optional partition key value to scope the query to one logical partition.", "required": False},
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "Structured query results and execution metadata."},
                },
                {
                    "name": "validate_query",
                    "description": "Validate that a Cosmos DB query is read-only and shaped for this configured container.",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Cosmos DB SQL query text.", "required": True},
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "Validation result with issues and recommendations."},
                },
                {
                    "name": "query_container",
                    "description": "Execute a read-only query for a natural-language question and return structured results with the original question context.",
                    "parameters": [
                        {"name": "question", "type": "str", "description": "The user question being answered.", "required": True},
                        {"name": "query", "type": "str", "description": "Cosmos DB SQL query text.", "required": True},
                        {"name": "parameters", "type": "List[Dict[str, Any]] | Dict[str, Any]", "description": "Optional query parameters using @name placeholders.", "required": False},
                        {"name": "max_items", "type": "int", "description": "Optional per-call item cap.", "required": False},
                        {"name": "partition_key", "type": "str", "description": "Optional partition key value to scope the query to one logical partition.", "required": False},
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "Structured query results and execution metadata with question context."},
                },
            ],
        }

    def get_functions(self) -> List[str]:
        return ["execute_query", "validate_query", "query_container"]

    def build_instruction_context(self) -> str:
        hint_lines = [f"- {field_hint}" for field_hint in self.field_hints] or ["- No field hints were configured."]
        return (
            f"### Cosmos Container: {self.database_name}.{self.container_name}\n"
            f"- Account endpoint: {self.endpoint}\n"
            f"- Partition key path: {self.partition_key_path}\n"
            f"- Max items per call: {self.max_items}\n"
            "- Queries must be read-only SELECT statements.\n"
            "- Prefer parameterized queries and pass the partition_key argument when the partition value is known.\n"
            "- Configured field hints:\n"
            + "\n".join(hint_lines)
        )

    @kernel_function(description="Execute a read-only Azure Cosmos DB SQL query against the configured database and container. Prefer parameterized queries and pass the partition_key argument when you know the partition value so the query can stay within a single logical partition.")
    @plugin_function_logger("CosmosQueryPlugin")
    def execute_query(
        self,
        query: str,
        parameters: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        max_items: Optional[int] = None,
        partition_key: Optional[str] = None,
    ) -> ResultWithMetadata:
        validation_result = self._validate_query(query)
        if not validation_result["is_valid"]:
            return ResultWithMetadata(
                {
                    "error": "Invalid Cosmos DB query.",
                    "issues": validation_result["issues"],
                    "recommendations": validation_result["recommendations"],
                    "query": query,
                },
                self.metadata,
            )

        normalized_parameters = self._normalize_query_parameters(parameters)
        effective_max_items = min(max_items or self.max_items, self.max_items)
        response_headers: Dict[str, str] = {}

        def capture_response_headers(headers: Dict[str, str], _: Dict[str, Any]) -> None:
            response_headers.clear()
            response_headers.update(headers)

        try:
            container_client = self._get_container_client()
            query_kwargs: Dict[str, Any] = {
                "query": self._clean_query(query),
                "parameters": normalized_parameters,
                "max_item_count": effective_max_items,
                "populate_query_metrics": True,
                "response_hook": capture_response_headers,
            }

            if partition_key not in (None, ""):
                query_kwargs["partition_key"] = partition_key
                query_kwargs["enable_cross_partition_query"] = False
            else:
                query_kwargs["enable_cross_partition_query"] = True

            iterator = container_client.query_items(**query_kwargs)
            items = list(itertools.islice(iterator, effective_max_items + 1))
            is_truncated = len(items) > effective_max_items
            if is_truncated:
                items = items[:effective_max_items]

            result = {
                "database_name": self.database_name,
                "container_name": self.container_name,
                "partition_key_path": self.partition_key_path,
                "partition_key_applied": partition_key not in (None, ""),
                "field_hints": self.field_hints,
                "query": self._clean_query(query),
                "parameters": normalized_parameters,
                "items": items,
                "item_count": len(items),
                "is_truncated": is_truncated,
                "request_charge": response_headers.get("x-ms-request-charge"),
                "query_metrics": response_headers.get("x-ms-documentdb-query-metrics"),
                "activity_id": response_headers.get("x-ms-activity-id"),
            }

            log_event(
                "[CosmosQueryPlugin] Query executed successfully",
                extra={
                    "database_name": self.database_name,
                    "container_name": self.container_name,
                    "partition_key_applied": partition_key not in (None, ""),
                    "item_count": len(items),
                    "is_truncated": is_truncated,
                    "request_charge": response_headers.get("x-ms-request-charge"),
                },
                level=logging.INFO,
            )
            return ResultWithMetadata(result, self.metadata)
        except CosmosHttpResponseError as exc:
            log_event(
                f"[CosmosQueryPlugin] Cosmos query failed: {exc}",
                extra={
                    "database_name": self.database_name,
                    "container_name": self.container_name,
                    "status_code": getattr(exc, "status_code", None),
                    "activity_id": response_headers.get("x-ms-activity-id"),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return ResultWithMetadata(
                {
                    "error": str(exc),
                    "query": query,
                    "parameters": normalized_parameters,
                    "items": [],
                    "item_count": 0,
                },
                self.metadata,
            )
        except Exception as exc:
            log_event(
                f"[CosmosQueryPlugin] Unexpected query failure: {exc}",
                extra={
                    "database_name": self.database_name,
                    "container_name": self.container_name,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return ResultWithMetadata(
                {
                    "error": str(exc),
                    "query": query,
                    "parameters": normalized_parameters,
                    "items": [],
                    "item_count": 0,
                },
                self.metadata,
            )

    @kernel_function(description="Validate that an Azure Cosmos DB query is read-only and suitable for the configured container before executing it.")
    @plugin_function_logger("CosmosQueryPlugin")
    def validate_query(self, query: str) -> ResultWithMetadata:
        return ResultWithMetadata(self._validate_query(query), self.metadata)

    @kernel_function(description="Execute a read-only Azure Cosmos DB SQL query for a natural-language question and return the matching documents with the original question for context.")
    @plugin_function_logger("CosmosQueryPlugin")
    def query_container(
        self,
        question: str,
        query: str,
        parameters: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        max_items: Optional[int] = None,
        partition_key: Optional[str] = None,
    ) -> ResultWithMetadata:
        query_result = self.execute_query(
            query=query,
            parameters=parameters,
            max_items=max_items,
            partition_key=partition_key,
        )
        payload = dict(query_result.data) if isinstance(query_result.data, dict) else {"result": query_result.data}
        payload["question"] = question
        return ResultWithMetadata(payload, query_result.metadata)

    def _get_container_client(self):
        if self._container_client is None:
            client_cache_key = self._get_client_cache_key()
            client = self._client_cache.get(client_cache_key)
            if client is None:
                client = CosmosClient(
                    self.endpoint,
                    credential=self._get_client_credential(),
                    timeout=self.timeout,
                    connection_timeout=self.timeout,
                )
                self._client_cache[client_cache_key] = client

            database_client = client.get_database_client(self.database_name)
            self._container_client = database_client.get_container_client(self.container_name)
        return self._container_client

    def _validate_configuration(self) -> None:
        missing_fields = []
        if not self.endpoint:
            missing_fields.append("endpoint")
        if not self.database_name:
            missing_fields.append("database_name")
        if not self.container_name:
            missing_fields.append("container_name")
        if not self.partition_key_path:
            missing_fields.append("partition_key_path")
        if self.auth_type == "identity":
            pass
        elif self.auth_type == "key":
            if not self.auth_key:
                raise ValueError("CosmosQueryPlugin requires auth.key when auth.type is 'key'.")
        else:
            raise ValueError("CosmosQueryPlugin only supports auth.type values 'identity' and 'key'.")
        if missing_fields:
            raise ValueError(
                "CosmosQueryPlugin requires the following fields: " + ", ".join(missing_fields)
            )
        if self.max_items < 1:
            raise ValueError("CosmosQueryPlugin max_items must be at least 1.")
        if self.timeout < 1:
            raise ValueError("CosmosQueryPlugin timeout must be at least 1 second.")

    def _get_client_credential(self):
        if self.auth_type == "key":
            return self.auth_key
        return DefaultAzureCredential()

    def _get_client_cache_key(self) -> str:
        if self.auth_type == "key":
            key_hash = hashlib.sha256(self.auth_key.encode("utf-8")).hexdigest()[:16]
            return f"{self.endpoint}|{self.timeout}|key|{key_hash}"
        return f"{self.endpoint}|{self.timeout}|identity|{self.auth_identity or 'managed_identity'}"

    def _normalize_field_hints(self, field_hints: Optional[Union[str, Sequence[str]]]) -> List[str]:
        if isinstance(field_hints, str):
            values = re.split(r"[,\n]", field_hints)
            return [value.strip() for value in values if value.strip()]
        if isinstance(field_hints, Sequence):
            normalized = []
            for value in field_hints:
                if isinstance(value, str) and value.strip():
                    normalized.append(value.strip())
            return normalized
        return []

    def _normalize_query_parameters(
        self,
        parameters: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]],
    ) -> List[Dict[str, Any]]:
        if parameters is None:
            return []
        if isinstance(parameters, dict):
            normalized = []
            for name, value in parameters.items():
                placeholder_name = name if str(name).startswith("@") else f"@{name}"
                normalized.append({"name": placeholder_name, "value": value})
            return normalized
        normalized_list: List[Dict[str, Any]] = []
        for parameter in parameters:
            if not isinstance(parameter, dict):
                raise ValueError("Cosmos query parameters must be dictionaries with 'name' and 'value' keys.")
            name = parameter.get("name")
            if not name:
                raise ValueError("Each Cosmos query parameter requires a 'name'.")
            normalized_list.append(
                {
                    "name": name if str(name).startswith("@") else f"@{name}",
                    "value": parameter.get("value"),
                }
            )
        return normalized_list

    def _clean_query(self, query: str) -> str:
        return (query or "").strip()

    def _validate_query(self, query: str) -> Dict[str, Any]:
        cleaned_query = self._clean_query(query)
        issues: List[str] = []
        recommendations: List[str] = []

        if not cleaned_query:
            issues.append("A Cosmos DB query is required.")
        if cleaned_query and not re.match(r"^SELECT\b", cleaned_query, flags=re.IGNORECASE):
            issues.append("Only read-only SELECT queries are allowed.")
        if ";" in cleaned_query:
            issues.append("Multiple statements are not allowed.")

        blocked_keywords = [
            "INSERT",
            "UPDATE",
            "DELETE",
            "UPSERT",
            "REPLACE",
            "CREATE",
            "ALTER",
            "DROP",
            "TRUNCATE",
            "MERGE",
            "EXEC",
            "CALL",
            "GRANT",
            "REVOKE",
        ]
        blocked_keyword_pattern = r"\b(" + "|".join(blocked_keywords) + r")\b"
        if cleaned_query and re.search(blocked_keyword_pattern, cleaned_query, flags=re.IGNORECASE):
            issues.append("The query contains mutation or administrative keywords that are not allowed.")

        partition_key_field = self.partition_key_path.lstrip("/")
        if partition_key_field and partition_key_field not in cleaned_query:
            recommendations.append(
                f"Consider filtering on the configured partition key field '{partition_key_field}' or passing the partition_key argument to reduce cross-partition cost."
            )
        if self.field_hints:
            recommendations.append(
                "Use the configured field hints when selecting and filtering document properties: "
                + ", ".join(self.field_hints)
            )

        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "recommendations": recommendations,
            "partition_key_path": self.partition_key_path,
            "field_hints": self.field_hints,
        }