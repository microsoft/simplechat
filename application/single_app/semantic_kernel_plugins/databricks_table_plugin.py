# databricks_table_plugin.py
"""
Databricks Table Plugin for Semantic Kernel
- Dynamically created per table manifest
- Executes parameterized SQL via Databricks REST API
"""

import requests
import logging
from semantic_kernel_plugins.base_plugin import BasePlugin
from typing import Annotated, List, Optional, Required
from functions_appinsights import log_event
from semantic_kernel.functions import kernel_function

# Helper class to wrap results with metadata
class ResultWithMetadata:
    def __init__(self, data, metadata):
        self.data = data
        self.metadata = metadata
    def __str__(self):
        return str(self.data)
    def __repr__(self):
        return f"ResultWithMetadata(data={self.data!r}, metadata={self.metadata!r})"

class DatabricksTablePlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)
        self.manifest = manifest
        self.endpoint = manifest['endpoint']
        self.key = manifest.get('auth', {}).get('key', None)
        self.identity = manifest.get('auth', {}).get('identity', None)
        self.table_name = manifest['additionalFields']['table']
        self.columns = [col['name'] for col in manifest.get('additionalFields', {}).get('columns', [])]
        self._metadata = manifest['metadata']
        self.warehouse_id = manifest['additionalFields'].get('warehouse_id', '')

    @property
    def display_name(self) -> str:
        return "Databricks Table"

    @property
    def metadata(self):
        # Compose a detailed description for the LLM and Semantic Kernel
        user_desc = self._metadata.get("description", f"Databricks table plugin for {self.table_name}")
        api_desc = (
            "This plugin executes SQL statements against Azure Databricks using the Statement Execution API. "
            "It sends a POST request to the endpoint '/api/2.0/sql/statements' (e.g., 'https://<databricks-instance>/api/2.0/sql/statements'). "
            "Authentication is via a Databricks personal access token, passed as a Bearer token in the 'Authorization' header. "
            "The request body is JSON and must include: "
            "'statement': the SQL query string to execute, and 'warehouse_id': the ID of the Databricks SQL warehouse to use. "
            "Optional filters can be provided as keyword arguments and are converted into a SQL WHERE clause. "
            "The plugin constructs the SQL statement based on the selected columns and filters, then submits it to Databricks. "
            "The response is the result of the SQL query, returned as JSON. "
            "For more details, see: https://docs.databricks.com/api/azure/workspace/statementexecution/executestatement\n\n"
            "Configuration: The plugin is configured with the Databricks API endpoint, access token, warehouse_id, table name, and available columns via the plugin manifest. "
            "The manifest should provide: 'endpoint', 'auth.key', 'additionalFields.table', 'additionalFields.columns', and 'additionalFields.warehouse_id'. "
            "Example request body: { 'statement': 'SELECT * FROM my_table WHERE id = 1', 'warehouse_id': '<warehouse_id>' }. "
            "The plugin handles parameterization and SQL construction automatically."
        )
        full_desc = f"{user_desc}\n\n{api_desc}"
        return {
            "name": self._metadata.get("name", self.table_name),
            "type": "databricks_table",
            "description": full_desc,
            "methods": [
                {
                    "name": "query_table",
                    "description": "Query the Databricks table using parameterized SQL. Column names are listed in self.columns. Filters can be applied as keyword arguments.",
                    "parameters": [
                        {"name": "columns", "type": "List[str]", "description": "Columns to select", "required": False},
                        {"name": "warehouse_id", "type": "str", "description": "Databricks warehouse ID", "required": False},
                        {"name": "filters", "type": "dict", "description": "Additional filters as column=value pairs", "required": False}
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "The query result as a dictionary or list (Databricks SQL API response), always with a .metadata attribute."}
                }
            ]
        }

    def get_functions(self):
        return ["query_table"]

    @kernel_function(
        description="""
            Query the Databricks table using parameterized SQL. Column names are listed in self.columns.
            Filters can be applied as keyword arguments, e.g. `warehouse_id=123`.
            If no columns are specified, all columns will be selected.
        """,
        name="query_table_{self.table_name}",
    )
    async def query_table(
        self,
        columns: Annotated[Optional[List[str]], "List of columns to select from the table. If not provided, all columns will be selected."] = None,
        warehouse_id: Annotated[Optional[str], "Databricks warehouse ID to use for the query. Obtained from self.warehouse_id if not provided."] = None,
        **filters: Annotated[str, "Additional filters to apply as column=value pairs."]
    ) -> Annotated[ResultWithMetadata, "The query result as a dictionary or list (Databricks SQL API response), always with a .metadata attribute."]:
    
        # Determine columns to select
        if columns is None:
            select_cols = self.columns
        else:
            select_cols = columns
        # Validate columns
        for col in select_cols:
            if col not in self.columns:
                raise ValueError(f"Invalid column: {col}")

        # Build WHERE clause
        conditions = []
        for k, v in filters.items():
            if k in self.columns:
                if isinstance(v, str):
                    v = f"'{v}'"
                conditions.append(f"{k} = {v}")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"SELECT {', '.join(select_cols)} FROM {self.table_name} {where_clause}"

        headers = {
            'Authorization': f'Bearer {self.key}',
            'Content-Type': 'application/json'
        }
        # Prefer argument, then self.warehouse_id, then filters
        resolved_warehouse_id = warehouse_id or getattr(self, 'warehouse_id', None) or filters.get("warehouse_id", "")
        data = {
            "statement": sql,
            "warehouse_id": resolved_warehouse_id
        }
        response = requests.post(self.endpoint, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()

        # Robustly handle dict or list responses, always wrap in ResultWithMetadata
        if isinstance(result, (dict, list)):
            wrapped = ResultWithMetadata(result, self.metadata)
            log_event(
                f"[DatabricksTablePlugin] Returning dict ResultWithMetadata with .metadata: {wrapped.metadata}"
            )
            return wrapped
        else:
            log_event(
                f"[DatabricksTablePlugin] Unexpected result type: {type(result)}; wrapping anyway.",
                extra={"result_type": str(type(result)), "result_value": str(result)}
            )
            return ResultWithMetadata(result, self.metadata)
