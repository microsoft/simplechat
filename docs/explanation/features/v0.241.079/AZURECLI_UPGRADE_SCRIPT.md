# Azure CLI Upgrade Script

Version: 0.241.079

Fixed/Implemented in version: **0.241.079**

Dependencies: `deployers/azurecli/upgrade-simplechat.ps1`, `deployers/azurecli/README.md`, `docs/reference/deploy/azurecli_powershell_deploy.md`, `docs/how-to/upgrade_paths.md`, `functional_tests/test_azurecli_upgrade_script.py`

## Overview

This feature adds a standalone Azure CLI PowerShell upgrade script for SimpleChat container deployments.

The new script provides a code-only rollout path for the Azure CLI deployer. It builds the updated SimpleChat image in Azure Container Registry with ACR Tasks, updates the existing Azure App Service container configuration to that image, and restarts the site so the new container is pulled.

## Technical Specifications

The new `upgrade-simplechat.ps1` script is intentionally narrower than `deploy-simplechat.ps1`.

It does not provision or reconfigure the full Azure dependency stack. Instead, it focuses on the day-two operational path that is closest to `azd deploy` for a container-based App Service deployment.

The script supports two targeting modes:

- explicit target selection with `-ResourceGroupName` and `-WebAppName`
- derived target names with `-BaseName` and `-Environment`, matching the default `deploy-simplechat.ps1` naming convention of `sc-<base>-<environment>-rg` and `<base>-<environment>-app`

The rollout sequence is:

1. verify Azure CLI authentication and optional subscription selection
2. verify the target Azure Container Registry and enable the admin user if needed to match the existing Azure CLI deployer model
3. build the requested image tag in ACR with `az acr build`
4. update App Service container settings with `az webapp config container set`
5. verify that the web app container configuration now points to the requested image
6. restart the web app with `az webapp restart`

## Usage Instructions

Run the script from `deployers/azurecli`.

Example using explicit resource names:

```powershell
./upgrade-simplechat.ps1 `
    -AcrName registrysimplechatprod `
    -ImageName simplechat:2026-04-29_01 `
    -ResourceGroupName sc-contoso-prod-rg `
    -WebAppName contoso-prod-app
```

Example using deployer-style name derivation:

```powershell
./upgrade-simplechat.ps1 `
    -AcrName registrysimplechatprod `
    -ImageName simplechat:2026-04-29_01 `
    -BaseName contoso `
    -Environment prod
```

Optional switches:

- `-SkipAcrBuild` when the image tag is already present in ACR and only the App Service needs to move to it
- `-Slot <name>` to target a deployment slot instead of production

## Testing And Validation

Coverage for this feature includes:

- `functional_tests/test_azurecli_upgrade_script.py` for script and documentation wiring
- direct script syntax validation with PowerShell parsing
- focused functional execution of the new regression test

Known limitation:

- the upgrade script follows the current Azure CLI deployer’s ACR admin-credential model for App Service container pulls; it does not yet switch existing web apps to managed-identity-based ACR pull.
