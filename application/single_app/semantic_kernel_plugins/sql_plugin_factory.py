"""
SQL Plugin Factory and Utilities
Helper functions for creating and registering SQL plugins with Semantic Kernel
"""

from typing import Dict, Any, List, Optional, Union
import os
import json
from .sql_schema_plugin import SQLSchemaPlugin
from .sql_query_plugin import SQLQueryPlugin

class SQLPluginFactory:
    """Factory class for creating SQL plugins with common configurations"""
    
    @staticmethod
    def create_sql_server_plugins(
        server: str,
        database: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        connection_string: Optional[str] = None,
        read_only: bool = True,
        max_rows: int = 1000
    ) -> tuple:
        """
        Create both schema and query plugins for SQL Server
        
        Returns:
            tuple: (schema_plugin, query_plugin)
        """
        base_config = {
            "database_type": "sqlserver",
            "server": server,
            "database": database
        }
        
        if connection_string:
            base_config["connection_string"] = connection_string
        else:
            base_config.update({
                "username": username,
                "password": password,
                "driver": "ODBC Driver 17 for SQL Server"
            })
        
        # Schema plugin config
        schema_config = {
            **base_config,
            "name": f"sql_server_schema_{database}",
            "metadata": {
                "name": f"SQL Server Schema ({database})",
                "description": f"Extract schema information from SQL Server database: {database}"
            }
        }
        
        # Query plugin config
        query_config = {
            **base_config,
            "name": f"sql_server_query_{database}",
            "read_only": read_only,
            "max_rows": max_rows,
            "timeout": 30,
            "metadata": {
                "name": f"SQL Server Query ({database})",
                "description": f"Execute queries against SQL Server database: {database}"
            }
        }
        
        return SQLSchemaPlugin(schema_config), SQLQueryPlugin(query_config)
    
    @staticmethod
    def create_postgresql_plugins(
        server: str,
        database: str,
        username: str,
        password: str,
        port: int = 5432,
        read_only: bool = True,
        max_rows: int = 1000
    ) -> tuple:
        """
        Create both schema and query plugins for PostgreSQL
        
        Returns:
            tuple: (schema_plugin, query_plugin)
        """
        base_config = {
            "database_type": "postgresql",
            "server": server,
            "database": database,
            "username": username,
            "password": password
        }
        
        # Schema plugin config
        schema_config = {
            **base_config,
            "name": f"postgresql_schema_{database}",
            "metadata": {
                "name": f"PostgreSQL Schema ({database})",
                "description": f"Extract schema information from PostgreSQL database: {database}"
            }
        }
        
        # Query plugin config
        query_config = {
            **base_config,
            "name": f"postgresql_query_{database}",
            "read_only": read_only,
            "max_rows": max_rows,
            "timeout": 30,
            "metadata": {
                "name": f"PostgreSQL Query ({database})",
                "description": f"Execute queries against PostgreSQL database: {database}"
            }
        }
        
        return SQLSchemaPlugin(schema_config), SQLQueryPlugin(query_config)
    
    @staticmethod
    def create_mysql_plugins(
        server: str,
        database: str,
        username: str,
        password: str,
        port: int = 3306,
        read_only: bool = True,
        max_rows: int = 1000
    ) -> tuple:
        """
        Create both schema and query plugins for MySQL
        
        Returns:
            tuple: (schema_plugin, query_plugin)
        """
        base_config = {
            "database_type": "mysql",
            "server": server,
            "database": database,
            "username": username,
            "password": password
        }
        
        # Schema plugin config
        schema_config = {
            **base_config,
            "name": f"mysql_schema_{database}",
            "metadata": {
                "name": f"MySQL Schema ({database})",
                "description": f"Extract schema information from MySQL database: {database}"
            }
        }
        
        # Query plugin config
        query_config = {
            **base_config,
            "name": f"mysql_query_{database}",
            "read_only": read_only,
            "max_rows": max_rows,
            "timeout": 30,
            "metadata": {
                "name": f"MySQL Query ({database})",
                "description": f"Execute queries against MySQL database: {database}"
            }
        }
        
        return SQLSchemaPlugin(schema_config), SQLQueryPlugin(query_config)
    
    @staticmethod
    def create_sqlite_plugins(
        database_path: str,
        read_only: bool = True,
        max_rows: int = 1000
    ) -> tuple:
        """
        Create both schema and query plugins for SQLite
        
        Returns:
            tuple: (schema_plugin, query_plugin)
        """
        db_name = os.path.basename(database_path).replace('.db', '')
        
        base_config = {
            "database_type": "sqlite",
            "connection_string": database_path
        }
        
        # Schema plugin config
        schema_config = {
            **base_config,
            "name": f"sqlite_schema_{db_name}",
            "metadata": {
                "name": f"SQLite Schema ({db_name})",
                "description": f"Extract schema information from SQLite database: {database_path}"
            }
        }
        
        # Query plugin config
        query_config = {
            **base_config,
            "name": f"sqlite_query_{db_name}",
            "read_only": read_only,
            "max_rows": max_rows,
            "timeout": 30,
            "metadata": {
                "name": f"SQLite Query ({db_name})",
                "description": f"Execute queries against SQLite database: {database_path}"
            }
        }
        
        return SQLSchemaPlugin(schema_config), SQLQueryPlugin(query_config)
    
    @staticmethod
    def create_azure_sql_plugins(
        server: str,
        database: str,
        use_managed_identity: bool = True,
        username: Optional[str] = None,
        password: Optional[str] = None,
        read_only: bool = True,
        max_rows: int = 1000
    ) -> tuple:
        """
        Create both schema and query plugins for Azure SQL Database
        
        Returns:
            tuple: (schema_plugin, query_plugin)
        """
        if use_managed_identity:
            connection_string = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};Authentication=ActiveDirectoryMsi"
        else:
            connection_string = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password}"
        
        base_config = {
            "database_type": "sqlserver",
            "connection_string": connection_string
        }
        
        auth_method = "Managed Identity" if use_managed_identity else "SQL Auth"
        
        # Schema plugin config
        schema_config = {
            **base_config,
            "name": f"azure_sql_schema_{database}",
            "metadata": {
                "name": f"Azure SQL Schema ({database})",
                "description": f"Extract schema information from Azure SQL database: {database} using {auth_method}"
            }
        }
        
        # Query plugin config
        query_config = {
            **base_config,
            "name": f"azure_sql_query_{database}",
            "read_only": read_only,
            "max_rows": max_rows,
            "timeout": 30,
            "metadata": {
                "name": f"Azure SQL Query ({database})",
                "description": f"Execute queries against Azure SQL database: {database} using {auth_method}"
            }
        }
        
        return SQLSchemaPlugin(schema_config), SQLQueryPlugin(query_config)

