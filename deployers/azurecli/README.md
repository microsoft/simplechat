# Simple Chat - Deployment using Azure CLI + PowerShell

[Return to Main](../../README.md)

## Overview

This deployment path uses [deploy-simplechat.ps1](deploy-simplechat.ps1) to provision the core Simple Chat resources with Azure CLI and PowerShell.

This option is useful when you want a script-driven deployment flow without using AZD or Terraform.

It is also useful when you want more script-level control over deployment sequencing and post-deployment recovery steps than the native AZD workflow provides.

For day-to-day work on this deployer, Visual Studio Code and Dev Containers are recommended so the script, repository layout, and Docker build context stay consistent across environments.

## What this deployer does

The Azure CLI deployer provisions the main Simple Chat application resources, including:

- container image build in Azure Container Registry via `az acr build` when enabled
- Resource group
- App Service plan and web app
- Azure Container Registry integration
- Cosmos DB
- Azure OpenAI account creation or reuse
- Azure OpenAI default GPT and embedding model deployments
- Azure AI Search
- Document Intelligence
- Key Vault
- Application Insights and Log Analytics
- Optional Entra security groups

## Private networking support

This deployer now supports the same core private networking flow as the Bicep deployer for the services it provisions.

It can:

- create a new VNet with dedicated App Service integration and private endpoint subnets
- reuse an existing VNet by supplying existing subnet resource IDs
- create private endpoints for Key Vault, Cosmos DB, Azure Container Registry, Azure AI Search, Azure OpenAI, Document Intelligence, Storage, and the App Service
- create private DNS zones automatically
- reuse customer-managed private DNS zones by resource ID
- create or skip private DNS VNet links on a per-zone basis

If you provide only external endpoint information without Azure resource metadata, the script cannot automate Azure OpenAI private endpoint creation for that endpoint.

## Files in this folder

- [deploy-simplechat.ps1](deploy-simplechat.ps1) - Main deployment script
- [publish-simplechat.ps1](publish-simplechat.ps1) - Interactive or parameter-driven ACR publisher that preserves existing pull authentication
- [upgrade-simplechat.ps1](upgrade-simplechat.ps1) - Code-only container upgrade script for existing Azure CLI deployments
- [destroy-simplechat.ps1](destroy-simplechat.ps1) - Cleanup script
- [appRegistrationRoles.json](appRegistrationRoles.json) - App role definition source
- [ai_search-index-group.json](ai_search-index-group.json) - Group search index definition
- [ai_search-index-user.json](ai_search-index-user.json) - User search index definition

## Prerequisites

Before running the deployment:

1. Install Azure CLI
2. Install PowerShell
3. Sign in to the target Azure cloud and subscription
4. Make sure an Azure Container Registry already exists
5. Make sure Azure OpenAI is already available if you plan to reuse an existing instance
6. Make sure you have permission to create resources in the target subscription and tenant
7. If private networking is enabled, make sure you can manage VNets, subnets, private endpoints, private DNS zones, and private DNS VNet links
8. If `param_BuildContainerImageWithAcr = $true`, make sure the target source context contains [application/single_app/Dockerfile](application/single_app/Dockerfile) and the rest of the repository files needed by that Docker build

Platform note:

- Windows users can run the examples directly in PowerShell.
- Linux and macOS users should run the same script with `pwsh`.
- Keep PowerShell variable syntax in PowerShell. This deployer is PowerShell-first, even when Azure CLI commands are part of the workflow.

For Azure Government:

```azurecli
az cache purge
az account clear
az cloud set --name AzureUSGovernment
az login --scope https://management.core.usgovcloudapi.net//.default
az login --scope https://graph.microsoft.us//.default
az account set -s "<subscription-id>"
```

For Azure Commercial:

```azurecli
az cache purge
az account clear
az cloud set --name AzureCloud
az login --scope https://management.azure.com//.default
az login --scope https://graph.microsoft.com//.default
az account set -s "<subscription-id>"
```

## Quick start

1. Open [deploy-simplechat.ps1](deploy-simplechat.ps1)
2. Update the configuration variables near the top of the script
3. Decide whether the script should build the image in ACR by setting `param_BuildContainerImageWithAcr`
4. Run the script from PowerShell

Example:

```powershell
cd deployers/azurecli
.\deploy-simplechat.ps1
```

Linux or macOS example:

```bash
cd deployers/azurecli
pwsh ./deploy-simplechat.ps1
```

## Default capacity choices

