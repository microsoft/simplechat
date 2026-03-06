# SQL Query Plugin Schema Awareness Fix

## Fix Title
SQL Query Plugin - Schema Awareness, Companion Plugin Auto-Creation, and Workflow Guidance

## Issue Description
When users asked database-related questions (e.g., "what is user1 licensed to use?"), agents connected to SQL databases would ask for clarification about table/column names instead of querying the database directly. The agent had no citations, meaning it never actually called any database tools.

## Root Cause Analysis

### Original Root Causes (v0.239.014)
Three interconnected issues caused the initial failure:

1. **Generic `@kernel_function` descriptions**: The SQL Query and SQL Schema plugin function descriptions were terse and generic (e.g., "Execute a SQL query and return results"). They provided no workflow guidance telling the LLM to discover the schema first before writing queries.

2. **No schema context in agent instructions**: Agent instructions were passed through verbatim from configuration with no automatic injection of database schema information.

3. **Independent, disconnected plugins**: The SQL Schema Plugin and SQL Query Plugin operated as completely independent plugins with no linkage.

### Deeper Root Causes Discovered (v0.239.015)
The v0.239.014 fix improved descriptions but actually made things **worse** because:

4. **No companion schema plugin was ever loaded**: The ESAM agent only had ONE action configured (`sql_query` type). No `sql_schema` action existed in the agent's actions. The `_create_sql_plugin()` method creates exactly what the manifest requests — so only `SQLQueryPlugin` was loaded, never `SQLSchemaPlugin`.

5. **Descriptions demanded non-existent functions**: The v0.239.014 descriptions said "you MUST first call get_database_schema or get_table_list from the SQL Schema plugin" — but those functions didn't exist in the kernel since no schema plugin was loaded. This created an **impossible dependency** that made the LLM ask for clarification instead.

6. **Schema extraction found nothing**: `_extract_sql_schema_for_instructions()` only searched for `SQLSchemaPlugin` instances. Since none existed in the kernel, it returned an empty string, so no schema was injected into agent instructions.

7. **SQLPluginFactory was disconnected**: The `SQLPluginFactory` class was designed to create `(SQLSchemaPlugin, SQLQueryPlugin)` pairs, but was never called by the `LoggedPluginLoader` pipeline.

### Empty Schema Tables from INFORMATION_SCHEMA (v0.239.016)
After the v0.239.015 fix, the agent could answer simple queries (e.g., "what is user1 licensed to use?" correctly returned Office 365 license data). However, complex multi-table JOIN queries (e.g., "which department is spending the most on licensing?") still failed because:

8. **INFORMATION_SCHEMA views returned empty results on Azure SQL**: The `_get_tables_query()`, `_get_columns_query()`, and `_get_primary_keys_query()` methods used `INFORMATION_SCHEMA.TABLES`, `INFORMATION_SCHEMA.COLUMNS`, and `INFORMATION_SCHEMA.KEY_COLUMN_USAGE` respectively. These views returned **zero rows** in this Azure SQL environment, even though the database contained 5 user tables.

9. **sys.\* catalog views worked correctly**: The `_get_relationships_data()` method used `sys.foreign_keys`, `sys.tables`, and `sys.columns` — and successfully returned 4 foreign key relationships. This proved the database connection and permissions were fine, but `INFORMATION_SCHEMA` access was restricted or misconfigured.

10. **pyodbc.Row type mismatch**: The table iteration code used `isinstance(table, tuple)` to check row types, but `pyodbc.Row` objects may not pass this check depending on the pyodbc version. When `isinstance` returned `False`, the code fell into an `else` branch that assigned the entire Row object as the table name, causing subsequent SQL queries to fail silently in the exception handler.

11. **Result**: `get_database_schema` returned `{'tables': {}, 'relationships': [4 items]}` — the agent had foreign key metadata but no table/column definitions, making it impossible to construct multi-table JOINs.

## Version Implemented
**Initial fix in version: 0.239.014**
**Companion plugin fix in version: 0.239.015**
**Schema catalog views fix in version: 0.239.016**

## Files Modified

