# tabular_processing_plugin.py
"""
TabularProcessingPlugin for Semantic Kernel: provides data analysis operations
on tabular files (CSV, XLSX, XLS, XLSM) stored in Azure Blob Storage.

Works with both workspace documents (user-documents container) and
chat-uploaded documents (personal-chat container).
"""
import io
import json
import logging
import pandas
from typing import Annotated, Optional, List
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from functions_appinsights import log_event
from config import (
    CLIENTS,
    TABULAR_EXTENSIONS,
    storage_account_user_documents_container_name,
    storage_account_personal_chat_container_name,
    storage_account_group_documents_container_name,
)


class TabularProcessingPlugin:
    """Provides data analysis functions on tabular files stored in blob storage."""

    SUPPORTED_EXTENSIONS = {'.csv', '.xlsx', '.xls', '.xlsm'}

    def _get_blob_service_client(self):
        """Get the blob service client from CLIENTS cache."""
        client = CLIENTS.get("storage_account_office_docs_client")
        if not client:
            raise RuntimeError("Blob storage client not available. Enhanced citations must be enabled.")
        return client

    def _list_tabular_blobs(self, container_name: str, prefix: str) -> List[str]:
        """List all tabular file blobs under a given prefix."""
        client = self._get_blob_service_client()
        container_client = client.get_container_client(container_name)
        blobs = []
        for blob in container_client.list_blobs(name_starts_with=prefix):
            name_lower = blob['name'].lower()
            if any(name_lower.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS):
                blobs.append(blob['name'])
        return blobs

    def _read_tabular_blob_to_dataframe(self, container_name: str, blob_name: str) -> pandas.DataFrame:
        """Download a blob and read it into a pandas DataFrame."""
        client = self._get_blob_service_client()
        blob_client = client.get_blob_client(container=container_name, blob=blob_name)
        stream = blob_client.download_blob()
        data = stream.readall()

        name_lower = blob_name.lower()
        if name_lower.endswith('.csv'):
            return pandas.read_csv(io.BytesIO(data), keep_default_na=False, dtype=str)
        elif name_lower.endswith('.xlsx') or name_lower.endswith('.xlsm'):
            return pandas.read_excel(io.BytesIO(data), engine='openpyxl', keep_default_na=False, dtype=str)
        elif name_lower.endswith('.xls'):
            return pandas.read_excel(io.BytesIO(data), engine='xlrd', keep_default_na=False, dtype=str)
        else:
            raise ValueError(f"Unsupported tabular file type: {blob_name}")

    def _try_numeric_conversion(self, df: pandas.DataFrame) -> pandas.DataFrame:
        """Attempt to convert string columns to numeric where possible."""
        for col in df.columns:
            try:
                df[col] = pandas.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
        return df

    def _resolve_blob_location(self, user_id: str, conversation_id: str, filename: str, source: str) -> tuple:
        """Resolve container name and blob path from source type."""
        source = source.lower().strip()
        if source == 'chat':
            container = storage_account_personal_chat_container_name
            blob_path = f"{user_id}/{conversation_id}/{filename}"
        elif source == 'workspace':
            container = storage_account_user_documents_container_name
            blob_path = f"{user_id}/{filename}"
        else:
            raise ValueError(f"Unknown source '{source}'. Use 'workspace' or 'chat'.")
        return container, blob_path

    @kernel_function(
        description=(
            "List all tabular data files available for a user. Checks both workspace documents "
            "(user-documents container) and chat-uploaded documents (personal-chat container). "
            "Returns a JSON list of available files with their source (workspace or chat)."
        ),
        name="list_tabular_files"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    def list_tabular_files(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"]
    ) -> Annotated[str, "JSON list of available tabular files"]:
        """List all tabular files available for the user in workspace and chat containers."""
        results = []
        try:
            workspace_prefix = f"{user_id}/"
            workspace_blobs = self._list_tabular_blobs(
                storage_account_user_documents_container_name, workspace_prefix
            )
            for blob in workspace_blobs:
                filename = blob.split('/')[-1]
                results.append({
                    "filename": filename,
                    "blob_path": blob,
                    "source": "workspace",
                    "container": storage_account_user_documents_container_name
                })
        except Exception as e:
            log_event(f"[TabularProcessingPlugin] Error listing workspace blobs: {e}", level=logging.WARNING)

        try:
            chat_prefix = f"{user_id}/{conversation_id}/"
            chat_blobs = self._list_tabular_blobs(
                storage_account_personal_chat_container_name, chat_prefix
            )
            for blob in chat_blobs:
                filename = blob.split('/')[-1]
                results.append({
                    "filename": filename,
                    "blob_path": blob,
                    "source": "chat",
                    "container": storage_account_personal_chat_container_name
                })
        except Exception as e:
            log_event(f"[TabularProcessingPlugin] Error listing chat blobs: {e}", level=logging.WARNING)

        return json.dumps(results, indent=2)

    @kernel_function(
        description=(
            "Get a summary of a tabular file including column names, row count, data types, "
            "and a preview of the first few rows."
        ),
        name="describe_tabular_file"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    def describe_tabular_file(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        source: Annotated[str, "Source: 'workspace' or 'chat'"] = "chat"
    ) -> Annotated[str, "JSON summary of the tabular file"]:
        """Get schema and preview of a tabular file."""
        try:
            container, blob_path = self._resolve_blob_location(user_id, conversation_id, filename, source)
            df = self._read_tabular_blob_to_dataframe(container, blob_path)
            df_numeric = self._try_numeric_conversion(df.copy())

            summary = {
                "filename": filename,
                "row_count": len(df),
                "column_count": len(df.columns),
                "columns": list(df.columns),
                "dtypes": {col: str(dtype) for col, dtype in df_numeric.dtypes.items()},
                "preview": df.head(5).to_dict(orient='records'),
                "null_counts": df.isnull().sum().to_dict()
            }
            return json.dumps(summary, indent=2, default=str)
        except Exception as e:
            log_event(f"[TabularProcessingPlugin] Error describing file: {e}", level=logging.WARNING)
            return json.dumps({"error": str(e)})

    @kernel_function(
        description=(
            "Execute an aggregation operation on a column of a tabular file. "
            "Supported operations: sum, mean, count, min, max, median, std, nunique, value_counts."
        ),
        name="aggregate_column"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    def aggregate_column(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        column: Annotated[str, "The column name to aggregate"],
        operation: Annotated[str, "Aggregation: sum, mean, count, min, max, median, std, nunique, value_counts"],
        source: Annotated[str, "Source: 'workspace' or 'chat'"] = "chat"
    ) -> Annotated[str, "JSON result of the aggregation"]:
        """Execute an aggregation operation on a column."""
        try:
            container, blob_path = self._resolve_blob_location(user_id, conversation_id, filename, source)
            df = self._read_tabular_blob_to_dataframe(container, blob_path)
            df = self._try_numeric_conversion(df)

            if column not in df.columns:
                return json.dumps({"error": f"Column '{column}' not found. Available: {list(df.columns)}"})

            series = df[column]
            op = operation.lower().strip()

            if op == 'sum':
                result = series.sum()
            elif op == 'mean':
                result = series.mean()
            elif op == 'count':
                result = series.count()
            elif op == 'min':
                result = series.min()
            elif op == 'max':
                result = series.max()
            elif op == 'median':
                result = series.median()
            elif op == 'std':
                result = series.std()
            elif op == 'nunique':
                result = series.nunique()
            elif op == 'value_counts':
                result = series.value_counts().to_dict()
            else:
                return json.dumps({"error": f"Unsupported operation: {operation}. Use sum, mean, count, min, max, median, std, nunique, value_counts."})

            return json.dumps({"column": column, "operation": op, "result": result}, indent=2, default=str)
        except Exception as e:
            log_event(f"[TabularProcessingPlugin] Error aggregating column: {e}", level=logging.WARNING)
            return json.dumps({"error": str(e)})

    @kernel_function(
        description=(
            "Filter rows in a tabular file based on conditions and return matching rows. "
            "Supports operators: ==, !=, >, <, >=, <=, contains, startswith, endswith."
        ),
        name="filter_rows"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    def filter_rows(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        column: Annotated[str, "The column to filter on"],
        operator: Annotated[str, "Operator: ==, !=, >, <, >=, <=, contains, startswith, endswith"],
        value: Annotated[str, "The value to compare against"],
        source: Annotated[str, "Source: 'workspace' or 'chat'"] = "chat",
        max_rows: Annotated[str, "Maximum rows to return"] = "100"
    ) -> Annotated[str, "JSON list of matching rows"]:
        """Filter rows based on a condition."""
        try:
            container, blob_path = self._resolve_blob_location(user_id, conversation_id, filename, source)
            df = self._read_tabular_blob_to_dataframe(container, blob_path)
            df = self._try_numeric_conversion(df)

            if column not in df.columns:
                return json.dumps({"error": f"Column '{column}' not found. Available: {list(df.columns)}"})

            series = df[column]
            op = operator.strip().lower()

            numeric_value = None
            try:
                numeric_value = float(value)
            except (ValueError, TypeError):
                pass

            if op == '==' or op == 'equals':
                if numeric_value is not None and pandas.api.types.is_numeric_dtype(series):
                    mask = series == numeric_value
                else:
                    mask = series.astype(str).str.lower() == value.lower()
            elif op == '!=':
                if numeric_value is not None and pandas.api.types.is_numeric_dtype(series):
                    mask = series != numeric_value
                else:
                    mask = series.astype(str).str.lower() != value.lower()
            elif op == '>':
                mask = series > numeric_value
            elif op == '<':
                mask = series < numeric_value
            elif op == '>=':
                mask = series >= numeric_value
            elif op == '<=':
                mask = series <= numeric_value
            elif op == 'contains':
                mask = series.astype(str).str.contains(value, case=False, na=False)
            elif op == 'startswith':
                mask = series.astype(str).str.lower().str.startswith(value.lower())
            elif op == 'endswith':
                mask = series.astype(str).str.lower().str.endswith(value.lower())
            else:
                return json.dumps({"error": f"Unsupported operator: {operator}"})

            limit = int(max_rows)
            filtered = df[mask].head(limit)
            return json.dumps({
                "total_matches": int(mask.sum()),
                "returned_rows": len(filtered),
                "data": filtered.to_dict(orient='records')
            }, indent=2, default=str)
        except Exception as e:
            log_event(f"[TabularProcessingPlugin] Error filtering rows: {e}", level=logging.WARNING)
            return json.dumps({"error": str(e)})

    @kernel_function(
        description=(
            "Execute a pandas query expression against a tabular file for advanced analysis. "
            "The query string uses pandas DataFrame.query() syntax. "
            "Examples: 'Age > 30 and State == \"CA\"', 'Price < 100'"
        ),
        name="query_tabular_data"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    def query_tabular_data(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        query_expression: Annotated[str, "Pandas query expression (e.g. 'Age > 30 and State == \"CA\"')"],
        source: Annotated[str, "Source: 'workspace' or 'chat'"] = "chat",
        max_rows: Annotated[str, "Maximum rows to return"] = "100"
    ) -> Annotated[str, "JSON result of the query"]:
        """Execute a pandas query expression against a tabular file."""
        try:
            container, blob_path = self._resolve_blob_location(user_id, conversation_id, filename, source)
            df = self._read_tabular_blob_to_dataframe(container, blob_path)
            df = self._try_numeric_conversion(df)

            result_df = df.query(query_expression)
            limit = int(max_rows)
            return json.dumps({
                "total_matches": len(result_df),
                "returned_rows": min(len(result_df), limit),
                "data": result_df.head(limit).to_dict(orient='records')
            }, indent=2, default=str)
        except Exception as e:
            log_event(f"[TabularProcessingPlugin] Error querying data: {e}", level=logging.WARNING)
            return json.dumps({"error": f"Query error: {str(e)}. Ensure column names and values are correct."})

    @kernel_function(
        description=(
            "Perform a group-by aggregation on a tabular file. "
            "Groups data by one column and aggregates another column. "
            "Supported operations: sum, mean, count, min, max."
        ),
        name="group_by_aggregate"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    def group_by_aggregate(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        group_by_column: Annotated[str, "The column to group by"],
        aggregate_column: Annotated[str, "The column to aggregate"],
        operation: Annotated[str, "Aggregation operation: sum, mean, count, min, max"],
        source: Annotated[str, "Source: 'workspace' or 'chat'"] = "chat"
    ) -> Annotated[str, "JSON result of the group-by aggregation"]:
        """Group by one column and aggregate another."""
        try:
            container, blob_path = self._resolve_blob_location(user_id, conversation_id, filename, source)
            df = self._read_tabular_blob_to_dataframe(container, blob_path)
            df = self._try_numeric_conversion(df)

            for col in [group_by_column, aggregate_column]:
                if col not in df.columns:
                    return json.dumps({"error": f"Column '{col}' not found. Available: {list(df.columns)}"})

            op = operation.lower().strip()
            grouped = df.groupby(group_by_column)[aggregate_column].agg(op)
            return json.dumps({
                "group_by": group_by_column,
                "aggregate_column": aggregate_column,
                "operation": op,
                "groups": len(grouped),
                "result": grouped.to_dict()
            }, indent=2, default=str)
        except Exception as e:
            log_event(f"[TabularProcessingPlugin] Error in group-by: {e}", level=logging.WARNING)
            return json.dumps({"error": str(e)})
