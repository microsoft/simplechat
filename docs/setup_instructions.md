---
layout: page
title: "Setup Instructions"
description: "Complete guide to deploying and configuring Simple Chat"
section: "Tutorials"
nav_links:
  next:
    title: "Manual Setup"
    url: /setup_instructions_manual/
---

# Simple Chat - Setup Instructions

## Summary

Simple Chat supports several deployment paths, but they are not equal in automation, coverage, or current repo support.

If you want the best-supported path with the most up-to-date guidance, start with **Azure Developer CLI** and run `azd up`. That workflow uses the repo's Bicep templates under the hood and is the primary deployment path reflected across the current README and deployment docs.

Recommended order:
- [Azure Developer CLI (`azd up`)](#azure-developer-cli-azd-up)
- [Azure CLI with PowerShell](#azure-cli-with-powershell)
- [Bicep](#bicep)
- [Terraform](#terraform)
- [Manual Deployment](#manual-deployment)
- [Upgrade Existing Deployments](#upgrade-existing-deployments)
- [Special Deployment Scenarios](#special-deployment-scenarios)

Why multiple deployment technologies?
We want teams to be able to adopt Simple Chat using the deployment tooling that best fits their environment, while still making the most-supported default path clear.

## Azure Developer CLI (`azd up`)

This is the primary recommended deployment path.

Use it when you want the most automation, the most repo-level guidance, and the fewest manual decisions. `azd up` packages, provisions, and deploys Simple Chat through one workflow, and it uses the repo's Bicep templates behind the scenes.

[Azure Developer CLI deployment guide](./reference/deploy/azd-cli_deploy.md)

## Azure CLI with PowerShell

Use this path when you want a script-driven deployment flow without `azd`.

Azure CLI performs the Azure resource work, while PowerShell handles orchestration, sequencing, and recovery-oriented scripting. This is the next-best fit when you want more direct control than the `azd` workflow provides.

[Azure CLI with PowerShell deployment guide](./reference/deploy/azurecli_powershell_deploy.md)

## Bicep

Bicep is the infrastructure layer behind the primary `azd` deployment flow.

Use this path when you want to inspect or customize the Bicep modules directly. For most deployments, start with **Azure Developer CLI** instead of treating Bicep as a separate first-choice workflow.

[Bicep deployment guide](./reference/deploy/bicep_deploy.md)

## Terraform

Use Terraform when it is the standard infrastructure workflow in your environment.

This path manages a container-based Azure App Service deployment, but it expects your application image to be published before you apply the infrastructure changes.

[Terraform deployment guide](./reference/deploy/terraform_deploy.md)

## Manual Deployment

This is the step-by-step process required to deploy the infrastructure and configurations needed to run Simple Chat without the repo's container-based deployers.

This path is useful for native Python App Service scenarios and for understanding the lower-level configuration details, but it is not the preferred starting point when one of the automated deployment paths fits your environment.

[Link to manual deployment steps](./setup_instructions_manual.md)

## Upgrade Existing Deployments

If you already have Simple Chat deployed and only need to update the application, use the dedicated upgrade guide instead of rerunning the full setup flow.

[Link to upgrade paths](./how-to/upgrade_paths.md)

## Special Deployment Scenarios

The sections below cover scenarios that sit alongside the main deployment paths rather than replacing them.

This includes topics such as:
- Azure Commercial vs Azure Government deployments
- Managed Identity configurations
- Enterprise Networking Requirements

[Link to special deployment configurations](./setup_instructions_special.md)