# Cosmos Query Plugin

Implemented in version: **0.241.022**

## Overview

The Cosmos Query Plugin adds a read-only Azure Cosmos DB for NoSQL action type to the shared action system. It is designed to mirror the existing SQL action workflow where that makes sense, while keeping the first release intentionally narrow and safer.

This version supports one configured Cosmos DB container per action, managed identity authentication only, read-only `SELECT` queries only, and configuration-supplied field hints instead of runtime schema discovery.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.022"`.

## Dependencies

- Azure Cosmos DB Python SDK
- Azure Identity with `DefaultAzureCredential`
- Shared plugin modal flow in the workspace and group workspace experiences
- Shared Semantic Kernel plugin loading and validation pipeline

## Technical Specifications

### Architecture

The feature is split across backend validation and execution, loader integration, and shared modal UI support.

- Backend plugin: `application/single_app/semantic_kernel_plugins/cosmos_query_plugin.py`
- Manifest validation: `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
- Loader instruction injection: `application/single_app/semantic_kernel_loader.py`
- Connection test route: `application/single_app/route_backend_plugins.py`
- Shared modal UI: `application/single_app/templates/_plugin_modal.html`
- Shared modal controller: `application/single_app/static/js/plugin_modal_stepper.js`
- Shared type icon mapping: `application/single_app/static/js/workspace/view-utils.js`

### Action Type Shape

The new action type is `cosmos_query`.

Required configuration:

- `endpoint`
- `additionalFields.database_name`
- `additionalFields.container_name`
- `additionalFields.partition_key_path`
- `auth.type = identity`
- `auth.identity = managed_identity`

Optional configuration:

- `additionalFields.field_hints`
- `additionalFields.max_items`
- `additionalFields.timeout`

### Runtime Behavior

- Queries must be read-only `SELECT` statements.
- Mutation and administrative keywords are blocked before execution.
- Query parameters are normalized into Cosmos SDK `@name` placeholders.
- When a partition key is provided, the plugin scopes the query to a single logical partition.
- The plugin captures execution metadata such as request charge and activity ID.
- The loader injects configured Cosmos container guidance into agent instructions so the model can use the configured field hints.

## Usage Instructions

### How to Configure

1. Open the shared action modal from the workspace or group workspace actions area.
2. Select the `Cosmos Query` action type.
3. Provide the account endpoint, database name, container name, and partition key path.
4. Optionally add one field hint per line to guide query construction.
5. Optionally tune the max item cap and timeout.
6. Use the built-in Cosmos connection test before saving.

### Authentication Model

This feature uses managed identity only in v0.241.022.

- Assign the application's managed identity a Cosmos DB built-in data reader role for the target account.
- No connection strings, keys, or user-password flows are exposed in the modal.

### Integration Points

- The action modal now shows a dedicated Cosmos configuration step.
- The summary step now renders a Cosmos-specific configuration card.
- Saved manifests flow through the same plugin validation and loading pipeline as other action types.

## Testing and Validation

Functional coverage:

- `functional_tests/test_cosmos_query_plugin.py`

UI coverage:

- `ui_tests/test_workspace_cosmos_action_modal.py`

Validation focus:

- read-only query enforcement
- parameter normalization
- instruction-context generation
- loader discovery
- workspace modal rendering, connection test wiring, and summary rendering

## Known Limitations

- One container per action in this version
- No runtime container schema discovery
- No mutation support
- Managed identity only
- No dedicated group or admin Cosmos UI variations beyond the shared modal behavior