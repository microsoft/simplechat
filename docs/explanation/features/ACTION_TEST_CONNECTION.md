# Action Test Connection

## Overview

Configurable SimpleChat actions can now be validated from the action modal before they are saved. A **Test Connection** button authenticates with the credentials entered in Step 3 and performs one lightweight read against the configured resource, so a wrong warehouse ID, container name, subscription key, personal access token, or MCP endpoint is caught immediately instead of surfacing as a tool failure during a chat.

This extends the pattern already used by SQL, Cosmos DB, Yamcs, and RocksDB actions to eight more action types.

**Implemented in version:** **0.250.217**

**Related issue:** [microsoft/simplechat#1267](https://github.com/microsoft/simplechat/issues/1267)

### Supported action types

| Action type | Manifest type | Endpoint |
| --- | --- | --- |
| OpenAPI | `openapi` | `POST /api/plugins/test-openapi-connection` |
| Azure Maps (OpenLayers) | `azure_maps_openlayers` | `POST /api/plugins/test-azure-maps-connection` |
| Blob Storage | `blob_storage` | `POST /api/plugins/test-blob-storage-connection` |
| Databricks | `databricks` | `POST /api/plugins/test-databricks-connection` |
| Log Analytics | `log_analytics` | `POST /api/plugins/test-log-analytics-connection` |
| MCP | `mcp` | `POST /api/plugins/test-mcp-connection` |
| Snowflake | `snowflake` | `POST /api/plugins/test-snowflake-connection` |
| Tableau | `tableau` | `POST /api/plugins/test-tableau-connection` |

SQL, Cosmos DB, Yamcs, and RocksDB actions keep their existing `POST /api/plugins/test-sql-connection`, `POST /api/plugins/test-cosmos-connection`, `POST /api/plugins/test-yamcs-connection`, and `POST /api/plugins/test-rocksdb-connection` routes, which are unchanged apart from the secret-scoping hardening described below.

### Dependencies

Connection testing reuses the packages the actions already need at runtime:

- `requests` (OpenAPI, Azure Maps, Databricks)
- `azure-storage-blob`, `azure-identity` (Blob Storage)
- `azure-monitor-query` (Log Analytics)
- `mcp` connectors via `McpPluginFactory` (MCP)
- `snowflake-connector-python` (Snowflake)
- `tableauserverclient` (Tableau)

If an optional package is missing from the container image, the test returns HTTP 501 with a message naming the package to install instead of a generic 500.

## Technical specifications

### Architecture

```
Action modal (Step 3)
  └── plugin_modal_stepper.js
        ├── ACTION_CONNECTION_TEST_CONFIG   (test key -> button prefix + route)
        ├── buildActionConnectionTestConfig (per-type field collection + pre-checks)
        ├── buildActionConnectionTestPayload(manifest + scope + plugin context)
        └── runActionConnectionTest         (spinner, fetch, Bootstrap alert)
                    │
                    ▼
route_backend_plugins.py
  ├── _prepare_action_test_manifest  (load stored action, resolve scope, rehydrate
  │                                   masked secrets, hydrate reusable identities,
  │                                   validate the manifest)
  └── _run_action_connection_test    (error mapping + JSON response shaping)
                    │
                    ▼
functions_action_connection_tests.py
  └── one tester per action type, each returning
      {success, message | error, status, details}
```

Routes stay thin: they only prepare and validate the transient manifest, then delegate to the matching tester. All outbound work and error sanitization lives in `functions_action_connection_tests.py`.

### What each test verifies

| Action type | Verification performed |
| --- | --- |
| OpenAPI | Loads the stored specification through `OpenApiPluginFactory`, reports the operation count, then issues an authenticated `GET` to the base URL. HTTP 401/403 is reported as an authentication problem; any other response confirms reachability. |
| Azure Maps | Requests tile `0/0/0` of `microsoft.base.road` from `{endpoint}/map/tile` with the subscription key and confirms an image response. |
| Blob Storage | Builds the `BlobServiceClient`, reads container properties, then lists one blob under the configured prefix to prove list permission. |
| Databricks | Calls `GET {workspace_url}/api/2.0/sql/warehouses/{warehouse_id}` with the resolved token and reports the warehouse name and state. |
| Log Analytics | Runs `print TestConnection = 1` against the workspace through `LogsQueryClient.query_workspace`. |
| MCP | Runs the same `McpPluginFactory.probe_server_from_config` probe used by Discover Tools and reports transport, auth method, tool count, and any warnings. The cached tool metadata is **not** overwritten. |
| Snowflake | Opens a connection and runs `SELECT CURRENT_VERSION()`, then closes the cursor and connection. |
| Tableau | Signs in to the configured server and site and reports the negotiated API version. |

Every outbound call is capped at `ACTION_CONNECTION_TEST_MAX_TIMEOUT_SECONDS` (20 seconds).

### Request payload

```json
{
  "name": "commercial_databricks_sql",
  "displayName": "Commercial Databricks SQL",
  "description": "Read-only Databricks SQL tools",
  "type": "databricks",
  "endpoint": "https://adb-1234567890123456.7.azuredatabricks.net",
  "auth": { "type": "key", "key": "..." },
  "metadata": {},
  "additionalFields": { "warehouse_id": "warehouse-123", "cloud": "azure_commercial" },
  "action_scope": "personal",
  "identity_id": "optional-reusable-identity-id",
  "plugin_context": { "scope": "user", "id": "action-id", "name": "action_name" }
}
```

`action_scope` is one of `personal`, `group`, or `global`. `plugin_context` is only sent when editing an existing action; it lets the backend resolve masked secrets from storage.

### Response payload

```json
{
  "success": true,
  "message": "Connected to Databricks SQL warehouse 'Analytics' (state: RUNNING).",
  "details": { "warehouse_id": "warehouse-123", "warehouse_state": "RUNNING" }
}
```

Failures return `{"success": false, "error": "..."}` with an HTTP status that reflects the cause: `400` for configuration problems, `403` for authentication or authorization failures, `404` for a missing resource, `501` for a missing optional package, and `502` for transport failures.

### Security

- **No credential ever round-trips.** `sanitize_connection_error` removes every literal secret present in the manifest (`auth.key`, `auth.identity`, `auth.tenantId`, `additionalFields.private_key_passphrase`, and MCP custom header values), including base64-encoded forms, then applies generic redaction for `password`, `pwd`, `passphrase`, `private key`, `secret`, `token`, `api key`, `AccountKey=`, `SharedAccessSignature`, and `Authorization: Bearer`/`Basic` values.
- **Key Vault references resolve only within the owning action's scope.** A reference name arrives in the request body, so it is untrusted input. `_prepare_action_test_manifest` derives the expected scope from the *loaded* action with `_resolve_plugin_secret_context(existing_plugin, user_id)` and resolves through `resolve_secret_reference_for_context`, which raises on a scope mismatch. Without this, an authenticated user could submit another user's, group's, or global action's reference name and have the plaintext secret forwarded to an endpoint they control. The scoped helper `_resolve_secret_value_for_action_test` takes no defaults for `scope_value`, `scope`, or `allowed_sources`, and fails closed when the scope cannot be determined.
- **Reference sources are per field.** `auth.*` references are stored with source `action` and `additionalFields.*` plus MCP custom headers with `action-addset`, matching `keyvault_plugin_get_helper`. The route module keeps these as `ACTION_AUTH_SECRET_SOURCES` and `ACTION_ADDITIONAL_SECRET_SOURCES`; a functional test cross-checks them against `functions_keyvault.py` so a mismatch cannot silently break edit-mode testing.
- **Global actions are admin-gated at the loader.** `_load_existing_plugin_for_test` requires the Admin role before returning a global action, so every test route inherits the check — including routes that do not otherwise resolve an action identity scope.
- **Masked secrets resolve server-side.** Editing an existing action and pressing Test Connection without retyping a credential works: `_load_existing_plugin_for_test` resolves the stored Key Vault reference for the transient test only.
- **Reusable identities are honored.** When an action uses a workspace identity, `hydrate_action_identity_reference` resolves it before the test runs.
- **Scope is revalidated.** `_resolve_action_identity_context` re-checks group membership and the Admin role for group and global actions; a caller cannot test a global action without the Admin role.
- **MCP keeps discovery parity.** The MCP route enforces `_reject_non_admin_mcp_stdio` (stdio remains admin/global only) and `_enforce_mcp_destination_policy` with the `mcp_connection_test` operation label, so it is not a weaker outbound path than `/api/plugins/mcp/discover`.
- Every route carries `@swagger_route(security=get_auth_security())`, `@login_required`, and `@user_required`.

### File structure

| File | Change |
| --- | --- |
| `application/single_app/functions_action_connection_tests.py` | New. One tester per action type plus shared sanitization, result, and timeout helpers. |
| `application/single_app/route_backend_plugins.py` | Eight new routes plus `_prepare_action_test_manifest`, `_run_action_connection_test`, `_rehydrate_action_test_secret`, and the scope-checked `_resolve_secret_value_for_action_test`. The unscoped `_resolve_secret_value_for_plugin_test` helper was removed, and the existing MCP discovery, Cosmos, Yamcs, RocksDB, and SQL test paths now use the scoped resolver. |
| `application/single_app/templates/_plugin_modal.html` | Test Connection block in each of the eight Step 3 sections, plus the new `#log-analytics-config-section`. |
| `application/single_app/static/js/plugin_modal_stepper.js` | Shared test runner, per-type payload builders, and full Log Analytics configuration support. |

## Usage instructions

### Running a connection test

1. Open **Workspace → Actions** (or **Admin → Actions** for global actions) and create or edit an action.
2. Choose one of the supported action types and continue to **Step 3: Configuration**.
3. Fill in the connection fields and credentials.
4. Press **Test Connection**.
   - A green alert confirms the resource was reached and read.
   - A red alert names the failure: rejected credentials, a missing warehouse or container, an unreachable host, or an uninstalled driver.
   - A yellow alert means required fields are still empty; no request is sent.
5. Fix anything the test reports, then continue to the summary and save.

The test never changes the action. It is safe to run repeatedly, and it does not overwrite MCP discovered tool metadata.

### Log Analytics configuration section

Log Analytics previously reused the generic endpoint and authentication form, with **Workspace ID** and **Cloud** rendered in Step 4 under *Advanced → Additional Fields*. It now has a dedicated Step 3 section:

- **Workspace ID** (required) — the workspace GUID, not the resource ID.
- **Cloud** — Azure Commercial, Azure US Government, or Custom.
- **API Endpoint** — optional; blank uses the default endpoint for the selected cloud.
- **Authority Host** and **Endpoint Override** — shown and required only when the cloud is Custom.
- **Authentication** — a reusable workspace identity, or Managed Identity, On-Behalf-Of User, Service Principal, or Key.

Existing `log_analytics` actions keep the same manifest shape. The section reads and writes the same `endpoint`, `auth`, and `additionalFields` keys, and `getLogAnalyticsConfiguration()` seeds `additionalFields` from the stored action so `query_history` and any other stored keys survive an edit. New actions default `query_history` to an empty list.

Because Log Analytics is now a structured configuration type, Step 4 no longer renders duplicate Workspace ID and Cloud inputs.

## Testing and validation

### Functional tests

| Test | Coverage |
| --- | --- |
| `functional_tests/test_action_test_connection_endpoints.py` | All eight routes are registered on the `admin_plugins` Blueprint, accept only `POST`, carry the required decorator stack, delegate to a dedicated tester, the MCP route retains the stdio scope restriction and destination policy, and Key Vault references are resolved only within the owning action's scope. |
| `functional_tests/test_action_connection_test_secret_redaction.py` | Manifest secrets, generic credential patterns, and base64-encoded credentials are stripped from error messages; result helpers and the timeout clamp behave correctly. |
| `functional_tests/test_action_test_connection_modal_wiring.py` | The modal renders a button, result container, and alert for all eight types; each button maps to a registered route; results render without an `innerHTML` sink; the Log Analytics section exists, is a structured config type, and preserves `query_history`. |

Run them with:

```bash
cd functional_tests
python test_action_test_connection_endpoints.py
python test_action_connection_test_secret_redaction.py
python test_action_test_connection_modal_wiring.py
```

### UI tests

| Test | Coverage |
| --- | --- |
| `ui_tests/test_workspace_action_test_connection_controls.py` | Parametrized over all eight action types: warning state without required fields, success alert with a mocked 200, danger alert with a mocked 403, and the submitted payload shape. |
| `ui_tests/test_workspace_log_analytics_action_modal.py` | The dedicated Log Analytics section renders, custom cloud and service principal fields toggle correctly, validation blocks an empty workspace ID, and the saved manifest keeps `query_history`. |
| `ui_tests/test_workspace_azure_maps_action_modal.py`, `test_workspace_blob_storage_action_modal.py`, `test_workspace_databricks_action_modal.py`, `test_workspace_mcp_action_modal.py`, `test_tableau_action_modal_workflow.py` | Updated to assert the Test Connection control renders alongside the existing configuration flow. |

UI tests skip unless `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE` are set.

### Known limitations

- The OpenAPI test probes the base URL rather than invoking a specific operation, so an API that returns 404 at its root is reported as reachable with that status rather than as a failure.
- Managed identity and service principal tests exercise the application identity of the running SimpleChat instance, so results reflect that identity's permissions, not the signed-in user's.
- The Log Analytics On-Behalf-Of User mode tests with the signed-in user's token, so results depend on that user's workspace permissions.
- Connection tests are capped at 20 seconds. A resource that is reachable but slower than that is reported as a transport failure.
