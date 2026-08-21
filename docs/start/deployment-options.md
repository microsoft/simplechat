---
layout: page
title: "Getting Started"
description: "Choose the right deployment path, line up the prerequisites, and follow the repo's recommended rollout order for Simple Chat."
section: "Start"
nav_links:
  next:
    title: "Manual Setup"
    url: /setup_instructions_manual/
permalink: /start/deployment-options/
redirect_from:
  - /setup_instructions/
---

If you want the most current, least ambiguous deployment path, start with Azure Developer CLI and run `azd up`. The rest of the deployment options exist to match different operating models, not because they are all equally preferred.

## Deployment options in recommended order

All of these paths are supported, but they differ in how much automation, flexibility, and operational context they give you. Start with the most-used path first unless your environment already has a stronger reason to choose another deployer.

| Recommended order | Deployment option | Use when | Why it matters | Guide |
| --- | --- | --- | --- | --- |
| 1 | Azure Developer CLI | You want the smoothest repo-supported experience. It provisions infrastructure, packages the app, and deploys it through the same workflow. | This is the path reflected across the main README and the current deployment documentation. | [Read AZD guide]({{ '/reference/deploy/azd-cli_deploy/' | relative_url }}) |
| 2 | Azure CLI with PowerShell | You want more direct control over sequencing, recovery steps, and script-driven operations without moving to a fully manual deployment. | It keeps deployment scripted while exposing more of the individual Azure operations. | [Read Azure CLI guide]({{ '/reference/deploy/azurecli_powershell_deploy/' | relative_url }}) |
| 3 | Bicep | You want to inspect or customize the infrastructure modules directly. | It is the same IaC layer that the AZD path builds on. | [Inspect Bicep flow]({{ '/reference/deploy/bicep_deploy/' | relative_url }}) |
| 4 | Terraform | Terraform is already the standard in your environment and you are comfortable handling image publishing as part of the rollout. | It matches Terraform-first operating models that already own their image publishing process. | [Review Terraform guide]({{ '/reference/deploy/terraform_deploy/' | relative_url }}) |

## What a clean first deployment looks like

These four steps keep you aligned with the repo's expectations and reduce the chance of backtracking later.

1. **Prepare access**: confirm Azure subscription permissions, app registration creation rights, and access to container build resources before you begin.
2. **Choose the deployer**: default to AZD unless your environment already depends on a different provisioning workflow or you need native Python deployment details.
3. **Deploy infrastructure and app**: run the chosen workflow end to end so the app service, identity, storage, search, and runtime expectations stay in sync.
4. **Plan the upgrade path**: once the first environment is live, switch to the dedicated upgrade guidance for updates instead of replaying the initial setup flow.

## What to line up before you run anything

Most failed first deployments come from missing access, not from the deployer itself.

| Prerequisite area | What you need |
| --- | --- |
| Azure and identity permissions | Subscription-level deployment rights plus the ability to create or coordinate an Entra application registration for the app. |
| Local toolchain | At minimum, line up Azure CLI, Azure Developer CLI, Python 3.12, PowerShell 7, and Visual Studio Code before starting the primary flow. |
| Platform model | Know whether you need sovereign cloud support, private networking, managed identity-specific configuration, or native Python hosting, and review the related docs before deploying. |

## Python is part of the AZD toolchain

The repo's AZD workflow runs Python during the `preprovision` and `postprovision` hooks defined in `deployers/azure.yaml`. Install Python 3.12 and confirm `python` works on Windows or `python3` works on Linux/macOS before running `azd up`.

## Use the follow-on guides when the default path is not enough

These documents sit alongside the main setup flow instead of replacing it.

| Guide | Use it for |
| --- | --- |
| [Manual deployment]({{ '/setup_instructions_manual/' | relative_url }}) | Native Python App Service deployments or when you need the lower-level configuration path spelled out. |
| [Special deployment scenarios]({{ '/deploy/special-scenarios/' | relative_url }}) | Guidance for Azure Government, managed identities, enterprise networking, and other non-default rollout patterns. |
| [Upgrade existing deployments]({{ '/guides/upgrade-paths/' | relative_url }}) | Once you are live, use the upgrade guide to decide between code-only, image-only, and infrastructure-aware updates. |
