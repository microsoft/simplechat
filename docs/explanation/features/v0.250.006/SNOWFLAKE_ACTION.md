# Snowflake Action

Implemented in version: **0.250.006**

Version reference: `application/single_app/config.py` was updated to `VERSION = "0.250.006"` for this feature.

Dependencies: Snowflake Connector for Python with pandas extras, Semantic Kernel action loading, workspace identities, and Key Vault action secret handling.

## Overview

The Snowflake action adds a built-in Semantic Kernel plugin type, `snowflake`, for querying Snowflake data warehouses from SimpleChat agents. It is designed for data retrieval and analysis, not Snowflake administration or data management.

Agents can use the action to discover databases, schemas, tables, and table columns, then execute read-only SQL queries and use the returned tabular rows for analysis, charts, generated documents, exports, or other user-requested outputs.

## Technical Specifications

### Architecture

- Plugin type: `snowflake`
- Default endpoint: `snowflake://query`
- Backend plugin: `semantic_kernel_plugins/snowflake_plugin.py`
- Factory: `semantic_kernel_plugins/snowflake_plugin_factory.py`
- Shared normalization helpers: `functions_snowflake_operations.py`
- UI configuration: `templates/_plugin_modal.html` and `static/js/plugin_modal_stepper.js`
- Connector dependency: `snowflake-connector-python[pandas]==3.14.0`

### Authentication

The action supports:

- Password authentication through `auth.type = username_password`
- Key-pair authentication through `auth.type = key` and `additionalFields.auth_method = key_pair`
- OAuth token authentication through `auth.type = key` and `additionalFields.auth_method = oauth`
- Reusable workspace identities for username/password, API key private-key material, and bearer-token OAuth flows

Secrets are handled through the existing action Key Vault paths. Passwords, private keys, private key passphrases, and OAuth tokens are redacted and resolved server-side when Key Vault secret storage is enabled.

### Query Safety

The Snowflake action enforces read-only execution by default:

- Allows `SELECT`, `WITH`, `SHOW`, `DESCRIBE`, `DESC`, and `EXPLAIN`
- Rejects multiple statements in one call
- Blocks write, DDL, staging, role, and system-function keywords such as `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `PUT`, `COPY`, `GRANT`, `USE`, and `SYSTEM$`
- Adds `LIMIT` to `SELECT` and `WITH` queries that do not already include `LIMIT` or `FETCH`
- Caps returned rows and serialized result size

### Semantic Kernel Functions

The plugin exposes:

- `execute_sql_query(query)`
- `get_databases()`
- `get_schemas(database="")`
- `get_tables(database="", schema="")`
- `describe_table(table_name)`

Each query response includes query metadata, columns, row dictionaries, row counts, and truncation status.

## Usage Instructions

1. Add a new action and select **Snowflake**.
2. Enter the Snowflake account identifier, warehouse, and optional default database, schema, and role.
3. Choose password, key-pair, OAuth token, or a reusable identity.
4. Configure row and timeout limits.
5. Assign the action to agents that should analyze Snowflake data.

Agents should use the discovery functions before writing SQL so generated queries reference valid Snowflake objects.

## Testing and Validation

Functional coverage lives in `functional_tests/test_snowflake_action_plugin.py` and validates:

- Manifest defaults and factory normalization
- Health checker validation
- Read-only query rejection before connector access
- Automatic `LIMIT` handling
- Structured columns/rows result shape
- Discovery helper SQL generation

Known limitation: the functional test uses a fake connector and does not validate live Snowflake network connectivity or account-level permissions.