# SQL Plugins Configuration Guide

This guide shows how to configure the SQL plugins through the web interface.

## Plugin Types Available

### 1. SQL Schema Plugin (`sql_schema`)
- **Purpose**: Extract database schema information (tables, columns, relationships)
- **Use Case**: Help AI agents understand database structure before generating queries
- **Functions**: `get_database_schema`, `get_table_schema`, `get_table_list`, `get_relationships`

### 2. SQL Query Plugin (`sql_query`)
- **Purpose**: Execute SQL queries safely with validation and security features
- **Use Case**: Allow AI agents to query databases with proper safeguards
- **Functions**: `execute_query`, `execute_scalar`, `validate_query`

## Configuration Steps

### Step 1: Select Plugin Type
1. Open the plugin modal
2. Search for "SQL" or browse through available plugins
3. Select either "SQL Schema" or "SQL Query" plugin

### Step 2: Plugin Details
1. **Plugin Name**: Enter a unique name (e.g., `hr_database_schema`, `analytics_query`)
2. **Display Name**: Human-readable name (e.g., "HR Database Schema", "Analytics Query Engine")
3. **Description**: Describe what this plugin does

### Step 3: Database Configuration

#### Database Type Selection
Choose from:
- **SQL Server**: On-premises SQL Server
- **Azure SQL**: Azure SQL Database with enhanced features
- **PostgreSQL**: PostgreSQL database
- **MySQL**: MySQL/MariaDB database
- **SQLite**: File-based SQLite database

#### Connection Configuration
Choose connection method:

**Option A: Connection String**
- Provide complete connection string
- Examples are shown based on selected database type

**Option B: Individual Parameters**
- Server hostname
- Database name
- Port (optional, uses defaults)
- Driver selection (for SQL Server)

#### Authentication
Choose authentication method:
- **Username & Password**: Traditional credentials
- **Integrated Authentication**: Windows authentication (SQL Server)
- **Managed Identity**: Azure AD authentication (Azure SQL)
- **Service Principal**: Azure AD application credentials
- **Connection String Only**: All auth in connection string

### Step 4: Plugin-Specific Settings

#### SQL Query Plugin Settings
- **Read Only Mode**: Prevent data modification (recommended: Yes)
- **Max Rows**: Limit query results (recommended: 1000)
- **Timeout**: Query timeout in seconds (recommended: 30)

#### SQL Schema Plugin Settings
- **Include System Tables**: Include database system tables (recommended: No)
- **Table Filter**: Pattern to filter table names (optional, use * as wildcard)

## Example Configurations

### Azure SQL Database with Managed Identity

**Schema Plugin:**
```json
{
  "name": "azure_sql_schema",
  "database_type": "azure_sql",
  "connection_string": "DRIVER={ODBC Driver 17 for SQL Server};SERVER=myserver.database.windows.net;DATABASE=mydatabase;Authentication=ActiveDirectoryMsi",
  "metadata": {
    "description": "Extract schema from Azure SQL database using Managed Identity"
  }
}
```

**Query Plugin:**
```json
{
  "name": "azure_sql_query",
  "database_type": "azure_sql", 
  "connection_string": "DRIVER={ODBC Driver 17 for SQL Server};SERVER=myserver.database.windows.net;DATABASE=mydatabase;Authentication=ActiveDirectoryMsi",
  "read_only": true,
  "max_rows": 500,
  "timeout": 30,
  "metadata": {
    "description": "Query Azure SQL database safely using Managed Identity"
  }
}
```

### PostgreSQL with Username/Password

**Schema Plugin:**
```json
{
  "name": "postgres_schema",
  "database_type": "postgresql",
  "server": "postgres-server.example.com",
  "database": "production_db",
  "username": "readonly_user",
  "password": "secure_password",
  "metadata": {
    "description": "Extract schema from PostgreSQL production database"
  }
}
```

**Query Plugin:**
```json
{
  "name": "postgres_query",
  "database_type": "postgresql",
  "server": "postgres-server.example.com", 
  "database": "production_db",
  "username": "readonly_user",
  "password": "secure_password",
  "read_only": true,
  "max_rows": 1000,
  "timeout": 45,
  "metadata": {
    "description": "Query PostgreSQL production database"
  }
}
```

### SQLite Local Database

**Schema Plugin:**
```json
{
  "name": "local_sqlite_schema",
  "database_type": "sqlite",
  "connection_string": "/app/data/application.db",
  "metadata": {
    "description": "Extract schema from local SQLite database"
  }
}
```

**Query Plugin:**
```json
{
  "name": "local_sqlite_query",
  "database_type": "sqlite",
  "connection_string": "/app/data/application.db", 
  "read_only": true,
  "max_rows": 2000,
  "timeout": 15,
  "metadata": {
    "description": "Query local SQLite database"
  }
}
```

## Security Best Practices

1. **Use Read-Only Mode**: Always enable read-only mode for query plugins in production
2. **Limit Results**: Set appropriate max_rows to prevent large data retrieval
3. **Use Managed Identity**: For Azure SQL, prefer Managed Identity over passwords
4. **Separate Users**: Create dedicated database users with minimal permissions
5. **Monitor Usage**: Enable logging to track query execution
6. **Rotate Credentials**: Regularly rotate passwords and connection strings
7. **Network Security**: Use private endpoints and firewall rules when possible

## Troubleshooting

### Connection Issues
- Verify network connectivity to database server
- Check firewall rules and security groups
- Validate connection string format
- Ensure database server is running

### Authentication Failures
- Verify credentials are correct and not expired
- Check user permissions on target database
- For Managed Identity, ensure proper role assignments
- Validate client ID, tenant ID for service principals

### Query Execution Issues
- Check for SQL syntax errors
- Verify table and column names exist
- Ensure user has SELECT permissions
- Review timeout settings for long-running queries

### Common Error Messages
- "Import could not be resolved": Database driver not installed
- "Connection timeout": Network or server issues
- "Invalid query": SQL validation failed
- "Permission denied": Insufficient database permissions

## Usage in AI Workflows

### Typical Workflow
1. **Schema Discovery**: Use schema plugin to understand database structure
2. **Query Generation**: AI agent uses schema info to generate appropriate SQL
3. **Query Validation**: Query plugin validates SQL before execution
4. **Safe Execution**: Query plugin executes with security safeguards
5. **Result Processing**: AI agent processes structured results

### Example Conversation Flow
```
User: "Show me all active users in the engineering department"

AI Agent:
1. Calls schema plugin to find relevant tables
2. Discovers Users table with department_id and status columns
3. Discovers Departments table with name column
4. Generates JOIN query
5. Validates query for safety
6. Executes query with limits
7. Returns formatted results
```

This configuration provides a secure, scalable way to enable AI agents to interact with your databases while maintaining proper security controls and data governance.