class SQLPluginRegistry:
    """Registry for managing SQL plugins in Semantic Kernel"""
    
    def __init__(self, kernel):
        self.kernel = kernel
        self.registered_plugins = {}
    
    def register_database_plugins(
        self,
        database_type: str,
        schema_plugin_name: str,
        query_plugin_name: str,
        **kwargs
    ) -> tuple:
        """
        Register both schema and query plugins for a database
        
        Args:
            database_type: Type of database (sqlserver, postgresql, mysql, sqlite, azure_sql)
            schema_plugin_name: Name to register the schema plugin under
            query_plugin_name: Name to register the query plugin under
            **kwargs: Database connection parameters
        
        Returns:
            tuple: (schema_plugin, query_plugin)
        """
        # Create plugins based on database type
        if database_type == "sqlserver":
            schema_plugin, query_plugin = SQLPluginFactory.create_sql_server_plugins(**kwargs)
        elif database_type == "postgresql":
            schema_plugin, query_plugin = SQLPluginFactory.create_postgresql_plugins(**kwargs)
        elif database_type == "mysql":
            schema_plugin, query_plugin = SQLPluginFactory.create_mysql_plugins(**kwargs)
        elif database_type == "sqlite":
            schema_plugin, query_plugin = SQLPluginFactory.create_sqlite_plugins(**kwargs)
        elif database_type == "azure_sql":
            schema_plugin, query_plugin = SQLPluginFactory.create_azure_sql_plugins(**kwargs)
        else:
            raise ValueError(f"Unsupported database type: {database_type}")
        
        # Register with kernel
        self.kernel.import_plugin(schema_plugin, plugin_name=schema_plugin_name)
        self.kernel.import_plugin(query_plugin, plugin_name=query_plugin_name)
        
        # Track registered plugins
        self.registered_plugins[schema_plugin_name] = schema_plugin
        self.registered_plugins[query_plugin_name] = query_plugin
        
        print(f"✅ Registered {database_type} plugins: {schema_plugin_name}, {query_plugin_name}")
        
        return schema_plugin, query_plugin
    
    def get_plugin(self, plugin_name: str):
        """Get a registered plugin by name"""
        return self.registered_plugins.get(plugin_name)
    
    def list_plugins(self) -> List[str]:
        """List all registered plugin names"""
        return list(self.registered_plugins.keys())
    
    def unregister_plugin(self, plugin_name: str):
        """Unregister a plugin"""
        if plugin_name in self.registered_plugins:
            del self.registered_plugins[plugin_name]
            print(f"🗑️  Unregistered plugin: {plugin_name}")

