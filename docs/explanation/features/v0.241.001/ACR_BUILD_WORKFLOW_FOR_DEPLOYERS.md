# ACR Build Workflow for Deployers

Fixed/Implemented in version: **0.237.025**

## Overview

This update aligns the deployment experience around Azure Container Registry Tasks so deployers can publish the application image in ACR without requiring a local Docker daemon.

## Scope

This change affects:

- AZD/Bicep deployment flow in `deployers/azure.yaml`
- Azure CLI deployment guidance in `deployers/azurecli/deploy-simplechat.ps1` and `deployers/azurecli/README.md`
- Azure environment bootstrap guidance in `deployers/Initialize-AzureEnvironment.ps1`
- Terraform deployment guidance in `deployers/terraform/ReadMe.md`

## Technical Details

### AZD / Bicep

The `predeploy` hook in `deployers/azure.yaml` now uses:

- `az acr build`
- `application/single_app/Dockerfile`
- a timestamped tag and `latest`

This removes the previous dependency on:

- local `docker build`
- local `docker tag`
- local `docker push`

### Azure CLI

The Azure CLI deployer already supports building the image in ACR through configurable settings in `deploy-simplechat.ps1`.

#### Interactive publisher (deployer 1.0.32)

Implemented in version: **deployer 1.0.32**, alongside application **0.261.042**
in `application/single_app/config.py`. Deployment-only version tracking uses
`deployers/version.txt`; the application version is unchanged. Refs #1518.

`deployers/azurecli/publish-simplechat.ps1` adds numbered subscription, registry,
and web-app selection for existing Linux single-container App Service deployments.
Every selection also accepts an explicit parameter, and `-NonInteractive -Yes`
supports automation. `-WhatIf` provides a read-only preflight. VS Code tasks invoke
the same script for interactive selection, preview, or prefilled beta/dev targets.

Updated in version: **deployer 1.0.35**. Every task now prompts for an image
reference defaulting to `simplechat:latest`; `-ImageName` supplies the same
`repository:tag` value for parameter-driven runs. The script still generates a
unique tag when none is supplied directly. Builds use `--no-logs` with Azure CLI's
built-in completion polling to avoid Windows Unicode console errors. This update
does not change the application version in `config.py`.

The beta and dev tasks use `-UseWebhook`: they verify an enabled ACR push hook
matching the requested tag and ensure the app is already configured to that tag.
They leave App Service configuration unchanged so the webhook can restart the app
and pull the pushed image. Webhook delivery and startup health still require
verification. Ordinary publisher runs continue to set and verify a digest-pinned
image reference.

The publisher uploads the local repository-root context to ACR Tasks and requires
approval for uncommitted source. Ordinary runs deploy a resolved image digest;
webhook-mode runs preserve the existing tag. It preserves
the CLI default subscription/cloud and existing app settings/pull authentication.
Unlike the legacy upgrade path, it never enables registry admin access or reads
registry passwords. Failed builds cannot update the app. Successful ordinary
builds use their own run output digest rather than looking up a mutable tag, so
another build replacing `latest` does not change the deployed artifact.
Webhook-mode tasks deliberately keep the mutable tag and are not covered by that
digest-pinning guarantee. Runtime health/version still require verification.

Dependencies are PowerShell 7.2+, Azure CLI, Git, an authenticated Azure session,
and existing resource permissions. Registry network restrictions still apply.
Sidecar, Compose, Windows, code-based apps, and registry-authentication changes
are outside this publisher's scope. It does not provision or swap slots.

See the [publisher usage and parameter reference](https://github.com/microsoft/simplechat/blob/main/deployers/azurecli/README.md#interactive-container-publishing).
Offline behavioral coverage lives in
`functional_tests/test_azurecli_publish_script.ps1`. A real beta-target `-WhatIf`
preflight passed on 2026-09-23; remote builds and runtime startup were not tested.

### Environment Bootstrap

`deployers/Initialize-AzureEnvironment.ps1` now reflects that ACR is also used for deployer-driven image builds, not only for GitHub Actions secrets.

The script now emits:

- ACR resource identifiers
- ACR login server and credentials
- Azure OpenAI values
- An example `az acr build` command

### Terraform

Terraform still consumes an already-published image tag through `image_name`, but the deployment guidance now recommends `az acr build` as the primary way to publish that image.

## Usage

Example command from the repository root:

```azurecli
az acr build --registry <acr-name> --file application/single_app/Dockerfile --image simplechat:latest .
```

## Benefits

- No local Docker daemon required for AZD/Bicep deployments
- More consistent deployment behavior across deployment paths
- Better fit for locked-down administrator workstations
- Keeps container builds inside Azure infrastructure

## Validation

Validation completed with:

- workspace error checks on the updated YAML and Markdown files
- review of the updated deployment flow in `deployers/azure.yaml`
- confirmation that Terraform remains image-tag-driven while its guidance now matches the ACR build approach
