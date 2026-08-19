# Action App-Identity Endpoint Hardening Fix

Fixed in version: **0.260.006**

Reported through MSRC as the application-side boundary in a report about cross-resource token
selection in the `azure-storage-blob` bearer-challenge policy. No public issue was filed for this
work.

## Issue Description

Actions could be configured with a caller-supplied endpoint while authenticating with the
application's own workload identity. When the optional Semantic Kernel, per-user Semantic Kernel,
personal agents, and personal plugins features were enabled, a caller holding only the normal
`User` role could save a personal `blob_storage` action with an arbitrary endpoint and
`auth.type=identity`, then bind it to a personal agent. At runtime the application constructed a
Blob client for that endpoint using `DefaultAzureCredential()`, so a token minted for the
application's own managed identity was sent to a destination the caller chose.

The reporter's broader finding is a defect in the Azure SDK for Python, where
`StorageBearerTokenCredentialPolicy.on_challenge` trusts the `resource_id` returned in a
`WWW-Authenticate` challenge without confirming it is an Azure Storage resource. That allows a
hostile endpoint to escalate a Storage token into a token for an unrelated resource such as Azure
Resource Manager. That defect belongs to `Azure/azure-sdk-for-python` and is not addressed here.

This fix removes the application-side precondition: the ability for a lower-privileged caller to
direct application credentials at an endpoint of their choosing.

## Root Cause Analysis

Three independent gaps combined:

1. **`allowedAuthTypes` was advisory only.** Each `static/json/schemas/<type>.definition.json`
   declares the auth types an action type supports, but the value was read only by the action modal
   and by `GET /api/plugins/<type>/auth-types`. No save path enforced it, so a manifest could
   declare any auth type for any action type.

2. **No origin validation on endpoints that receive application credentials.** The blob storage,
   queue storage, Cosmos query, and Databricks plugins each built a client or minted a token
   against a fully caller-supplied endpoint. The `/api/plugins/test-cosmos-connection` route did the
   same directly, bypassing both manifest validation and the plugin class.

3. **Log Analytics custom clouds were unconstrained.** With `additionalFields.cloud='custom'`,
   `authorityHost` flowed straight into `DefaultAzureCredential(authority=...)` and
   `endpointOverride` became the query endpoint. For `auth.type='user'` the override also became the
   OAuth scope, letting the manifest choose the resource for a delegated user token.

Requiring an administrator-created identity reference would not have been sufficient on its own.
Any caller with the `User` role can create a personal workspace identity with
`auth_type='managed_identity'`, and `_apply_generic_action_identity_auth` maps that back to
`auth.type='identity'` and the same application credential. Endpoint origin validation is the
effective control; auth-type enforcement is the supporting one.

## Technical Details

### Files Modified

- `application/single_app/functions_azure_endpoint_validation.py` (new)
- `application/single_app/json_schema_validation.py`
- `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
- `application/single_app/semantic_kernel_plugins/blob_storage_plugin.py`
- `application/single_app/semantic_kernel_plugins/queue_storage_plugin.py`
- `application/single_app/semantic_kernel_plugins/cosmos_query_plugin.py`
- `application/single_app/semantic_kernel_plugins/databricks_plugin.py`
- `application/single_app/semantic_kernel_plugins/log_analytics_plugin.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/functions_file_sync.py`
- `application/single_app/static/json/schemas/blob_storage.definition.json`
- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/templates/_plugin_modal.html`
- `application/single_app/config.py`
- `functional_tests/test_action_app_identity_endpoint_hardening.py` (new)
- `functional_tests/test_file_sync_azure_blob_storage.py`

### Code Changes

- Added a shared, dependency-light endpoint validation module with hardcoded allowlists for Azure
  Storage blob and queue hostnames, Cosmos DB accounts, Azure Databricks workspaces, Azure Monitor
  query endpoints, and Microsoft Entra authority hosts, covering the public, US Government, China,
  and Germany clouds. Each validator rejects non-HTTPS schemes, embedded credentials, explicit
  ports, query strings, parameters, fragments, local hostnames, and IP literals, then returns a
  canonical rebuilt origin so only the validated destination reaches an SDK client.
