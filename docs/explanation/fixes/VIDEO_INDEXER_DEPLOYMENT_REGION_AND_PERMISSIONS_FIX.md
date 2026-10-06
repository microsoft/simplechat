# Video Indexer Deployment Region and Permissions Fix (v0.261.260)

## Overview

The deployers can now place Azure Video Indexer in a supported region other than the application region, and they grant the App Service identity the role SimpleChat needs to request Video Indexer access tokens. The azd preprovision hook now stops before provisioning when Video Indexer is unavailable in the chosen region. Post-provision configuration no longer erases a manually configured Video Indexer account.

Fixed in version: **0.261.260** (deployer version **1.0.33**)

Dependencies: Azure Developer CLI hooks, Bicep, Terraform with azapi 2.x, the Azure CLI deployer, and the Azure Video Indexer ARM API (`2025-04-01` in Azure Commercial, `2024-01-01` in Azure Government).

The application version was updated in `application/single_app/config.py` from `0.261.259` to `0.261.260`, and the deployer version in `deployers/version.txt` from `1.0.32` to `1.0.33`.

## Issue Description

In an environment deployed to North Central US, **Admin Settings > AI Video Intelligence** showed *Needs configuration*. The subscription, resource group, and location were filled in, but the account name and account ID were blank, and no Video Indexer account existed. The first deployment ran with `deployVideoIndexerService=false`. A later attempt with it set to `true` failed Azure Resource Manager validation: Video Indexer is not offered in North Central US, and the deployer had no way to place it elsewhere.

## Root Cause

Four gaps combined:

1. Video Indexer always used the deployment `location`. There was no override and no preflight check, so an unsupported region failed the entire deployment.
2. `postconfig.py` gated only `enable_video_file_support` on a deployed account. It always wrote the resource group, subscription, and deployment location. It also wrote the account name and ID from deployment outputs, which are empty when Video Indexer is not deployed. Every provision without Video Indexer therefore blanked a manual configuration and reset its location, leaving the half-filled state described above.
3. No deployer granted the App Service identity a role on the Video Indexer account. SimpleChat calls the ARM `generateAccessToken` API with that identity in every authentication mode, so a deployer-created account rejected video processing until an administrator added Contributor by hand.
4. Terraform passed `azapi_resource.video_indexer[0].output` through `jsondecode()`. azapi 2.x, which `main.tf` requires, returns `output` as an object rather than a JSON string.

## Technical Details

### Files Modified

- `deployers/bicep/main.bicep`, `deployers/bicep/main.json` (regenerated), and `deployers/bicep/main.parameters.json`
- `deployers/bicep/modules/videoIndexer.bicep`
- `deployers/bicep/modules/setVideoIndexerPermissions.bicep` (new)
- `deployers/bicep/modules/setPermissions.bicep` and `deployers/bicep/modules/setNativeWebAppPermissions.bicep`
- `deployers/bicep/postconfig.py` and `deployers/bicep/validate_azd_prerequisites.py`
- `deployers/azure.yaml`
- `deployers/terraform/main.tf`
- `deployers/azurecli/deploy-simplechat.ps1`
- `deployers/version.txt` and `application/single_app/config.py`
- `deployers/bicep/README.md`, `deployers/terraform/ReadMe.md`, `docs/deploy/manual/provision-azure-resources.md`, and `docs/admin/knowledge.md`
- `functional_tests/test_video_indexer_deployment_region_permissions.py` (new) and `functional_tests/test_deployment_configuration.py`

### Code Changes

- **Region selection.** Each deployer accepts a Video Indexer region that defaults to the deployment region: `videoIndexerLocation` in Bicep (azd `VIDEO_INDEXER_LOCATION`), `param_video_indexer_location` in Terraform, and `$param_VideoIndexerLocation` in the Azure CLI deployer. When that region differs from the deployment region, the deployer also creates `<appName><environment>vi`, a Standard general-purpose v2 storage account in the Video Indexer region. Under private networking, its firewall admits trusted Azure services and denies other traffic. Bicep reports the account's normalized region as `var_videoIndexerLocation`.
- **Preflight.** `validate_azd_prerequisites.py` compares the target region with the regions returned by `az provider show --namespace Microsoft.VideoIndexer`. If Video Indexer is unavailable there, it prints the supported regions and the `azd env set VIDEO_INDEXER_LOCATION` command, then fails. If the region list cannot be read, it only warns, because Azure Resource Manager still validates the region.
- **Application access.** The App Service system-assigned identity receives **Video Indexer Account Contributor** in Azure Commercial and **Contributor** in Azure Government and custom clouds. The grant does not depend on `authenticationType`. In Bicep, `setVideoIndexerPermissions.bicep` holds this grant and the Video Indexer storage grant, which keeps its earlier assignment name. The optional native Python app receives the same role. Terraform and the Azure CLI deployer add the same grant; the Azure CLI deployer checks for an existing assignment first.
- **Settings.** `postconfig.py` writes every Video Indexer setting only when the deployment created the account, and records the account's own region.
- **Terraform.** The Video Indexer identity is read from `azapi_resource.video_indexer[0].output` directly. New outputs report the account name, account ID, and region for Admin Settings.

## Testing And Validation

- `python functional_tests/test_video_indexer_deployment_region_permissions.py` passed 10 of 10 tests. They cover the Bicep source and generated ARM, Terraform, the Azure CLI deployer, preflight behavior for unsupported, overridden, disabled, and failed-lookup cases, and the version.
- `python -m pytest functional_tests/test_video_indexer_deployment_region_permissions.py functional_tests/test_deployment_configuration.py` passed 43 tests. Against the previous `postconfig.py`, the two new postconfig cases fail: a manual resource group is overwritten, and the deployment region is written instead of the account region.
- Twelve related deployer and Video Indexer test files report the same 11 failures before and after this change. All of them are pre-existing exact-version checks or checks unrelated to Video Indexer deployment.
- `az bicep build` with Bicep 0.44.1, the version that generated `main.json`, reported no warnings. `terraform fmt -check` passed, and `terraform validate` passed with Terraform 1.12.2 and the required providers. The Azure CLI deployer parses without errors.
- The fixed modules were applied to the affected North Central US environment. `what-if` showed only new resources. The deployment created a Video Indexer account in Central US with its own storage account, plus the application, storage, and Azure OpenAI role assignments. ARM `generateAccessToken` and a Video Indexer API call that used the new account ID and `centralus` both succeeded.

## Impact Analysis

### Before

- Enabling Video Indexer in a region without it failed the whole deployment, and administrators had no way to place Video Indexer elsewhere.
- A deployer-created Video Indexer account could not process video until an administrator granted Contributor manually.
- Every provision without Video Indexer erased the Video Indexer account name and ID and reset the location.

### After

- Video Indexer can run in any region that offers it while the rest of SimpleChat stays in its region, and azd explains unsupported regions before provisioning.
- Deployer-created accounts work without manual role assignments, using the least-privilege role in Azure Commercial.
- Manually configured Video Indexer settings survive later provisioning runs.

## Known Limitations

- An existing Video Indexer account cannot move regions. Set the region before the first deployment that enables Video Indexer.
- In Azure Government and custom clouds, a manual Contributor assignment at the account scope duplicates the new assignment and returns `RoleAssignmentExists`. Adopt that assignment as the deployer READMEs describe.
- Speech settings in `postconfig.py` are still written on every run, even when Speech is not deployed. This change does not alter that behavior.
