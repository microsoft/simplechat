# AZD Managed Identity Preflight Fix

Fixed in version: **0.242.057**
Deployer version: **1.0.15**

## Issue Description

When an AZD deployment selected `managed_identity`, the deployment could proceed until Azure role-assignment creation failed or, in some script paths, continue after warnings that were easy to miss. That made it possible for deployment output to look successful while the application identity did not have the RBAC access required at runtime.

## Root Cause Analysis

Managed identity deployment depends on Azure RBAC assignments for the App Service identity and related resources. The deployer created those assignments during provisioning, but the preprovision validation did not check whether the signed-in Azure identity could create role assignments or custom role definitions before longer-running deployment work began.

## Technical Details

Files modified:

- `deployers/bicep/validate_azd_prerequisites.py`
- `deployers/bicep/README.md`
- `deployers/version.txt`
- `application/single_app/config.py`
- `functional_tests/test_azd_managed_identity_preflight.py`

Code changes summary:

- Added a managed identity preflight check to the AZD preprovision script.
- The check only runs when `AUTHENTICATION_TYPE` resolves to `managed_identity`.
- The check validates effective Azure permissions for `Microsoft.Authorization/roleAssignments/write` and `Microsoft.Authorization/roleDefinitions/write` at the target deployment scopes.
- The deployer now fails fast if `CONFIGURE_APPLICATION_PERMISSIONS=false` is paired with managed identity automation.
- Failure guidance tells users to rerun with an Azure identity that has Owner, Role Based Access Control Administrator, or equivalent custom permissions, or to switch to key-based authentication with `azd env set AUTHENTICATION_TYPE key` if that model is acceptable.
- Updated `application/single_app/config.py` to version `0.242.057` and `deployers/version.txt` to deployer version `1.0.15`.

## Validation

Functional coverage is provided by `functional_tests/test_azd_managed_identity_preflight.py`.

Before the fix, managed identity permission gaps could surface late or be hidden behind postprovision warnings. After the fix, managed identity deployments stop during preprovision with a clear explanation and remediation path.

## Post-Provision Reliability (0.261.028)

Fixed/Implemented in version: **0.261.028**, tracked in
`application/single_app/config.py`; deployer version **1.0.31** in `deployers/version.txt`.

The former postprovision hook always retrieved Cosmos keys, even for managed-identity
deployments. A disabled-local-auth account therefore failed its probe, which was
misreported as a firewall propagation delay. Its CLI firewall lookup also used the
ARM response path `properties.ipRules` against the CLI's flattened response, risking
replacement of existing rules with a runner-only rule.

Both platform hooks now use the credential-aware `deployment_cosmos.py` path through
`postconfig.py`. It never changes network rules, never falls back from Entra to keys,
and distinguishes network errors from authentication or RBAC failures. Windows fallback
lookups are explicitly bound to `AZURE_ENV_NAME`, including the subscription alias.
The POSIX role script also uses the deployment subscription rather than the CLI default.

`deployment_configuration.py` removes the duplicate Redis-writing paths and routes
settings writes through the app's `AppSettingsStore`, preserving concurrent unrelated
settings and publishing the shared cache with the existing fenced-write protocol.
Publication failures remain failures, even if the Cosmos write has already completed.
The runner must have Redis data access when the app uses Redis; automatic migration
between active cache configurations is intentionally refused.

The same configuration step now creates only missing Search indexes using the app's
JSON definitions. Existing indexes are never updated or deleted by the deployer.

Offline regression coverage lives in `test_deployment_cosmos_access.py` and
`test_deployment_configuration.py`, including Windows and POSIX hook execution,
explicit environment selection, key-disabled accounts, concurrency, cache publication
failure, first-run settings creation, preserved external caches and index-creation races.
No tenant exemptions or production resource changes are required to run these tests.

Tracked in [#1489](https://github.com/microsoft/simplechat/issues/1489), implemented by
[PR #1488](https://github.com/microsoft/simplechat/pull/1488). The new hook implementation
has offline regression coverage; Azure validation with an appropriately authorized
deployment runner remains a follow-up before calling the cloud workflow verified.