- Enforced each action type's `allowedAuthTypes` inside
  `PluginHealthChecker.validate_plugin_manifest`, the single choke point shared by personal saves,
  group create and patch, admin add and edit, every `test-*-connection` route, and MCP discovery.
  Identity-bound manifests are exempt because their auth type is resolved server-side from a stored
  workspace identity, and that hydration legitimately rewrites `auth.type`.
- Repointed `GET /api/plugins/<type>/auth-types` at the same helper so the modal cannot offer an
  auth type the backend will reject.
- Added endpoint origin validation to the blob storage, queue storage, Cosmos query, Databricks, and
  Log Analytics branches of manifest validation, including the endpoint derived from a blob storage
  connection string.
- Revalidated endpoints immediately before client construction or token acquisition in each plugin,
  so actions stored before this change stop working rather than continuing to leak credentials.
- Constrained Log Analytics custom clouds so `authorityHost` must be a known Entra authority and
  `endpointOverride` must be a known Azure Monitor query endpoint, at save time and at runtime.
- Validated the endpoint in `/api/plugins/test-cosmos-connection`, which builds its own client.
- Widened `blob_storage.definition.json` to `connection_string`, `identity`, and `key`, and extended
  the blob storage modal with an authentication selector plus endpoint and account-key fields,
  including a client-side mirror of the Azure Blob hostname allowlist.
- Refactored `functions_file_sync.py` to source the Azure Storage suffix allowlist and blob hostname
  check from the shared module, removing the duplicated definition introduced in 0.250.068.

## Testing Approach

`functional_tests/test_action_app_identity_endpoint_hardening.py` covers accepted canonical Azure
endpoints for each supported cloud, rejection of hostile, internal, metadata-service, lookalike,
credential-bearing, port-bearing, query-bearing, and fragment-bearing endpoints, cross-service
endpoint mismatches, `allowedAuthTypes` enforcement including the identity-bound exemption and the
legacy Databricks type, Log Analytics custom-cloud constraints, runtime rejection of a stored
hostile manifest, modal wiring, and the File Sync refactor.

`functional_tests/test_file_sync_azure_blob_storage.py` continues to pass, confirming the shared
allowlist preserves the existing File Sync SSRF protections.

## Validation

- Before: a `User`-role caller could save an action with an arbitrary endpoint and application
  managed-identity authentication, and the application would send a token minted for its own
  workload identity to that endpoint.
- After: only canonical Azure service origins reach a credentialed client. Save-time validation
  rejects the configuration, and runtime revalidation blocks actions stored before this change.
- Two pre-existing unrelated test failures were confirmed to exist on the unmodified branch and were
  not introduced here: `test_file_sync_routes_do_not_disclose_exception_details`, and
  `test_blob_storage_action_capabilities.py`, which requires live Azure credentials to import.

## Impact Analysis

Deployments using standard Azure hostnames are unaffected. Azure Private Endpoint configurations
continue to work through the standard account hostname with private DNS resolution. Custom domains,
Azurite and development storage, Azure Stack endpoints, and direct private-link hostnames are
intentionally rejected, matching the precedent set by the Azure Blob File Sync fix in 0.250.068.

## Known Limitations and Follow-Ups

- A non-administrator can still create a personal workspace identity with
  `auth_type='managed_identity'` and bind it to an action. After this change that no longer permits
  arbitrary-origin credential delivery, but it still allows a non-administrator to use the
  application's workload identity against legitimate Azure resources the application can reach.
  Restricting `managed_identity` workspace identities to administrator or global scope is worth a
  separate decision.
- The bundled Bicep grants the web application built-in ARM `Contributor` on the Cosmos DB account
  (`deployers/bicep/modules/setPermissions.bicep`), which widens the blast radius of any leaked
  token. A least-privilege review of that assignment is a separate change; no files under
  `deployers/` were modified here, so `deployers/version.txt` was not incremented.
- The underlying `resource_id` validation defect still requires an upstream fix in
  `Azure/azure-sdk-for-python` across the Blob, Queue, File Share, and Data Lake challenge policies.
  Nothing in this change substitutes for that.
