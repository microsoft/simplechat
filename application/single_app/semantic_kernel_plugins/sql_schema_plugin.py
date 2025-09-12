"""
SQL Schema Plugin for Semantic Kernel
- Connects to various SQL databases (SQL Server, PostgreSQL, MySQL, SQLite)
- Extracts schema information (tables, columns, data types, relationships)
- Provides structured schema data for query generation
"""

import logging
from typing import Dict, Any, List, Optional, Union
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from functions_appinsights import log_event
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from functions_debug import debug_print

# Helper class to wrap results with metadata
class ResultWithMetadata:
    def __init__(self, data, metadata):
        self.data = data
        self.metadata = metadata
    def __str__(self):
        return str(self.data)
    def __repr__(self):
        return f"ResultWithMetadata(data={self.data!r}, metadata={self.metadata!r})"

class SQLSchemaPlugin(BasePlugin):
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
        self._metadata = manifest.get('metadata', {})
        
        # Add comprehensive logging
        log_event(f"[SQLSchemaPlugin] Initializing plugin", extra={
            "database_type": self.database_type,
            "auth_type": self.auth_type,
            "server": self.server,
            "database": self.database,
            "has_connection_string": bool(self.connection_string),
            "has_username": bool(self.username),
            "manifest_keys": list(manifest.keys())
        })
        print(f"[SQLSchemaPlugin] Initializing - DB Type: {self.database_type}, Auth: {self.auth_type}, Server: {self.server}, Database: {self.database}")
        
        # Validate required configuration
        if not self.connection_string and not (self.server and self.database):
            error_msg = "SQLSchemaPlugin requires either 'connection_string' or 'server' and 'database' in the manifest."
            log_event(f"[SQLSchemaPlugin] Configuration error: {error_msg}", extra={"manifest": manifest})
            print(f"[SQLSchemaPlugin] ERROR: {error_msg}")
            raise ValueError(error_msg)
        
        # Set up database-specific configurations
        self._setup_database_config()
        
        # Initialize connection (lazy loading)
        self._connection = None
        print(f"[SQLSchemaPlugin] Initialization complete")

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
                    return pyodbc.connect(self.connection_string)
                else:
                    driver = self.driver or self.supported_databases['sqlserver']['default_driver']
                    conn_str = f"DRIVER={{{driver}}};SERVER={self.server};DATABASE={self.database}"
                    if self.username and self.password:
                        conn_str += f";UID={self.username};PWD={self.password}"
                    else:
                        conn_str += ";Trusted_Connection=yes"
                    return pyodbc.connect(conn_str)
                    
            elif self.database_type == 'postgresql':
                import psycopg2
                if self.connection_string:
                    return psycopg2.connect(self.connection_string)
                else:
                    return psycopg2.connect(
                        host=self.server,
                        database=self.database,
                        user=self.username,
                        password=self.password
                    )
                    
            elif self.database_type == 'mysql':
                import pymysql
                if self.connection_string:
                    # Parse connection string for MySQL
                    # This is a simplified parser - you might want to use a proper URL parser
                    return pymysql.connect(self.connection_string)
                else:
                    return pymysql.connect(
                        host=self.server,
                        database=self.database,
                        user=self.username,
                        password=self.password
                    )
                    
            elif self.database_type == 'sqlite':
                import sqlite3
                database_path = self.connection_string or self.database
                return sqlite3.connect(database_path)
                
        except ImportError as e:
            raise ImportError(f"Required database driver not installed for {self.database_type}: {e}")
        except Exception as e:
            log_event(f"[SQLSchemaPlugin] Connection failed: {e}", extra={"database_type": self.database_type})
            raise

    @property
    def display_name(self) -> str:
        return "SQL Schema"

    @property
    def metadata(self) -> Dict[str, Any]:
        user_desc = self._metadata.get("description", f"SQL Schema plugin for {self.database_type} database")
        api_desc = (
            "This plugin connects to SQL databases and extracts schema information including tables, columns, "
            "data types, primary keys, foreign keys, and relationships. It supports SQL Server, PostgreSQL, "
            "MySQL, and SQLite databases. The plugin provides structured schema data that can be used by "
            "AI agents to understand database structure and generate appropriate SQL queries. "
            "Authentication supports connection strings, username/password, and integrated authentication. "
            "The plugin handles database-specific SQL variations for schema extraction."
        )
        full_desc = f"{user_desc}\n\n{api_desc}"
        
        return {
            "name": self._metadata.get("name", "sql_schema_plugin"),
            "type": "sql_schema",
            "description": full_desc,
            "methods": [
                {
                    "name": "get_database_schema",
                    "description": "Get complete database schema including all tables, columns, and relationships",
                    "parameters": [
                        {"name": "include_system_tables", "type": "bool", "description": "Whether to include system tables in the schema", "required": False},
                        {"name": "table_filter", "type": "str", "description": "Optional filter pattern for table names (supports wildcards)", "required": False}
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "Complete database schema with tables, columns, data types, and relationships"}
                },
                {
                    "name": "get_table_schema",
                    "description": "Get detailed schema for a specific table",
                    "parameters": [
                        {"name": "table_name", "type": "str", "description": "Name of the table to get schema for", "required": True}
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "Detailed table schema including columns, data types, constraints, and indexes"}
                },
                {
                    "name": "get_table_list",
                    "description": "Get list of all tables in the database",
                    "parameters": [
                        {"name": "include_system_tables", "type": "bool", "description": "Whether to include system tables", "required": False},
                        {"name": "table_filter", "type": "str", "description": "Optional filter pattern for table names", "required": False}
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "List of table names with basic information"}
                },
                {
                    "name": "get_relationships",
                    "description": "Get foreign key relationships between tables",
                    "parameters": [
                        {"name": "table_name", "type": "str", "description": "Optional table name to get relationships for specific table", "required": False}
                    ],
                    "returns": {"type": "ResultWithMetadata", "description": "Foreign key relationships and table dependencies"}
                }
            ]
        }

    def get_functions(self) -> List[str]:
        return ["get_database_schema", "get_table_schema", "get_table_list", "get_relationships"]

    @plugin_function_logger("SQLSchemaPlugin")
    @kernel_function(description="Get complete database schema including all tables, columns, and relationships")
    def get_database_schema(
        self, 
        include_system_tables: bool = False,
        table_filter: Optional[str] = None
    ) -> ResultWithMetadata:
        """Get complete database schema"""
        log_event(f"[SQLSchemaPlugin] get_database_schema called", extra={
            "database_type": self.database_type,
            "database": self.database,
            "include_system_tables": include_system_tables,
            "table_filter": table_filter
        })
        print(f"[SQLSchemaPlugin] Getting database schema - DB: {self.database}, Include System: {include_system_tables}")
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            schema_data = {
                "database_type": self.database_type,
                "database_name": self.database,
                "tables": {},
                "relationships": []
            }
            
            # Get tables list
            tables_query = self._get_tables_query(include_system_tables, table_filter)
            debug_print(f"[SQLSchemaPlugin] Executing tables query: {tables_query}")
            cursor.execute(tables_query)
            tables = cursor.fetchall()
            
            print(f"[SQLSchemaPlugin] Found {len(tables)} tables")
            
            # Get schema for each table
            for table in tables:
                if isinstance(table, tuple) and len(table) >= 2:
                    table_name = table[0]
                    schema_name = table[1]
                    qualified_table_name = f"{schema_name}.{table_name}"
                else:
                    table_name = table[0] if isinstance(table, tuple) else table
                    schema_name = None
                    qualified_table_name = table_name
                    
                try:
                    table_schema = self._get_table_schema_data(cursor, table_name, schema_name)
                    schema_data["tables"][table_name] = table_schema
                    print(f"[SQLSchemaPlugin] Got schema for table: {qualified_table_name}")
                except Exception as e:
                    print(f"[SQLSchemaPlugin] Error getting schema for table {qualified_table_name}: {e}")
                    log_event(f"[SQLSchemaPlugin] Error getting table schema", extra={
                        "table_name": qualified_table_name,
                        "error": str(e)
                    })
            
            # Get relationships
            try:
                relationships = self._get_relationships_data(cursor)
                schema_data["relationships"] = relationships
                print(f"[SQLSchemaPlugin] Found {len(relationships)} relationships")
            except Exception as e:
                print(f"[SQLSchemaPlugin] Error getting relationships: {e}")
                
            log_event(f"[SQLSchemaPlugin] get_database_schema completed", extra={
                "tables_count": len(schema_data["tables"]),
                "relationships_count": len(schema_data["relationships"])
            })
            
            return ResultWithMetadata(
                schema_data,
                {
                    "source": "sql_schema_plugin",
                    "database_type": self.database_type,
                    "table_count": len(schema_data["tables"]),
                    "relationship_count": len(schema_data["relationships"])
                }
            )
            
        except Exception as e:
            error_msg = f"Failed to get database schema: {str(e)}"
            print(f"[SQLSchemaPlugin] ERROR: {error_msg}")
            log_event(f"[SQLSchemaPlugin] get_database_schema failed", extra={
                "error": str(e),
                "database_type": self.database_type,
                "database": self.database
            })
            return ResultWithMetadata(
                {"error": error_msg},
                {"source": "sql_schema_plugin", "success": False}
            )
            
            # Get tables
            tables_query = self._get_tables_query(include_system_tables, table_filter)
            cursor.execute(tables_query)
            tables = cursor.fetchall()
            
            # Get schema for each table
            for table_row in tables:
                table_name = table_row[0] if isinstance(table_row, (list, tuple)) else table_row
                table_schema = self._get_table_schema_data(cursor, table_name)
                schema_data["tables"][table_name] = table_schema
            
            # Get relationships
            relationships = self._get_relationships_data(cursor)
            schema_data["relationships"] = relationships
            
            log_event(f"[SQLSchemaPlugin] Retrieved schema for {len(schema_data['tables'])} tables")
            return ResultWithMetadata(schema_data, self.metadata)
            
        except Exception as e:
            log_event(f"[SQLSchemaPlugin] Error getting database schema: {e}")
            raise

    @kernel_function(description="Get detailed schema for a specific table")
    @plugin_function_logger("SQLSchemaPlugin")
    def get_table_schema(self, table_name: str) -> ResultWithMetadata:
        """Get detailed schema for a specific table"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            table_schema = self._get_table_schema_data(cursor, table_name)
            
            log_event(f"[SQLSchemaPlugin] Retrieved schema for table: {table_name}")
            return ResultWithMetadata(table_schema, self.metadata)
            
        except Exception as e:
            log_event(f"[SQLSchemaPlugin] Error getting table schema for {table_name}: {e}")
            raise

    @kernel_function(description="Get list of all tables in the database")
    @plugin_function_logger("SQLSchemaPlugin")
    def get_table_list(
        self, 
        include_system_tables: bool = False,
        table_filter: Optional[str] = None
    ) -> ResultWithMetadata:
        """Get list of all tables in the database"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            tables_query = self._get_tables_query(include_system_tables, table_filter)
            cursor.execute(tables_query)
            tables = cursor.fetchall()
            
            table_list = []
            for table_row in tables:
                if isinstance(table_row, (list, tuple)):
                    table_info = {
                        "table_name": table_row[0],
                        "schema": table_row[1] if len(table_row) > 1 else None,
                        "table_type": table_row[2] if len(table_row) > 2 else "TABLE"
                    }
                else:
                    table_info = {"table_name": table_row, "schema": None, "table_type": "TABLE"}
                table_list.append(table_info)
            
            log_event(f"[SQLSchemaPlugin] Retrieved {len(table_list)} tables")
            return ResultWithMetadata(table_list, self.metadata)
            
        except Exception as e:
            log_event(f"[SQLSchemaPlugin] Error getting table list: {e}")
            raise

    @kernel_function(description="Get foreign key relationships between tables")
    def get_relationships(self, table_name: Optional[str] = None) -> ResultWithMetadata:
        """Get foreign key relationships between tables"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            relationships = self._get_relationships_data(cursor, table_name)
            
            log_event(f"[SQLSchemaPlugin] Retrieved {len(relationships)} relationships")
            return ResultWithMetadata(relationships, self.metadata)
            
        except Exception as e:
            log_event(f"[SQLSchemaPlugin] Error getting relationships: {e}")
            raise

    def _get_tables_query(self, include_system_tables: bool, table_filter: Optional[str]) -> str:
        """Get database-specific query for listing tables"""
        if self.database_type == 'sqlserver':
            base_query = """
                SELECT TABLE_NAME, TABLE_SCHEMA, TABLE_TYPE 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_TYPE = 'BASE TABLE'
            """
            if not include_system_tables:
                base_query += " AND TABLE_SCHEMA NOT IN ('sys', 'information_schema')"
            if table_filter:
                base_query += f" AND TABLE_NAME LIKE '{table_filter.replace('*', '%')}'"
            return base_query
            
        elif self.database_type == 'postgresql':
            base_query = """
                SELECT tablename, schemaname, 'BASE TABLE' as table_type
                FROM pg_tables
            """
            if not include_system_tables:
                base_query += " WHERE schemaname NOT IN ('information_schema', 'pg_catalog')"
            if table_filter:
                base_query += f" {'AND' if not include_system_tables else 'WHERE'} tablename LIKE '{table_filter.replace('*', '%')}'"
            return base_query
            
        elif self.database_type == 'mysql':
            base_query = f"SHOW TABLES"
            if self.database:
                base_query += f" FROM {self.database}"
            if table_filter:
                base_query += f" LIKE '{table_filter.replace('*', '%')}'"
            return base_query
            
        elif self.database_type == 'sqlite':
            base_query = "SELECT name FROM sqlite_master WHERE type='table'"
            if not include_system_tables:
                base_query += " AND name NOT LIKE 'sqlite_%'"
            if table_filter:
                base_query += f" AND name LIKE '{table_filter.replace('*', '%')}'"
            return base_query

    def _get_table_schema_data(self, cursor, table_name: str, schema_name: str = None) -> Dict[str, Any]:
        """Get detailed schema data for a specific table"""
        schema_data = {
            "table_name": table_name,
            "schema_name": schema_name,
            "columns": [],
            "primary_keys": [],
            "foreign_keys": [],
            "indexes": []
        }
        
        # Get columns
        columns_query = self._get_columns_query(table_name, schema_name)
        cursor.execute(columns_query)
        columns = cursor.fetchall()
        
        for col in columns:
            column_info = self._parse_column_info(col)
            schema_data["columns"].append(column_info)
        
        # Get primary keys
        pk_query = self._get_primary_keys_query(table_name, schema_name)
        if pk_query:
            cursor.execute(pk_query)
            pks = cursor.fetchall()
            schema_data["primary_keys"] = [pk[0] if isinstance(pk, (list, tuple)) else pk for pk in pks]
        
        return schema_data

    def _get_columns_query(self, table_name: str, schema_name: str = None) -> str:
        """Get database-specific query for table columns"""
        if self.database_type == 'sqlserver':
            where_clause = f"WHERE TABLE_NAME = '{table_name}'"
            if schema_name:
                where_clause += f" AND TABLE_SCHEMA = '{schema_name}'"
            return f"""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, 
                       CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE
                FROM INFORMATION_SCHEMA.COLUMNS 
                {where_clause}
                ORDER BY ORDINAL_POSITION
            """
        elif self.database_type == 'postgresql':
            return f"""
                SELECT column_name, data_type, is_nullable, column_default,
                       character_maximum_length, numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_name = '{table_name}'
                ORDER BY ordinal_position
            """
        elif self.database_type == 'mysql':
            return f"DESCRIBE {table_name}"
        elif self.database_type == 'sqlite':
            return f"PRAGMA table_info({table_name})"

    def _get_primary_keys_query(self, table_name: str, schema_name: str = None) -> Optional[str]:
        """Get database-specific query for primary keys"""
        if self.database_type == 'sqlserver':
            where_clause = f"WHERE TABLE_NAME = '{table_name}'"
            if schema_name:
                where_clause += f" AND TABLE_SCHEMA = '{schema_name}'"
            return f"""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                {where_clause}
                AND CONSTRAINT_NAME LIKE 'PK_%'
            """
        elif self.database_type == 'postgresql':
            return f"""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = '{table_name}'::regclass AND i.indisprimary
            """
        elif self.database_type == 'mysql':
            return f"""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
                WHERE TABLE_NAME = '{table_name}' AND CONSTRAINT_NAME = 'PRIMARY'
            """
        # SQLite primary keys are handled in the table_info query
        return None

    def _parse_column_info(self, col) -> Dict[str, Any]:
        """Parse column information based on database type"""
        if self.database_type in ['sqlserver', 'postgresql']:
            return {
                "column_name": col[0],
                "data_type": col[1],
                "is_nullable": col[2] == 'YES',
                "default_value": col[3],
                "max_length": col[4],
                "precision": col[5],
                "scale": col[6]
            }
        elif self.database_type == 'mysql':
            return {
                "column_name": col[0],
                "data_type": col[1],
                "is_nullable": col[2] == 'YES',
                "default_value": col[4],
                "extra": col[5] if len(col) > 5 else None
            }
        elif self.database_type == 'sqlite':
            return {
                "column_name": col[1],
                "data_type": col[2],
                "is_nullable": col[3] == 0,
                "default_value": col[4],
                "is_primary_key": col[5] == 1
            }

    def _get_relationships_data(self, cursor, table_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get foreign key relationships"""
        relationships = []
        
        if self.database_type == 'sqlserver':
            query = """
                SELECT 
                    fk.name AS constraint_name,
                    tp.name AS parent_table,
                    cp.name AS parent_column,
                    tr.name AS referenced_table,
                    cr.name AS referenced_column
                FROM sys.foreign_keys fk
                INNER JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
                INNER JOIN sys.tables tp ON fkc.parent_object_id = tp.object_id
                INNER JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id AND fkc.parent_column_id = cp.column_id
                INNER JOIN sys.tables tr ON fkc.referenced_object_id = tr.object_id
                INNER JOIN sys.columns cr ON fkc.referenced_object_id = cr.object_id AND fkc.referenced_column_id = cr.column_id
            """
            if table_name:
                query += f" WHERE tp.name = '{table_name}' OR tr.name = '{table_name}'"
                
        elif self.database_type == 'postgresql':
            query = """
                SELECT
                    tc.constraint_name,
                    tc.table_name AS parent_table,
                    kcu.column_name AS parent_column,
                    ccu.table_name AS referenced_table,
                    ccu.column_name AS referenced_column
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
            """
            if table_name:
                query += f" AND (tc.table_name = '{table_name}' OR ccu.table_name = '{table_name}')"
                
        else:
            # MySQL and SQLite have different approaches for foreign keys
            return relationships
        
        try:
            cursor.execute(query)
            fks = cursor.fetchall()
            for fk in fks:
                relationships.append({
                    "constraint_name": fk[0],
                    "parent_table": fk[1],
                    "parent_column": fk[2],
                    "referenced_table": fk[3],
                    "referenced_column": fk[4]
                })
        except Exception as e:
            log_event(f"[SQLSchemaPlugin] Error getting relationships: {e}")
        
        return relationships

    def __del__(self):
        """Clean up database connection"""
        if hasattr(self, '_connection') and self._connection:
            try:
                self._connection.close()
            except:
                pass
