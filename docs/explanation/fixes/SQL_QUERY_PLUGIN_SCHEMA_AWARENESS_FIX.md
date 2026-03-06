# SQL Query Plugin Schema Awareness Fix

## Fix Title
SQL Query Plugin - Schema Awareness and Workflow Guidance

## Issue Description
When users asked database-related questions (e.g., "what is user1 licensed to use?"), agents connected to SQL databases would ask for clarification about table/column names instead of querying the database directly. The agent had no citations, meaning it never actually called any database tools.

## Root Cause Analysis
Three interconnected issues caused this failure:

1. **Generic `@kernel_function` descriptions**: The SQL Query and SQL Schema plugin function descriptions were terse and generic (e.g., "Execute a SQL query and return results"). They provided no workflow guidance telling the LLM to discover the schema first before writing queries. In contrast, the working LogAnalyticsPlugin uses highly prescriptive descriptions like "Use this function FIRST to discover which tables are available BEFORE attempting to query."

2. **No schema context in agent instructions**: Agent instructions were passed through verbatim from configuration with no automatic injection of database schema information. Without knowing what tables (e.g., `dbo.Licenses`, `dbo.Usage`, `dbo.Procurements`) and columns existed, the LLM couldn't generate valid SQL queries.

3. **Independent, disconnected plugins**: The SQL Schema Plugin and SQL Query Plugin operated as completely independent plugins with no linkage. There was no mechanism to ensure schema discovery happened before query execution.

## Version Implemented
**Fixed in version: 0.239.014**

## Files Modified

| File | Change |
|------|--------|
| `application/single_app/semantic_kernel_plugins/sql_schema_plugin.py` | Rewrote all `@kernel_function` descriptions with prescriptive workflow guidance; updated `metadata` property description |
| `application/single_app/semantic_kernel_plugins/sql_query_plugin.py` | Rewrote all `@kernel_function` descriptions with schema-first workflow guidance; added `query_database` convenience function; updated `metadata` property description |
| `application/single_app/semantic_kernel_loader.py` | Added `_extract_sql_schema_for_instructions()` helper function; auto-injects database schema into agent instructions at load time when SQL plugins are detected |
| `application/single_app/semantic_kernel_plugins/logged_plugin_loader.py` | Uncommented the SQL-specific plugin creation path (`_create_sql_plugin`) for explicit SQL plugin handling |
| `application/single_app/config.py` | Version bump to 0.239.014 |

## Code Changes Summary

### 1. Prescriptive Function Descriptions (sql_schema_plugin.py, sql_query_plugin.py)
- `get_database_schema`: Now says "ALWAYS call this function FIRST before executing any SQL queries"
- `get_table_list`: Now says "Use this function first to discover which tables are available"
- `get_table_schema`: Now says "Call this after discovering tables via get_database_schema or get_table_list"
- `get_relationships`: Now says "Use this to understand how tables connect via JOIN conditions"
- `execute_query`: Now says "IMPORTANT: Before calling this function, you MUST first call get_database_schema or get_table_list"
- `execute_scalar`: Now says "You MUST first discover the database schema"
- Pattern modeled after the successfully working LogAnalyticsPlugin

### 2. New `query_database` Convenience Function (sql_query_plugin.py)
- Accepts `question` (natural language) and `query` (SQL) parameters
- Returns results with the original question context for better LLM response formatting
- Gives the LLM an intent-aligned tool option

### 3. Auto Schema Injection (semantic_kernel_loader.py)
- New `_extract_sql_schema_for_instructions()` function detects SQL Schema plugins in the kernel
- Calls `get_database_schema()` at agent load time to fetch full schema
- Formats schema as markdown tables (table names, columns, types, relationships)
- Appends schema to agent instructions with directive: "Do NOT ask the user for table or column names"
- This ensures the LLM ALWAYS has schema context even if it doesn't call the schema plugin

### 4. Enabled SQL Plugin Creation Path (logged_plugin_loader.py)
- Uncommented the `elif plugin_type in ['sql_schema', 'sql_query']` branch
- SQL plugins now use the explicit `_create_sql_plugin()` method instead of generic discovery fallback

## Testing Approach
- Functional test: `functional_tests/test_sql_query_plugin_schema_awareness.py`
- Validates all `@kernel_function` descriptions contain workflow guidance keywords
- Verifies `query_database` function exists with correct parameters
- Confirms SQL plugin creation path is enabled (not commented out)
- Checks schema injection function exists and is integrated into agent loading

## Impact Analysis
- **SQL-connected agents**: Will now automatically receive database schema in their instructions, enabling proper query generation without user clarification
- **Non-SQL agents**: Completely unaffected (schema injection only triggers when SQL Schema plugins are detected)
- **LogAnalytics agents**: Unaffected (different plugin type)
- **Performance**: One-time schema fetch at agent load time adds minimal latency; schema is cached in instructions for the session

## Before/After Comparison

### Before
- User: "What is user1 licensed to use?"
- Agent: "I need the exact user identifier... Please provide the identifier..."  (no database call, no citations)

### After (Expected)
- User: "What is user1 licensed to use?"
- Agent: Calls `get_database_schema` → sees Licenses, Usage, Procurements tables → generates JOIN query → returns actual license data with citations