def load_plugin_config(config_file: str) -> Dict[str, Any]:
    """
    Load plugin configuration from JSON file
    
    Args:
        config_file: Path to JSON configuration file
        
    Returns:
        Dict containing plugin configurations
    """
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Configuration file not found: {config_file}")
    
    with open(config_file, 'r') as f:
        return json.load(f)

def create_plugin_from_config(config: Dict[str, Any], plugin_type: str):
    """
    Create a plugin from configuration dictionary
    
    Args:
        config: Plugin configuration
        plugin_type: Type of plugin ('schema' or 'query')
        
    Returns:
        Plugin instance
    """
    if plugin_type == "schema":
        return SQLSchemaPlugin(config)
    elif plugin_type == "query":
        return SQLQueryPlugin(config)
    else:
        raise ValueError(f"Unknown plugin type: {plugin_type}")

# Example usage functions
def example_sql_server_setup(kernel, server: str, database: str, username: str, password: str):
    """Example: Set up SQL Server plugins"""
    registry = SQLPluginRegistry(kernel)
    
    schema_plugin, query_plugin = registry.register_database_plugins(
        database_type="sqlserver",
        schema_plugin_name="SQLServerSchema",
        query_plugin_name="SQLServerQuery",
        server=server,
        database=database,
        username=username,
        password=password,
        read_only=True,
        max_rows=500
    )
    
    return registry

def example_sqlite_setup(kernel, database_path: str):
    """Example: Set up SQLite plugins"""
    registry = SQLPluginRegistry(kernel)
    
    schema_plugin, query_plugin = registry.register_database_plugins(
        database_type="sqlite",
        schema_plugin_name="SQLiteSchema",
        query_plugin_name="SQLiteQuery",
        database_path=database_path,
        read_only=True,
        max_rows=1000
    )
    
    return registry

def example_azure_sql_setup(kernel, server: str, database: str):
    """Example: Set up Azure SQL plugins with Managed Identity"""
    registry = SQLPluginRegistry(kernel)
    
    schema_plugin, query_plugin = registry.register_database_plugins(
        database_type="azure_sql",
        schema_plugin_name="AzureSQLSchema",
        query_plugin_name="AzureSQLQuery",
        server=server,
        database=database,
        use_managed_identity=True,
        read_only=True,
        max_rows=1000
    )
    
    return registry