The Azure CLI deployer defaults to Azure AI Search Standard S1 with standard Semantic Ranker and Cosmos DB provisioned throughput using dedicated autoscale throughput on each SimpleChat container. These defaults are intended for reliable workspace search, document upload processing, and semantic retrieval after deployment while avoiding the 25-container limit for shared-throughput Cosmos databases.

For a short-lived MVP or evaluation environment, you can edit the variables near the top of [deploy-simplechat.ps1](deploy-simplechat.ps1) to use `Serverless` Cosmos DB or `free` Azure AI Search/Semantic Ranker. Those settings are intentionally opt-in because Free Search and serverless Cosmos DB have limits that can surface as search, indexing, or quota problems under real usage.

## Interactive container publishing

Implemented in deployer **1.0.32**, alongside application **0.261.042** in
`application/single_app/config.py`. This deployment-tooling change increments
`deployers/version.txt` independently of the application version. Refs #1518.
Updated in deployer **1.0.35** with webhook-based publishing for the beta/dev
targets. The shared image prompt and dev target were added in **1.0.34**.
Application version remains **0.261.042**.

Use [publish-simplechat.ps1](publish-simplechat.ps1) for routine updates to an
existing Linux single-container App Service. It uploads local source and builds
and pushes in ACR Tasks. By default, it updates the app to the resolved digest.
With `-UseWebhook`, it instead verifies that the app already uses the requested
tag and that an enabled ACR push webhook matches, then leaves the image setting
unchanged for the webhook to refresh. No local Docker daemon or image push is
needed. Unlike the legacy upgrade script below, it does not enable ACR admin
credentials, retrieve passwords, or change your default cloud/subscription.

Prerequisites: PowerShell 7.2+, Azure CLI, Git, and an authenticated `az login`
session in the desired cloud. The account needs subscription/resource discovery,
ACR task execution and image metadata access, and App Service configuration
read/write permissions. The app must already be configured to pull from the chosen
registry. Prefer managed identity; this script preserves existing authentication
and never grants roles or opens network access.

From the repository root:

```powershell
pwsh -NoProfile -File ./deployers/azurecli/publish-simplechat.ps1
```

Choose a subscription (displayed with ID and tenant), an ACR, and a Linux web app
from numbered menus. Use `q` to cancel. The resource group is resolved from the
selected app, and the repository defaults to its current image repository.
Review the displayed target/image and confirm before any build or update. Local
uncommitted files require a separate approval. Build-only mode prompts for the
image repository instead of a web app.

In VS Code, run **Tasks: Run Task**, then choose:

- **SimpleChat: Publish container (interactive)** for resource selection.
- **SimpleChat: Preview container publish (interactive)** for a read-only preview.
- **SimpleChat: Publish beta container (confirm)** for the prefilled beta target
	using its ACR webhook.
- **SimpleChat: Publish dev container (confirm)** for the prefilled dev target
	using its ACR webhook.

Every task first prompts for a `repository:tag` image reference, defaulting to
`simplechat:latest`. Enter, for example, `simplechat:dev-20260925` to use a distinct
tag. Omit the registry hostname. Dirty-source approval and final confirmation are
still required for publishing; the preview task never mutates resources. The beta
and dev tasks require the app to already use that exact image tag and an enabled
matching ACR push webhook. Their configured default is `simplechat:latest`; entering
a different tag fails preflight before the build unless the app and webhook have
already been set up for that tag.

| Prefilled target | Subscription | Resource group | ACR | App Service |
| --- | --- | --- | --- | --- |
| Beta | `8a60416d-813d-4904-b115-2cebaaf63fea` | `simplechat-2026beta-rg` | `simplechat2026betaacr` | `simplechat-2026beta-app` |
| Dev | `8c7e0020-34d5-4be4-ac62-5c744df2700b` | `simplechat-2026dev-rg` | `simplechat2026devacr` | `simplechat-2026dev-app` |

The dev subscription is named `ME-MngEnvMCAP522061-paullizer-3`. Tasks use explicit
IDs rather than changing the CLI's active subscription. All tasks invoke the same
script. Shared tasks live in `.vscode/tasks.json`; other local VS Code settings
remain ignored.

### Explicit parameters

Omitted resource selections prompt unless `-NonInteractive` is supplied. This
example targets the beta app and deliberately includes reviewed local changes:

```powershell
pwsh -NoProfile -File ./deployers/azurecli/publish-simplechat.ps1 `
		-SubscriptionId 8a60416d-813d-4904-b115-2cebaaf63fea `
		-AcrName simplechat2026betaacr `
		-WebAppName simplechat-2026beta-app `
		-ImageName simplechat:latest `
		-UseWebhook -NonInteractive -Yes -AllowDirty
