"""
Azure Log Analytics Semantic Kernel Plugin

This plugin exposes Azure Log Analytics workspace querying and schema discovery as plugin functions.
"""

from typing import Dict, Any, List, Optional
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function

try:
    from azure.monitor.query import LogsQueryClient
    from azure.identity import DefaultAzureCredential, AzureAuthorityHosts
except ImportError:
    LogsQueryClient = None
    DefaultAzureCredential = None

class LogAnalyticsPlugin(BasePlugin):
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        self.manifest = manifest or {}
        self.endpoint = self.manifest.get("endpoint")
        self.auth = self.manifest.get("auth", {})
        self.metadata_dict = self.manifest.get("metadata", {})
        self.additional_fields = self.manifest.get("additionalFields", {})
        self.workspace_id = self.additional_fields.get("workspaceId")
        self.cloud = self.additional_fields.get("cloud", "public")
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

        if self.auth.get("type") == "managedIdentity":
            # Support user-specified identity client ID, fallback to system-assigned
            identity_client_id = (
                self.auth.get("identity")
                or self.additional_fields.get("identity")
            )
            if identity_client_id:
                credential = DefaultAzureCredential(authority=authority_host, managed_identity_client_id=identity_client_id)
            else:
                credential = DefaultAzureCredential(authority=authority_host)
        elif self.auth.get("type") == "servicePrincipal":
            # Service principal auth: use identity as clientId, key as clientSecret, tenantId as tenant
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
            # Use a custom TokenCredential that fetches the user's access token from session
            try:
                from application.single_app.functions_authentication import get_valid_access_token
            except ImportError:
                from functions_authentication import get_valid_access_token

            from azure.core.credentials import AccessToken, TokenCredential
            import time

            class UserTokenCredential(TokenCredential):
                def __init__(self, scope):
                    self.scope = scope

                def get_token(self, *args, **kwargs):
                    token = get_valid_access_token(scopes=[self.scope])
                    if not token:
                        raise RuntimeError("Could not acquire user access token for Log Analytics API.")
                    # Azure SDK expects expires_on as epoch seconds; set to 5 minutes from now (token is short-lived)
                    expires_on = int(time.time()) + 300
                    return AccessToken(token, expires_on)

            # Determine correct scope for the selected cloud
            if self.cloud == "custom":
                scope = f"{self.endpoint_override}/.default" if self.endpoint_override else "https://api.loganalytics.io/.default"
            elif self.cloud == "usgovernment":
                scope = "https://api.loganalytics.us/.default"
            else:
                scope = "https://api.loganalytics.io/.default"
            credential = UserTokenCredential(scope)
        elif self.auth.get("type") == "key":
            # Key-based auth not directly supported by SDK; placeholder for custom logic
            credential = None
        else:
            credential = None

        if credential:
            # Determine endpoint for the selected cloud
            if self.cloud == "custom":
                endpoint = self.endpoint_override
            elif self.cloud == "usgovernment":
                endpoint = "https://api.loganalytics.us"
            else:
                endpoint = "https://api.loganalytics.io"
            # The SDK uses endpoint internally, but we can store it for reference
            self.endpoint = endpoint
            return LogsQueryClient(credential)
        return None

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
                "description": "List all tables in the Log Analytics workspace using the Azure Monitor Query SDK.",
                "parameters": [],
                "returns": {"type": "list", "description": "List of table names."}
            },
            {
                "name": "get_table_schema",
                "description": "Get schema (columns/types) for a table by running a describe query.",
                "parameters": [
                    {"name": "table_name", "type": "string", "description": "Table name.", "required": True}
                ],
                "returns": {"type": "object", "description": "Column names and types."}
            },
            {
                "name": "run_query",
                "description": "Run a KQL query and return results, chunked for LLMs if needed. Uses Azure Monitor Query SDK.",
                "parameters": [
                    {"name": "query", "type": "string", "description": "KQL query string.", "required": True},
                    {"name": "max_rows", "type": "integer", "description": "Max rows to return.", "required": False}
                ],
                "returns": {"type": "list", "description": "Query results as list of dicts."}
            },
            {
                "name": "summarize_results",
                "description": "Summarize a result set for LLM consumption, including row count and column names.",
                "parameters": [
                    {"name": "results", "type": "list", "description": "Query results.", "required": True}
                ],
                "returns": {"type": "string", "description": "Summary of results."}
            },
            {
                "name": "get_query_history",
                "description": "Return the last N queries run by this plugin instance.",
                "parameters": [
                    {"name": "limit", "type": "integer", "description": "Number of queries to return.", "required": False}
                ],
                "returns": {"type": "list", "description": "List of previous queries."}
            },
            {
                "name": "validate_query",
                "description": "Validate a KQL query for basic safety and allowed patterns.",
                "parameters": [
                    {"name": "query", "type": "string", "description": "KQL query string.", "required": True}
                ],
                "returns": {"type": "boolean", "description": "True if query is valid, False otherwise."}
            }
        ]
        return {"methods": methods}

    def get_functions(self) -> List[str]:
        return [m["name"] for m in self._metadata["methods"]]

    @kernel_function(description="List all tables in the Log Analytics workspace.")
    def list_tables(self) -> List[str]:
        if not self._client:
            raise RuntimeError("Log Analytics client not initialized.")
        query = ".show tables"
        # SDK requires a timespan even for metadata queries; use dummy value
        response = self._client.query_workspace(self.workspace_id, query, timespan="PT1H")
        tables = []
        if response.tables:
            for row in response.tables[0].rows:
                tables.append(row[0])
        return tables

    @kernel_function(description="Get schema (columns/types) for a table by running a describe query.")
    def get_table_schema(self, table_name: str) -> Dict[str, str]:
        if not self._client:
            raise RuntimeError("Log Analytics client not initialized.")
        query = f".show table {table_name} schema"
        # SDK requires a timespan even for metadata queries; use dummy value
        response = self._client.query_workspace(self.workspace_id, query, timespan="PT1H")
        schema = {}
        if response.tables and response.tables[0].rows:
            for row in response.tables[0].rows:
                # row: [ColumnName, ColumnType, ...]
                schema[row[0]] = row[1]
        return schema

    @kernel_function(description="Run a KQL query and return results, chunked for LLMs if needed. Uses Azure Monitor Query SDK.")
    def run_query(self, query: str, max_rows: int = 100, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._client:
            raise RuntimeError("Log Analytics client not initialized.")
        response = self._client.query_workspace(self.workspace_id, query, top=max_rows)
        results = []
        if response.tables:
            columns = [col.name for col in response.tables[0].columns]
            for row in response.tables[0].rows[:max_rows]:
                results.append(dict(zip(columns, row)))
        # Save to Cosmos query history if user_id is provided
        if user_id:
            self._save_query_history_to_cosmos(user_id, query)
        return results

    @kernel_function(description="Summarize a result set for LLM consumption, including row count and column names.")
    def summarize_results(self, results: List[Dict[str, Any]]) -> str:
        if not results:
            return "No results."
        columns = results[0].keys()
        summary = f"Rows: {len(results)}\nColumns: {', '.join(columns)}\nSample: {results[0]}"
        return summary

    @kernel_function(description="Return the last N queries run by this plugin instance. They should be numbered for the user to allow easy selection.")
    def get_query_history(self, limit: int = 20, user_id: Optional[str] = None) -> List[str]:
        if not user_id:
            return []
        return self._get_query_history_from_cosmos(user_id, limit)

    def _save_query_history_to_cosmos(self, user_id: str, query: str, max_history: int = 20):
        try:
            from application.single_app.functions_settings import get_user_settings, update_user_settings
        except ImportError:
            # Fallback for testing or if import path changes
            from functions_settings import get_user_settings, update_user_settings

        doc = get_user_settings(user_id)
        settings = doc.get('settings', {})
        plugins = settings.get('plugins', [])
        plugin_name = self.manifest.get('name') or self.__class__.__name__
        # Find or create plugin entry by name only
        plugin_entry = None
        for p in plugins:
            if p.get('name') == plugin_name:
                plugin_entry = p
                break
        if not plugin_entry:
            plugin_entry = {'name': plugin_name, 'query_history': []}
            plugins.append(plugin_entry)
        # Append and trim history
        plugin_entry['query_history'].append(query)
        if len(plugin_entry['query_history']) > max_history:
            plugin_entry['query_history'] = plugin_entry['query_history'][-max_history:]
        # Save back
        settings['plugins'] = plugins
        update_user_settings(user_id, {'plugins': plugins})

    def _get_query_history_from_cosmos(self, user_id: str, limit: int = 5) -> List[str]:
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
                return p.get('query_history', [])[-limit:]
        return []

    @kernel_function(description="Validate a KQL query for basic safety and allowed patterns.")
    def validate_query(self, query: str) -> bool:
        # Basic validation: block dangerous commands, allow only select/read queries
        forbidden = [".drop", ".delete", ".alter", ".set", ".ingest", ".clear", ".purge"]
        if any(f in query.lower() for f in forbidden):
            return False
        # Optionally, add more checks here
        return True