| File | Change |
|------|--------|
| `application/single_app/semantic_kernel_plugins/sql_schema_plugin.py` | Rewrote all `@kernel_function` descriptions with prescriptive workflow guidance (v0.239.014); migrated all SQL Server queries from INFORMATION_SCHEMA to sys.\* catalog views and fixed pyodbc.Row handling (v0.239.016) |
| `application/single_app/semantic_kernel_plugins/sql_query_plugin.py` | Rewrote all `@kernel_function` descriptions with resilient conditional guidance (v0.239.015); added `query_database` convenience function (v0.239.014); updated `metadata` property description |
| `application/single_app/semantic_kernel_loader.py` | Added `_extract_sql_schema_for_instructions()` helper function; auto-injects database schema into agent instructions; added SQLQueryPlugin fallback detection (v0.239.015) |
| `application/single_app/semantic_kernel_plugins/logged_plugin_loader.py` | Enabled SQL plugin creation path (v0.239.014); added `_auto_create_companion_schema_plugin()` method that auto-creates a SQLSchemaPlugin whenever a SQLQueryPlugin is loaded (v0.239.015) |
| `application/single_app/config.py` | Version bump to 0.239.016 |

## Code Changes Summary

### v0.239.014 Changes

#### 1. Prescriptive Function Descriptions (sql_schema_plugin.py)
- `get_database_schema`: Now says "ALWAYS call this function FIRST before executing any SQL queries"
- `get_table_list`: Now says "Use this function first to discover which tables are available"
- `get_table_schema`: Now says "Call this after discovering tables via get_database_schema or get_table_list"
- `get_relationships`: Now says "Use this to understand how tables connect via JOIN conditions"

#### 2. New `query_database` Convenience Function (sql_query_plugin.py)
- Accepts `question` (natural language) and `query` (SQL) parameters
- Returns results with the original question context for better LLM response formatting

#### 3. Auto Schema Injection (semantic_kernel_loader.py)
- New `_extract_sql_schema_for_instructions()` function detects SQL Schema plugins in the kernel
- Calls `get_database_schema()` at agent load time to fetch full schema
- Formats schema as markdown tables (table names, columns, types, relationships)
- Appends schema to agent instructions with directive: "Do NOT ask the user for table or column names"

#### 4. Enabled SQL Plugin Creation Path (logged_plugin_loader.py)
- Uncommented the `elif plugin_type in ['sql_schema', 'sql_query']` branch

### v0.239.015 Changes (Complete Fix)

#### 5. Auto-Create Companion Schema Plugin (logged_plugin_loader.py)
- New `_auto_create_companion_schema_plugin()` method
- When a `sql_query` plugin is loaded, automatically creates a companion `SQLSchemaPlugin` using the same connection details
- Derives schema plugin name: `enterprise_software_asset_management_query` → `enterprise_software_asset_management_schema`
- Checks if the companion already exists (idempotent)
- Enables logging, wraps functions, registers with kernel
- This is the **critical fix** — ensures schema discovery is always available even when only `sql_query` is configured

#### 6. Resilient Function Descriptions (sql_query_plugin.py)
- Changed from "you MUST first call get_database_schema" to "If the database schema is provided in your instructions, use those exact table and column names. If no schema is available, call get_database_schema"
- This dual-path approach works whether schema is injected in instructions OR available via schema plugin functions

#### 7. SQLQueryPlugin Fallback in Schema Extraction (semantic_kernel_loader.py)
- Added fallback in `_extract_sql_schema_for_instructions()` that also detects `SQLQueryPlugin` instances
- If no `SQLSchemaPlugin` is found, creates a temporary `SQLSchemaPlugin` from the query plugin's connection config
- Belt-and-suspenders safety net in case companion auto-creation fails
- Appends schema to agent instructions with directive: "Do NOT ask the user for table or column names"
- This ensures the LLM ALWAYS has schema context even if it doesn't call the schema plugin

### 4. Enabled SQL Plugin Creation Path (logged_plugin_loader.py)
- Uncommented the `elif plugin_type in ['sql_schema', 'sql_query']` branch
- SQL plugins now use the explicit `_create_sql_plugin()` method instead of generic discovery fallback

### v0.239.016 Changes (Schema Catalog Views Fix)

