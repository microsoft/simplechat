"""
SQL Query Plugin for Semantic Kernel
- Executes SQL queries against various databases (SQL Server, PostgreSQL, MySQL, SQLite)
- Handles query sanitization and validation
- Returns structured results with proper error handling
- Supports parameterized queries for security
"""

import logging
import re
from typing import Dict, Any, List, Optional, Union
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from functions_appinsights import log_event
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger

# Helper class to wrap results with metadata
class ResultWithMetadata:
    def __init__(self, data, metadata):
        self.data = data
        self.metadata = metadata
    def __str__(self):
        return str(self.data)
    def __repr__(self):
        return f"ResultWithMetadata(data={self.data!r}, metadata={self.metadata!r})"

class SQLQueryPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)
        self.manifest = manifest
        
        # Extract parameters from additionalFields if present, otherwise use direct manifest
        additional_fields = manifest.get('additionalFields', {})
        
        self.connection_string = manifest.get('connection_string') or additional_fields.get('connection_string')
        raw_db_type = (manifest.get('database_type') or additional_fields.get('database_type', 'sqlserver')).lower()
        # Map azure_sql to sqlserver for compatibility
        self.database_type = 'sqlserver' if raw_db_type in ['azure_sql', 'azuresql'] else raw_db_type
        self.auth_type = manifest.get('auth', {}).get('type', 'connection_string')
        self.server = manifest.get('server') or additional_fields.get('server')
        self.database = manifest.get('database') or additional_fields.get('database')
        self.username = manifest.get('username') or additional_fields.get('username')
        self.password = manifest.get('password') or additional_fields.get('password')
        self.driver = manifest.get('driver') or additional_fields.get('driver')
        self.read_only = manifest.get('read_only') or additional_fields.get('read_only', True)  # Default to read-only for safety
        self.max_rows = manifest.get('max_rows') or additional_fields.get('max_rows', 1000)  # Limit result size
        self.timeout = manifest.get('timeout') or additional_fields.get('timeout', 30)  # Query timeout in seconds
        self._metadata = manifest.get('metadata', {})
        
        # Add comprehensive logging
        log_event(f"[SQLQueryPlugin] Initializing plugin", extra={
            "database_type": self.database_type,
            "auth_type": self.auth_type,
            "server": self.server,
            "database": self.database,
            "read_only": self.read_only,
            "max_rows": self.max_rows,
            "timeout": self.timeout,
            "has_connection_string": bool(self.connection_string),
            "has_username": bool(self.username),
            "manifest_keys": list(manifest.keys())
        })
        print(f"[SQLQueryPlugin] Initializing - DB Type: {self.database_type}, Auth: {self.auth_type}, Server: {self.server}, Database: {self.database}, Read-Only: {self.read_only}")
        
        # Validate required configuration
        if not self.connection_string and not (self.server and self.database):
            error_msg = "SQLQueryPlugin requires either 'connection_string' or 'server' and 'database' in the manifest."
            log_event(f"[SQLQueryPlugin] Configuration error: {error_msg}", extra={"manifest": manifest})
            print(f"[SQLQueryPlugin] ERROR: {error_msg}")
            raise ValueError(error_msg)
        
        # Set up database-specific configurations
        self._setup_database_config()
        
        # Initialize connection (lazy loading)
        self._connection = None
        print(f"[SQLQueryPlugin] Initialization complete")

    def _setup_database_config(self):
        """Setup database-specific configurations and import requirements"""
        self.supported_databases = {
            'sqlserver': {
                'module': 'pyodbc',
                'default_driver': 'ODBC Driver 17 for SQL Server',
                'default_port': 1433
            },
            'postgresql': {
                'module': 'psycopg2',
                'default_driver': None,
                'default_port': 5432
            },
            'mysql': {
                'module': 'pymysql',
                'default_driver': None,
                'default_port': 3306
            },
            'sqlite': {
                'module': 'sqlite3',
                'default_driver': None,
                'default_port': None
            }
        }
        
        if self.database_type not in self.supported_databases:
            raise ValueError(f"Unsupported database type: {self.database_type}. Supported types: {list(self.supported_databases.keys())}")

    def _get_connection(self):
        """Lazy initialization of database connection"""
        if self._connection is None:
            self._connection = self._create_connection()
        return self._connection

    def _create_connection(self):
        """Create database connection based on database type"""
        try:
            if self.database_type == 'sqlserver':
                import pyodbc
                if self.connection_string:
                    return pyodbc.connect(self.connection_string, timeout=self.timeout)
                else:
                    driver = self.driver or self.supported_databases['sqlserver']['default_driver']
                    conn_str = f"DRIVER={{{driver}}};SERVER={self.server};DATABASE={self.database}"
                    if self.username and self.password:
                        conn_str += f";UID={self.username};PWD={self.password}"
                    else:
                        conn_str += ";Trusted_Connection=yes"
                    return pyodbc.connect(conn_str, timeout=self.timeout)
                    
            elif self.database_type == 'postgresql':
                import psycopg2
                if self.connection_string:
                    return psycopg2.connect(self.connection_string)
                else:
                    return psycopg2.connect(
                        host=self.server,
                        database=self.database,
                        user=self.username,
                        password=self.password,
                        connect_timeout=self.timeout
                    )
                    
            elif self.database_type == 'mysql':
                import pymysql
                if self.connection_string:
                    # Parse connection string for MySQL
                    return pymysql.connect(self.connection_string)
                else:
                    return pymysql.connect(
                        host=self.server,
                        database=self.database,
                        user=self.username,
                        password=self.password,
                        connect_timeout=self.timeout
                    )
                    
            elif self.database_type == 'sqlite':
                import sqlite3
                database_path = self.connection_string or self.database
                conn = sqlite3.connect(database_path, timeout=self.timeout)
                # Enable row factory for better column access
                conn.row_factory = sqlite3.Row
                return conn
                
        except ImportError as e:
            raise ImportError(f"Required database driver not installed for {self.database_type}: {e}")
        except Exception as e:
            log_event(f"[SQLQueryPlugin] Connection failed: {e}", extra={"database_type": self.database_type})
            raise

    @property
    def display_name(self) -> str:
        return "SQL Query"

    @property
    def metadata(self) -> Dict[str, Any]:
        user_desc = self._metadata.get("description", f"SQL Query plugin for {self.database_type} database")
        api_desc = (
            "This plugin executes SQL queries against databases and returns structured results. "
            "It supports SQL Server, PostgreSQL, MySQL, and SQLite databases. The plugin includes "
            "query sanitization, validation, and security features including parameterized queries, "
            "read-only mode, result limiting, and timeout protection. It automatically cleans queries "
            "from unnecessary characters and formats results for easy consumption by AI agents. "
            "The plugin handles database-specific SQL variations and connection management."
        )
        full_desc = f"{user_desc}\n\n{api_desc}"
        
        return {
            "name": self._metadata.get("name", "sql_query_plugin"),
            "type": "sql_query",
            "description": full_desc,
            "methods": [
                {
                    "name": "execute_query",
                    "description": "Execute a SQL query and return results",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "The SQL query to execute", "required": True},
                        {"name": "parameters", "type": "Dict[str, Any]", "description": "Optional parameters for parameterized queries", "required": False},
                        {"name": "max_rows", "type": "int", "description": "Maximum number of rows to return (overrides default)", "required": False}
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "Query results with columns and data"}
                },
                {
                    "name": "execute_scalar",
                    "description": "Execute a query that returns a single value",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "The SQL query to execute", "required": True},
                        {"name": "parameters", "type": "Dict[str, Any]", "description": "Optional parameters for parameterized queries", "required": False}
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "Single scalar value result"}
                },
                {
                    "name": "validate_query",
                    "description": "Validate a SQL query without executing it",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "The SQL query to validate", "required": True}
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "Validation result with any issues found"}
                }
            ]
        }

    def get_functions(self) -> List[str]:
        return ["execute_query", "execute_scalar", "validate_query"]

    @kernel_function(description="Execute a SQL query and return results")
    @plugin_function_logger("SQLQueryPlugin")
    def execute_query(
        self, 
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        max_rows: Optional[int] = None
    ) -> ResultWithMetadata:
        """Execute a SQL query and return results"""
        try:
            # Clean and validate the query
            cleaned_query = self._clean_query(query)
            validation_result = self._validate_query(cleaned_query)
            
            if not validation_result["is_valid"]:
                raise ValueError(f"Invalid query: {validation_result['issues']}")
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Set query timeout
            if hasattr(cursor, 'settimeout'):
                cursor.settimeout(self.timeout)
            
            # Execute query with parameters if provided
            if parameters:
                cursor.execute(cleaned_query, parameters)
            else:
                cursor.execute(cleaned_query)
            
            # Get column names
            if hasattr(cursor, 'description') and cursor.description:
                columns = [desc[0] for desc in cursor.description]
            else:
                columns = []
            
            # Fetch results with row limit
            effective_max_rows = max_rows or self.max_rows
            
            if self.database_type == 'sqlite':
                # SQLite doesn't support fetchmany limit directly
                rows = cursor.fetchall()
                if len(rows) > effective_max_rows:
                    rows = rows[:effective_max_rows]
                # Convert sqlite3.Row to dict for consistency
                results = [dict(row) for row in rows]
            else:
                # For other databases, fetch with limit
                rows = cursor.fetchmany(effective_max_rows)
                results = []
                for row in rows:
                    if isinstance(row, (list, tuple)):
                        results.append(dict(zip(columns, row)))
                    else:
                        results.append(row)
            
            # Prepare result data
            result_data = {
                "columns": columns,
                "data": results,
                "row_count": len(results),
                "is_truncated": len(results) >= effective_max_rows,
                "query": cleaned_query
            }
            
            log_event(f"[SQLQueryPlugin] Executed query successfully, returned {len(results)} rows")
            return ResultWithMetadata(result_data, self.metadata)
            
        except Exception as e:
            log_event(f"[SQLQueryPlugin] Error executing query: {e}")
            error_result = {
                "error": str(e),
                "query": query,
                "columns": [],
                "data": [],
                "row_count": 0
            }
            return ResultWithMetadata(error_result, self.metadata)

    @kernel_function(description="Execute a query that returns a single value")
    @plugin_function_logger("SQLQueryPlugin")
    def execute_scalar(
        self, 
        query: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> ResultWithMetadata:
        """Execute a query that returns a single value"""
        try:
            # Clean and validate the query
            cleaned_query = self._clean_query(query)
            validation_result = self._validate_query(cleaned_query)
            
            if not validation_result["is_valid"]:
                raise ValueError(f"Invalid query: {validation_result['issues']}")
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Set query timeout
            if hasattr(cursor, 'settimeout'):
                cursor.settimeout(self.timeout)
            
            # Execute query with parameters if provided
            if parameters:
                cursor.execute(cleaned_query, parameters)
            else:
                cursor.execute(cleaned_query)
            
            # Fetch single value
            result = cursor.fetchone()
            
            if result:
                if isinstance(result, (list, tuple)):
                    scalar_value = result[0]
                elif hasattr(result, '__getitem__'):  # For sqlite3.Row
                    scalar_value = result[0]
                else:
                    scalar_value = result
            else:
                scalar_value = None
            
            result_data = {
                "value": scalar_value,
                "query": cleaned_query
            }
            
            log_event(f"[SQLQueryPlugin] Executed scalar query successfully")
            return ResultWithMetadata(result_data, self.metadata)
            
        except Exception as e:
            log_event(f"[SQLQueryPlugin] Error executing scalar query: {e}")
            error_result = {
                "error": str(e),
                "query": query,
                "value": None
            }
            return ResultWithMetadata(error_result, self.metadata)

    @kernel_function(description="Validate a SQL query without executing it")
    @plugin_function_logger("SQLQueryPlugin")
    def validate_query(self, query: str) -> ResultWithMetadata:
        """Validate a SQL query without executing it"""
        try:
            cleaned_query = self._clean_query(query)
            validation_result = self._validate_query(cleaned_query)
            
            log_event(f"[SQLQueryPlugin] Query validation completed")
            return ResultWithMetadata(validation_result, self.metadata)
            
        except Exception as e:
            log_event(f"[SQLQueryPlugin] Error validating query: {e}")
            error_result = {
                "is_valid": False,
                "issues": [str(e)],
                "query": query
            }
            return ResultWithMetadata(error_result, self.metadata)

    def _clean_query(self, query: str) -> str:
        """Clean query from unnecessary characters and formatting"""
        if not query:
            return ""
        
        # Remove common markdown code block markers
        query = re.sub(r'^```sql\s*', '', query, flags=re.IGNORECASE | re.MULTILINE)
        query = re.sub(r'^```\s*', '', query, flags=re.MULTILINE)
        query = re.sub(r'\s*```$', '', query, flags=re.MULTILINE)
        
        # Remove excessive whitespace
        query = re.sub(r'\s+', ' ', query)
        
        # Remove leading/trailing whitespace
        query = query.strip()
        
        # Ensure query ends with semicolon if it doesn't already
        if query and not query.endswith(';'):
            query += ';'
        
        return query

    def _validate_query(self, query: str) -> Dict[str, Any]:
        """Validate SQL query for safety and correctness"""
        issues = []
        
        if not query:
            return {"is_valid": False, "issues": ["Query is empty"], "query": query}
        
        # Check for potentially dangerous operations if in read-only mode
        if self.read_only:
            dangerous_patterns = [
                r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE|REPLACE)\b',
                r'\b(EXEC|EXECUTE|xp_|sp_)\b',
                r'--;',  # SQL comment that might hide malicious code
                r'/\*.*\*/',  # Block comments
            ]
            
            for pattern in dangerous_patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    issues.append(f"Potentially dangerous operation detected: {pattern}")
        
        # Check for basic SQL injection patterns
        injection_patterns = [
            r"';\s*(DROP|DELETE|UPDATE|INSERT)",
            r"UNION\s+SELECT",
            r"1\s*=\s*1",
            r"OR\s+1\s*=\s*1",
            r"AND\s+1\s*=\s*1",
        ]
        
        for pattern in injection_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                issues.append(f"Potential SQL injection pattern detected: {pattern}")
        
        # Check for basic syntax
        if not re.search(r'\bSELECT\b', query, re.IGNORECASE) and self.read_only:
            issues.append("Only SELECT statements are allowed in read-only mode")
        
        # Check for multiple statements (could be injection)
        statements = [s.strip() for s in query.split(';') if s.strip()]
        if len(statements) > 1:
            issues.append("Multiple statements detected - only single statements are allowed")
        
        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "query": query,
            "statement_count": len(statements)
        }

    def _format_results(self, cursor, max_rows: int) -> Dict[str, Any]:
        """Format query results into a structured format"""
        # Get column information
        if hasattr(cursor, 'description') and cursor.description:
            columns = []
            for desc in cursor.description:
                col_info = {
                    "name": desc[0],
                    "type": str(desc[1]) if len(desc) > 1 else "unknown"
                }
                columns.append(col_info)
        else:
            columns = []
        
        # Fetch data
        rows = cursor.fetchmany(max_rows)
        data = []
        
        for row in rows:
            if isinstance(row, (list, tuple)):
                row_dict = {}
                for i, value in enumerate(row):
                    col_name = columns[i]["name"] if i < len(columns) else f"column_{i}"
                    row_dict[col_name] = value
                data.append(row_dict)
            else:
                data.append(row)
        
        return {
            "columns": [col["name"] for col in columns],
            "column_info": columns,
            "data": data,
            "row_count": len(data),
            "is_truncated": len(data) >= max_rows
        }

    def __del__(self):
        """Clean up database connection"""
        if hasattr(self, '_connection') and self._connection:
            try:
                self._connection.close()
            except:
                pass
