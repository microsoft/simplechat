# SQL Actions/Plugins for Semantic Kernel

**Version Implemented:** 0.229.001

This directory contains comprehensive SQL Action/plugins for Semantic Kernel that enable AI agents to interact with SQL databases effectively. The plugins provide schema extraction and query execution capabilities across multiple database platforms.

## Plugins Overview

### 1. SQL Schema Action/Plugin (`sql_schema_plugin.py`)

Extracts database schema information including tables, columns, data types, primary keys, foreign keys, and relationships. This is essential for AI agents to understand database structure before generating queries.

**Key Features:**
- Multi-database support (SQL Server, PostgreSQL, MySQL, SQLite)
- Complete schema extraction with relationships
- Table-specific schema queries
- Foreign key relationship mapping
- System table filtering
- Table name pattern filtering

### 2. SQL Query Action/Plugin (`sql_query_plugin.py`)

Executes SQL queries with comprehensive safety and security features. Designed for AI agents to safely query databases with proper validation and result formatting.

**Key Features:**
- Multi-database support (SQL Server, PostgreSQL, MySQL, SQLite)
- Query sanitization and validation
- SQL injection protection
- Read-only mode enforcement
- Result limiting and timeout protection
- Parameterized query support
- Scalar value queries

## Supported Databases

| Database | Plugin Support | Required Package | Connection Method |
|----------|---------------|------------------|-------------------|
| SQL Server | ✅ | `pyodbc` | Connection string, Username/Password, Integrated Auth |
| PostgreSQL | ✅ | `psycopg2-binary` | Connection string, Username/Password |
| MySQL | ✅ | `pymysql` | Connection string, Username/Password |
| SQLite | ✅ | `sqlite3` (built-in) | File path |
| Azure SQL | ✅ | `pyodbc` | Connection string, Managed Identity |

## Installation

### Required Dependencies

Add the following to your `requirements.txt`:

```txt
# SQL Server support
pyodbc>=4.0.0

# PostgreSQL support  
psycopg2-binary>=2.9.0

# MySQL support
PyMySQL>=1.0.0

# SQLite support is built into Python
```

### Database Driver Installation

#### SQL Server (pyodbc)
```bash
pip install pyodbc
```

#### PostgreSQL (psycopg2)
```bash
pip install psycopg2-binary
```

#### MySQL (PyMySQL)
```bash
pip install PyMySQL
```

## Configuration

### Plugin Manifest Structure

Both plugins use similar manifest structures:

```json
{
  "name": "plugin_name",
  "database_type": "sqlserver|postgresql|mysql|sqlite",
  "server": "server_hostname",
  "database": "database_name",
  "username": "username",
  "password": "password",
  "connection_string": "full_connection_string",
  "auth": {
    "type": "connection_string|username_password"
  },
  "metadata": {
    "name": "Display Name",
    "description": "Plugin description"
  }
}
```

### SQL Query Plugin Additional Options

```json
{
  "read_only": true,
  "max_rows": 1000,
  "timeout": 30,
  "driver": "ODBC Driver 17 for SQL Server"
}
```

## Configuration Examples

### SQL Server with Connection String
```json
{
  "name": "sql_server_schema",
  "database_type": "sqlserver",
  "connection_string": "DRIVER={ODBC Driver 17 for SQL Server};SERVER=server.database.windows.net;DATABASE=mydb;UID=user;PWD=password",
  "metadata": {
    "name": "SQL Server Schema",
    "description": "Extract schema from SQL Server"
  }
}
```

### PostgreSQL with Credentials
```json
{
  "name": "postgresql_query",
  "database_type": "postgresql",
  "server": "localhost",
  "database": "mydb",
  "username": "user",
  "password": "password",
  "read_only": true,
  "max_rows": 500,
  "metadata": {
    "name": "PostgreSQL Query",
    "description": "Query PostgreSQL database"
  }
}
```

### Azure SQL with Managed Identity
```json
{
  "name": "azure_sql_query",
  "database_type": "sqlserver",
  "connection_string": "DRIVER={ODBC Driver 17 for SQL Server};SERVER=server.database.windows.net;DATABASE=mydb;Authentication=ActiveDirectoryMsi",
  "read_only": true,
  "metadata": {
    "name": "Azure SQL Query",
    "description": "Query Azure SQL with Managed Identity"
  }
}
```

### SQLite
```json
{
  "name": "sqlite_schema",
  "database_type": "sqlite",
  "connection_string": "/path/to/database.db",
  "metadata": {
    "name": "SQLite Schema",
    "description": "Extract schema from SQLite"
  }
}
```

## Usage Examples

### SQL Schema Plugin

```python
from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin

# Initialize plugin
manifest = {
    "database_type": "sqlserver",
    "connection_string": "your_connection_string",
    "metadata": {"name": "Database Schema"}
}
schema_plugin = SQLSchemaPlugin(manifest)

# Get complete database schema
schema = schema_plugin.get_database_schema()
print(f"Found {len(schema.data['tables'])} tables")

# Get specific table schema
table_schema = schema_plugin.get_table_schema("Users")
print(f"Table has {len(table_schema.data['columns'])} columns")

# Get table relationships
relationships = schema_plugin.get_relationships()
print(f"Found {len(relationships.data)} foreign key relationships")
```

