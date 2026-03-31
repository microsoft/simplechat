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