#### 8. Migrated SQL Server Queries to sys.\* Catalog Views (sql_schema_plugin.py)
- **`_get_tables_query()`**: Replaced `INFORMATION_SCHEMA.TABLES` with `sys.tables t INNER JOIN sys.schemas s ON t.schema_id = s.schema_id WHERE t.type = 'U'`
- **`_get_columns_query()`**: Replaced `INFORMATION_SCHEMA.COLUMNS` with `sys.columns c INNER JOIN sys.tables t ... LEFT JOIN sys.default_constraints dc ...` using `TYPE_NAME(c.user_type_id)` for data type resolution
- **`_get_primary_keys_query()`**: Replaced `INFORMATION_SCHEMA.KEY_COLUMN_USAGE` with `sys.index_columns ic INNER JOIN sys.indexes i ... WHERE i.is_primary_key = 1`
- This makes all SQL Server schema queries consistent with `_get_relationships_data()`, which already used sys.\* views successfully

#### 9. Robust pyodbc.Row Handling (sql_schema_plugin.py)
- **`get_database_schema()`**: Replaced `isinstance(table, tuple)` checks with try/except indexing; all row field values cast to `str()` before use as dict keys
- **`get_table_list()`**: Same robust Row handling pattern applied to table row iteration
- **`_get_table_schema_data()`**: Primary key list comprehension updated to use `str(pk[0])` without isinstance checks
- This ensures the code works correctly regardless of whether `pyodbc.Row` inherits from `tuple` in the installed pyodbc version

## Testing Approach
- Functional test (v0.239.014): `functional_tests/test_sql_query_plugin_schema_awareness.py`
- Functional test (v0.239.015): `functional_tests/test_sql_auto_schema_companion.py`
- Validates `_auto_create_companion_schema_plugin` method exists with correct signature
- Confirms companion creation is triggered in `load_plugin_from_manifest` for `sql_query` type
- Verifies schema plugin name derivation logic (`_query` → `_schema` suffix swap)
- Checks `@kernel_function` descriptions are resilient (no hard dependency on non-existent functions)
- Validates `_extract_sql_schema_for_instructions` has SQLQueryPlugin fallback
- Confirms version updated to 0.239.015
- Functional test (v0.239.016): `functional_tests/test_sql_schema_sys_catalog_views.py`
- Validates all SQL Server queries use `sys.tables`, `sys.columns`, `sys.indexes` instead of `INFORMATION_SCHEMA`
- Confirms pyodbc.Row-safe iteration (no `isinstance(table, tuple)` checks)
- Verifies primary key query uses `sys.index_columns` with `is_primary_key = 1`
- Checks PostgreSQL/MySQL/SQLite queries remain unchanged
- Confirms version updated to 0.239.016

## Impact Analysis
- **SQL-connected agents**: Will now automatically have BOTH a query plugin AND a companion schema plugin, even when only `sql_query` is configured. Schema is injected into agent instructions at load time.
- **Non-SQL agents**: Completely unaffected (companion creation only triggers for `sql_query` type)
- **LogAnalytics agents**: Unaffected (different plugin type)
- **Performance**: One-time schema fetch at agent load time adds minimal latency; schema is cached in instructions for the session
- **Backwards compatible**: If both `sql_query` and `sql_schema` actions are explicitly configured, the companion auto-creation is skipped (checks for existing plugin)

## Before/After Comparison

### Before (v0.239.014)
- User: "What is user1 licensed to use?"
- Agent: "I need the exact user identifier... Please provide the identifier..." (no database call, no citations)
- Root cause: Descriptions demanded calling schema functions that didn't exist in the kernel

### After v0.239.015
- User: "What is user1 licensed to use?"
- Agent: Correctly returns Office 365 license data with LicenseID 1, TotalQuantity 52 (simple single-table queries work)
- User: "Which department is spending the most on licensing?"
- Agent: Fails — says "I don't see a department dimension in the current schema" and calls `get_database_schema` which returns `{'tables': {}}` (empty)
- Root cause: INFORMATION_SCHEMA views returned no results on Azure SQL

### After v0.239.016
- User: "What is user1 licensed to use?"
- Agent: Correctly returns license data (still works)
- User: "Which department is spending the most on licensing?"
- Agent: Has full schema with all 5 tables and their columns → can construct multi-table JOINs (Licenses → Procurements for cost, Usage for department) → returns department-level spending analysis
