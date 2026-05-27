# AZD Windows Hook Environment and Auth Diagnostic Fix - Version 0.241.101

## Header Information

**Issue description:** On Windows, `azd deploy` could fail in the `predeploy` hook with `Unable to resolve resource group from var_rgName, Cosmos DB, or Web App` even when the active azd environment contained `var_rgName`, Cosmos DB, and Web App outputs.

**Root cause analysis:** The Windows hook scripts read deployment outputs from `$env:var_*` process environment variables. In this azd execution path, the values were available through `azd env get-value` but were not present in the hook process environment, so the resolver treated the resource group, Cosmos DB account, and Web App name as missing. A second failure mode occurred when Azure CLI returned `Need user interaction to continue` for management-plane lookups; the hook suppressed that stderr and fell through to the same generic resource-group error.

**Fixed in version:** **0.241.101**

**Related version updates:** `application/single_app/config.py` was updated to `0.241.101`, and `deployers/version.txt` was updated to `1.0.9` for the deployer workflow change.

## Technical Details

**Files modified:**

- `deployers/azure.yaml`
- `deployers/version.txt`
- `application/single_app/config.py`
- `functional_tests/test_azd_windows_hook_environment.py`

**Code changes summary:** The Windows `postprovision`, `predeploy`, and `postup` hooks now call an `Import-AzdHookEnvironment` helper before subscription or resource-group resolution. The helper keeps existing process environment values intact, and hydrates missing values from the active azd environment through `azd env get-value`. Resource lookup commands now preserve Azure CLI error output and detect interactive-auth failures so the hook can tell the operator to run `az login --scope "https://management.core.windows.net//.default"` instead of reporting a missing resource group.

**Testing approach:** Added a functional regression test that validates the affected Windows hooks import required `AZURE_SUBSCRIPTION_ID` and `var_*` values before calling the resource resolver or deployer commands, and preserve Azure CLI auth failure output for diagnostics.

**Impact analysis:** Windows `azd deploy` can now resolve stored deployment outputs consistently when the values exist in `.azure/<environment>/.env` but are not exposed as process environment variables. POSIX hook behavior is unchanged.

## Validation

**Test results:** `functional_tests/test_azd_windows_hook_environment.py` validates the hook hydration and auth diagnostic wiring.

**Before/after comparison:** Before the fix, Windows predeploy could fail before stopping the Web App or starting the ACR build because `$env:var_rgName` and fallback resource identifiers were empty, or because Azure CLI needed interactive management-plane authentication and the hook hid that message. After the fix, the hook hydrates deployment values from azd environment storage before resource resolution and reports Azure CLI interactive-auth requirements directly.

**User experience improvements:** Re-running `azd deploy` from `deployers` should no longer require manually exporting `var_rgName` or related deployment outputs in the PowerShell session.