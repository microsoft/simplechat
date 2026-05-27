# Databricks Action Configuration

Implemented in version: **0.241.104**

## Overview

The Databricks action adds Azure Commercial Databricks SQL Warehouse support to the SimpleChat action workflow. It exposes read-only Databricks SQL tools to Semantic Kernel agents through the Databricks Statement Execution API.

## Version Implemented

- Version implemented: **0.241.104**
- Related version update: [application/single_app/config.py](../../../../application/single_app/config.py)

## Dependencies

- Azure Commercial Databricks workspace
- Databricks SQL Warehouse ID
- Databricks token, Azure service principal, managed identity, or reusable workspace identity
- Semantic Kernel action loading

## Technical Specifications

### Architecture

- `DatabricksPluginFactory` normalizes stored action manifests and creates the Databricks plugin.
- `DatabricksPlugin` executes SQL through `/api/2.0/sql/statements` and does not require an ODBC driver.
- `functions_databricks_operations.py` centralizes cloud, auth, and default configuration constants.
- Runtime loaders use the factory the same way OpenAPI and MCP actions are factory-created.

### Supported Cloud

- `azure_commercial` is the only enabled cloud in this release.
- Government and other national cloud support should be added as cloud-specific factory branches after API and auth support are validated for each cloud.

### Exposed Functions

- `execute_sql_query`
- `get_catalogs`
- `get_schemas`
- `get_tables`
- `describe_table`

### Configuration

Action manifests use type `databricks` with these key fields:

- `endpoint`: Databricks workspace URL
- `auth.type`: `key`, `identity`, or `servicePrincipal`
- `additionalFields.cloud`: `azure_commercial`
- `additionalFields.warehouse_id`: Databricks SQL Warehouse ID
- `additionalFields.catalog`: optional default catalog
- `additionalFields.schema`: optional default schema
- `additionalFields.max_rows`: default SELECT/WITH row cap when no LIMIT is supplied
- `additionalFields.timeout`: HTTP timeout in seconds
- `additionalFields.wait_timeout`: Statement Execution wait timeout in seconds

## Usage Instructions

1. Open workspace Actions.
2. Add a new Databricks action.
3. Enter the Azure Commercial workspace URL and SQL Warehouse ID.
4. Choose token, service principal, managed identity, or reusable identity authentication.
5. Assign the action to an agent.

## Testing and Validation

- Functional test: [functional_tests/test_databricks_action_plugin.py](../../../../functional_tests/test_databricks_action_plugin.py)
- UI test: [ui_tests/test_workspace_databricks_action_modal.py](../../../../ui_tests/test_workspace_databricks_action_modal.py)
- The plugin validates read-only SQL before issuing HTTP requests.
- The modal normalizes workspace URLs that accidentally include the Statement Execution API path.

## Known Limitations

- Only Azure Commercial is supported in this release.
- SQL execution is intentionally read-only by default.
- Complex quoted Databricks identifiers are not exposed through helper functions; use simple catalog, schema, and table identifiers.