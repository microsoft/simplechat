# Cosmos Query Plugin

Implemented in version: **0.241.024**

## Overview

This update extends the Cosmos Query Plugin so the shared action system now supports two authentication paths for Azure Cosmos DB for NoSQL:

- Managed identity
- Account key

The original Cosmos action release stayed intentionally narrow. This follow-up keeps the same one-container, read-only design while adding account-key support for environments that already use Key Vault-backed action secret storage.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.024"`.

## Dependencies

- Azure Cosmos DB Python SDK
- Azure Identity with `DefaultAzureCredential`
- Existing Key Vault action secret storage helpers in `functions_keyvault.py`
- Shared plugin modal flow in workspace and group workspace experiences
- Shared Semantic Kernel plugin loading and validation pipeline

## Technical Specifications

### Architecture

The account-key enhancement touches the existing Cosmos action runtime, validation, connection test route, and shared modal UI.

- Backend plugin: `application/single_app/semantic_kernel_plugins/cosmos_query_plugin.py`
- Manifest validation: `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
- Connection test route: `application/single_app/route_backend_plugins.py`
- Action type definition: `application/single_app/static/json/schemas/cosmos_query.definition.json`
- Shared modal UI: `application/single_app/templates/_plugin_modal.html`
- Shared modal controller: `application/single_app/static/js/plugin_modal_stepper.js`

### Action Type Shape

The action type remains `cosmos_query`.

Required configuration:

- `endpoint`
- `additionalFields.database_name`
- `additionalFields.container_name`
- `additionalFields.partition_key_path`
- `auth.type = identity | key`

Additional requirements by auth type:

- `identity`: no secret is required; the app uses `DefaultAzureCredential`
- `key`: `auth.key` is required and can be persisted through the existing Key Vault action-secret helpers

Optional configuration:

- `additionalFields.field_hints`
- `additionalFields.max_items`
- `additionalFields.timeout`

### Runtime Behavior

- Queries must still be read-only `SELECT` statements.
- Mutation and administrative keywords are still blocked before execution.
- The runtime now chooses the Cosmos SDK credential based on `auth.type`:
  - `identity` uses `DefaultAzureCredential()`
  - `key` uses the configured account key string
- The connection test route now resolves stored Key Vault secret references during edit-time tests, so existing key-backed actions can be re-tested without re-entering the key.
- The shared modal summary now reflects whether the action uses Managed Identity or Account Key.

## Usage Instructions

### How to Configure

1. Open the shared action modal from the workspace or group workspace actions area.
2. Select the `Cosmos Query` action type.
3. Provide the account endpoint, database name, container name, and partition key path.
4. Choose either `Managed Identity` or `Account Key`.
5. If using `Account Key`, provide the primary or secondary account key.
6. Optionally add one field hint per line to guide query construction.
7. Optionally tune the max item cap and timeout.
8. Use the built-in Cosmos connection test before saving.

### Authentication Model

Managed identity remains the recommended option.

- Use managed identity when the app identity has Azure Cosmos DB built-in data reader access.
- Use account keys when RBAC-based access is not the right fit for the target environment.
- When app-level Key Vault secret storage is enabled, account keys follow the same `auth.key` secret-storage path already used by other action types.

## Testing and Validation

Functional coverage:

- `functional_tests/test_cosmos_query_plugin.py`

UI coverage:

- `ui_tests/test_workspace_cosmos_action_modal.py`

Validation focus:

- read-only query enforcement
- parameter normalization
- account-key credential wiring into the Cosmos SDK client
- workspace modal auth switching
- browser-side Cosmos connection test payload generation
- summary rendering for account-key auth

## Known Limitations

- One container per action in this version
- No runtime container schema discovery
- No mutation support
- No connection-string-based Cosmos auth path
- No dedicated group or admin Cosmos UI variations beyond the shared modal behavior