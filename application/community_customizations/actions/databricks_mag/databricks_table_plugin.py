# databricks_table_plugin.py
"""
Databricks Table Plugin for Semantic Kernel
- Dynamically created per table manifest
- Executes parameterized SQL via Databricks REST API
"""

import requests
import logging
import pyodbc
import re
import sqlglot
from semantic_kernel_plugins.base_plugin import BasePlugin
from typing import Annotated, List, Optional, Required
from functions_appinsights import log_event
from semantic_kernel.functions import kernel_function

class DatabricksTablePlugin(BasePlugin):
    def __init__(self, manifest):
        self.manifest = manifest
        self.authtype = manifest.get('auth', {}).get('type', 'key')
        self.endpoint = manifest['endpoint']
        self.key = manifest.get('auth', {}).get('key', None)
        self.identity = manifest.get('auth', {}).get('identity', None)
        self.client_id = manifest.get('auth', {}).get('identity', None)
        self.client_secret = manifest.get('auth', {}).get('key', None)
        self.tenant_id = manifest.get('auth', {}).get('tenantId', None)
        self._metadata = manifest['metadata']
        self.warehouse_id = manifest['additionalFields'].get('warehouse_id', '')
        self.table_name = manifest['additionalFields'].get('table_name', '')
        self.port = manifest['additionalFields'].get('port', 443)
        self.http_path = manifest['additionalFields'].get('httpPath', '')

    def _get_azure_ad_token(self):
        """Acquire Azure AD token for Databricks using Service Principal credentials, supporting Commercial and MAG."""
        # Determine the correct login endpoint and scope based on the Databricks endpoint
        if ".azure.us" in self.endpoint or ".us/" in self.endpoint:
            login_host = "login.microsoftonline.us"
            scope = "https://databricks.azure.us/.default"
        else:
            login_host = "login.microsoftonline.com"
            scope = "https://databricks.azure.net/.default"
        url = f"https://{login_host}/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": scope
        }
        resp = requests.post(url, data=data)
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _get_databricks_token(self):
        if ".azure.us" in self.endpoint or ".us/" in self.endpoint:
            login_host = "login.microsoftonline.us"
            scope = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default"
        else:
            login_host = "login.microsoftonline.com"
            scope = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default"
        url = f"https://{login_host}/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": scope
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(url, data=data, headers=headers)
        resp.raise_for_status()
        print(f"[DBP] Received Databricks token response")
        return resp.json()["access_token"]

    def _get_pyodbc_connection(self, additional_fields: dict = None):
        """
        Create and return a DSN-less pyodbc connection to Databricks using parameters from the manifest and additional_fields.
        Supports only Personal Access Token (PAT) authentication for now.
        Args:
            additional_fields (dict, optional): Additional connection parameters to override manifest values.
        Returns:
            pyodbc.Connection: An open pyodbc connection to Databricks.
        Raises:
            ValueError: If required fields are missing or authentication is not supported.
            pyodbc.Error: If connection fails.
        """
        # Merge manifest and additional_fields
        fields = dict(self.manifest.get('additionalFields', {}))
        if additional_fields:
            fields.update(additional_fields)

        if not (self.warehouse_id and self.http_path and self.key and self.endpoint):
            raise ValueError("Missing required ODBC connection parameters: warehouse_id, httpPath, endpoint, or PAT (key)")

        # Parse hostname from endpoint (strip protocol and path)
        match = re.match(r"https?://([^/]+)", self.endpoint)
        if not match:
            raise ValueError(f"Invalid endpoint URL: {self.endpoint}")
        host = match.group(1)
        conn_str = None
        # Only support PAT for now
        if self.identity and self.identity.lower() == "managedIdentity":
            raise NotImplementedError("Managed Identity authentication is not yet supported for ODBC.")

        # Build ODBC connection string
        if self.authtype == "key":
            print("[DBP] Using Personal Access Token Auth")
            conn_str =  "Driver={Simba Spark ODBC Driver};" + \
                f"Host={host};" + \
                f"Port={self.port};" + \
                f"HTTPPath={self.http_path};" + \
                "AuthMech=3;" + \
                "UID=token;" + \
                f"PWD={self.key};" + \
                "SSL=1;" + \
                "SSLVersion=TLSv1.2;" + \
                "ThriftTransport=2;" + \
                "Database=default;" + \
                "SparkServerType=3;"

        if self.authtype == "servicePrincipal":
            print("[DBP] Using Service Principal Auth")
            #access_token = self._get_azure_ad_token()
            access_token = self._get_databricks_token()
            conn_str = "Driver={Simba Spark ODBC Driver};" + \
                f"Host={host};"  + \
                f"Port={self.port};" + \
                f"HTTPPath={self.http_path};" + \
                f"Auth_AccessToken={access_token};" + \
                "AuthMech=11;" + \
                "Auth_Flow=0;" + \
                "SSL=1;" + \
                "SSLVersion=TLSv1.2;" + \
                "ThriftTransport=2;" + \
                "Database=default;" + \
                "SparkServerType=3;"
        
        if conn_str is None:
            print(f"[DBP] Unsupported auth type for ODBC: {self.authtype}")
            raise ValueError(f"Unsupported authentication type for ODBC: {self.authtype}")

        try:
            conn = pyodbc.connect(conn_str, autocommit=True)
            print("[DBP] Successfully connected to Databricks via ODBC")
            return conn
        except Exception as ex:
            logging.error(f"Failed to connect to Databricks ODBC: {ex}")
            raise

    @property
    def metadata(self):
        # Compose a detailed description for the LLM and Semantic Kernel
        user_desc = self._metadata.get("description", f"Databricks table plugin (table name required, columns optional)")
        api_desc = (
            "This plugin executes SQL statements against Azure Databricks using the Statement Execution API. "
            "It sends a POST request to the Databricks SQL endpoint provided in the manifest (e.g., 'https://<databricks-instance>/api/2.0/sql/statements'). "
            "Authentication is via a Databricks personal access token or Azure AD token (for Service Principal), passed as a Bearer token in the 'Authorization' header. "
            "The request body is JSON and must include: "
            "'statement': the SQL query string to execute, and 'warehouse_id': the ID of the Databricks SQL warehouse to use. "
            "Optional filters can be provided as keyword arguments and are converted into a SQL WHERE clause. "
            "The plugin constructs the SQL statement based on the provided columns (optional), table_name (required), and filters, then submits it to Databricks. "
            "If columns is not provided, all columns will be selected (SELECT *). "
            "The response is the result of the SQL query, returned as JSON. "
            "For more details, see: https://docs.databricks.com/api/azure/workspace/statementexecution/executestatement\n\n"
            "Configuration: The plugin is configured with the Databricks API endpoint (from the manifest), access token or service principal credentials, warehouse_id via the plugin manifest. "
            "The manifest should provide: 'endpoint', 'auth.key' or service principal fields, and 'additionalFields.warehouse_id'. "
            "Example request body: { 'statement': 'SELECT * FROM my_table WHERE id = 1', 'warehouse_id': '<warehouse_id>' }. "
            "The plugin handles parameterization and SQL construction automatically.\n\n"
            "NOTE: The table name is required, columns is optional for the query_table function."
        )
        full_desc = f"{user_desc}\n\n{api_desc}"
        return {
            "name": self._metadata.get("name", "databricks_table_plugin"),
            "type": "databricks_table",
            "description": full_desc,
            "methods": [
                {
                    "name": "query_table",
                    "description": "Query the Databricks table using parameterized SQL. Table name is required, columns is optional. Filters can be applied as keyword arguments.",
                    "parameters": [
                        {"name": "table_name", "type": "str", "description": "Name of the table to query", "required": True},
                        {"name": "columns", "type": "List[str]", "description": "Columns to select (optional, selects all if not provided)", "required": False},
                        {"name": "warehouse_id", "type": "str", "description": "Databricks warehouse ID", "required": False},
                        {"name": "filters", "type": "dict", "description": "Additional filters as column=value pairs", "required": False}
                    ],
                    "returns": {"type": "dict", "description": "The query result as a dictionary (Databricks SQL API response)."}
                }
            ]
        }

    def get_functions(self):
        return ["query_table"]

    @kernel_function(
        description="""
            Query the Databricks table using parameterized SQL. Table name is required and should be databasename.tablename format.
            Only read-only queries (SELECT, SHOW, DESCRIBE, EXPLAIN) are allowed.
            Returns the query result as a list of dictionaries, or an error result if the query is not allowed or fails.
        """,
        name="query_table",
    )
    async def query_table(
        self,
        query: str,
    ) -> dict:
        # Only allow read-only queries
        try:
            statements = sqlglot.parse(query)
            for stmt in statements:
                if stmt.key.upper() not in ("SELECT", "SHOW", "DESCRIBE", "EXPLAIN"):
                    return {
                        "error": True,
                        "message": f"Only read-only queries (SELECT, SHOW, DESCRIBE, EXPLAIN) are allowed. Found: {stmt.key}",
                        "query": query,
                        "result": []
                    }
            conn = self._get_pyodbc_connection()
            cursor = conn.cursor()
            print(f"[DBP] Executing SQL: {query}")
            cursor.execute(query)
            print(f"[DBP] Executed successfully: {query}")
            # JSON format
            """
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            result = [dict(zip(columns, row)) for row in rows]
            """
            #CSV format for data compression
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            csv_lines = [",".join(columns)]
            for row in rows:
                csv_row = [str(val).replace('"', '""') for val in row]
                csv_lines.append(",".join(f'"{v}"' for v in csv_row))

            result = "\n".join(csv_lines)

            cursor.close()
            conn.close()
            # Estimate token count (approximate: 1 token ≈ 4 characters)
            result_str = str(result)
            char_count = len(result_str)
            approx_tokens = char_count // 4
            print(f"[DBP] Queried {len(result)} rows from query | {char_count} chars ≈ {approx_tokens} tokens")
            return {
                "error": False,
                "message": "Success",
                "query": query,
                "result": result
            }
        except Exception as ex:
            logging.error(f"Failed to run query {query}: {ex}")
            print(f"[DBP] Failed to run query: {query}\n {ex}")
            return {
                "error": True,
                "message": f"Error: {ex}",
                "query": query,
                "result": []
            }
