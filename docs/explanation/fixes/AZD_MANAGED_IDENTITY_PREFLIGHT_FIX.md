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