```

For a preflight instead, replace `-Yes -AllowDirty` with `-WhatIf`.
`-WhatIf` performs discovery and local checks but no upload, build, image update,
or confirmation prompt. It does not prove build permission or runtime health.

To publish `simplechat:latest` to dev with explicit parameters:

```powershell
pwsh -NoProfile -File ./deployers/azurecli/publish-simplechat.ps1 `
	-SubscriptionId 8c7e0020-34d5-4be4-ac62-5c744df2700b `
	-ResourceGroupName simplechat-2026dev-rg `
	-AcrName simplechat2026devacr `
	-WebAppName simplechat-2026dev-app `
	-ImageName simplechat:latest `
	-UseWebhook -NonInteractive -Yes -AllowDirty
```

Only pass `-AllowDirty` after reviewing the local changes included in the upload.
Direct script calls without an image tag still generate a unique timestamp/revision
tag; only the VS Code task prompt defaults to `simplechat:latest`.

| Parameter | Behavior |
| --- | --- |
| `-SubscriptionId`, `-AcrName`, `-WebAppName` | Skip corresponding menus; validate the supplied targets against accessible resources. |
| `-ResourceGroupName` | Optionally restrict web-app discovery. The ACR may be in a different resource group. |
| `-ImageName` | Supply `repository:tag`, such as `simplechat:latest`. Cannot be combined with `-ImageRepository` or `-ImageTag`. |
| `-ImageRepository` | Override the current app's repository, or supply the repository for build-only runs. |
| `-ImageTag` | Override the generated UTC timestamp/revision/dirty-state tag. `latest` is allowed; publishing replaces any existing tag with that name. |
| `-Slot` | Update the named existing deployment slot. Without it, the target is the production slot. |
| `-NonInteractive` | Fail on missing required selections; never use selection prompts. |
| `-Yes` | Approve build/update without the final prompt. Required for noninteractive mutations. |
| `-AllowDirty` | Include reviewed uncommitted/local source files without the separate dirty-source prompt. |
| `-BuildOnly` | Build and resolve the digest without accessing an App Service. |
| `-SkipBuild` | Deploy an existing repository/tag; requires a tag in `-ImageName` or an explicit `-ImageTag`. |
| `-UseWebhook` | Build and push without changing App Service configuration. Requires a fresh build, an exact match with the app's configured image tag, and an enabled ACR push webhook with a matching scope. Does not verify webhook delivery or app health. |
| `-WhatIf` | Read-only preflight. |

### Safety and recovery

- The fixed context is the repository root, regardless of the current terminal
	directory. The root `.dockerignore` excludes environment files, caches,
	sessions, and local tooling. Review any custom files included under
	`application/single_app` and `docker-customization`; never put secrets in them.
- Builds include local changes when approved, not just the committed remote
	branch. The printed revision is the base commit, not a reproducible identifier
	for a dirty tree. Commit reviewed source for reproducible releases.
- Build and digest verification failures stop subsequent steps. The task default
	replaces `latest`; webhook-mode apps stay configured to that mutable tag. The
	ordinary mode pins App Service to the new ACR run's digest, not a later lookup of
	the tag. `-UseWebhook` avoids the configuration update, but a mutable tag is not a
	rollback point: prefer the ordinary unique-tag/digest mode when simple rollback
	matters. `-SkipBuild` resolves the existing tag once.
- Sidecar, Compose, Windows, and code-based apps fail preflight before building.
	An app using a different registry is also rejected; configure and verify pull
	authentication separately rather than changing credentials during publishing.
- The script checks the saved image reference, not the running app. Wait for
	startup, inspect App Service logs, and verify the application version and
	authenticated workflows before accepting a rollout. No deployment slot is
	created and no slot swap is performed.
- In ordinary digest-update mode, the previous image reference is printed before
	updating and can be restored with `az webapp config set --subscription <id>
	--resource-group <group> --name <app> --linux-fx-version
	"DOCKER|<previous-image>" --output none`, including `--slot <slot>` when
	applicable. In webhook mode, `latest` is overwritten; retaining a previous
	version requires a separate tag or other preserved digest. No automatic rollback
	occurs.

If ACR reports `failed to download context`, the Docker build has not begun. The
CLI uploads its own local context, avoiding the extension's upload path, but
expired upload URLs, registry networking, or permissions can still fail. Check the
ACR run details and approved network/task access; do not enable admin passwords
or public access as an automatic workaround.

### Build logs and completion

The publisher uses `az acr build --no-logs` without `--no-wait`. Azure CLI polls
the remote run until completion, without streaming build output through the local
console. This avoids Windows `cp1252`/Colorama failures when logs contain Unicode
characters. `--only-show-errors` alone suppresses CLI warnings, not build logs.

The publisher requires `Succeeded` plus the matching output image and a valid
digest before proceeding. The ordinary mode then updates and verifies the App
Service image. Webhook mode leaves that configuration unchanged and relies on the
ACR push notification; check the webhook event status and app startup separately.
The publisher prints the run ID and status when the command returns. While waiting,
inspect the ACR run in the Azure portal for logs or progress. No separate script
polling loop or automatic build retry is used.

A previous CLI encoding error does not prove the remote build failed or stopped.
Check its ACR run before starting another build. No authentication or registry
network settings are changed by this workaround.

### Validation

Run `pwsh -NoProfile -File ./functional_tests/test_azurecli_publish_script.ps1`
for offline behavioral tests. They replace Azure CLI, Git, and prompts with scoped
fakes and never bootstrap the application or contact Azure. The beta target also
passed a real read-only CLI preflight on 2026-09-23; no build/deployment was run.
The deployer 1.0.35 offline checks cover task defaults and beta/dev webhook wiring,
webhook tag/scope preflight, skipped config updates, log suppression, failed or
incomplete runs, invalid image metadata, and ordinary-mode digest pinning when
`latest` changes concurrently. No live build or dev deployment was performed for
this update.

## Legacy code-only upgrade flow

For an existing Azure CLI deployment where infrastructure is unchanged, use `upgrade-simplechat.ps1` instead of rerunning the full deployer.

This legacy flow enables ACR admin credentials. Prefer the interactive publisher
above when the app already has working registry pull authentication.

This script:

- builds the requested image tag in ACR with `az acr build`
- updates the existing App Service container image with `az webapp config container set`
- verifies the App Service now points to the requested image
- restarts the web app so the new image is pulled

Example with explicit resource names:

```powershell
cd deployers/azurecli
./upgrade-simplechat.ps1 `
	-AcrName registrysimplechatprod `
	-ImageName simplechat:2026-04-29_01 `
	-ResourceGroupName sc-contoso-prod-rg `
	-WebAppName contoso-prod-app