### SQL Query Plugin

```python
from semantic_kernel_plugins.sql_query_plugin import SQLQueryPlugin

# Initialize plugin
manifest = {
    "database_type": "sqlserver", 
    "connection_string": "your_connection_string",
    "read_only": True,
    "max_rows": 100,
    "metadata": {"name": "Database Query"}
}
query_plugin = SQLQueryPlugin(manifest)

# Execute a query
result = query_plugin.execute_query("SELECT TOP 10 * FROM Users WHERE Status = 'Active'")
print(f"Query returned {result.data['row_count']} rows")

# Execute scalar query
count_result = query_plugin.execute_scalar("SELECT COUNT(*) FROM Users")
print(f"Total users: {count_result.data['value']}")

# Validate query without execution
validation = query_plugin.validate_query("SELECT * FROM Users; DROP TABLE Users;")
if not validation.data['is_valid']:
    print(f"Query validation failed: {validation.data['issues']}")
```

## Security Features

### SQL Query Plugin Security

1. **Read-Only Mode**: Default enforcement prevents data modification
2. **Query Validation**: Checks for dangerous operations and SQL injection patterns
3. **Result Limiting**: Prevents excessive data retrieval
4. **Query Timeout**: Prevents long-running queries
5. **Query Sanitization**: Removes unnecessary characters and formatting
6. **Parameterized Queries**: Support for safe parameter binding

### Detected Dangerous Patterns

- Data modification: `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, `TRUNCATE`
- System procedures: `EXEC`, `EXECUTE`, `xp_`, `sp_`
- SQL injection: `UNION SELECT`, `1=1`, `OR 1=1`, multiple statements
- Comments that might hide malicious code

## Error Handling

Both plugins include comprehensive error handling:

- **Connection Errors**: Clear messages for connection failures
- **Query Errors**: Detailed SQL error information
- **Validation Errors**: Specific security violation details
- **Timeout Errors**: Handling for long-running operations
- **Data Type Errors**: Proper handling of different result types

## Integration with Semantic Kernel

### Plugin Registration

```python
import semantic_kernel as sk
from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin
from semantic_kernel_plugins.sql_query_plugin import SQLQueryPlugin

# Create kernel
kernel = sk.Kernel()

# Register plugins
schema_plugin = SQLSchemaPlugin(schema_manifest)
query_plugin = SQLQueryPlugin(query_manifest)

kernel.import_plugin(schema_plugin, plugin_name="DatabaseSchema")
kernel.import_plugin(query_plugin, plugin_name="DatabaseQuery")
```

### Using in AI Workflows

```python
# AI agent can first understand the schema
schema_result = await kernel.invoke("DatabaseSchema", "get_database_schema")

# Then generate and execute appropriate queries
query_result = await kernel.invoke("DatabaseQuery", "execute_query", 
                                 query="SELECT * FROM Users WHERE Department = 'Engineering'")
```

## Best Practices

1. **Always use schema plugin first** to understand database structure
2. **Enable read-only mode** for query plugin in production
3. **Set appropriate max_rows limits** to prevent large result sets
4. **Use parameterized queries** when dealing with user input
5. **Validate queries** before execution in sensitive environments
6. **Monitor query execution** through logging and telemetry
7. **Use connection pooling** for high-volume scenarios
8. **Implement proper authentication** (preferably Managed Identity for Azure)

## Troubleshooting

### Common Issues

1. **Driver Not Found**: Install appropriate database driver packages
2. **Connection Timeout**: Check network connectivity and increase timeout
3. **Authentication Failures**: Verify credentials and connection strings
4. **Permission Denied**: Ensure database user has appropriate permissions
5. **Query Validation Failures**: Review security settings and query patterns

### Debug Logging

Enable detailed logging to troubleshoot issues:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Example Workflow

Here's a complete example of using both plugins together:

```python
# 1. Get database schema
schema = schema_plugin.get_database_schema()
tables = [table for table in schema.data['tables'].keys()]
print(f"Available tables: {tables}")

# 2. Get specific table structure
user_schema = schema_plugin.get_table_schema("Users")
columns = [col['column_name'] for col in user_schema.data['columns']]
print(f"User table columns: {columns}")

# 3. Generate and execute query
query = f"SELECT {', '.join(columns[:5])} FROM Users WHERE Status = 'Active'"
result = query_plugin.execute_query(query, max_rows=50)

if 'error' not in result.data:
    print(f"Retrieved {result.data['row_count']} active users")
    for row in result.data['data'][:3]:  # Show first 3 rows
        print(row)
else:
    print(f"Query failed: {result.data['error']}")
```

This comprehensive solution provides AI agents with the ability to understand database schemas and execute queries safely across multiple database platforms.
