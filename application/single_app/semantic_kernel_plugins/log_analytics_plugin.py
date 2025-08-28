# log_analytics_plugin.py
"""
Azure Log Analytics Semantic Kernel Plugin

This plugin exposes Azure Log Analytics workspace querying and schema discovery as plugin functions.
"""


from typing import Dict, Any, List, Optional
from datetime import timedelta
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from config import *
import json
import logging

try:
    from azure.monitor.query import LogsQueryClient
    from azure.identity import DefaultAzureCredential, AzureAuthorityHosts
except ImportError:
    LogsQueryClient = None
    DefaultAzureCredential = None

class LogAnalyticsPlugin(BasePlugin):
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        self.manifest = manifest or {}
        # Ensure required manifest/additionalFields paths are present
        if "additionalFields" not in self.manifest:
            self.manifest["additionalFields"] = {}
        self.additional_fields = self.manifest["additionalFields"]

        # Set cloud if not present
        if "cloud" not in self.additional_fields:
            self.additional_fields["cloud"] = None
        self.cloud = self.additional_fields["cloud"]
        # Set workspaceId if not present
        self.workspace_id = self.additional_fields.get("workspaceId")
        # Set endpoint if not present
        if "endpoint" not in self.manifest:
            self.manifest["endpoint"] = None
        self.endpoint = self.manifest.get("endpoint")
        self.auth = self.manifest.get("auth", {})
        self.metadata_dict = self.manifest.get("metadata", {})
        self.authority_host = self.additional_fields.get("authorityHost") if self.cloud == "custom" else None
        self.endpoint_override = self.additional_fields.get("endpointOverride") if self.cloud == "custom" else None
        self._metadata = self._generate_metadata()
        self._client = None
        if LogsQueryClient and self.workspace_id:
            self._client = self._init_client()

    
    def _init_client(self):
        # Determine authority host for the selected cloud
        if self.cloud == "custom":
            authority_host = self.authority_host
        elif self.cloud == "usgovernment":
            authority_host = AzureAuthorityHosts.AZURE_GOVERNMENT
        else:
            authority_host = AzureAuthorityHosts.AZURE_PUBLIC_CLOUD

        # Auth selection logic (unchanged)
        if self.auth.get("type") == "identity":
            identity_client_id = (
                self.auth.get("identity")
                or self.additional_fields.get("identity")
            )
            if identity_client_id:
                credential = DefaultAzureCredential(authority=authority_host, managed_identity_client_id=identity_client_id)
            else:
                credential = DefaultAzureCredential(authority=authority_host)
        elif self.auth.get("type") == "servicePrincipal":
            try:
                from azure.identity import ClientSecretCredential
            except ImportError:
                ClientSecretCredential = None
            client_id = self.auth.get("identity")
            client_secret = self.auth.get("key")
            tenant_id = self.auth.get("tenantId")
            if client_id and client_secret and tenant_id and ClientSecretCredential:
                credential = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret, authority=authority_host)
            else:
                credential = None
        elif self.auth.get("type") == "user":
            try:
                from application.single_app.functions_authentication import get_valid_access_token_for_plugins
            except ImportError:
                from functions_authentication import get_valid_access_token_for_plugins

            from azure.core.credentials import AccessToken, TokenCredential
            import time

            class UserTokenCredential(TokenCredential):
                def __init__(self, scope):
                    self.scope = scope

                def get_token(self, *args, **kwargs):
                    token_result = get_valid_access_token_for_plugins(scopes=[self.scope])
                    if isinstance(token_result, dict) and token_result.get("access_token"):
                        token = token_result["access_token"]
                    elif isinstance(token_result, dict) and token_result.get("error"):
                        # Propagate error up to plugin
                        raise Exception(token_result)
                    else:
                        raise RuntimeError("Could not acquire user access token for Log Analytics API.")
                    expires_on = int(time.time()) + 300
                    return AccessToken(token, expires_on)

            if self.cloud == "custom":
                scope = f"{self.endpoint_override}/.default" if self.endpoint_override else "https://api.loganalytics.io/.default"
            elif self.cloud == "usgovernment":
                scope = "https://api.loganalytics.us/.default"
            else:
                scope = "https://api.loganalytics.io/.default"
            credential = UserTokenCredential(scope)
        elif self.auth.get("type") == "key":
            credential = None
        else:
            credential = None

        # Endpoint selection: prefer additionalFields.cloud, then manifest["endpoint"], then fallback
        endpoint = None
        if self.cloud == "custom":
            endpoint = self.endpoint_override or self.manifest.get("endpoint")
        elif self.cloud == "usgovernment":
            endpoint = "https://api.loganalytics.us"
        elif self.cloud == "public":
            endpoint = "https://api.loganalytics.io"
        else:
            endpoint = self.manifest.get("endpoint")

        # If endpoint is still None, fallback to a default
        if not endpoint:
            endpoint = "https://api.loganalytics.io"

        # Ensure /v1 is present as the first path segment
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(endpoint)
        path = parsed.path or ""
        if not path.startswith("/v1"):
            # Insert /v1 at the start of the path
            new_path = "/v1" + (path if path.startswith("/") else "/" + path)
            endpoint = urlunparse(parsed._replace(path=new_path))

        self.endpoint = endpoint

        if credential:
            # Use endpoint parameter in LogsQueryClient if supported
            try:
                return LogsQueryClient(credential, endpoint=endpoint)
            except TypeError:
                # Fallback for older SDKs
                return LogsQueryClient(credential)
        return None

    @property
    def display_name(self) -> str:
        return "Log Analytics"
    
    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": "LogAnalyticsPlugin",
            "type": "log_analytics",
            "description": "Plugin for querying Azure Log Analytics and discovering schema.",
            "methods": self._metadata["methods"]
        }

    def _generate_metadata(self) -> Dict[str, Any]:
        methods = [
            {
                "name": "list_tables",
                "description": "List all tables in the connected Azure Log Analytics workspace. Useful for schema discovery and query authoring.",
                "parameters": [],
                "returns": {"type": "list[string]", "description": "A list of all table names in the workspace."}
            },
            {
                "name": "get_table_schema",
                "description": "Get the schema (column names and types) for a specific table by running a describe query in Log Analytics.",
                "parameters": [
                    {"name": "table_name", "type": "string", "description": "The name of the table to describe.", "required": True}
                ],
                "returns": {"type": "object", "description": "A dictionary mapping column names to their types for the specified table."}
            },
            {
                "name": "get_all_table_schemas",
                "description": "Return a dictionary of all tables and their schemas (column names and types, including Properties virtual columns) in the connected Azure Log Analytics workspace. This combines list_tables and get_table_schema for efficient schema discovery.",
                "parameters": [],
                "returns": {"type": "object", "description": "A dictionary mapping table names to their schemas (column name to type)."}
            },
            {
                "name": "run_query",
                "description": "Run a KQL (Kusto Query Language) query against the Log Analytics workspace and return the results. Results are chunked for LLMs if needed. Accepts an optional timespan parameter (timedelta, tuple, or hours).",
                "parameters": [
                    {"name": "query", "type": "string", "description": "The KQL query string to execute.", "required": True},
                    {"name": "user_id", "type": "string", "description": "User ID for query history tracking (optional).", "required": False},
                    {"name": "timespan", "type": "any", "description": "Query timespan: timedelta, (start, end) tuple, or number of hours (optional).", "required": False}
                ],
                "returns": {"type": "list[object]", "description": "A list of result rows, each as a dictionary of column values."}
            },
            {
                "name": "summarize_results",
                "description": "Summarize a result set for LLM consumption, including row count, column names, and a sample row.",
                "parameters": [
                    {"name": "results", "type": "list[object]", "description": "The query results to summarize.", "required": True}
                ],
                "returns": {"type": "string", "description": "A human-readable summary of the results, including row count, columns, and a sample row."}
            },
            {
                "name": "get_query_history",
                "description": "Return the last N queries run by this plugin instance for the current user. Useful for re-running or editing previous queries.",
                "parameters": [
                    {"name": "limit", "type": "integer", "description": "Number of queries to return (default 20).", "required": False},
                    {"name": "user_id", "type": "string", "description": "User ID for query history tracking (optional).", "required": False}
                ],
                "returns": {"type": "list[string]", "description": "A list of previous KQL queries, most recent last."}
            },
            {
                "name": "validate_query",
                "description": "Validate a KQL query for basic safety and allowed patterns. Blocks dangerous commands (drop, delete, alter, etc).",
                "parameters": [
                    {"name": "query", "type": "string", "description": "The KQL query string to validate.", "required": True}
                ],
                "returns": {"type": "boolean", "description": "True if the query is valid and safe, False otherwise."}
            }
        ]
        return {"methods": methods}

    def get_functions(self) -> List[str]:
        return [m["name"] for m in self._metadata["methods"]]
    
    @plugin_function_logger("LogAnalyticsPlugin")
    @kernel_function(description="Return a dictionary of all tables and their schemas (column names and types, including Properties virtual columns) in the connected Azure Log Analytics workspace. This combines list_tables and get_table_schema for efficient schema discovery.")
    def get_all_table_schemas(self) -> Dict[str, Dict[str, str]]:
        """
        Returns a dict: {table_name: {column_name: type, ...}, ...}
        """
        logging.debug("[LA] Getting all table schemas")
        tables = self.list_tables()
        if isinstance(tables, dict) and ("error" in tables or "consent_url" in tables):
            return tables
        all_schemas = {}
        for table in tables:
            schema = self.get_table_schema(table)
            all_schemas[table] = schema
        logging.debug(f"[LA] get_all_table_schemas: {list(all_schemas.keys())}")
        return all_schemas

    @plugin_function_logger("LogAnalyticsPlugin")
    @kernel_function(description="Return the names of all tables in the connected Azure Log Analytics workspace that have data in the last 365 days. Use this function first to discover which tables are available before attempting to query or get schemas for specific tables.")
    def list_tables(self) -> Any:
        logging.debug("[LA] Listing tables")
        if not self._client:
            raise RuntimeError("Log Analytics client not initialized.")
        # Use a union query to get all table names (avoid TableName collision)
        query = """
            union withsource=SourceTable *
            | where TimeGenerated > ago(365d)
            | summarize by SourceTable
        """
        try:
            response = self._client.query_workspace(workspace_id=self.workspace_id, query=query, timespan=timedelta(days=365))
        except Exception as ex:
            # If the exception is a dict from get_valid_access_token, propagate it
            if isinstance(ex.args[0], dict):
                return ex.args[0]
            msg = str(ex)
            return {"error": msg}
        try:
            logging.debug("[LA] list_tables raw response: %s", repr(response))
        except Exception as e:
            logging.debug(f"[LA] list_tables raw response could not be repr'd: {e}")
        # Log the response.tables if present
        try:
            if hasattr(response, 'tables'):
                logging.debug("[LA] list_tables response.tables: %s", repr(response.tables))
        except Exception as e:
            logging.debug(f"[LA] list_tables response.tables could not be repr'd: {e}")
        if isinstance(response, dict) and ("error" in response or "consent_url" in response):
            return response
        # Extract SourceTable names from results using column index
        tables = []
        if response.tables and response.tables[0].columns:
            columns = response.tables[0].columns
            rows = response.tables[0].rows
            # Support both string and object columns
            def col_name(col):
                return getattr(col, 'name', col)
            try:
                idx = next(i for i, col in enumerate(columns) if col_name(col) == "SourceTable")
                for row in rows:
                    val = row[idx]
                    if val:
                        tables.append(val)
            except StopIteration:
                # SourceTable column not found
                pass
        # Log the output tables as JSON
        try:
            logging.debug("[LA] list_tables output: %s", json.dumps(tables))
        except Exception as e:
            logging.debug(f"[LA] list_tables output could not be JSON serialized: {e}")
        return tables

    @plugin_function_logger("LogAnalyticsPlugin")
    @kernel_function(description="Get the schema (column names and data types) for a specific table. Call this multiple times looping through tables discovered by list_tables to discover valid columns and data types before constructing or validating queries, ensuring that all column names used in queries are correct and exist in the table.")
    def get_table_schema(self, table_name: str) -> Any:
        logging.debug(f"[LA] Getting schema for table: {table_name}")
        if not self._client:
            raise RuntimeError("Log Analytics client not initialized.")
        query = f"{table_name} | getschema"
        # Use run_query for consistent consent/error handling
        response = self._client.query_workspace(workspace_id=self.workspace_id, query=query, timespan=timedelta(days=365))
        # Debug log the raw response and response.tables
        try:
            logging.debug("[LA] get_table_schema raw response: %s", repr(response))
        except Exception as e:
            logging.debug(f"[LA] get_table_schema raw response could not be repr'd: {e}")
        try:
            if hasattr(response, 'tables'):
                logging.debug("[LA] get_table_schema response.tables: %s", repr(response.tables))
        except Exception as e:
            logging.debug(f"[LA] get_table_schema response.tables could not be repr'd: {e}")
        # If response is a dict with error or consent_url, propagate it
        if isinstance(response, dict) and ("error" in response or "consent_url" in response):
            return response
        schema = {}
        dynamic_columns = []  # List of (col_val, data_type, column_type)
        if response.tables and response.tables[0].columns:
            columns = response.tables[0].columns
            rows = response.tables[0].rows
            def col_name(col):
                return getattr(col, 'name', col)
            # Find column indexes
            idx_col = idx_type = idx_columntype = None
            for i, col in enumerate(columns):
                name = col_name(col)
                if name == "ColumnName":
                    idx_col = i
                elif name == "DataType":
                    idx_type = i
                elif name == "ColumnType":
                    idx_columntype = i
            if idx_col is not None and idx_type is not None:
                for row in rows:
                    col_val = row[idx_col]
                    data_type = row[idx_type]
                    column_type = row[idx_columntype] if idx_columntype is not None else None
                    # Log both data_type and column_type for debugging
                    logging.debug(f"[LA] get_table_schema: col={col_val}, data_type={data_type}, column_type={column_type}")
                    if col_val and (data_type or column_type):
                        schema[col_val] = {
                            "data_type": data_type,
                            "column_type": column_type
                        }
                        # Track all dynamic columns
                        if (
                            (data_type and str(data_type).lower() == "dynamic") or
                            (column_type and str(column_type).lower() == "dynamic")
                        ):
                            logging.debug(f"[LA] get_table_schema: {col_val} is dynamic (data_type={data_type}, column_type={column_type}), will extract keys as virtual columns.")
                            dynamic_columns.append(col_val)
            else:
                logging.debug(f"[LA] get_table_schema: Could not find ColumnName/DataType columns in getschema result for table {table_name}.")

        # For each dynamic column, extract all unique keys as virtual columns
        logging.debug(f"[LA] get_table_schema: Processing response for table {table_name}. dynamic_columns={dynamic_columns}")
        for dyn_col in dynamic_columns:
            try:
                # Query to extract all unique keys from this dynamic column
                dyn_query = f"{table_name} | where TimeGenerated > ago(365d) | where isnotempty({dyn_col}) | extend keys = bag_keys({dyn_col}) | mv-expand keys | summarize count() by tostring(keys)"
                dyn_response = self._client.query_workspace(workspace_id=self.workspace_id, query=dyn_query, timespan=timedelta(days=365))
                if dyn_response.tables and dyn_response.tables[0].columns:
                    dyn_columns = dyn_response.tables[0].columns
                    dyn_rows = dyn_response.tables[0].rows
                    # Find the column index for 'keys'
                    idx_keys = None
                    for i, col in enumerate(dyn_columns):
                        if getattr(col, 'name', col) == 'keys':
                            idx_keys = i
                            break
                    if idx_keys is not None:
                        for row in dyn_rows:
                            key = row[idx_keys]
                            if key:
                                # Add as a virtual column: dyn_col.key
                                schema[f"{dyn_col}.{key}"] = {
                                    "data_type": "dynamic_property",
                                    "column_type": "dynamic_property"
                                }
                logging.debug(f"[LA] get_table_schema: Extracted virtual columns for {dyn_col}: {[k for k in schema.keys() if k.startswith(dyn_col + '.')]}" )
            except Exception as e:
                logging.debug(f"[LA] get_table_schema: Could not extract keys for {dyn_col}: {e}")
        return schema

    @plugin_function_logger("LogAnalyticsPlugin")
    @kernel_function(description="Execute a KQL (Kusto Query Language) query against a specific table in the Log Analytics workspace and return the results as a list of rows (each as a dictionary of column values). Use this function after discovering available tables and their schemas to retrieve data. Accepts an optional timespan parameter to limit the query window as a timedelta, tuple of datetimes, or number of hours. Limitations on returns should be specified in the query (ex: take N). Always provide user_id to enable saving the query to Cosmos DB for user history tracking.")
    def run_query(
        self,
        query: str,
        user_id: Optional[str] = None,
        timespan: Optional[Any] = None
    ) -> Any:
        logging.debug(f"[LA] Running query: {query} with user_id={user_id}, timespan={timespan}")
        if not self._client:
            raise RuntimeError("Log Analytics client not initialized.")
        # Determine if this is a control command (starts with '.')
        is_control_command = query.strip().startswith('.')
        query_args = {"workspace_id": self.workspace_id, "query": query}
        if is_control_command:
            query_args["timespan"] = None  # Control commands do not use timespan
        else:
            # Data query: resolve timespan
            resolved_timespan = timespan
            if timespan is None:
                # resolved_timespan = timedelta(hours=1) # Commented out to allow None and test in query
                resolved_timespan = None
            elif isinstance(timespan, (int, float)):
                resolved_timespan = timedelta(hours=timespan)
            # else: pass through timedelta or tuple
            query_args["timespan"] = resolved_timespan
        try:
            response = self._client.query_workspace(**query_args)
        except Exception as ex:
            # If the exception is a dict from get_valid_access_token, propagate it
            if isinstance(ex.args[0], dict):
                return ex.args[0]
            msg = str(ex)
            return {"error": msg}
        results = []
        try:
            if response.tables:
                import pprint
                logging.debug("[LA] run_query raw response: %s", repr(response))
                # Log the structure of response.tables in a readable way
                for idx, t in enumerate(response.tables):
                    logging.debug(f"[LA] Table {idx}: type={type(t)}, attrs={dir(t)}")
                    # Columns info
                    if hasattr(t, 'columns'):
                        col_info = [
                            {"name": getattr(col, 'name', str(col)), "type": getattr(col, 'type', None)}
                            for col in t.columns
                        ]
                        logging.debug(f"[LA] Table {idx} columns: {pprint.pformat(col_info)}")
                    # Rows sample
                    if hasattr(t, 'rows'):
                        sample_rows = t.rows[:2] if len(t.rows) > 2 else t.rows
                        logging.debug(f"[LA] Table {idx} sample rows: {pprint.pformat(sample_rows)}")
                # Log response.tables as JSON (columns and rows)
                try:
                    tables_json = []
                    for t in response.tables:
                        def col_name(col):
                            return getattr(col, 'name', col)
                        table_dict = {
                            "columns": [col_name(col) for col in t.columns],
                            "rows": t.rows
                        }
                        tables_json.append(table_dict)
                    logging.debug("[LA] run_query response.tables (json): %s", json.dumps(tables_json))
                except Exception as e:
                    logging.debug(f"[LA] run_query response.tables could not be JSON serialized: {e}")
                # Support both string and object columns
                def col_name(col):
                    return getattr(col, 'name', col)
                columns = [col_name(col) for col in response.tables[0].columns]
                for row in response.tables[0].rows:
                    results.append(dict(zip(columns, row)))
            # Handle unexpected result types
            if not isinstance(results, list) or (results and not isinstance(results[0], dict)):
                logging.warning(f"[LA] run_query returned unexpected value: {repr(results)}")
                return {"error": "No rows found for the query and timeframe."}
            if not results:
                return {"error": "No rows found for the query and timeframe."}
            return results
        except Exception as e:
            logging.error(f"[LA] Error processing query results: {e}")
            return {"error": "Failed to process query results."}
        finally:
            # Save to Cosmos query history if user_id is provided
            if user_id:
                self._save_query_history_to_cosmos(user_id, query)

    @plugin_function_logger("LogAnalyticsPlugin")
    @kernel_function(description="Summarize a result set for LLM consumption, including row count and column names.")
    def summarize_results(self, results: List[Dict[str, Any]]) -> str:
        if not results:
            return "No results."
        columns = results[0].keys()
        summary = f"Rows: {len(results)}\nColumns: {', '.join(columns)}\nSample: {results[0]}"
        return summary

    @plugin_function_logger("LogAnalyticsPlugin")
    @kernel_function(description="Return the last N queries run by this plugin instance. They should be numbered for the user to allow easy selection.")
    def get_query_history(self, limit: int = 20, user_id: Optional[str] = None) -> List[str]:
        if not user_id:
            return []
        return self._get_query_history_from_cosmos(user_id, limit)

    def _save_query_history_to_cosmos(self, user_id: str, query: str, max_history: int = 20):
        # Update query_history in the correct plugin's additionalFields in Cosmos DB, and sync manifest
        try:
            from application.single_app.functions_settings import get_user_settings, update_user_settings
        except ImportError:
            from functions_settings import get_user_settings, update_user_settings

        doc = get_user_settings(user_id)
        settings = doc.get('settings', {})
        plugins = settings.get('plugins', [])
        plugin_name = self.manifest.get('name') or self.__class__.__name__
        plugin_entry = None
        for p in plugins:
            if p.get('name') == plugin_name:
                plugin_entry = p
                break
        if not plugin_entry:
            plugin_entry = {'name': plugin_name, 'additionalFields': {}}
            plugins.append(plugin_entry)
        # Ensure additionalFields exists
        if 'additionalFields' not in plugin_entry or not isinstance(plugin_entry['additionalFields'], dict):
            plugin_entry['additionalFields'] = {}
        # Ensure query_history exists
        if 'query_history' not in plugin_entry['additionalFields'] or not isinstance(plugin_entry['additionalFields']['query_history'], list):
            plugin_entry['additionalFields']['query_history'] = []
        plugin_entry['additionalFields']['query_history'].append(query)
        if len(plugin_entry['additionalFields']['query_history']) > max_history:
            plugin_entry['additionalFields']['query_history'] = plugin_entry['additionalFields']['query_history'][-max_history:]
        # Save back to Cosmos
        settings['plugins'] = plugins
        update_user_settings(user_id, {'plugins': plugins})
        # Sync manifest's additionalFields.query_history
        self.additional_fields['query_history'] = list(plugin_entry['additionalFields']['query_history'])

    def _get_query_history_from_cosmos(self, user_id: str, limit: int = 5) -> List[str]:
        # Read query_history from the correct plugin's additionalFields in Cosmos DB, and sync manifest
        try:
            from application.single_app.functions_settings import get_user_settings
        except ImportError:
            from functions_settings import get_user_settings
        doc = get_user_settings(user_id)
        settings = doc.get('settings', {})
        plugins = settings.get('plugins', [])
        plugin_name = self.manifest.get('name') or self.__class__.__name__
        for p in plugins:
            if p.get('name') == plugin_name:
                qh = p.get('additionalFields', {}).get('query_history', [])
                # Sync manifest's additionalFields.query_history
                self.additional_fields['query_history'] = list(qh) if isinstance(qh, list) else []
                return self.additional_fields['query_history'][-limit:]
        # If not found, ensure manifest is empty
        self.additional_fields['query_history'] = []
        return []

    @plugin_function_logger("LogAnalyticsPlugin")
    @kernel_function(description="Validate a KQL query for basic safety and allowed patterns.")
    def validate_query(self, query: str) -> bool:
        # Basic validation: block dangerous commands, allow only select/read queries
        forbidden = [".drop", ".delete", ".alter", ".set", ".ingest", ".clear", ".purge"]
        if any(f in query.lower() for f in forbidden):
            return False
        # Optionally, add more checks here
        return True