```

Example using the same base-name and environment naming convention as `deploy-simplechat.ps1`:

```powershell
cd deployers/azurecli
./upgrade-simplechat.ps1 `
	-AcrName registrysimplechatprod `
	-ImageName simplechat:2026-04-29_01 `
	-BaseName contoso `
	-Environment prod
```

This flow is the Azure CLI deployer's PowerShell-first equivalent to a normal container-only `azd deploy`, without invoking the AZD post-configuration Python path.

If the image already exists in ACR and you only want App Service to move to that tag, add `-SkipAcrBuild`.

## Configuration areas to review

The script contains editable configuration variables for:

- `globalWhichAzurePlatform`
- `paramTenantId`
- `paramLocation`
- `paramEnvironment`
- `paramBaseName`
- `ACR_NAME`
- `IMAGE_NAME`
- `param_BuildContainerImageWithAcr`
- `param_DockerfilePath`
- `param_DockerBuildContextPath`
- `param_PublishLatestImageTag`
- existing Azure OpenAI resource settings
- `param_DeployAzureOpenAiModels`
- `param_AzureOpenAiDeploymentType`
- Azure OpenAI GPT and embedding model names, versions, deployment names, and capacities
- optional Entra security group creation
- `param_EnablePrivateNetworking`
- `param_ExistingVirtualNetworkId`
- `param_ExistingAppServiceSubnetId`
- `param_ExistingPrivateEndpointSubnetId`
- `param_PrivateNetworkAddressPrefixes`
- `param_AppServiceIntegrationSubnetAddressPrefixes`
- `param_PrivateEndpointSubnetAddressPrefixes`
- `param_PrivateDnsZoneConfigs`

Review those values before running the script.

## Azure OpenAI deployment types and quota handling

The Azure CLI deployer can now create the default GPT and embedding model deployments for the Azure OpenAI account it creates or reuses. The Azure OpenAI account still uses the Cognitive Services account SKU, but the model deployments themselves use `Standard`, `DatazoneStandard`, or `GlobalStandard`.

For Azure Commercial, leave `param_AzureOpenAiDeploymentType` blank to be prompted during deployment, or set it explicitly in the script before you run it. For Azure Government, the script automatically uses `Standard`.

If a model deployment fails because of quota or regional availability, the script lets you retry that deployment with a different deployment type. If the retry still fails, request additional quota, lower the configured capacity, or set `param_DeployAzureOpenAiModels = $false` and reuse existing Azure OpenAI deployments instead.

Default model behavior:

- GPT deployment defaults to `gpt-4o`
- GPT model version defaults to `2024-11-20` in Azure Commercial and `2024-05-13` in Azure Government
- Embedding deployment defaults to `text-embedding-3-small` in Azure Commercial and `text-embedding-ada-002` in `usgovvirginia`
- Deployment capacities default to `100` for GPT and `80` for embeddings

After the infrastructure deployment completes, review the resulting Azure OpenAI deployments in the Simple Chat UI under `Admin Settings` > `AI Models` > `Chat Model` and `Embeddings Configuration`. For the full manual path, see `docs/setup_instructions_manual.md` and `docs/admin_configuration.md`.

## Container build behavior

By default, the Azure CLI deployer now builds the container image in ACR instead of assuming you already built and pushed it locally.

Default behavior:

- `param_BuildContainerImageWithAcr = $true`
- the script submits the build to ACR Tasks with `az acr build`
- the script uses [application/single_app/Dockerfile](application/single_app/Dockerfile)
- the build context defaults to the repository root via `..\..`

If you want to skip the image build and deploy an image that already exists in ACR:

- set `param_BuildContainerImageWithAcr = $false`
- set `IMAGE_NAME` to the repository and tag you want the App Service to pull

Example:

```powershell
$IMAGE_NAME = "simplechat:2026-03-11_main_42"
$param_BuildContainerImageWithAcr = $true
$param_DockerfilePath = "application/single_app/Dockerfile"
$param_DockerBuildContextPath = "..\.."
```

## Private DNS questions to answer before running

If `param_EnablePrivateNetworking = $true`, decide the following before you run the script:

- Will the script create private DNS zones, or will you reuse existing zones?
- If you reuse zones, what are the full resource IDs for those zones?
- Should the script create the VNet links, or are those links already managed by central networking?

Supported zone keys in `param_PrivateDnsZoneConfigs`:

- `keyVault`
- `cosmosDb`
- `containerRegistry`
- `aiSearch`
- `blobStorage`
- `cognitiveServices`
- `openAi`
- `webSites`

Example:

```powershell
$param_PrivateDnsZoneConfigs = @{
	openAi = @{
		zoneResourceId = "/subscriptions/<sub>/resourceGroups/<dns-rg>/providers/Microsoft.Network/privateDnsZones/privatelink.openai.azure.com"
		createVNetLink = $false
	}
	webSites = @{
		zoneResourceId = "/subscriptions/<sub>/resourceGroups/<dns-rg>/providers/Microsoft.Network/privateDnsZones/privatelink.azurewebsites.net"
	}
}
```

## Post-deployment tasks

After deployment, you should still complete the manual steps described in [deploy-simplechat.ps1](deploy-simplechat.ps1), including:

- App Service authentication provider setup
- Entra admin consent for Graph permissions
- Azure OpenAI model deployment review or existing-endpoint configuration
- Azure AI Search index deployment
- App settings review in the web UI
- Security group membership assignment, if used

## When to use another deployer

Choose a different deployer when:

- You want the broadest deployment coverage and the most mature deployment path → use [../bicep/README.md](../bicep/README.md)
- You want Terraform-managed infrastructure → use [../terraform/ReadMe.md](../terraform/ReadMe.md)
- You want an AZD-first deployment experience → use [../bicep/README.md](../bicep/README.md)

## Cleanup

To remove a deployment created with this folder, review and run [destroy-simplechat.ps1](destroy-simplechat.ps1).

Cleanup behavior:

- The destroy script deletes the Simple Chat deployment resource group.
- That removes private endpoints, private DNS zones, and the deployment VNet only when those resources were created inside that deployment resource group.
- If the deployment reused an existing VNet, existing subnets, or customer-managed private DNS zones outside the deployment resource group, those shared resources are not deleted.
- The destroy script also removes the Entra application registration and the Simple Chat security groups created by the Azure CLI deployer.

## Runtime Startup Behavior

- This deployer configures Azure App Service to run the published **container image**.
- Gunicorn is already started by the container entrypoint in `application/single_app/Dockerfile`.
- You do **not** need to add anything to App Service Stack Settings Startup command when using this deployer.
- If you manually switch to a native Python App Service deployment instead of containers, deploy the `application/single_app` folder and use:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```