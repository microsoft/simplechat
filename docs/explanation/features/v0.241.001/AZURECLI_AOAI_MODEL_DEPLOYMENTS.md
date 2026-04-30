# Azure CLI Azure OpenAI Model Deployments

Fixed/Implemented in version: **0.237.048**

## Overview

This update extends the Azure CLI deployer so it can create the default Azure OpenAI GPT and embedding model deployments, not just the Azure OpenAI account resource.

## Scope

This change affects:

- `deployers/azurecli/deploy-simplechat.ps1`
- `deployers/azurecli/README.md`
- `functional_tests/test_azurecli_aoai_model_deployments.py`

## Technical Details

### Deployment Behavior

The Azure CLI deployer can now:

- create model deployments for a newly created Azure OpenAI account
- create missing model deployments for a reused Azure OpenAI account
- skip model deployment creation when `param_DeployAzureOpenAiModels = $false`
- prompt for `Standard`, `DatazoneStandard`, or `GlobalStandard` in Azure Commercial when no deployment type is preconfigured
- retry a failed model deployment with a different deployment type when quota or regional availability blocks the first attempt

### Default Model Definitions

The deployer now includes cloud-aware defaults that mirror the main infrastructure deployment path:

- GPT deployment name: `gpt-4o`
- GPT model version: `2024-11-20` in Azure Commercial, `2024-05-13` in Azure Government
- Embedding deployment: `text-embedding-3-small` by default, with `text-embedding-ada-002` retained for `usgovvirginia`
- Deployment capacities: `100` for GPT and `80` for embeddings

### Idempotency

Before creating a model deployment, the script checks whether that deployment name already exists on the target Azure OpenAI account. Existing deployments are left in place so the script can be rerun safely.

## Benefits

- Reduces manual Azure OpenAI setup after Azure CLI deployments
- Aligns the Azure CLI deployer more closely with the Bicep deployer behavior
- Gives operators a direct retry path when the first deployment type hits quota or availability issues

## Validation

Validation completed with:

- workspace error checks on the updated PowerShell and Markdown files
- review of the Azure CLI model deployment command flow in `deployers/azurecli/deploy-simplechat.ps1`
- regression coverage in `functional_tests/test_azurecli_aoai_model_deployments.py`