# Global Model Connection Edit and Delete Recovery (v0.261.392)

Fixed in version: **0.261.392**

Application version: `application/single_app/config.py`.

## Issue and root cause

Administrators could list global AI Connections but receive a 400 response when
editing a connection or a 500 response when deleting one. A saved Custom
connection without an explicit API type could block operations on other
connections, including otherwise valid Azure connections.

The V2 per-connection routes normalized the entire saved list. Persistence then
validated every remaining connection and processed every connection's credentials.
Consequently, deleting one incomplete Custom connection still failed if another
incomplete connection remained. DELETE did not handle the model-validation error
as a client configuration error, so it returned a generic server failure.

Normalization also removed API-version and deployment-name fields from Custom
records with missing or unsupported API types. That could hide information needed
to repair the record when preparing the editor's sanitized response.

## Changes and impact

`application/single_app/route_backend_v2.py` now normalizes only the POST or PATCH
candidate. The persistence helper validates and stages credentials only for that
connection. Unchanged records retain their stored fields and credentials.
Deleting a connection no longer normalizes, validates, or stages credentials for
the remaining connections. Applicable model-validation failures return a safe
400 response rather than a generic 500.

Whole-state embedding compatibility checks and model-default reconciliation still
run. Settings must commit before superseded or deleted credentials are cleaned
up. Storage and Key Vault failures are not converted into successful responses.

`application/single_app/functions_settings.py` retains contract-specific model
identifiers and API-version metadata when a Custom API type is unresolved.
Supported API types keep their existing canonicalization rules. Frontend
responses still remove stored secrets.

This change applies to global V2 per-connection mutations. It does not introduce
a migration, infer API types, or change the scoped connection authorization rules.

## Repair an existing Custom connection

Open the connection's editor and explicitly choose the API contract implemented by
the provider or gateway. For Azure OpenAI, confirm the deployment name and API
version. For OpenAI-compatible contracts, confirm the request model name. Fill any
other required connection fields, then save.

Repair connections individually; another unresolved Custom connection does not
block the save. Alternatively, delete an obsolete connection through its normal
confirmation dialog. An incomplete Custom connection still cannot be saved as a
valid configuration without an explicit, supported API type.

The application does not guess the protocol from a URL, APIM gateway name, or
model family. Metadata that was already removed by a previous saved change must
be supplied again from the provider's actual configuration.

## Validation

`functional_tests/test_model_endpoint_legacy_custom_crud.py` exercises real
application modules and Flask routes in fresh, network-blocked subprocesses,
including optimized Python. Coverage includes mixed valid/unresolved lists,
sequential repair, secret redaction, unchanged-record preservation, invalid
candidate rejection, and failed-delete commit behavior.

`ui_tests/test_admin_custom_connections.py` covers explicit repair through the
real React editor using the existing closed browser fixture, including stable
connection/model IDs and reuse of stored credentials. Existing endpoint,
embedding, Key Vault, and route-policy tests cover related behavior.

Before the fix, unresolved records could block unrelated operations and lose
repair metadata during normalization. After the fix, each global mutation acts
on its requested connection without requiring unrelated records to be repaired.

### Results

- The combined normalization, Custom endpoint, V2 CRUD, embedding-default, and
  mixed-list regression selection passed: **101 tests and 53 subtests**. The
  selection excluded `loader_registration` tests, which exercise unrelated
  Semantic Kernel registration scaffolding.
- The final expanded real-module mixed-list regressions passed in both normal
  and optimized Python: **2 tests**, each exercising all six scenarios.
- Endpoint Key Vault secret-storage regressions passed: **9 tests**.
- The complete Custom connection browser suite passed: **11 tests**.
- Blueprint policy inventory, unauthenticated policy contracts, and policy-test
  coverage passed: **15, 10, and 3 checks**, respectively.
- The React production build passed. No frontend implementation changes were
  required to use the existing explicit API-type selector.

The initial wider run also exposed existing test-harness limitations outside this
fix: Semantic Kernel extraction fixtures omit required symbols, the scoped secret
reference harness lacks a model-client stub export, and the admin diagnostics
fixture expects a Search SDK `deserialize` method absent from the installed SDK.
Those suites are not represented as passing by the targeted results above.
Live Azure access was read-only; the fix has not been deployed by this change.

See [Custom Model Endpoint Provider](../features/CUSTOM_MODEL_ENDPOINT_PROVIDER.md)
for API contracts and configuration requirements.
